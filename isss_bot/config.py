import os
import secrets
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

MAX_QUESTION_CHARACTERS = 1000
RATE_LIMIT_MESSAGES = int(os.environ.get("RATE_LIMIT_MESSAGES") or 20)
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS") or 3600)
TRUSTED_PROXIES = frozenset(filter(None, (os.environ.get("TRUSTED_PROXIES") or "").split(",")))
IP_HASH_SECRET = os.environ.get("IP_HASH_SECRET") or "local-development"
DEV_MODE = (os.environ.get("DEV_MODE") or "").lower() in {"1", "true", "yes"}

ALLOWED_EMAIL_DOMAINS = frozenset(
    domain.strip().lower() for domain in (os.environ.get("ALLOWED_EMAIL_DOMAINS") or "drexel.edu").split(",")
)
JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(32)
COOKIE_SECURE = (os.environ.get("COOKIE_SECURE") or "true").lower() not in {"0", "false", "no"}
MAILER = os.environ.get("MAILER") or "console"
MAIL_FROM = os.environ.get("MAIL_FROM") or ""
AUTH_RATE_LIMIT_ATTEMPTS = int(os.environ.get("AUTH_RATE_LIMIT_ATTEMPTS") or 10)
AUTH_RATE_LIMIT_IP_ATTEMPTS = int(os.environ.get("AUTH_RATE_LIMIT_IP_ATTEMPTS") or 50)
AUTH_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("AUTH_RATE_LIMIT_WINDOW_SECONDS") or 900)
DAILY_QUESTION_LIMIT = int(os.environ.get("DAILY_QUESTION_LIMIT") or 30)
DAILY_COST_CAP_USD = float(os.environ.get("DAILY_COST_CAP_USD") or 3)
USAGE_TIMEZONE = "America/New_York"
CHAT_RETENTION_DAYS = int(os.environ.get("CHAT_RETENTION_DAYS") or 15)
