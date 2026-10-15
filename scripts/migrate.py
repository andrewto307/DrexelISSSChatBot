import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isss_bot import migrate


def main() -> int:
    applied = migrate.apply()
    print("Applied: " + ", ".join(applied) if applied else "Database is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
