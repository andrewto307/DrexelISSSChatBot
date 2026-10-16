import socket
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn

from app.accounts import SESSION_COOKIE
from app.main import AppOptions, create_app
from isss_bot import db
from tests.fakes import (
    CPT_URL,
    PASSWORD,
    RESET_TABLES,
    FakeClient,
    FakeMailer,
    claude_message,
    search_result,
    session_cookie_for,
)

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect

pytestmark = pytest.mark.browser

UPDATE_URL = "https://drexel.edu/x/announcements/2026/September/postponed"
OPT_URL = "https://drexel.edu/x/opt"
ANSWER = (
    f"**Generally no.** CPT needs one full academic year first. See [Curricular Practical Training]({CPT_URL}). "
    f"A court [postponed a related rule]({UPDATE_URL})."
)


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as playwright:
        try:
            chromium = playwright.chromium.launch()
        except playwright_api.Error as error:
            pytest.skip(f"Playwright's Chromium isn't installed: {error}")
        yield chromium
        chromium.close()


@pytest.fixture
def live_server(migrated_database_url):
    with db.connect(migrated_database_url) as conn:
        conn.execute(RESET_TABLES)
        conn.commit()
    mailer = FakeMailer()
    app = create_app(
        AppOptions(
            database_url=migrated_database_url,
            client=FakeClient(default_reply=claude_message(ANSWER)),
            search=lambda conn, query, limit=6: [
                search_result(),
                search_result(url=OPT_URL, title="Optional Practical Training"),
            ],
            find_updates=lambda conn, results: [
                search_result(
                    url=UPDATE_URL, title="Court postpones the rule", page_type="announcement", updates=CPT_URL
                )
            ],
            followup_search="concat",
            mailer=mailer,
            cookie_secure=False,
        )
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("The test server didn't start")
        time.sleep(0.05)
    yield SimpleNamespace(url=f"http://127.0.0.1:{port}", mailer=mailer)
    server.should_exit = True
    thread.join(timeout=10)


def logged_in_page(browser, live_server, database_url, **context_options):
    context = browser.new_context(**context_options)
    with db.connect(database_url) as conn:
        token = session_cookie_for(conn)
    context.add_cookies([{"name": SESSION_COOKIE, "value": token, "url": live_server.url}])
    page = context.new_page()
    page.goto(live_server.url)
    return page


def test_a_visitor_must_log_in_to_ask_and_keeps_the_question(browser, live_server):
    page = browser.new_page()
    page.goto(live_server.url)
    expect(page.get_by_role("heading", name="Questions about your student visa status at Drexel?")).to_be_visible()
    expect(page.get_by_role("button", name="Log out")).to_be_hidden()

    page.get_by_role("button", name="Can I do CPT in my first year?").click()
    notice = page.get_by_role("status").filter(has_text="Log in to ask questions")
    expect(notice).to_be_visible()
    expect(page.get_by_text("CPT needs one full academic year first.")).to_have_count(0)
    notice.get_by_role("link", name="Log in").click()
    expect(page.get_by_role("heading", name="Log in")).to_be_visible()

    page.get_by_role("link", name="Create an account").click()
    signup = page.get_by_role("region", name="Create an account")
    signup.get_by_role("textbox", name="Drexel email").fill("abc123@gmail.com")
    signup.get_by_label("Password").fill(PASSWORD)
    signup.get_by_role("button", name="Create account").click()
    expect(signup.get_by_role("alert")).to_contain_text("Use your Drexel email address")

    signup.get_by_role("textbox", name="Drexel email").fill("abc123@drexel.edu")
    signup.get_by_role("button", name="Create account").click()
    verify = page.get_by_role("region", name="Check your email")
    expect(verify).to_contain_text("abc123@drexel.edu")
    verify.get_by_role("textbox", name="6-digit code").fill(live_server.mailer.last_code("abc123@drexel.edu", "verify"))
    verify.get_by_role("button", name="Verify").click()

    question = page.get_by_role("textbox", name="Your question")
    expect(question).to_have_value("Can I do CPT in my first year?")
    expect(page.get_by_role("link", name="Log in")).to_be_hidden()
    question.press("Enter")
    expect(page.get_by_text("CPT needs one full academic year first.")).to_be_visible()

    page.get_by_role("button", name="Account").click()
    expect(page.get_by_text("abc123@drexel.edu")).to_be_visible()
    page.get_by_role("button", name="Log out").click()
    expect(page.get_by_role("link", name="Log in")).to_be_visible()
    expect(page.get_by_text("CPT needs one full academic year first.")).to_have_count(0)
    expect(page.get_by_role("button", name="Account")).to_be_hidden()


def test_a_student_can_ask_rate_reload_and_start_over(browser, live_server, migrated_database_url):
    page = logged_in_page(browser, live_server, migrated_database_url)
    expect(page.get_by_role("heading", name="Questions about your student visa status at Drexel?")).to_be_visible()

    page.get_by_role("button", name="Can I do CPT in my first year?").click()
    expect(page.get_by_text("CPT needs one full academic year first.")).to_be_visible()
    expect(page.get_by_role("link", name="Curricular Practical Training (CPT) ISSS page")).to_be_visible()
    expect(page.get_by_text("Update", exact=True)).to_be_visible()
    expect(page.get_by_text("Optional Practical Training")).to_have_count(0)

    helpful = page.get_by_role("button", name="Helpful", exact=True)
    helpful.click()
    expect(helpful).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_text("Thanks for the feedback")).to_be_visible()
    with db.connect(migrated_database_url) as conn:
        assert conn.execute("SELECT rating FROM feedback").fetchone()["rating"] == 1

    page.reload()
    expect(page.get_by_text("CPT needs one full academic year first.")).to_be_visible()
    expect(page.get_by_role("button", name="Helpful", exact=True)).to_have_attribute("aria-pressed", "true")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="New chat").click()
    expect(page.get_by_role("heading", name="Questions about your student visa status at Drexel?")).to_be_visible()
    expect(page.get_by_text("CPT needs one full academic year first.")).to_have_count(0)


def test_the_theme_choice_applies_and_survives_a_reload(browser, live_server, migrated_database_url):
    page = logged_in_page(browser, live_server, migrated_database_url, color_scheme="light")
    expect(page.get_by_role("radio", name="Match system theme")).to_have_attribute("aria-checked", "true")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")

    page.get_by_role("radio", name="Dark theme").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.get_by_role("radio", name="Dark theme")).to_have_attribute("aria-checked", "true")


def test_typing_a_question_and_pressing_enter_sends_it(browser, live_server, migrated_database_url):
    page = logged_in_page(browser, live_server, migrated_database_url)
    send = page.get_by_role("button", name="Send question")
    expect(send).to_be_disabled()
    question = page.get_by_role("textbox", name="Your question")
    question.fill("Can I work off campus?")
    expect(send).to_be_enabled()
    question.press("Enter")
    expect(page.get_by_text("Can I work off campus?")).to_be_visible()
    expect(page.get_by_text("CPT needs one full academic year first.")).to_be_visible()
    expect(question).to_have_value("")


def test_starting_a_new_chat_asks_first(browser, live_server, migrated_database_url):
    page = logged_in_page(browser, live_server, migrated_database_url)
    answer = page.get_by_text("CPT needs one full academic year first.")
    page.get_by_role("button", name="Can I do CPT in my first year?").click()
    expect(answer).to_be_visible()

    asked = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    page.get_by_role("button", name="New chat").click()
    expect(answer).to_be_visible()
    assert asked == ["Starting a new chat clears this one. You won't be able to come back to it."]

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="New chat").click()
    expect(page.get_by_role("heading", name="Questions about your student visa status at Drexel?")).to_be_visible()
    expect(answer).to_have_count(0)
    page.reload()
    expect(answer).to_have_count(0)

    page.get_by_role("button", name="Account").click()
    expect(page.get_by_text("student@drexel.edu")).to_be_visible()
    expect(page.get_by_role("button", name="Log out")).to_be_visible()
    expect(page.get_by_text("Delete my chats")).to_have_count(0)
