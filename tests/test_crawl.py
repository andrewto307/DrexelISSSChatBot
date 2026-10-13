from isss_bot.crawl import mark_gone, save_page
from isss_bot.extract import Extracted, Link

URL = "https://test.invalid/studentlife/student-success/international-student-support/test-page"


def _page(text: str, links: list[Link]) -> Extracted:
    return Extracted(url=URL, title="Test", page_type="page", content_type="text/html", text=text, links=links)


def _links(conn) -> set[str]:
    rows = conn.execute(
        "SELECT links.url FROM links JOIN pages ON pages.id = links.from_page_id WHERE pages.url = %s", (URL,)
    )
    return {row["url"] for row in rows}


def test_save_page_reports_new_unchanged_and_changed(conn):
    uscis = Link("https://www.uscis.gov/i-765", "Form I-765", "external")
    portal = Link("https://drexel0.sharepoint.com/sites/ISSS-StudentPortal", "ISSS Student Portal", "login_only")

    assert save_page(conn, _page("First version", [uscis])) == "new"
    assert save_page(conn, _page("First version", [uscis])) == "unchanged"
    assert save_page(conn, _page("Second version", [portal])) == "changed"

    row = conn.execute("SELECT text, status FROM pages WHERE url = %s", (URL,)).fetchone()
    assert row == {"text": "Second version", "status": "active"}
    assert _links(conn) == {portal.url}


def test_gone_pages_lose_their_chunks_and_come_back_as_new(conn):
    save_page(conn, _page("Text", []))
    page_id = conn.execute("SELECT id FROM pages WHERE url = %s", (URL,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO chunks (page_id, chunk_index, heading_path, content, token_count, embedding) "
        "VALUES (%s, 0, 'Test', 'Text', 1, array_fill(0.1, ARRAY[1024])::vector)",
        (page_id,),
    )

    mark_gone(conn, [page_id])
    assert conn.execute("SELECT status FROM pages WHERE id = %s", (page_id,)).fetchone()["status"] == "gone"
    assert conn.execute("SELECT count(*) FROM chunks WHERE page_id = %s", (page_id,)).fetchone()["count"] == 0
    assert save_page(conn, _page("Text", [])) == "new"
