import argparse
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isss_bot import db
from isss_bot.store import text_of, unique_sources

NOT_HELPFUL = """
SELECT feedback.created_at, feedback.comment, answer.id AS message_id, answer.content, answer.sources,
       question.question_text
FROM feedback
JOIN messages AS answer ON answer.id = feedback.message_id
JOIN messages AS question
  ON question.conversation_id = answer.conversation_id AND question.position = answer.position - 1
WHERE feedback.rating = -1 AND feedback.created_at > now() - make_interval(days => %s)
ORDER BY feedback.created_at DESC
"""

RECENT_QUESTIONS = """
SELECT conversation_id, position, question_text FROM messages
WHERE role = 'user' AND in_history AND created_at > now() - make_interval(days => %s)
ORDER BY created_at DESC
LIMIT %s
"""

EARLIER_QUESTIONS = """
SELECT question_text FROM messages
WHERE conversation_id = %s AND role = 'user' AND in_history AND position < %s
ORDER BY position
"""


def print_not_helpful(conn, days: int) -> None:
    rows = conn.execute(NOT_HELPFUL, (days,)).fetchall()
    print(f"Answers rated not helpful in the last {days} days: {len(rows)}\n")
    for row in rows:
        print(f"{row['created_at']:%Y-%m-%d %H:%M} · message {row['message_id']}")
        print(f"Question: {row['question_text']}")
        print(textwrap.indent(textwrap.shorten(text_of(row["content"]), 600), "Answer:   ").lstrip())
        for source in unique_sources(row["sources"] or []):
            print(f"Source:   {source['url']}")
        if row["comment"]:
            print(f"Comment:  {row['comment']}")
        print()


def print_question_drafts(conn, days: int, limit: int) -> None:
    rows = conn.execute(RECENT_QUESTIONS, (days, limit)).fetchall()
    for number, row in enumerate(reversed(rows), start=1):
        history = [
            earlier["question_text"]
            for earlier in conn.execute(EARLIER_QUESTIONS, (row["conversation_id"], row["position"]))
        ]
        draft = {
            "id": f"r{number:03d}",
            "type": "follow-up" if history else "",
            "history": history,
            "question": row["question_text"],
            "expected_urls": [],
            "notes": "",
        }
        print(json.dumps(draft, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Review student feedback and collect real questions for the eval set.")
    parser.add_argument("--days", type=int, default=30, help="how far back to look (default 30)")
    parser.add_argument(
        "--questions", type=int, metavar="N", help="print the N most recent questions as draft eval lines"
    )
    args = parser.parse_args()
    with db.connect() as conn:
        if args.questions:
            print_question_drafts(conn, args.days, args.questions)
        else:
            print_not_helpful(conn, args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
