from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.events import log_event
from app.limits import client_ip
from isss_bot import auth
from isss_bot.mailer import MailError

SESSION_COOKIE = "isss_session"
LOGIN_REQUIRED_MESSAGE = "Your session has ended. Log in to keep chatting."
DOMAIN_MESSAGE = "Use your Drexel email address (ending in @drexel.edu)."
TOO_MANY_ATTEMPTS_MESSAGE = "Too many attempts. Wait 15 minutes and try again."
WRONG_LOGIN_MESSAGE = "That email and password don't match an account."
VERIFY_FIRST_MESSAGE = "Verify your email first. Enter the 6-digit code we sent you."
WRONG_CODE_MESSAGE = "That code is wrong or has expired. Check the email, or send a new code."
EMAIL_ERROR_MESSAGE = "We couldn't send the email right now. Please try again in a few minutes."

router = APIRouter(prefix="/api/auth")

Email = Annotated[str, Field(max_length=254)]
Password = Annotated[str, Field(max_length=200)]
Code = Annotated[str, Field(max_length=20)]


class EmailRequest(BaseModel):
    email: Email


class PasswordRequest(BaseModel):
    email: Email
    password: Password


class CodeRequest(BaseModel):
    email: Email
    code: Code


class ResetRequest(BaseModel):
    email: Email
    code: Code
    password: Password


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with request.app.state.pool.connection() as conn:
        return auth.session_user(conn, token)


MaybeUser = Annotated[dict | None, Depends(current_user)]


def require_user(user: MaybeUser) -> dict:
    if user is None:
        raise HTTPException(401, LOGIN_REQUIRED_MESSAGE)
    return user


User = Annotated[dict, Depends(require_user)]


def limit_attempts(request: Request, email: str) -> None:
    state = request.app.state
    ip = client_ip(request, state.trusted_proxies)
    if not (state.auth_ip_limiter.allow(ip) and state.auth_limiter.allow(email)):
        raise HTTPException(429, TOO_MANY_ATTEMPTS_MESSAGE)


def start_session(request: Request, response: Response, user_id: int, session_version: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        auth.session_token(user_id, session_version),
        max_age=int(auth.SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=request.app.state.cookie_secure,
        samesite="lax",
    )


def send_email(request: Request, email: str, purpose: str, code: str | None = None) -> None:
    try:
        request.app.state.mailer.send(email, purpose, code)
    except MailError as error:
        log_event("email_error", purpose=purpose, error=str(error))
        raise HTTPException(503, EMAIL_ERROR_MESSAGE) from error


def code_sent(email: str) -> dict:
    return {"email": email, "message": f"We sent a 6-digit code to {email}. It expires in 15 minutes."}


@router.post("/signup", status_code=202)
def signup(body: PasswordRequest, request: Request) -> dict:
    email = auth.normalize_email(body.email)
    if not auth.allowed_email(email):
        raise HTTPException(400, DOMAIN_MESSAGE)
    if problem := auth.password_problem(body.password):
        raise HTTPException(400, problem)
    limit_attempts(request, email)
    password_hash = auth.hash_password(body.password)
    purpose, code = "exists", None
    with request.app.state.pool.connection() as conn:
        user = auth.find_user(conn, email)
        user_id = None if user and user["verified_at"] else auth.save_unverified_user(conn, email, password_hash)
        if user_id is not None:
            purpose, code = "verify", auth.issue_code(conn, user_id, "verify")
    if purpose == "exists" or code:
        send_email(request, email, purpose, code)
    return code_sent(email)


@router.post("/resend", status_code=202)
def resend(body: EmailRequest, request: Request) -> dict:
    email = auth.normalize_email(body.email)
    limit_attempts(request, email)
    code = None
    with request.app.state.pool.connection() as conn:
        user = auth.find_user(conn, email)
        if user and not user["verified_at"]:
            code = auth.issue_code(conn, user["id"], "verify")
    if code:
        send_email(request, email, "verify", code)
    return code_sent(email)


@router.post("/verify")
def verify(body: CodeRequest, request: Request, response: Response) -> dict:
    email = auth.normalize_email(body.email)
    limit_attempts(request, email)
    with request.app.state.pool.connection() as conn:
        user = auth.find_user(conn, email)
        verified = bool(user and not user["verified_at"] and auth.use_code(conn, user["id"], "verify", body.code))
        if verified:
            auth.mark_verified(conn, user["id"])
            auth.record_login(conn, user["id"])
    if not verified:
        raise HTTPException(400, WRONG_CODE_MESSAGE)
    start_session(request, response, user["id"], user["session_version"])
    return {"email": email}


@router.post("/login")
def login(body: PasswordRequest, request: Request, response: Response) -> dict:
    email = auth.normalize_email(body.email)
    limit_attempts(request, email)
    code = None
    with request.app.state.pool.connection() as conn:
        user = auth.find_user(conn, email)
        matched = auth.check_password(body.password, user["password_hash"] if user else None)
        if matched and user["verified_at"]:
            auth.record_login(conn, user["id"])
        elif matched:
            code = auth.issue_code(conn, user["id"], "verify")
    if not matched:
        raise HTTPException(401, WRONG_LOGIN_MESSAGE)
    if not user["verified_at"]:
        if code:
            send_email(request, email, "verify", code)
        raise HTTPException(403, VERIFY_FIRST_MESSAGE)
    start_session(request, response, user["id"], user["session_version"])
    return {"email": email}


@router.post("/logout", status_code=204)
def logout(request: Request, user: MaybeUser) -> Response:
    if user:
        with request.app.state.pool.connection() as conn:
            auth.end_sessions(conn, user["id"])
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=request.app.state.cookie_secure, samesite="lax")
    return response


@router.post("/forgot", status_code=202)
def forgot(body: EmailRequest, request: Request) -> dict:
    email = auth.normalize_email(body.email)
    limit_attempts(request, email)
    code = None
    with request.app.state.pool.connection() as conn:
        user = auth.find_user(conn, email)
        if user:
            code = auth.issue_code(conn, user["id"], "reset")
    if code:
        send_email(request, email, "reset", code)
    return {"email": email, "message": f"If {email} has an account, we sent it a 6-digit code."}


@router.post("/reset")
def reset(body: ResetRequest, request: Request, response: Response) -> dict:
    email = auth.normalize_email(body.email)
    if problem := auth.password_problem(body.password):
        raise HTTPException(400, problem)
    limit_attempts(request, email)
    password_hash = auth.hash_password(body.password)
    with request.app.state.pool.connection() as conn:
        user = auth.find_user(conn, email)
        changed = bool(user and auth.use_code(conn, user["id"], "reset", body.code))
        if changed:
            session_version = auth.set_password(conn, user["id"], password_hash)
            auth.record_login(conn, user["id"])
    if not changed:
        raise HTTPException(400, WRONG_CODE_MESSAGE)
    start_session(request, response, user["id"], session_version)
    return {"email": email}


@router.get("/me")
def me(user: User) -> dict:
    return {"email": user["email"]}
