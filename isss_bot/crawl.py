import hashlib
import time
import xml.etree.ElementTree as ElementTree
from collections import Counter, deque
from dataclasses import dataclass, field
from urllib.robotparser import RobotFileParser

import httpx
import psycopg

from isss_bot import config
from isss_bot.extract import Extracted, extract_html, extract_pdf
from isss_bot.urls import is_isss_page, normalize_url, url_key

RETRY_DELAYS_SECONDS = (5, 15)
SITEMAP_NAMESPACE = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


@dataclass
class CrawlReport:
    outcomes: dict[str, list[str]] = field(
        default_factory=lambda: {"new": [], "changed": [], "unchanged": [], "gone": []}
    )
    errors: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    link_kinds: Counter = field(default_factory=Counter)


@dataclass(frozen=True)
class QueueItem:
    url: str
    is_document: bool = False
    anchor_text: str | None = None


class Fetcher:
    def __init__(self, delay_seconds: float = config.CRAWL_DELAY_SECONDS):
        self.client = httpx.Client(headers={"User-Agent": config.USER_AGENT}, follow_redirects=True, timeout=30.0)
        self.delay_seconds = delay_seconds
        self.next_request_at = 0.0
        self.robots = self._load_robots()

    def _load_robots(self) -> RobotFileParser:
        parser = RobotFileParser(config.ROBOTS_URL)
        response = self.get(config.ROBOTS_URL)
        if response.status_code >= 500:
            response.raise_for_status()
        if response.status_code >= 400:
            parser.allow_all = True
        else:
            parser.parse(response.text.splitlines())
        return parser

    def allowed(self, url: str) -> bool:
        return self.robots.can_fetch(config.USER_AGENT, url)

    def get(self, url: str) -> httpx.Response:
        retry_delays = list(RETRY_DELAYS_SECONDS)
        while True:
            time.sleep(max(0.0, self.next_request_at - time.monotonic()))
            try:
                response = self.client.get(url)
            except httpx.TransportError:
                if not retry_delays:
                    raise
            else:
                if response.status_code < 500 or not retry_delays:
                    return response
            finally:
                self.next_request_at = time.monotonic() + self.delay_seconds
            time.sleep(retry_delays.pop(0))

    def close(self) -> None:
        self.client.close()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sitemap_urls(fetcher: Fetcher) -> list[str]:
    response = fetcher.get(config.SITEMAP_URL)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    urls = (loc.text.strip() for loc in root.iter(f"{SITEMAP_NAMESPACE}loc") if loc.text)
    return [url for url in urls if is_isss_page(normalize_url(url))]


def _media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";")[0].strip().lower()


def save_page(conn: psycopg.Connection, page: Extracted) -> str:
    new_hash = content_hash(page.text)
    row = conn.execute("SELECT id, content_hash, status FROM pages WHERE url = %s", (page.url,)).fetchone()
    values = (page.title, page.page_type, page.content_type, page.announcement_date, page.text, new_hash)
    if row is None:
        page_id = conn.execute(
            """
            INSERT INTO pages (url, title, page_type, content_type, announcement_date, text, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (page.url, *values),
        ).fetchone()["id"]
        outcome = "new"
    elif row["content_hash"] == new_hash and row["status"] == "active":
        page_id = row["id"]
        conn.execute("UPDATE pages SET fetched_at = now() WHERE id = %s", (page_id,))
        outcome = "unchanged"
    else:
        page_id = row["id"]
        conn.execute(
            """
            UPDATE pages
            SET title = %s, page_type = %s, content_type = %s, announcement_date = %s, text = %s,
                content_hash = %s, status = 'active', fetched_at = now(), changed_at = now()
            WHERE id = %s
            """,
            (*values, page_id),
        )
        outcome = "changed" if row["status"] == "active" else "new"

    conn.execute("DELETE FROM links WHERE from_page_id = %s", (page_id,))
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO links (from_page_id, url, anchor_text, kind) VALUES (%s, %s, %s, %s)",
            [(page_id, link.url, link.anchor_text, link.kind) for link in page.links],
        )
    return outcome


def mark_gone(conn: psycopg.Connection, page_ids: list[int]) -> None:
    conn.execute("UPDATE pages SET status = 'gone', indexed_hash = NULL WHERE id = ANY(%s)", (page_ids,))
    conn.execute("DELETE FROM chunks WHERE page_id = ANY(%s)", (page_ids,))


class Crawler:
    def __init__(self, conn: psycopg.Connection, fetcher: Fetcher, log=print):
        self.conn = conn
        self.fetcher = fetcher
        self.log = log
        self.report = CrawlReport()
        self.queue: deque[QueueItem] = deque()
        self.queued: set[str] = set()
        self.stored: set[str] = set()
        self.failed: set[str] = set()

    def enqueue(self, item: QueueItem) -> None:
        key = url_key(item.url)
        if key not in self.queued:
            self.queued.add(key)
            self.queue.append(item)

    def run(self) -> CrawlReport:
        self.enqueue(QueueItem(config.ISSS_HOME))
        for url in sitemap_urls(self.fetcher):
            self.enqueue(QueueItem(url))
        for row in self.conn.execute("SELECT url FROM pages WHERE status = 'active' AND page_type <> 'document'"):
            self.enqueue(QueueItem(row["url"]))

        while self.queue:
            item = self.queue.popleft()
            try:
                self._process(item)
            except psycopg.Error:
                raise
            except Exception as error:
                self.failed.add(url_key(item.url))
                self.report.errors.append((item.url, f"{type(error).__name__}: {error}"))
                self.log(f"  error  {item.url}: {error}")
        self._mark_unreached_gone()
        return self.report

    def _process(self, item: QueueItem) -> None:
        if not self.fetcher.allowed(item.url):
            self.report.skipped.append((item.url, "disallowed by robots.txt"))
            return
        response = self.fetcher.get(item.url)
        if response.status_code in (404, 410):
            return
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")

        final_url = normalize_url(str(response.url))
        media_type = _media_type(response)
        if item.is_document:
            if media_type != "application/pdf" and not response.content.startswith(b"%PDF"):
                self.report.skipped.append((item.url, f"unsupported document type {media_type or 'unknown'}"))
                return
            page = extract_pdf(response.content, final_url, item.anchor_text)
        else:
            if not is_isss_page(final_url):
                self.report.skipped.append((item.url, f"redirects outside ISSS to {final_url}"))
                return
            if media_type != "text/html":
                self.report.skipped.append((item.url, f"unexpected content type {media_type or 'unknown'}"))
                return
            is_home = url_key(final_url) == url_key(config.ISSS_HOME)
            page = extract_html(response.content, final_url, keep_contact_box=is_home)

        key = url_key(page.url)
        self.queued.update({key, url_key(final_url)})
        if key in self.stored:
            return
        self.stored.add(key)

        outcome = save_page(self.conn, page)
        self.conn.commit()
        self.report.outcomes[outcome].append(page.url)
        self.report.link_kinds.update(link.kind for link in page.links)
        if outcome != "unchanged":
            self.log(f"  {outcome:<9} {page.url}")

        for url in page.linked_pages:
            self.enqueue(QueueItem(url))
        for link in page.links:
            if link.kind == "isss_document":
                self.enqueue(QueueItem(link.url, is_document=True, anchor_text=link.anchor_text))

    def _mark_unreached_gone(self) -> None:
        rows = self.conn.execute("SELECT id, url, page_type FROM pages WHERE status = 'active'").fetchall()
        gone = []
        for row in rows:
            key = url_key(row["url"])
            if key in self.stored or key in self.failed:
                continue
            if row["page_type"] == "document" and self.report.errors:
                continue
            gone.append(row)
        if gone:
            mark_gone(self.conn, [row["id"] for row in gone])
            self.conn.commit()
        self.report.outcomes["gone"].extend(row["url"] for row in gone)


def crawl(conn: psycopg.Connection, log=print) -> CrawlReport:
    fetcher = Fetcher()
    try:
        return Crawler(conn, fetcher, log).run()
    finally:
        fetcher.close()
