import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

import pymupdf
from lxml import html as lxml_html

from isss_bot.urls import classify_link, is_isss_page, normalize_url, url_key

BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
SKIPPED_TAGS = frozenset(
    {
        "audio",
        "button",
        "form",
        "iframe",
        "img",
        "input",
        "noscript",
        "picture",
        "script",
        "select",
        "source",
        "style",
        "svg",
        "template",
        "textarea",
        "video",
    }
)
BOILERPLATE_CLASSES = frozenset(
    {
        "breadcrumbs",
        "go-back",
        "image-block",
        "search-listing",
        "secondary-navigation",
        "share",
        "skip-link",
        "slim-breadcrumb",
        "visually-hidden",
    }
)
ACCORDION_CLASS = "simple-accordion"
ACCORDION_TRIGGER_CLASS = "simple-accordion__trigger"
CONTACT_BOX_CLASS = "prefooter"

MONTHS = {
    name: number
    for number, name in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
ANNOUNCEMENT_PATH = re.compile(r"/announcements/(\d{4})/([a-z]+)/[^/]+$")
WHITESPACE = re.compile(r"[ \t\r\n\f\v\xa0]+")
LINE_BREAK = "\x00"
DOCUMENT_TITLE_NOISE = re.compile(r"\[\s*pdf\s*\]|\(\s*pdf\s*\)|^\s*(download|click here for|view)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Link:
    url: str
    anchor_text: str
    kind: str


@dataclass
class Extracted:
    url: str
    title: str
    page_type: str
    content_type: str
    text: str
    announcement_date: date | None = None
    links: list[Link] = field(default_factory=list)
    linked_pages: list[str] = field(default_factory=list)


def _classes(element) -> set[str]:
    return set((element.get("class") or "").split())


def _is_boilerplate(element) -> bool:
    return any(name.split("__")[0] in BOILERPLATE_CLASSES for name in _classes(element))


def _collapse(text: str) -> str:
    text = WHITESPACE.sub(" ", text)
    lines = (line.strip() for line in text.split(LINE_BREAK))
    return "\n".join(line for line in lines if line)


class MarkdownRenderer:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.links: dict[str, Link] = {}
        self.section_level = 1

    def render(self, root) -> str:
        blocks: list[str] = []
        self._block(root, blocks)
        return "\n\n".join(block for block in blocks if block.strip())

    def _skipped(self, element) -> bool:
        if not isinstance(element.tag, str):
            return True
        if element.get("hidden") is not None or _is_boilerplate(element):
            return True
        return element.tag in SKIPPED_TAGS and not self._is_accordion_trigger(element)

    @staticmethod
    def _is_accordion_trigger(element) -> bool:
        return element.tag == "button" and ACCORDION_TRIGGER_CLASS in _classes(element)

    def _block(self, element, blocks: list[str]) -> None:
        if self._skipped(element):
            return
        tag = element.tag
        if tag in HEADING_TAGS:
            text = _collapse(self._inline(element)).replace("\n", " ")
            if text:
                self.section_level = HEADING_TAGS[tag]
                blocks.append(f"{'#' * self.section_level} {text}")
        elif self._is_accordion_trigger(element):
            text = _collapse(self._inline(element)).replace("\n", " ")
            if text:
                blocks.append(f"{'#' * min(self.section_level + 1, 6)} {text}")
        elif tag in ("ul", "ol"):
            blocks.append(self._list(element, depth=0))
        elif tag == "table":
            blocks.append(self._table(element))
        elif tag in ("p", "pre", "dt", "dd", "figcaption", "summary"):
            blocks.append(_collapse(self._inline(element)))
        elif tag == "blockquote":
            inner: list[str] = []
            self._container(element, inner)
            quoted = "\n\n".join(block for block in inner if block.strip())
            blocks.append("\n".join(f"> {line}" if line else ">" for line in quoted.split("\n")))
        elif ACCORDION_CLASS in _classes(element):
            level = self.section_level
            self._container(element, blocks)
            self.section_level = level
        elif tag != "hr":
            self._container(element, blocks)

    def _container(self, element, blocks: list[str]) -> None:
        buffer = [element.text or ""]
        for child in element:
            if self._skipped(child):
                buffer.append(child.tail or "")
            elif child.tag in BLOCK_TAGS or self._is_accordion_trigger(child):
                blocks.append(_collapse("".join(buffer)))
                self._block(child, blocks)
                buffer = [child.tail or ""]
            else:
                buffer.append(self._inline_element(child))
                buffer.append(child.tail or "")
        blocks.append(_collapse("".join(buffer)))

    def _inline(self, element) -> str:
        parts = [element.text or ""]
        for child in element:
            if not self._skipped(child):
                parts.append(self._inline_element(child))
            parts.append(child.tail or "")
        return "".join(parts)

    def _inline_element(self, element) -> str:
        tag = element.tag
        if tag == "br":
            return LINE_BREAK
        if tag == "a":
            return self._link(element)
        inner = self._inline(element)
        if tag in ("strong", "b"):
            return self._wrap(inner, "**")
        if tag in ("em", "i"):
            return self._wrap(inner, "*")
        if tag in BLOCK_TAGS:
            return f" {inner} "
        return inner

    @staticmethod
    def _wrap(inner: str, marker: str) -> str:
        stripped = inner.strip(" \t\r\n\xa0")
        if not stripped or LINE_BREAK in stripped:
            return inner
        leading = inner[: len(inner) - len(inner.lstrip(" \t\r\n\xa0"))]
        trailing = inner[len(inner.rstrip(" \t\r\n\xa0")) :]
        return f"{leading}{marker}{stripped}{marker}{trailing}"

    def _link(self, element) -> str:
        inner = self._inline(element)
        text = _collapse(inner).replace("\n", " ")
        href = (element.get("href") or "").strip()
        if not text or not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return inner
        url = normalize_url(urljoin(self.base_url, href))
        kind = classify_link(url)
        if kind is None:
            return inner
        self.links.setdefault(url, Link(url=url, anchor_text=text, kind=kind))
        return f"[{text}]({url})"

    def _list(self, element, depth: int) -> str:
        lines: list[str] = []
        indent = "  " * depth
        number = 0
        for item in element:
            if self._skipped(item) or item.tag != "li":
                continue
            number += 1
            marker = f"{number}." if element.tag == "ol" else "-"
            parts = [item.text or ""]
            nested: list[str] = []
            for child in item:
                if self._skipped(child):
                    pass
                elif child.tag in ("ul", "ol"):
                    nested.append(self._list(child, depth + 1))
                elif child.tag in BLOCK_TAGS:
                    parts.append(LINE_BREAK + self._inline(child) + LINE_BREAK)
                else:
                    parts.append(self._inline_element(child))
                parts.append(child.tail or "")
            text = _collapse("".join(parts)).replace("\n", f"\n{indent}  ")
            if text:
                lines.append(f"{indent}{marker} {text}")
            lines.extend(block for block in nested if block)
        return "\n".join(lines)

    def _table(self, element) -> str:
        rows = []
        for row in element.iter("tr"):
            cells = [
                _collapse(self._inline(cell)).replace("\n", " ").replace("|", "\\|")
                for cell in row
                if cell.tag in ("td", "th")
            ]
            if any(cells):
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n".join(lines)


def announcement_date_from_url(url: str) -> date | None:
    match = ANNOUNCEMENT_PATH.search(unquote(urlsplit(url).path).lower())
    if not match or match.group(2) not in MONTHS:
        return None
    return date(int(match.group(1)), MONTHS[match.group(2)], 1)


def _published_date(document) -> date | None:
    published = document.xpath('string(//meta[@property="article:published_time"]/@content)').strip()
    try:
        return datetime.fromisoformat(published).date() if published else None
    except ValueError:
        return None


def _canonical_url(document, final_url: str) -> str:
    final_url = normalize_url(final_url)
    declared = document.xpath('string(//meta[@property="og:url"]/@content)').strip()
    if declared and url_key(declared) == url_key(final_url):
        return normalize_url(declared)
    return final_url


def _linked_pages(document, base_url: str) -> list[str]:
    urls = (normalize_url(urljoin(base_url, href.strip())) for href in document.xpath("//a/@href"))
    return list(dict.fromkeys(url for url in urls if is_isss_page(url)))


def extract_html(html: bytes | str, final_url: str, keep_contact_box: bool = False) -> Extracted:
    document = lxml_html.fromstring(html)
    url = _canonical_url(document, final_url)
    linked_pages = _linked_pages(document, final_url)
    main = next(iter(document.xpath('//main[@id="main-content"]')), None)
    if main is None:
        main = document.find("body") if document.find("body") is not None else document
    if not keep_contact_box:
        for box in main.xpath(f'.//*[contains(concat(" ", normalize-space(@class), " "), " {CONTACT_BOX_CLASS} ")]'):
            box.getparent().remove(box)

    renderer = MarkdownRenderer(base_url=final_url)
    text = renderer.render(main)
    title = _collapse(main.xpath("string((.//h1)[1])")) or _collapse(document.xpath("string(//title)"))
    title = title or PurePosixPath(urlsplit(url).path).name

    announcement_date = announcement_date_from_url(url)
    if announcement_date:
        announcement_date = _published_date(document) or announcement_date
    return Extracted(
        url=url,
        title=title,
        page_type="announcement" if announcement_date else "page",
        content_type="text/html",
        text=text,
        announcement_date=announcement_date,
        links=list(renderer.links.values()),
        linked_pages=linked_pages,
    )


def document_title(anchor_text: str | None, url: str) -> str:
    title = DOCUMENT_TITLE_NOISE.sub("", anchor_text or "").strip(" -:")
    if len(title) >= 4:
        return title
    stem = PurePosixPath(unquote(urlsplit(url).path)).stem
    return re.sub(r"[-_]+", " ", stem).strip().title() or url


def extract_pdf(body: bytes, final_url: str, anchor_text: str | None = None) -> Extracted:
    paragraphs = []
    with pymupdf.open(stream=body, filetype="pdf") as pdf:
        for page in pdf:
            for block in page.get_text("blocks", sort=True):
                if block[6] != 0:
                    continue
                paragraph = WHITESPACE.sub(" ", block[4].replace("-\n", "-").replace("\n", " ")).strip()
                if paragraph:
                    paragraphs.append(paragraph)
    return Extracted(
        url=normalize_url(final_url),
        title=document_title(anchor_text, final_url),
        page_type="document",
        content_type="application/pdf",
        text="\n\n".join(paragraphs),
    )
