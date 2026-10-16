import uuid

import psycopg
from psycopg.types.json import Json, Jsonb

from isss_bot import config
from isss_bot.answer import Answer, Conversation
from isss_bot.search import SearchResult
from isss_bot.urls import linked_url_keys, url_key


def source_record(result: SearchResult) -> dict:
    return {
        "url": result.url,
        "title": result.title,
        "type": result.page_type,
        "published": result.announcement_date.isoformat() if result.announcement_date else None,
        "section": result.heading_path,
        "updates": result.updates,
    }


def unique_sources(records: list[dict]) -> list[dict]:
    pages: dict[str, dict] = {}
    for record in records:
        pages.setdefault(record["url"], record)
    return list(pages.values())


def cited_sources(text: str, records: list[dict]) -> list[dict]:
    linked = linked_url_keys(text)
    return [record for record in unique_sources(records) if url_key(record["url"]) in linked]


def text_of(content: list[dict]) -> str:
    return "".join(block.get("text", "") for block in content if block.get("type") == "text")


def create_conversation(conn: psycopg.Connection, user_id: int | None, client_ip_hash: str | None) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO conversations (id, user_id, client_ip_hash) VALUES (%s, %s, %s)",
        (conversation_id, user_id, client_ip_hash),
    )
    return conversation_id


def load_conversation(
    conn: psycopg.Connection, conversation_id: uuid.UUID, user_id: int | None, **options
) -> Conversation | None:
    owned = conn.execute(
        "SELECT 1 FROM conversations WHERE id = %s AND user_id IS NOT DISTINCT FROM %s", (conversation_id, user_id)
    ).fetchone()
    if owned is None:
        return None
    rows = conn.execute(
        """
        SELECT role, content, question_text FROM messages
        WHERE conversation_id = %s AND in_history
        ORDER BY position
        """,
        (conversation_id,),
    ).fetchall()
    return Conversation(
        conn,
        messages=[{"role": row["role"], "content": row["content"]} for row in rows],
        questions=[row["question_text"] for row in rows if row["role"] == "user"],
        answers=[text_of(row["content"]) for row in rows if row["role"] == "assistant"],
        **options,
    )


def save_turn(conn: psycopg.Connection, conversation_id: uuid.UUID, question: str, answer: Answer) -> int:
    position = conn.execute(
        "SELECT coalesce(max(position), -1) + 1 AS next FROM messages WHERE conversation_id = %s",
        (conversation_id,),
    ).fetchone()["next"]
    in_history = not answer.refused
    conn.execute(
        """
        INSERT INTO messages (conversation_id, position, role, content, in_history, question_text)
        VALUES (%s, %s, 'user', %s, %s, %s)
        """,
        (conversation_id, position, Json(answer.user_content), in_history, question),
    )
    return conn.execute(
        """
        INSERT INTO messages (conversation_id, position, role, content, in_history, search_queries, sources,
                              stop_reason, usage, cost_usd)
        VALUES (%s, %s, 'assistant', %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            conversation_id,
            position + 1,
            Json(answer.assistant_content),
            in_history,
            Jsonb(answer.search_queries),
            Jsonb([source_record(result) for result in answer.sources]),
            answer.stop_reason,
            Jsonb(answer.usage.model_dump(mode="json")),
            round(answer.cost_usd, 6),
        ),
    ).fetchone()["id"]


def visible_messages(conn: psycopg.Connection, conversation_id: uuid.UUID) -> list[dict]:
    rows = conn.execute(
        """
        SELECT messages.id, messages.role, messages.content, messages.question_text, messages.sources,
               feedback.rating
        FROM messages LEFT JOIN feedback ON feedback.message_id = messages.id
        WHERE messages.conversation_id = %s AND messages.in_history
        ORDER BY messages.position
        """,
        (conversation_id,),
    ).fetchall()
    visible = []
    for row in rows:
        if row["role"] == "user":
            visible.append({"role": "user", "text": row["question_text"]})
        else:
            text = text_of(row["content"])
            visible.append(
                {
                    "role": "assistant",
                    "message_id": row["id"],
                    "text": text,
                    "sources": cited_sources(text, row["sources"] or []),
                    "rating": row["rating"],
                }
            )
    return visible


def record_usage(conn: psycopg.Connection, user_id: int, cost_usd: float) -> None:
    conn.execute(
        """
        INSERT INTO daily_usage (user_id, day, questions, cost_usd)
        VALUES (%s, (now() AT TIME ZONE %s)::date, 1, %s)
        ON CONFLICT (user_id, day) DO UPDATE
        SET questions = daily_usage.questions + 1, cost_usd = daily_usage.cost_usd + EXCLUDED.cost_usd
        """,
        (user_id, config.USAGE_TIMEZONE, round(cost_usd, 6)),
    )


def questions_today(conn: psycopg.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT questions FROM daily_usage WHERE user_id = %s AND day = (now() AT TIME ZONE %s)::date",
        (user_id, config.USAGE_TIMEZONE),
    ).fetchone()
    return row["questions"] if row else 0


def cost_today(conn: psycopg.Connection) -> float:
    row = conn.execute(
        "SELECT coalesce(sum(cost_usd), 0) AS total FROM daily_usage WHERE day = (now() AT TIME ZONE %s)::date",
        (config.USAGE_TIMEZONE,),
    ).fetchone()
    return float(row["total"])


def save_feedback(
    conn: psycopg.Connection, user_id: int | None, message_id: int, rating: int, comment: str | None
) -> bool:
    found = conn.execute(
        """
        SELECT 1 FROM messages JOIN conversations ON conversations.id = messages.conversation_id
        WHERE messages.id = %s AND messages.role = 'assistant' AND conversations.user_id IS NOT DISTINCT FROM %s
        """,
        (message_id, user_id),
    ).fetchone()
    if found is None:
        return False
    conn.execute(
        """
        INSERT INTO feedback (message_id, rating, comment) VALUES (%s, %s, %s)
        ON CONFLICT (message_id) DO UPDATE
        SET rating = EXCLUDED.rating, comment = EXCLUDED.comment, created_at = now()
        """,
        (message_id, rating, comment),
    )
    return True
