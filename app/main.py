import hashlib
import hmac
import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import anthropic
import psycopg
import voyageai.error
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, StringConstraints

from app import accounts
from app.accounts import MaybeUser, User
from app.limits import RateLimiter, client_ip
from isss_bot import config, db, migrate, store
from isss_bot.answer import MAX_QUESTIONS, Answer, AnswerError, Conversation, TextDelta
from isss_bot.mailer import Mailer, create_mailer
from isss_bot.search import newer_updates, search

STATIC_DIR = Path(__file__).with_name("static")
SECURITY_HEADERS = {
    "Content-Security-Policy": "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            "img-src 'self' data:",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
}
STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
RATE_LIMIT_MESSAGE = "You've sent a lot of questions in a short time. Please wait a few minutes and try again."
RESTING_MESSAGE = (
    "The assistant is resting until tomorrow because it reached its daily limit. "
    "For anything urgent, contact ISSS directly."
)
REFUSAL_MESSAGE = "I can't help with that one. Try asking about an ISSS topic in a different way."
SAVE_ERROR_MESSAGE = "Something went wrong while saving this answer. Please try again."
UNEXPECTED_ERROR_MESSAGE = "Something went wrong on our side. Please try again."

logger = logging.getLogger("isss_bot.app")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

Question = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=config.MAX_QUESTION_CHARACTERS)
]


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: Question


class FeedbackRequest(BaseModel):
    message_id: int
    rating: Literal[-1, 1]
    comment: Annotated[str | None, Field(max_length=1000)] = None


@dataclass
class AppOptions:
    database_url: str | None = None
    client: anthropic.Anthropic | None = None
    search: Callable = search
    find_updates: Callable = newer_updates
    rate_limit: int = config.RATE_LIMIT_MESSAGES
    rate_window_seconds: int = config.RATE_LIMIT_WINDOW_SECONDS
    max_questions: int = MAX_QUESTIONS
    followup_search: str = config.FOLLOWUP_SEARCH
    dev_mode: bool = config.DEV_MODE
    trusted_proxies: frozenset[str] = config.TRUSTED_PROXIES
    mailer: Mailer | None = None
    cookie_secure: bool = config.COOKIE_SECURE
    auth_rate_limit: int = config.AUTH_RATE_LIMIT_ATTEMPTS
    auth_ip_rate_limit: int = config.AUTH_RATE_LIMIT_IP_ATTEMPTS
    auth_rate_window_seconds: int = config.AUTH_RATE_LIMIT_WINDOW_SECONDS
    daily_question_limit: int = config.DAILY_QUESTION_LIMIT
    daily_cost_cap_usd: float = config.DAILY_COST_CAP_USD


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def log_event(event: str, **fields) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str))


def hash_ip(ip: str) -> str:
    return hmac.new(config.IP_HASH_SECRET.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


def error_kind(error: AnswerError) -> str:
    cause = error.__cause__
    if isinstance(cause, voyageai.error.VoyageError):
        return "search_unavailable"
    if isinstance(cause, anthropic.RateLimitError):
        return "claude_rate_limited"
    if isinstance(cause, anthropic.APIError):
        return "claude_api_error"
    return "unknown"


def create_app(options: AppOptions | None = None) -> FastAPI:
    options = options or AppOptions()
    limiter = RateLimiter(options.rate_limit, options.rate_window_seconds)
    full_message = f"This chat reached {options.max_questions} questions. Start a new chat to keep going."
    daily_limit_message = (
        f"You've asked {options.daily_question_limit} questions today, the daily limit. You can ask more tomorrow."
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        migrate.apply(options.database_url)
        app.state.pool = db.create_pool(options.database_url)
        app.state.client = options.client or anthropic.Anthropic(max_retries=2)
        try:
            yield
        finally:
            app.state.pool.close()

    app = FastAPI(title="ISSS Assistant", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.mailer = options.mailer or create_mailer()
    app.state.cookie_secure = options.cookie_secure
    app.state.trusted_proxies = options.trusted_proxies
    app.state.auth_limiter = RateLimiter(options.auth_rate_limit, options.auth_rate_window_seconds)
    app.state.auth_ip_limiter = RateLimiter(options.auth_ip_rate_limit, options.auth_rate_window_seconds)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(accounts.router)

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        response.headers.setdefault("Cache-Control", "no-store" if request.url.path.startswith("/api/") else "no-cache")
        return response

    def conversation_options(request: Request) -> dict:
        return {
            "client": request.app.state.client,
            "search": options.search,
            "find_updates": options.find_updates,
            "max_questions": options.max_questions,
            "followup_search": options.followup_search,
        }

    def stream_answer(
        pool: ConnectionPool, user_id: int, conversation: Conversation, conversation_id: uuid.UUID, question: str
    ) -> Iterator[str]:
        started = time.monotonic()
        first_token_seconds = None
        answer: Answer | None = None
        yield sse("meta", {"conversation_id": str(conversation_id)})
        with pool.connection() as conn:
            conversation.conn = conn
            try:
                for event in conversation.ask(question):
                    if isinstance(event, TextDelta):
                        first_token_seconds = first_token_seconds or time.monotonic() - started
                        yield sse("token", {"text": event.text})
                    else:
                        answer = event
            except AnswerError as error:
                log_event("answer_error", conversation_id=conversation_id, error=error_kind(error))
                yield sse("error", {"message": str(error)})
                return
            except Exception as error:
                logger.exception("Unexpected error while answering")
                log_event("answer_error", conversation_id=conversation_id, error=type(error).__name__)
                yield sse("error", {"message": UNEXPECTED_ERROR_MESSAGE})
                return
            try:
                message_id = store.save_turn(conn, conversation_id, question, answer)
                store.record_usage(conn, user_id, answer.cost_usd)
                conn.commit()
            except psycopg.Error as error:
                conn.rollback()
                log_event("save_error", conversation_id=conversation_id, error=type(error).__name__)
                yield sse("error", {"message": SAVE_ERROR_MESSAGE})
                return

        usage = answer.usage
        sources = store.cited_sources(answer.text, [store.source_record(source) for source in answer.sources])
        log_event(
            "answer",
            conversation_id=conversation_id,
            message_id=message_id,
            seconds=round(time.monotonic() - started, 2),
            first_token_seconds=round(first_token_seconds, 2) if first_token_seconds else None,
            input_tokens=usage.input_tokens,
            cache_write_tokens=usage.cache_creation_input_tokens,
            cache_read_tokens=usage.cache_read_input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=round(answer.cost_usd, 6),
            stop_reason=answer.stop_reason,
            sources=len(answer.sources),
            cited_pages=len(sources),
            updates=sum(1 for source in answer.sources if source.updates),
            follow_up=len(conversation.questions) > 1,
        )
        if answer.refused:
            yield sse("refused", {"message": REFUSAL_MESSAGE})
            return
        done = {
            "message_id": message_id,
            "sources": sources,
            "conversation_full": conversation.is_full,
        }
        if options.dev_mode:
            done["debug"] = {
                "cost_usd": round(answer.cost_usd, 4),
                "search_queries": answer.search_queries,
                "output_tokens": usage.output_tokens,
            }
        yield sse("done", done)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/login", include_in_schema=False, response_model=None)
    def login_page(user: MaybeUser) -> FileResponse | RedirectResponse:
        if user is not None:
            return RedirectResponse("/", status_code=303)
        return FileResponse(STATIC_DIR / "login.html")

    @app.get("/health")
    def health(request: Request) -> dict:
        try:
            with request.app.state.pool.connection(timeout=5) as conn:
                conn.execute("SELECT 1")
        except psycopg.Error as error:
            raise HTTPException(503, "The database is unavailable.") from error
        return {"status": "ok"}

    @app.post("/api/chat")
    def chat(body: ChatRequest, request: Request, user: User) -> StreamingResponse:
        if not limiter.allow(f"user:{user['id']}"):
            raise HTTPException(429, RATE_LIMIT_MESSAGE)
        with request.app.state.pool.connection() as conn:
            if store.questions_today(conn, user["id"]) >= options.daily_question_limit:
                raise HTTPException(429, daily_limit_message)
            if store.cost_today(conn) >= options.daily_cost_cap_usd:
                log_event("daily_cost_cap_reached", cap_usd=options.daily_cost_cap_usd)
                raise HTTPException(503, RESTING_MESSAGE)
            conversation = None
            if body.conversation_id:
                conversation = store.load_conversation(
                    conn, body.conversation_id, user["id"], **conversation_options(request)
                )
            if conversation is None:
                ip_hash = hash_ip(client_ip(request, options.trusted_proxies))
                conversation_id = store.create_conversation(conn, user["id"], ip_hash)
                conversation = store.load_conversation(
                    conn, conversation_id, user["id"], **conversation_options(request)
                )
            else:
                conversation_id = body.conversation_id
            if conversation.is_full:
                raise HTTPException(409, full_message)
        return StreamingResponse(
            stream_answer(request.app.state.pool, user["id"], conversation, conversation_id, body.message),
            media_type="text/event-stream",
            headers=STREAM_HEADERS,
        )

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: uuid.UUID, request: Request, user: User) -> dict:
        with request.app.state.pool.connection() as conn:
            conversation = store.load_conversation(conn, conversation_id, user["id"], **conversation_options(request))
            if conversation is None:
                raise HTTPException(404, "This chat no longer exists.")
            return {
                "conversation_id": str(conversation_id),
                "messages": store.visible_messages(conn, conversation_id),
                "conversation_full": conversation.is_full,
            }

    @app.post("/api/feedback", status_code=204)
    def feedback(body: FeedbackRequest, request: Request, user: User) -> Response:
        with request.app.state.pool.connection() as conn:
            saved = store.save_feedback(conn, user["id"], body.message_id, body.rating, body.comment)
        if not saved:
            raise HTTPException(404, "That answer no longer exists.")
        return Response(status_code=204)

    return app


app = create_app()
