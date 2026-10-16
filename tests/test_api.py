import json
import uuid

import anthropic
import pytest
from fastapi.testclient import TestClient

from app.accounts import SESSION_COOKIE
from app.main import AppOptions, RateLimiter, client_ip, create_app
from isss_bot import db
from isss_bot.answer import content_as_sent
from tests.fakes import (
    CPT_URL,
    REQUEST,
    RESET_TABLES,
    FakeClient,
    FakeMailer,
    claude_message,
    search_result,
    session_cookie_for,
)

UPDATE_URL = "https://drexel.edu/x/announcements/2026/September/postponed"
ANSWER = f"CPT needs one academic year. See [CPT]({CPT_URL})."


def parse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def fake_search(conn, query, limit=6):
    return [search_result(), search_result(index=1, heading_path="CPT › Procedure")]


def fake_updates(conn, results):
    return [search_result(url=UPDATE_URL, title="Court postpones the rule", page_type="announcement", updates=CPT_URL)]


@pytest.fixture
def make_client(migrated_database_url):
    with db.connect(migrated_database_url) as conn:
        conn.execute(RESET_TABLES)
        conn.commit()
    clients = []

    def make(fake: FakeClient | None = None, user: str | None = "student@drexel.edu", **options) -> TestClient:
        settings = {"mailer": FakeMailer(), "cookie_secure": False, **options}
        app = create_app(
            AppOptions(
                database_url=migrated_database_url,
                client=fake or FakeClient(default_reply=claude_message(ANSWER)),
                search=fake_search,
                find_updates=fake_updates,
                **settings,
            )
        )
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        if user:
            with db.connect(migrated_database_url) as conn:
                client.cookies.set(SESSION_COOKIE, session_cookie_for(conn, user))
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def _chat(client: TestClient, message: str, conversation_id: str | None = None):
    response = client.post("/api/chat", json={"conversation_id": conversation_id, "message": message})
    return response, parse_events(response.text) if response.status_code == 200 else []


def _stored(migrated_database_url) -> list[dict]:
    with db.connect(migrated_database_url) as conn:
        return conn.execute("SELECT role, content, in_history FROM messages ORDER BY id").fetchall()


def test_chat_streams_meta_tokens_and_done(make_client, migrated_database_url):
    response, events = _chat(make_client(), "Can I do CPT in my first year?")

    assert response.headers["content-type"].startswith("text/event-stream")
    names = [name for name, _ in events]
    assert names[0] == "meta" and names[-1] == "done" and set(names[1:-1]) == {"token"}
    assert "".join(data["text"] for name, data in events if name == "token") == ANSWER
    done = events[-1][1]
    assert [source["url"] for source in done["sources"]] == [CPT_URL]
    assert done["conversation_full"] is False
    assert "debug" not in done

    user, assistant = _stored(migrated_database_url)
    assert "Student question: Can I do CPT in my first year?" in user["content"]
    assert assistant["content"] == [{"type": "text", "text": ANSWER}]


def test_sources_are_the_pages_the_answer_links_to(make_client):
    text = f"Generally no ([CPT]({CPT_URL}/#eligibility)). A court postponed the rule: {UPDATE_URL}."
    _, events = _chat(make_client(FakeClient(default_reply=claude_message(text))), "Can I do CPT?")
    sources = events[-1][1]["sources"]
    assert [source["url"] for source in sources] == [CPT_URL, UPDATE_URL]
    assert sources[1]["updates"] == CPT_URL


def test_follow_up_after_a_restart_resends_the_stored_history_exactly(make_client):
    fake = FakeClient(
        [claude_message("One academic year.", thinking="cpt rule"), claude_message("Use the portal.")],
        rewrite_reply=claude_message("How do I apply for CPT?"),
    )
    _, events = _chat(make_client(fake), "Can I do CPT now?")
    conversation_id = events[0][1]["conversation_id"]

    _, events = _chat(make_client(fake), "How do I apply?", conversation_id)

    assert events[0][1]["conversation_id"] == conversation_id
    first_call, second_call = fake.messages.stream_calls
    assert second_call["messages"][0] == first_call["messages"][0]
    assert second_call["messages"][1] == {
        "role": "assistant",
        "content": content_as_sent(claude_message("One academic year.", thinking="cpt rule").content),
    }
    assert second_call["messages"][1]["content"][0]["signature"] == "signature-for-cpt rule"


def test_refusals_are_reported_and_left_out_of_history(make_client, migrated_database_url):
    fake = FakeClient([claude_message("", stop_reason="refusal"), claude_message("Answer.")])
    client = make_client(fake, followup_search="concat")
    _, events = _chat(client, "Something odd")
    assert events[-1][0] == "refused"

    _chat(client, "Can I do CPT?", events[0][1]["conversation_id"])
    assert [row["in_history"] for row in _stored(migrated_database_url)] == [False, False, True, True]
    assert len(fake.messages.stream_calls[1]["messages"]) == 1


def test_api_errors_send_an_error_event_and_save_nothing(make_client, migrated_database_url):
    _, events = _chat(make_client(FakeClient([anthropic.APIConnectionError(request=REQUEST)])), "Can I do CPT?")
    assert [name for name, _ in events] == ["meta", "error"]
    assert "Couldn't reach the Claude API" in events[1][1]["message"]
    assert _stored(migrated_database_url) == []


def test_unexpected_failures_end_the_stream_with_an_error_event(make_client, migrated_database_url):
    _, events = _chat(make_client(FakeClient([RuntimeError("boom")])), "Can I do CPT?")
    assert [name for name, _ in events] == ["meta", "error"]
    assert _stored(migrated_database_url) == []


def test_unknown_conversation_ids_start_a_new_chat(make_client):
    unknown = str(uuid.uuid4())
    _, events = _chat(make_client(), "Can I do CPT?", unknown)
    assert events[0][1]["conversation_id"] != unknown


def test_feedback_is_saved_updated_and_validated(make_client, migrated_database_url):
    client = make_client()
    _, events = _chat(client, "Can I do CPT?")
    message_id = events[-1][1]["message_id"]

    assert client.post("/api/feedback", json={"message_id": message_id, "rating": 1}).status_code == 204
    response = client.post("/api/feedback", json={"message_id": message_id, "rating": -1, "comment": "Too long"})
    assert response.status_code == 204
    with db.connect(migrated_database_url) as conn:
        row = conn.execute("SELECT rating, comment FROM feedback WHERE message_id = %s", (message_id,)).fetchone()
    assert row == {"rating": -1, "comment": "Too long"}
    assert client.post("/api/feedback", json={"message_id": 999_999_999, "rating": 1}).status_code == 404
    assert client.post("/api/feedback", json={"message_id": message_id, "rating": 5}).status_code == 422


def test_rate_limit_returns_429_with_a_friendly_message(make_client):
    client = make_client(rate_limit=1)
    assert _chat(client, "First?")[0].status_code == 200
    response, _ = _chat(client, "Second?")
    assert response.status_code == 429
    assert "wait a few minutes" in response.json()["detail"]


def test_questions_must_be_present_and_not_too_long(make_client):
    client = make_client()
    assert _chat(client, "   ")[0].status_code == 422
    assert _chat(client, "x" * 1001)[0].status_code == 422


def test_a_full_conversation_asks_for_a_new_chat(make_client):
    client = make_client(max_questions=1)
    _, events = _chat(client, "First?")
    assert events[-1][1]["conversation_full"] is True
    response, _ = _chat(client, "Second?", events[0][1]["conversation_id"])
    assert response.status_code == 409
    assert "Start a new chat" in response.json()["detail"]


def test_a_conversation_can_be_redrawn_after_a_reload(make_client):
    client = make_client()
    _, events = _chat(client, "Can I do CPT?")
    conversation_id = events[0][1]["conversation_id"]

    body = client.get(f"/api/conversations/{conversation_id}").json()
    user, assistant = body["messages"]
    assert user == {"role": "user", "text": "Can I do CPT?"}
    assert assistant["text"] == ANSWER
    assert [source["url"] for source in assistant["sources"]] == [CPT_URL]
    assert assistant["message_id"] == events[-1][1]["message_id"]
    assert client.get(f"/api/conversations/{uuid.uuid4()}").status_code == 404


def test_dev_mode_adds_cost_details(make_client):
    _, events = _chat(make_client(dev_mode=True), "Can I do CPT?")
    debug = events[-1][1]["debug"]
    assert debug["search_queries"] == ["Can I do CPT?"]
    assert debug["cost_usd"] > 0


def test_health_page_and_security_headers(make_client):
    client = make_client()
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/")
    assert "Unofficial assistant" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["cache-control"] == "no-cache"
    script = client.get("/static/app.js")
    assert script.headers["cache-control"] == "no-cache"
    assert client.get("/static/app.js", headers={"If-None-Match": script.headers["etag"]}).status_code == 304
    assert client.get("/api/auth/me").headers["cache-control"] == "no-store"
    assert client.get("/login", follow_redirects=False).headers["location"] == "/"


def test_logged_out_visitors_see_the_chat_page_but_cannot_chat(make_client):
    client = make_client(user=None)
    page = client.get("/", follow_redirects=False)
    assert page.status_code == 200
    assert 'href="/login"' in page.text
    assert "Create an account" in client.get("/login").text
    assert client.post("/api/chat", json={"message": "Can I do CPT?"}).status_code == 401
    assert client.get(f"/api/conversations/{uuid.uuid4()}").status_code == 401
    assert client.post("/api/feedback", json={"message_id": 1, "rating": 1}).status_code == 401


def test_users_only_see_their_own_chats(make_client):
    owner = make_client()
    _, events = _chat(owner, "Can I do CPT?")
    conversation_id, message_id = events[0][1]["conversation_id"], events[-1][1]["message_id"]
    other = make_client(user="other@drexel.edu")

    assert other.get(f"/api/conversations/{conversation_id}").status_code == 404
    assert other.post("/api/feedback", json={"message_id": message_id, "rating": -1}).status_code == 404
    _, events = _chat(other, "How do I apply?", conversation_id)
    assert events[0][1]["conversation_id"] != conversation_id
    assert len(owner.get(f"/api/conversations/{conversation_id}").json()["messages"]) == 2


def test_the_daily_question_limit_stops_more_questions(make_client):
    client = make_client(daily_question_limit=1)
    assert _chat(client, "First?")[0].status_code == 200
    response, _ = _chat(client, "Second?")
    assert response.status_code == 429
    assert "daily limit" in response.json()["detail"]
    assert _chat(make_client(user="other@drexel.edu", daily_question_limit=1), "First?")[0].status_code == 200


def test_the_daily_cost_cap_rests_the_assistant_for_everyone(make_client):
    assert _chat(make_client(daily_cost_cap_usd=0.001), "First?")[0].status_code == 200
    response, _ = _chat(make_client(user="other@drexel.edu", daily_cost_cap_usd=0.001), "Second?")
    assert response.status_code == 503
    assert "resting until tomorrow" in response.json()["detail"]


def test_rate_limiter_forgets_old_requests():
    now = [0.0]
    limiter = RateLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")
    now[0] = 61
    assert limiter.allow("a")


class _Request:
    def __init__(self, peer: str, forwarded: str | None = None):
        self.client = type("Client", (), {"host": peer})()
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}


def test_forwarded_addresses_are_trusted_only_from_the_proxy():
    assert client_ip(_Request("127.0.0.1", "6.6.6.6, 1.2.3.4"), frozenset({"127.0.0.1"})) == "1.2.3.4"
    assert client_ip(_Request("9.9.9.9", "1.2.3.4"), frozenset({"127.0.0.1"})) == "9.9.9.9"
    assert client_ip(_Request("9.9.9.9"), frozenset()) == "9.9.9.9"
