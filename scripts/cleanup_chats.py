import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isss_bot import config, db, store


def main() -> int:
    with db.connect() as conn:
        deleted = store.delete_old_conversations(conn, config.CHAT_RETENTION_DAYS)
        conn.commit()
    summary = {"event": "chat_cleanup", "conversations_deleted": deleted, "older_than_days": config.CHAT_RETENTION_DAYS}
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
