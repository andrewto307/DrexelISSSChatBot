import math
from datetime import UTC, date, datetime, timedelta

import pytest
from pgvector import Vector

from isss_bot import config
from isss_bot.search import SearchResult, demote, newer_updates, reciprocal_rank_fusion, search

ANNOUNCEMENTS = "https://drexel.edu/studentlife/student-success/international-student-support/announcements"


def test_reciprocal_rank_fusion_rewards_agreement():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 1, 4]], k=60)
    assert [item for item, _ in fused] == [1, 3, 2, 4]
    assert fused[0][1] == 1 / 61 + 1 / 62


def test_reciprocal_rank_fusion_applies_weights():
    fused = reciprocal_rank_fusion([[1, 2], [2, 1]], weights=[1.0, 0.3], k=60)
    assert [item for item, _ in fused] == [1, 2]
    assert fused[0][1] == pytest.approx(1 / 61 + 0.3 / 62)


def test_reciprocal_rank_fusion_handles_empty_rankings():
    assert [item for item, _ in reciprocal_rank_fusion([[], [7, 8]])] == [7, 8]


def test_demote_lowers_only_the_given_items_and_reorders():
    fused = [(1, 0.020), (2, 0.019), (3, 0.010)]
    assert demote(fused, {1}, 0.9) == [(2, 0.019), (1, pytest.approx(0.018)), (3, 0.010)]
    assert demote(fused, set(), 0.9) == fused


def _unit_vector(*axes: int) -> list[float]:
    vector = [0.0] * config.EMBEDDING_DIMENSIONS
    for axis in axes:
        vector[axis] = 1 / math.sqrt(len(axes))
    return vector


def _add_page(
    conn,
    url: str,
    content: str,
    embedding: list[float] | None = None,
    status: str = "active",
    published: date | None = None,
    links: tuple[str, ...] = (),
) -> int:
    page_id = conn.execute(
        """
        INSERT INTO pages (url, title, page_type, content_type, announcement_date, text, content_hash, status)
        VALUES (%s, 'Test page', %s, 'text/html', %s, %s, 'hash', %s) RETURNING id
        """,
        (url, "announcement" if published else "page", published, content, status),
    ).fetchone()["id"]
    conn.execute(
        """
        INSERT INTO chunks (page_id, chunk_index, heading_path, content, token_count, embedding)
        VALUES (%s, 0, 'Test page', %s, 10, %s)
        """,
        (page_id, content, Vector(embedding or _unit_vector(0))),
    )
    for target in links:
        conn.execute(
            "INSERT INTO links (from_page_id, url, anchor_text, kind) VALUES (%s, %s, 'link', 'isss_page')",
            (page_id, target),
        )
    return page_id


def _shown(url: str, content: str) -> SearchResult:
    return SearchResult(
        chunk_id=0,
        chunk_index=0,
        url=url,
        title="Shown page",
        page_type="page",
        announcement_date=None,
        fetched_at=datetime(2026, 10, 12, tzinfo=UTC),
        heading_path="Shown page",
        content=content,
        score=0.0,
        vector_rank=1,
        keyword_rank=1,
    )


def test_search_combines_vector_and_keyword_matches(conn):
    _add_page(conn, "https://test.invalid/vector", "Semantic match about work permits.", _unit_vector(0))
    _add_page(conn, "https://test.invalid/keyword", "Bring your Form I-20 and the zqxvwplorp letter.", _unit_vector(5))
    _add_page(conn, "https://test.invalid/gone", "Old zqxvwplorp page.", _unit_vector(0), status="gone")

    results = {result.url: result for result in search(conn, "zqxvwplorp I-20", limit=40, query_vector=_unit_vector(0))}

    assert results["https://test.invalid/vector"].vector_rank == 1
    assert results["https://test.invalid/keyword"].keyword_rank == 1
    assert "https://test.invalid/gone" not in results


def test_search_ranks_announcements_older_than_three_years_a_little_lower(conn):
    today = date.today()
    _add_page(conn, "https://test.invalid/old", "Old rule.", _unit_vector(0), published=today - timedelta(days=4 * 365))
    _add_page(
        conn, "https://test.invalid/recent", "Recent rule.", _unit_vector(0), published=today - timedelta(days=30)
    )
    _add_page(conn, "https://test.invalid/page", "Current page.", _unit_vector(0))

    urls = [result.url for result in search(conn, "what is it?", query_vector=_unit_vector(0))]

    assert urls[-1] == "https://test.invalid/old"
    assert set(urls) == {"https://test.invalid/old", "https://test.invalid/recent", "https://test.invalid/page"}


def test_search_with_only_stop_words_uses_vectors(conn):
    _add_page(conn, "https://test.invalid/vector", "Semantic match.", _unit_vector(3))
    results = search(conn, "what is it?", query_vector=_unit_vector(3))
    assert results[0].url == "https://test.invalid/vector"
    assert results[0].keyword_rank is None


def test_newer_updates_follow_announcements_that_link_back(conn):
    rule = f"{ANNOUNCEMENTS}/2026/July/Final-Rule"
    postponed = f"{ANNOUNCEMENTS}/2026/September/Court-Postpones-Rule"
    guidance = f"{ANNOUNCEMENTS}/2026/October/Guidance-After-Postponement"
    earlier = f"{ANNOUNCEMENTS}/2026/January/Earlier-Post"
    _add_page(conn, rule, "The rule takes effect September 15.", published=date(2026, 7, 17))
    _add_page(conn, postponed, "A court postponed the rule.", published=date(2026, 9, 14), links=(rule,))
    _add_page(conn, guidance, "Guidance after the postponement.", published=date(2026, 10, 1), links=(postponed,))
    _add_page(conn, earlier, "An earlier post about the same topic.", published=date(2026, 1, 5), links=(rule,))
    cpt = _shown("https://drexel.edu/x/cpt", f"There is a [DHS Final Rule]({rule.lower()}) scheduled for September 15.")

    updates = newer_updates(conn, [cpt])

    assert [update.url for update in updates] == [guidance, postponed]
    assert [update.updates for update in updates] == [postponed, rule]
    assert updates[1].content == "A court postponed the rule."


def test_newer_updates_skip_shown_pages_and_respect_the_limit(conn):
    rule = f"{ANNOUNCEMENTS}/2026/July/Final-Rule"
    september, october, november = (
        f"{ANNOUNCEMENTS}/2026/{month}/Update" for month in ("September", "October", "November")
    )
    _add_page(conn, rule, "The rule.", published=date(2026, 7, 17))
    for url, day in ((september, date(2026, 9, 1)), (october, date(2026, 10, 1)), (november, date(2026, 11, 1))):
        _add_page(conn, url, "An update.", published=day, links=(rule,))

    updates = newer_updates(conn, [_shown(rule, "The rule."), _shown(october, "An update.")], limit=1)

    assert [update.url for update in updates] == [november]


def test_newer_updates_ignore_links_to_regular_pages(conn):
    _add_page(conn, f"{ANNOUNCEMENTS}/2026/July/Final-Rule", "The rule.", published=date(2026, 7, 17))
    opt = _shown("https://drexel.edu/x/opt", "See the [OPT page](https://drexel.edu/x/opt-details).")
    assert newer_updates(conn, [opt]) == []
