from dataclasses import dataclass

import psycopg
from pgvector import Vector

from isss_bot import config
from isss_bot.chunk import Chunk, chunk_page
from isss_bot.embed import embed_documents

PAGES_PER_BATCH = 20


@dataclass
class IndexReport:
    pages_indexed: int = 0
    chunks_written: int = 0
    chunks_removed: int = 0
    tokens_embedded: int = 0


def embedding_text(chunk: Chunk) -> str:
    return f"{chunk.heading_path}\n\n{chunk.content}"


def _replace_chunks(conn: psycopg.Connection, page: dict, chunks: list[Chunk], vectors: list, model: str) -> None:
    conn.execute("DELETE FROM chunks WHERE page_id = %s", (page["id"],))
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO chunks (page_id, chunk_index, heading_path, content, token_count, embedding)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (page["id"], position, chunk.heading_path, chunk.content, chunk.token_count, Vector(vector))
                for position, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
            ],
        )
    conn.execute(
        "UPDATE pages SET indexed_hash = %s, indexed_model = %s WHERE id = %s",
        (page["content_hash"], model, page["id"]),
    )


def index(conn: psycopg.Connection, model: str = config.VOYAGE_MODEL, log=print) -> IndexReport:
    report = IndexReport()
    removed = conn.execute(
        "DELETE FROM chunks USING pages WHERE chunks.page_id = pages.id AND pages.status <> 'active'"
    )
    report.chunks_removed = removed.rowcount
    conn.commit()

    pages = conn.execute(
        """
        SELECT id, url, title, text, content_hash FROM pages
        WHERE status = 'active'
          AND (indexed_hash IS DISTINCT FROM content_hash OR indexed_model IS DISTINCT FROM %s)
        ORDER BY id
        """,
        (model,),
    ).fetchall()

    for start in range(0, len(pages), PAGES_PER_BATCH):
        batch = [(page, chunk_page(page["title"], page["text"])) for page in pages[start : start + PAGES_PER_BATCH]]
        texts = [embedding_text(chunk) for _, chunks in batch for chunk in chunks]
        vectors, tokens = embed_documents(texts, model) if texts else ([], 0)
        offset = 0
        for page, chunks in batch:
            _replace_chunks(conn, page, chunks, vectors[offset : offset + len(chunks)], model)
            offset += len(chunks)
        conn.commit()
        report.pages_indexed += len(batch)
        report.chunks_written += len(texts)
        report.tokens_embedded += tokens
        log(f"  indexed {report.pages_indexed}/{len(pages)} pages ({report.chunks_written} chunks)")
    return report
