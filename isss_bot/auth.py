import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from functools import cache

import bcrypt
import jwt
import psycopg

from isss_bot import config

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+")
MIN_PASSWORD_CHARACTERS = 10
MAX_PASSWORD_BYTES = 72
BCRYPT_ROUNDS = 12
CODE_LIFETIME = timedelta(minutes=15)
CODE_RESEND_AFTER = timedelta(seconds=60)
MAX_CODE_ATTEMPTS = 5
SESSION_LIFETIME = timedelta(days=7)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def allowed_email(email: str) -> bool:
    return bool(EMAIL_PATTERN.fullmatch(email)) and email.rsplit("@", 1)[1] in config.ALLOWED_EMAIL_DOMAINS


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_CHARACTERS:
        return f"Use at least {MIN_PASSWORD_CHARACTERS} characters for your password."
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return f"That password is too long. Use {MAX_PASSWORD_BYTES} characters or fewer."
    return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


@cache
def _unused_hash() -> bytes:
    return bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt(BCRYPT_ROUNDS))


def check_password(password: str, password_hash: str | None) -> bool:
    candidate = password.encode()
    if password_hash is None or len(candidate) > MAX_PASSWORD_BYTES:
        bcrypt.checkpw(b"spend the same time as a real check", _unused_hash())
        return False
    return bcrypt.checkpw(candidate, password_hash.encode())


def session_token(user_id: int, session_version: int, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    claims = {"sub": str(user_id), "ver": session_version, "iat": issued, "exp": issued + SESSION_LIFETIME}
    return jwt.encode(claims, config.JWT_SECRET, algorithm="HS256")


def read_session_token(token: str) -> tuple[int, int] | None:
    try:
        claims = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"], options={"require": ["sub", "ver", "exp"]})
        return int(claims["sub"]), int(claims["ver"])
    except (jwt.InvalidTokenError, TypeError, ValueError):
        return None


def code_hash(user_id: int, purpose: str, code: str) -> str:
    message = f"{user_id}:{purpose}:{code}".encode()
    return hmac.new(config.JWT_SECRET.encode(), message, hashlib.sha256).hexdigest()


def find_user(conn: psycopg.Connection, email: str) -> dict | None:
    return conn.execute(
        "SELECT id, email, password_hash, verified_at, session_version FROM users WHERE email = %s", (email,)
    ).fetchone()


def session_user(conn: psycopg.Connection, token: str) -> dict | None:
    session = read_session_token(token)
    if session is None:
        return None
    user_id, session_version = session
    return conn.execute(
        """
        SELECT id, email FROM users
        WHERE id = %s AND session_version = %s AND verified_at IS NOT NULL
        """,
        (user_id, session_version),
    ).fetchone()


def save_unverified_user(conn: psycopg.Connection, email: str, password_hash: str) -> int | None:
    row = conn.execute(
        """
        INSERT INTO users (email, password_hash) VALUES (%s, %s)
        ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash
        WHERE users.verified_at IS NULL
        RETURNING id
        """,
        (email, password_hash),
    ).fetchone()
    return row["id"] if row else None


def issue_code(conn: psycopg.Connection, user_id: int, purpose: str) -> str | None:
    recent = conn.execute(
        "SELECT 1 FROM email_codes WHERE user_id = %s AND purpose = %s AND created_at > now() - %s",
        (user_id, purpose, CODE_RESEND_AFTER),
    ).fetchone()
    if recent:
        return None
    conn.execute(
        "UPDATE email_codes SET used_at = now() WHERE user_id = %s AND purpose = %s AND used_at IS NULL",
        (user_id, purpose),
    )
    code = f"{secrets.randbelow(10**6):06d}"
    conn.execute(
        "INSERT INTO email_codes (user_id, purpose, code_hash, expires_at) VALUES (%s, %s, %s, now() + %s)",
        (user_id, purpose, code_hash(user_id, purpose, code), CODE_LIFETIME),
    )
    return code


def use_code(conn: psycopg.Connection, user_id: int, purpose: str, code: str) -> bool:
    row = conn.execute(
        """
        SELECT id, code_hash, attempts FROM email_codes
        WHERE user_id = %s AND purpose = %s AND used_at IS NULL AND expires_at > now()
        ORDER BY created_at DESC LIMIT 1
        FOR UPDATE
        """,
        (user_id, purpose),
    ).fetchone()
    if row is None or row["attempts"] >= MAX_CODE_ATTEMPTS:
        return False
    if not hmac.compare_digest(row["code_hash"], code_hash(user_id, purpose, code.strip())):
        conn.execute("UPDATE email_codes SET attempts = attempts + 1 WHERE id = %s", (row["id"],))
        return False
    conn.execute("UPDATE email_codes SET used_at = now() WHERE id = %s", (row["id"],))
    return True


def mark_verified(conn: psycopg.Connection, user_id: int) -> None:
    conn.execute("UPDATE users SET verified_at = coalesce(verified_at, now()) WHERE id = %s", (user_id,))


def set_password(conn: psycopg.Connection, user_id: int, password_hash: str) -> int:
    return conn.execute(
        """
        UPDATE users
        SET password_hash = %s, session_version = session_version + 1, verified_at = coalesce(verified_at, now())
        WHERE id = %s
        RETURNING session_version
        """,
        (password_hash, user_id),
    ).fetchone()["session_version"]


def end_sessions(conn: psycopg.Connection, user_id: int) -> None:
    conn.execute("UPDATE users SET session_version = session_version + 1 WHERE id = %s", (user_id,))


def record_login(conn: psycopg.Connection, user_id: int) -> None:
    conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))
