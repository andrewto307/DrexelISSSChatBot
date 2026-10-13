import math
import re
from dataclasses import dataclass, field

MAX_TOKENS = 500
MIN_TOKENS = 120
MIN_PAGE_CHARACTERS = 40
PATH_SEPARATOR = " › "

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    heading_path: str
    content: str
    token_count: int


@dataclass
class Section:
    path: list[str]
    heading: str | None
    paragraphs: list[str] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def split_sections(text: str) -> list[Section]:
    sections = [Section(path=[], heading=None)]
    stack: list[tuple[int, str]] = []
    paragraph: list[str] = []

    def end_paragraph() -> None:
        if paragraph:
            sections[-1].paragraphs.append("\n".join(paragraph).strip())
            paragraph.clear()

    for line in text.splitlines():
        match = HEADING.match(line)
        if not match:
            if line.strip():
                paragraph.append(line)
            else:
                end_paragraph()
            continue
        end_paragraph()
        level, title = len(match.group(1)), match.group(2).strip()
        if level == 1:
            stack.clear()
            if sections[-1].heading or sections[-1].paragraphs:
                sections.append(Section(path=[], heading=None))
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        sections.append(Section(path=[name for _, name in stack], heading=line.strip()))
    end_paragraph()
    return [section for section in sections if section.heading or section.paragraphs]


def _split_long(text: str) -> list[str]:
    if estimate_tokens(text) <= MAX_TOKENS:
        return [text]
    for separator, joiner in (("\n", "\n"), (SENTENCE_END, " "), (" ", " ")):
        parts = separator.split(text) if isinstance(separator, re.Pattern) else text.split(separator)
        if len(parts) > 1:
            return [piece for group in _pack(parts, joiner) for piece in _split_long(group)]
    step = MAX_TOKENS * 4
    return [text[start : start + step] for start in range(0, len(text), step)]


def _pack(parts: list[str], joiner: str) -> list[str]:
    groups: list[str] = []
    for part in parts:
        if groups and estimate_tokens(groups[-1] + joiner + part) <= MAX_TOKENS:
            groups[-1] += joiner + part
        else:
            groups.append(part)
    return groups


def _pack_chunks(blocks: list[str]) -> list[str]:
    contents = _pack(blocks, "\n\n")
    if len(contents) > 1 and estimate_tokens(contents[-1]) < MIN_TOKENS // 2:
        last = contents.pop()
        contents[-1] += "\n\n" + last
    return contents


def _is_heading(block: str) -> bool:
    return all(HEADING.match(line) for line in block.split("\n\n"))


def _attach_headings(blocks: list[str]) -> list[str]:
    attached: list[str] = []
    for block in blocks:
        if attached and _is_heading(attached[-1]):
            attached[-1] = f"{attached[-1]}\n\n{block}"
        else:
            attached.append(block)
    return attached


def _common_prefix(paths: list[list[str]]) -> list[str]:
    prefix = paths[0]
    for path in paths[1:]:
        length = 0
        while length < min(len(prefix), len(path)) and prefix[length] == path[length]:
            length += 1
        prefix = prefix[:length]
    return prefix


def _section_blocks(section: Section, chunk_path: list[str]) -> list[str]:
    blocks = [section.heading] if section.heading and len(section.path) > len(chunk_path) else []
    return blocks + [piece for paragraph in section.paragraphs for piece in _split_long(paragraph)]


def _group_sections(sections: list[Section]) -> list[list[Section]]:
    groups: list[list[Section]] = []
    sizes: list[int] = []
    for section in sections:
        size = estimate_tokens("\n\n".join(_section_blocks(section, chunk_path=[])))
        if groups:
            same_top_heading = section.path[:1] == groups[-1][0].path[:1]
            small = sizes[-1] < MIN_TOKENS or (size < MIN_TOKENS and bool(section.paragraphs))
            if (same_top_heading or small) and sizes[-1] + size <= MAX_TOKENS:
                groups[-1].append(section)
                sizes[-1] += size
                continue
        groups.append([section])
        sizes.append(size)
    return groups


def chunk_page(title: str, text: str) -> list[Chunk]:
    sections = split_sections(text)
    body = "\n".join(paragraph for section in sections for paragraph in section.paragraphs)
    if len(body) < MIN_PAGE_CHARACTERS:
        return []

    chunks = []
    for group in _group_sections(sections):
        path = _common_prefix([section.path for section in group])
        blocks = _attach_headings([block for section in group for block in _section_blocks(section, path)])
        while blocks and _is_heading(blocks[-1]):
            blocks.pop()
        heading_path = PATH_SEPARATOR.join([title, *path])
        for content in _pack_chunks(blocks):
            if not _is_heading(content):
                chunks.append(Chunk(heading_path, content, estimate_tokens(content)))
    return chunks
