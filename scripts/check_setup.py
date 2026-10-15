import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
import psycopg
import voyageai
import voyageai.error

from isss_bot import config

ROOT = Path(__file__).resolve().parent.parent

failures = 0


def report(status: str, name: str, detail: str) -> None:
    global failures
    if status == "fail":
        failures += 1
    icon = {"ok": "✓", "warn": "!", "fail": "✗"}[status]
    print(f"{icon} {name}: {detail}")


def check_env_file() -> None:
    if not (ROOT / ".env").exists():
        report("fail", ".env", "missing; copy .env.example to .env and fill it in")
        return
    report("ok", ".env", "found")


def check_anthropic() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        report("fail", "Anthropic", "ANTHROPIC_API_KEY is not set in .env")
        return
    try:
        model = anthropic.Anthropic().models.retrieve(config.CHAT_MODEL)
    except anthropic.AuthenticationError:
        report("fail", "Anthropic", "key rejected; it may have been rotated, so update .env")
    except anthropic.NotFoundError:
        report("fail", "Anthropic", f"key works, but {config.CHAT_MODEL} isn't available to this account")
    except anthropic.APIConnectionError:
        report("fail", "Anthropic", "can't reach the API; check your internet connection")
    except anthropic.APIStatusError as e:
        error = e.body.get("error", {}) if isinstance(e.body, dict) else {}
        report("fail", "Anthropic", f"API error {e.status_code}: {error.get('message', 'no details')}")
    else:
        report("ok", "Anthropic", f"key works; {model.display_name} ({config.CHAT_MODEL}) available")


def check_database() -> None:
    try:
        with psycopg.connect(config.DATABASE_URL, connect_timeout=5) as conn:
            version = conn.execute("SHOW server_version").fetchone()[0].split()[0]
            vector = conn.execute(
                "SELECT default_version, installed_version FROM pg_available_extensions WHERE name = 'vector'"
            ).fetchone()
    except psycopg.OperationalError:
        report("fail", "Postgres", "can't connect; start it with `docker compose up -d`")
        return
    if vector is None:
        report("fail", "Postgres", f"{version} reachable, but the pgvector extension isn't available")
    elif vector[1] is None:
        report("ok", "Postgres", f"{version}; pgvector {vector[0]} available (not enabled in this database yet)")
    else:
        report("ok", "Postgres", f"{version}; pgvector {vector[1]} enabled")


def check_voyage() -> None:
    if not os.environ.get("VOYAGE_API_KEY"):
        report("warn", "Voyage AI", "VOYAGE_API_KEY not set")
        return
    model = config.VOYAGE_MODEL
    try:
        result = voyageai.Client().embed(
            ["setup check"], model=model, input_type="query", output_dimension=config.EMBEDDING_DIMENSIONS
        )
    except voyageai.error.AuthenticationError:
        report("fail", "Voyage AI", "key rejected; update VOYAGE_API_KEY in .env")
    except voyageai.error.InvalidRequestError:
        report("fail", "Voyage AI", f"key works, but the request failed; is VOYAGE_MODEL={model} correct?")
    except voyageai.error.VoyageError as e:
        report("fail", "Voyage AI", f"{type(e).__name__}; check your connection and try again")
    else:
        report("ok", "Voyage AI", f"key works; {model} returns {len(result.embeddings[0])}-dimension vectors")


def main() -> int:
    check_env_file()
    check_anthropic()
    check_database()
    check_voyage()
    print("\nAll required checks passed." if failures == 0 else f"\n{failures} required check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
