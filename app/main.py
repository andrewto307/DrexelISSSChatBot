import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import anthropic
import psycopg
import voyageai.error
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, StringConstraints

from isss_bot import config, db, migrate, store
from isss_bot.answer import MAX_QUESTIONS, Answer, AnswerError, Conversation, TextDelta
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


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self.lock:
            hits = self.hits[key]
            while hits and hits[0] <= now - self.window_seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def log_event(event: str, **fields) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str))


def client_ip(request: Request, trusted_proxies: frozenset[str]) -> str:
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer in trusted_proxies:
        return forwarded.split(",")[-1].strip()
    return peer


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


def current_user() -> None:
    return None


def create_app(options: AppOptions | None = None) -> FastAPI:
    options = options or AppOptions()
    limiter = RateLimiter(options.rate_limit, options.rate_window_seconds)
    full_message = f"This chat reached {options.max_questions} questions. Start a new chat to keep going."

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
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
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
        pool: ConnectionPool, conversation: Conversation, conversation_id: uuid.UUID, question: str
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

    @app.get("/health")
    def health(request: Request) -> dict:
        try:
            with request.app.state.pool.connection(timeout=5) as conn:
                conn.execute("SELECT 1")
        except psycopg.Error as error:
            raise HTTPException(503, "The database is unavailable.") from error
        return {"status": "ok"}

    @app.post("/api/chat")
    def chat(body: ChatRequest, request: Request, user: None = Depends(current_user)) -> StreamingResponse:
        ip = client_ip(request, options.trusted_proxies)
        if not limiter.allow(ip):
            raise HTTPException(429, RATE_LIMIT_MESSAGE)
        with request.app.state.pool.connection() as conn:
            conversation = None
            if body.conversation_id:
                conversation = store.load_conversation(conn, body.conversation_id, **conversation_options(request))
            if conversation is None:
                conversation_id = store.create_conversation(conn, hash_ip(ip))
                conversation = store.load_conversation(conn, conversation_id, **conversation_options(request))
            else:
                conversation_id = body.conversation_id
            if conversation.is_full:
                raise HTTPException(409, full_message)
        return StreamingResponse(
            stream_answer(request.app.state.pool, conversation, conversation_id, body.message),
            media_type="text/event-stream",
            headers=STREAM_HEADERS,
        )

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: uuid.UUID, request: Request, user: None = Depends(current_user)) -> dict:
        with request.app.state.pool.connection() as conn:
            conversation = store.load_conversation(conn, conversation_id, **conversation_options(request))
            if conversation is None:
                raise HTTPException(404, "This chat no longer exists.")
            return {
                "conversation_id": str(conversation_id),
                "messages": store.visible_messages(conn, conversation_id),
                "conversation_full": conversation.is_full,
            }

    @app.post("/api/feedback", status_code=204)
    def feedback(body: FeedbackRequest, request: Request, user: None = Depends(current_user)) -> Response:
        with request.app.state.pool.connection() as conn:
            if not store.save_feedback(conn, body.message_id, body.rating, body.comment):
                raise HTTPException(404, "That answer no longer exists.")
        return Response(status_code=204)

    return app


app = create_app()
