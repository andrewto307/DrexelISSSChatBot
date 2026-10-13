import re
import sys
from dataclasses import dataclass
from datetime import date, datetime

import psycopg
from pgvector import Vector

from isss_bot import db
from isss_bot.embed import embed_query
from isss_bot.urls import url_key

CANDIDATES_PER_METHOD = 40
KEYWORD_WEIGHT = 0.3
RRF_K = 60
DEFAULT_LIMIT = 6
MAX_UPDATES = 2
MARKDOWN_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")

VECTOR_SEARCH = """
SELECT chunks.id FROM chunks JOIN pages ON pages.id = chunks.page_id
WHERE pages.status = 'active'
ORDER BY chunks.embedding <=> %s
LIMIT %s
"""

KEYWORD_SEARCH = """
WITH terms AS (
    SELECT DISTINCT lexeme FROM unnest(tsvector_to_array(to_tsvector('english', %s))) AS lexeme
),
weights AS (
    SELECT terms.lexeme, ln((SELECT count(*) FROM chunks)::float / stats.ndoc) AS weight
    FROM terms JOIN ts_stat('SELECT tsv FROM chunks') AS stats ON stats.word = terms.lexeme
)
SELECT chunks.id
FROM chunks
JOIN pages ON pages.id = chunks.page_id
JOIN weights ON weights.lexeme = ANY(tsvector_to_array(chunks.tsv))
WHERE pages.status = 'active'
GROUP BY chunks.id
ORDER BY sum(weights.weight) DESC, chunks.id
LIMIT %s
"""

ANNOUNCEMENTS = """
SELECT id, url, announcement_date FROM pages
WHERE status = 'active' AND page_type = 'announcement' AND announcement_date IS NOT NULL
"""

ANNOUNCEMENT_LINKS = """
SELECT links.from_page_id AS page_id, links.url AS target_url
FROM links JOIN pages ON pages.id = links.from_page_id
WHERE pages.status = 'active' AND pages.page_type = 'announcement' AND links.kind = 'isss_page'
"""

FIRST_CHUNKS = """
SELECT DISTINCT ON (pages.id)
       chunks.id AS chunk_id, chunks.chunk_index, pages.url, pages.title, pages.page_type, pages.announcement_date,
       pages.fetched_at, chunks.heading_path, chunks.content
FROM chunks JOIN pages ON pages.id = chunks.page_id
WHERE pages.id = ANY(%s)
ORDER BY pages.id, chunks.chunk_index
"""

CHUNK_DETAILS = """
SELECT chunks.id AS chunk_id, chunks.chunk_index, pages.url, pages.title, pages.page_type, pages.announcement_date,
       pages.fetched_at, chunks.heading_path, chunks.content
FROM chunks JOIN pages ON pages.id = chunks.page_id
WHERE chunks.id = ANY(%s)
"""


@dataclass
class SearchResult:
    chunk_id: int
    chunk_index: int
    url: str
    title: str
    page_type: str
    announcement_date: date | None
    fetched_at: datetime
    heading_path: str
    content: str
    score: float
    vector_rank: int | None
    keyword_rank: int | None
    updates: str | None = None


def reciprocal_rank_fusion(
    rankings: list[list[int]], weights: list[float] | None = None, k: int = RRF_K
) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking, weight in zip(rankings, weights or [1.0] * len(rankings), strict=True):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def search(
    conn: psycopg.Connection, query: str, limit: int = DEFAULT_LIMIT, query_vector: list[float] | None = None
) -> list[SearchResult]:
    vector = Vector(query_vector if query_vector is not None else embed_query(query))
    vector_ids = [row["id"] for row in conn.execute(VECTOR_SEARCH, (vector, CANDIDATES_PER_METHOD))]
    keyword_ids = [row["id"] for row in conn.execute(KEYWORD_SEARCH, (query, CANDIDATES_PER_METHOD))]
    fused = reciprocal_rank_fusion([vector_ids, keyword_ids], [1.0, KEYWORD_WEIGHT])[:limit]

    details = {row["chunk_id"]: row for row in conn.execute(CHUNK_DETAILS, ([chunk_id for chunk_id, _ in fused],))}
    vector_ranks = {chunk_id: rank for rank, chunk_id in enumerate(vector_ids, start=1)}
    keyword_ranks = {chunk_id: rank for rank, chunk_id in enumerate(keyword_ids, start=1)}
    return [
        SearchResult(
            **details[chunk_id],
            score=score,
            vector_rank=vector_ranks.get(chunk_id),
            keyword_rank=keyword_ranks.get(chunk_id),
        )
        for chunk_id, score in fused
    ]


def newer_updates(
    conn: psycopg.Connection, results: list[SearchResult], limit: int = MAX_UPDATES
) -> list[SearchResult]:
    announcements = {url_key(row["url"]): row for row in conn.execute(ANNOUNCEMENTS)}
    by_id = {row["id"]: row for row in announcements.values()}
    linked_from: dict[str, list[dict]] = {}
    for link in conn.execute(ANNOUNCEMENT_LINKS):
        if link["page_id"] in by_id:
            linked_from.setdefault(url_key(link["target_url"]), []).append(by_id[link["page_id"]])

    shown = {url_key(result.url) for result in results}
    mentioned = {url_key(url) for result in results for url in MARKDOWN_LINK.findall(result.content)}
    starts = (shown | mentioned) & announcements.keys()

    found: dict[str, tuple[dict, str]] = {}
    queue = list(starts)
    while queue:
        target = announcements[queue.pop()]
        for source in linked_from.get(url_key(target["url"]), []):
            key = url_key(source["url"])
            if key not in starts and key not in found and source["announcement_date"] > target["announcement_date"]:
                found[key] = (source, target["url"])
                queue.append(key)

    newest = sorted(
        (pair for key, pair in found.items() if key not in shown),
        key=lambda pair: pair[0]["announcement_date"],
        reverse=True,
    )[:limit]
    if not newest:
        return []
    chunks = {row["url"]: row for row in conn.execute(FIRST_CHUNKS, ([source["id"] for source, _ in newest],))}
    return [
        SearchResult(**chunks[source["url"]], score=0.0, vector_rank=None, keyword_rank=None, updates=target_url)
        for source, target_url in newest
        if source["url"] in chunks
    ]


def main() -> None:
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        sys.exit('usage: python -m isss_bot.search "your question"')
    with db.connect() as conn:
        for rank, result in enumerate(search(conn, query), start=1):
            preview = " ".join(result.content.split())[:160]
            ranks = f"vector #{result.vector_rank}, keyword #{result.keyword_rank}"
            print(f"{rank}. {result.heading_path}  (score {result.score:.4f}, {ranks})")
            print(f"   {result.url}")
            print(f"   {preview}\n")


if __name__ == "__main__":
    main()
