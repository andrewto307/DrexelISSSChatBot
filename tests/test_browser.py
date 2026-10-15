import socket
import threading
import time

import pytest
import uvicorn

from app.main import AppOptions, create_app
from isss_bot import db
from tests.fakes import CPT_URL, FakeClient, claude_message, search_result

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
        conn.execute("TRUNCATE feedback, messages, conversations")
        conn.commit()
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
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_a_student_can_ask_rate_reload_and_start_over(browser, live_server, migrated_database_url):
    page = browser.new_page()
    page.goto(live_server)
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

    page.get_by_role("button", name="New chat").click()
    expect(page.get_by_role("heading", name="Questions about your student visa status at Drexel?")).to_be_visible()
    expect(page.get_by_text("CPT needs one full academic year first.")).to_have_count(0)


def test_the_theme_choice_applies_and_survives_a_reload(browser, live_server):
    page = browser.new_page(color_scheme="light")
    page.goto(live_server)
    expect(page.get_by_role("radio", name="Match system theme")).to_have_attribute("aria-checked", "true")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")

    page.get_by_role("radio", name="Dark theme").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.get_by_role("radio", name="Dark theme")).to_have_attribute("aria-checked", "true")


def test_typing_a_question_and_pressing_enter_sends_it(browser, live_server):
    page = browser.new_page()
    page.goto(live_server)
    send = page.get_by_role("button", name="Send question")
    expect(send).to_be_disabled()
    question = page.get_by_role("textbox", name="Your question")
    question.fill("Can I work off campus?")
    expect(send).to_be_enabled()
    question.press("Enter")
    expect(page.get_by_text("Can I work off campus?")).to_be_visible()
    expect(page.get_by_text("CPT needs one full academic year first.")).to_be_visible()
    expect(question).to_have_value("")
