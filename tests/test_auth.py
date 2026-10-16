from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.accounts import SESSION_COOKIE
from app.main import AppOptions, create_app
from isss_bot import auth, db
from isss_bot.mailer import ConsoleMailer
from tests.fakes import PASSWORD, RESET_TABLES, FakeClient, FakeMailer, claude_message, search_result

EMAIL = "abc123@drexel.edu"
NEW_PASSWORD = "a different long password"


@pytest.fixture
def make_site(migrated_database_url):
    with db.connect(migrated_database_url) as conn:
        conn.execute(RESET_TABLES)
        conn.commit()
    clients = []

    def make(**options) -> tuple[TestClient, FakeMailer]:
        mailer = FakeMailer()
        settings = {"mailer": mailer, "cookie_secure": False, **options}
        app = create_app(
            AppOptions(
                database_url=migrated_database_url,
                client=FakeClient(default_reply=claude_message("Answer.")),
                search=lambda conn, query, limit=6: [search_result()],
                find_updates=lambda conn, results: [],
                **settings,
            )
        )
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client, mailer

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def _sign_up(client: TestClient, mailer: FakeMailer, email: str = EMAIL) -> None:
    assert client.post("/api/auth/signup", json={"email": email, "password": PASSWORD}).status_code == 202
    code = mailer.last_code(email, "verify")
    assert client.post("/api/auth/verify", json={"email": email, "code": code}).status_code == 200


def _run_sql(database_url: str, query: str, params: tuple = ()) -> None:
    with db.connect(database_url) as conn:
        conn.execute(query, params)
        conn.commit()


@pytest.mark.parametrize(
    "email",
    ["abc123@drexel.edu", "ABC123@Drexel.EDU"],
)
def test_drexel_addresses_are_allowed(email):
    assert auth.allowed_email(auth.normalize_email(email))


@pytest.mark.parametrize(
    "email",
    [
        "abc123@gmail.com",
        "abc123@drexel.edu.evil.com",
        "abc123@evil-drexel.edu",
        "abc123@mail.drexel.edu",
        "abc@evil.com@drexel.edu",
        "drexel.edu",
        "@drexel.edu",
        "abc 123@drexel.edu",
    ],
)
def test_other_and_look_alike_addresses_are_rejected(email):
    assert not auth.allowed_email(auth.normalize_email(email))


def test_password_rules_and_hashing():
    assert auth.password_problem("short") is not None
    assert auth.password_problem("x" * 73) is not None
    assert auth.password_problem(PASSWORD) is None

    password_hash = auth.hash_password(PASSWORD)
    assert password_hash != PASSWORD
    assert auth.check_password(PASSWORD, password_hash)
    assert not auth.check_password("wrong password!", password_hash)
    assert not auth.check_password(PASSWORD, None)
    assert not auth.check_password("x" * 100, password_hash)


def test_session_tokens_reject_tampering_expiry_and_other_secrets(monkeypatch):
    token = auth.session_token(7, 2)
    assert auth.read_session_token(token) == (7, 2)
    assert auth.read_session_token(token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")) is None
    assert auth.read_session_token(auth.session_token(7, 2, now=datetime.now(UTC) - timedelta(days=8))) is None
    assert auth.read_session_token("not a token") is None
    monkeypatch.setattr(auth.config, "JWT_SECRET", "another secret that is long enough to use")
    assert auth.read_session_token(token) is None


def test_sign_up_verify_and_chat(make_site):
    client, mailer = make_site()
    response = client.post("/api/auth/signup", json={"email": " ABC123@drexel.edu ", "password": PASSWORD})
    assert response.status_code == 202
    assert response.json()["email"] == EMAIL
    [mail] = mailer.sent
    assert mail["email"] == EMAIL and mail["purpose"] == "verify" and len(mail["code"]) == 6

    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/chat", json={"message": "Can I do CPT?"}).status_code == 401

    response = client.post("/api/auth/verify", json={"email": EMAIL, "code": mail["code"]})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=604800" in cookie
    assert client.get("/api/auth/me").json() == {"email": EMAIL}
    assert client.post("/api/chat", json={"message": "Can I do CPT?"}).status_code == 200


def test_sign_up_rejects_other_domains_and_short_passwords(make_site, migrated_database_url):
    client, mailer = make_site()
    for email in ["abc123@gmail.com", "abc123@drexel.edu.evil.com"]:
        response = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD})
        assert response.status_code == 400
        assert "@drexel.edu" in response.json()["detail"]
    response = client.post("/api/auth/signup", json={"email": EMAIL, "password": "short"})
    assert response.status_code == 400
    assert "at least 10 characters" in response.json()["detail"]
    assert mailer.sent == []
    with db.connect(migrated_database_url) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()["count"] == 0


def test_unverified_accounts_cannot_log_in(make_site):
    client, mailer = make_site()
    client.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})

    response = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 403
    assert "Verify your email" in response.json()["detail"]
    assert client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong password!"}).status_code == 401
    assert SESSION_COOKIE not in client.cookies


def test_log_in_and_log_out(make_site):
    client, mailer = make_site()
    _sign_up(client, mailer)
    copied_cookie = client.cookies[SESSION_COOKIE]
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(SESSION_COOKIE, copied_cookie)
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.clear()

    response = client.post("/api/auth/login", json={"email": "Abc123@Drexel.edu", "password": PASSWORD})
    assert response.status_code == 200
    assert client.get("/api/auth/me").json() == {"email": EMAIL}

    wrong = client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong password!"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@drexel.edu", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_wrong_and_expired_codes_fail(make_site, migrated_database_url):
    client, mailer = make_site()
    client.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})
    code = mailer.last_code(EMAIL, "verify")
    wrong = "000000" if code != "000000" else "111111"

    response = client.post("/api/auth/verify", json={"email": EMAIL, "code": wrong})
    assert response.status_code == 400
    assert "wrong or has expired" in response.json()["detail"]

    _run_sql(migrated_database_url, "UPDATE email_codes SET expires_at = now() - interval '1 minute'")
    assert client.post("/api/auth/verify", json={"email": EMAIL, "code": code}).status_code == 400


def test_a_code_stops_working_after_five_wrong_tries(make_site):
    client, mailer = make_site()
    client.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})
    code = mailer.last_code(EMAIL, "verify")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(auth.MAX_CODE_ATTEMPTS):
        assert client.post("/api/auth/verify", json={"email": EMAIL, "code": wrong}).status_code == 400

    assert client.post("/api/auth/verify", json={"email": EMAIL, "code": code}).status_code == 400


def test_a_new_code_replaces_the_old_one_after_a_minute(make_site, migrated_database_url):
    client, mailer = make_site()
    client.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})
    first = mailer.last_code(EMAIL, "verify")
    assert client.post("/api/auth/resend", json={"email": EMAIL}).status_code == 202
    assert len(mailer.sent) == 1

    _run_sql(migrated_database_url, "UPDATE email_codes SET created_at = now() - interval '2 minutes'")
    client.post("/api/auth/resend", json={"email": EMAIL})
    second = mailer.last_code(EMAIL, "verify")
    assert len(mailer.sent) == 2
    if first != second:
        assert client.post("/api/auth/verify", json={"email": EMAIL, "code": first}).status_code == 400
    assert client.post("/api/auth/verify", json={"email": EMAIL, "code": second}).status_code == 200


def test_sign_up_and_forgot_password_answer_the_same_for_any_email(make_site):
    client, mailer = make_site()
    _sign_up(client, mailer)

    taken = client.post("/api/auth/signup", json={"email": EMAIL, "password": NEW_PASSWORD})
    fresh = client.post("/api/auth/signup", json={"email": "new1@drexel.edu", "password": NEW_PASSWORD})
    assert taken.status_code == fresh.status_code == 202
    assert taken.json()["message"].replace(EMAIL, "") == fresh.json()["message"].replace("new1@drexel.edu", "")
    assert mailer.sent[-2] == {"email": EMAIL, "purpose": "exists", "code": None}
    assert client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200

    known = client.post("/api/auth/forgot", json={"email": EMAIL})
    unknown = client.post("/api/auth/forgot", json={"email": "nobody@drexel.edu"})
    assert known.status_code == unknown.status_code == 202
    assert known.json()["message"].replace(EMAIL, "") == unknown.json()["message"].replace("nobody@drexel.edu", "")
    assert mailer.sent[-1]["purpose"] == "reset"
    assert not any(mail["email"] == "nobody@drexel.edu" for mail in mailer.sent)


def test_a_password_reset_logs_in_and_ends_other_sessions(make_site):
    first_device, mailer = make_site()
    _sign_up(first_device, mailer)
    second_device = TestClient(first_device.app)

    second_device.post("/api/auth/forgot", json={"email": EMAIL})
    code = mailer.last_code(EMAIL, "reset")
    short = second_device.post("/api/auth/reset", json={"email": EMAIL, "code": code, "password": "short"})
    assert short.status_code == 400
    response = second_device.post("/api/auth/reset", json={"email": EMAIL, "code": code, "password": NEW_PASSWORD})
    assert response.status_code == 200

    assert second_device.get("/api/auth/me").json() == {"email": EMAIL}
    assert first_device.get("/api/auth/me").status_code == 401
    assert first_device.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 401
    assert first_device.post("/api/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD}).status_code == 200


def test_tampered_and_expired_session_cookies_are_rejected(make_site, migrated_database_url):
    client, mailer = make_site()
    _sign_up(client, mailer)
    token = client.cookies[SESSION_COOKIE]

    client.cookies.set(SESSION_COOKIE, token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb"))
    assert client.get("/api/auth/me").status_code == 401
    with db.connect(migrated_database_url) as conn:
        user_id = auth.find_user(conn, EMAIL)["id"]
    client.cookies.set(SESSION_COOKIE, auth.session_token(user_id, 0, now=datetime.now(UTC) - timedelta(days=8)))
    assert client.get("/api/auth/me").status_code == 401


def test_login_attempts_are_rate_limited(make_site):
    client, _ = make_site(auth_rate_limit=3)
    for _ in range(3):
        assert client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong password!"}).status_code == 401
    response = client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong password!"})
    assert response.status_code == 429
    assert "Too many attempts" in response.json()["detail"]


def test_one_network_gets_more_attempts_than_one_email(make_site):
    client, _ = make_site(auth_rate_limit=2, auth_ip_rate_limit=4)
    for number in range(4):
        login = {"email": f"student{number}@drexel.edu", "password": "wrong password!"}
        assert client.post("/api/auth/login", json=login).status_code == 401
    response = client.post("/api/auth/login", json={"email": "student9@drexel.edu", "password": "wrong password!"})
    assert response.status_code == 429


def test_session_cookies_are_secure_when_configured(make_site):
    client, mailer = make_site(cookie_secure=True)
    client.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})
    response = client.post("/api/auth/verify", json={"email": EMAIL, "code": mailer.last_code(EMAIL, "verify")})
    assert "Secure" in response.headers["set-cookie"]


def test_the_console_mailer_prints_each_kind_of_email(capsys):
    mailer = ConsoleMailer()
    mailer.send(EMAIL, "verify", "123456")
    mailer.send(EMAIL, "reset", "654321")
    mailer.send(EMAIL, "exists")
    printed = capsys.readouterr().out
    assert "Email to abc123@drexel.edu" in printed
    assert "123456 is your ISSS Assistant code" in printed
    assert "654321 is your ISSS Assistant password reset code" in printed
    assert "already has an account" in printed
