import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL") or "postgresql://isss:isss_local_dev@localhost:5433/isss"

ISSS_HOME = "https://drexel.edu/studentlife/student-success/international-student-support"
SITEMAP_URL = "https://drexel.edu/sitemap.xml"
ROBOTS_URL = "https://drexel.edu/robots.txt"
USER_AGENT = "DrexelISSSChatBot/0.1 (+https://github.com/andrewto307/DrexelISSSChatBot)"
CRAWL_DELAY_SECONDS = float(os.environ.get("CRAWL_DELAY_SECONDS") or 1.0)

VOYAGE_MODEL = os.environ.get("VOYAGE_MODEL") or "voyage-4"
EMBEDDING_DIMENSIONS = 1024

CHAT_MODEL = os.environ.get("CHAT_MODEL") or "claude-sonnet-5-5"
CHAT_EFFORT = os.environ.get("CHAT_EFFORT") or "low"
REWRITE_MODEL = os.environ.get("REWRITE_MODEL") or "claude-haiku-4-5"
FOLLOWUP_SEARCH = os.environ.get("FOLLOWUP_SEARCH") or "rewrite"
