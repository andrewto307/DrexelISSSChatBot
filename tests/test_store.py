import uuid
from datetime import date

import pytest

from isss_bot import store
from isss_bot.answer import Answer, Conversation
from tests.fakes import CPT_URL, FakeClient, claude_message, search_result, verified_user

UPDATE_URL = "https://drexel.edu/x/announcements/2026/September/postponed"
OPT_URL = "https://drexel.edu/x/opt"


def _options(client):
    return {
        "client": client,
        "search": lambda conn, query, limit=6: [search_result(), search_result(index=1)],
        "find_updates": lambda conn, results: [
            search_result(url=UPDATE_URL, title="Court postpones the rule", page_type="announcement", updates=CPT_URL)
        ],
        "followup_search": "concat",
        "today": lambda: date(2026, 10, 12),
    }


def _ask(conversation: Conversation, question: str) -> Answer:
    return [event for event in conversation.ask(question) if isinstance(event, Answer)][0]


def test_a_reloaded_conversation_matches_what_was_sent(conn):
    client = FakeClient([claude_message("One academic year first.", thinking="cpt rule"), claude_message("Portal.")])
    conversation_id = store.create_conversation(conn, None, "iphash")
    conversation = store.load_conversation(conn, conversation_id, None, **_options(client))
    store.save_turn(conn, conversation_id, "Can I do CPT now?", _ask(conversation, "Can I do CPT now?"))

    reloaded = store.load_conversation(conn, conversation_id, None, **_options(client))
    assert reloaded.messages == conversation.messages
    assert reloaded.messages[1]["content"][0]["signature"] == "signature-for-cpt rule"
    assert reloaded.questions == ["Can I do CPT now?"]
    assert reloaded.answers == ["One academic year first."]

    store.save_turn(conn, conversation_id, "How?", _ask(reloaded, "How?"))
    second_request = client.messages.stream_calls[1]
    assert second_request["messages"][:2] == conversation.messages


def test_refused_turns_are_kept_for_review_but_not_resent(conn):
    client = FakeClient([claude_message("", stop_reason="refusal"), claude_message("Answer.")])
    conversation_id = store.create_conversation(conn, None, None)
    conversation = store.load_conversation(conn, conversation_id, None, **_options(client))
    store.save_turn(conn, conversation_id, "Odd question", _ask(conversation, "Odd question"))

    stored = conn.execute("SELECT role, in_history FROM messages WHERE conversation_id = %s", (conversation_id,))
    assert [(row["role"], row["in_history"]) for row in stored] == [("user", False), ("assistant", False)]
    reloaded = store.load_conversation(conn, conversation_id, None, **_options(client))
    assert reloaded.messages == []
    assert store.visible_messages(conn, conversation_id) == []


def test_visible_messages_show_questions_answers_cited_sources_and_ratings(conn):
    client = FakeClient([claude_message(f"One academic year first. See [CPT]({CPT_URL}).")])
    conversation_id = store.create_conversation(conn, None, None)
    conversation = store.load_conversation(conn, conversation_id, None, **_options(client))
    message_id = store.save_turn(conn, conversation_id, "Can I do CPT now?", _ask(conversation, "Can I do CPT now?"))
    assert store.save_feedback(conn, None, message_id, 1, None)

    user, assistant = store.visible_messages(conn, conversation_id)
    assert user == {"role": "user", "text": "Can I do CPT now?"}
    assert assistant["text"] == f"One academic year first. See [CPT]({CPT_URL})."
    assert assistant["rating"] == 1
    assert [source["url"] for source in assistant["sources"]] == [CPT_URL]


def test_cited_sources_keep_each_linked_page_once_in_search_order():
    records = [
        store.source_record(search_result()),
        store.source_record(search_result(url=OPT_URL, title="Optional Practical Training (OPT)")),
        store.source_record(search_result(index=1)),
        store.source_record(
            search_result(url=UPDATE_URL, title="Court postpones the rule", page_type="announcement", updates=CPT_URL)
        ),
    ]
    www_cpt = CPT_URL.replace("https://", "https://www.")
    text = f"A court postponed it: {UPDATE_URL}. Apply early ([CPT]({www_cpt}/#steps))."

    cited = store.cited_sources(text, records)
    assert [record["url"] for record in cited] == [CPT_URL, UPDATE_URL]
    assert cited[1]["updates"] == CPT_URL
    assert store.cited_sources("I couldn't find that on the ISSS website.", records) == []


def test_feedback_is_updated_and_unknown_messages_are_rejected(conn):
    client = FakeClient([claude_message("Answer.")])
    conversation_id = store.create_conversation(conn, None, None)
    conversation = store.load_conversation(conn, conversation_id, None, **_options(client))
    message_id = store.save_turn(conn, conversation_id, "Question?", _ask(conversation, "Question?"))

    assert store.save_feedback(conn, None, message_id, 1, None)
    assert store.save_feedback(conn, None, message_id, -1, "Missing the deadline")
    row = conn.execute("SELECT rating, comment FROM feedback WHERE message_id = %s", (message_id,)).fetchone()
    assert row == {"rating": -1, "comment": "Missing the deadline"}
    assert not store.save_feedback(conn, None, message_id - 1, 1, None)
    assert not store.save_feedback(conn, None, 999_999_999, 1, None)


def test_unknown_conversations_load_as_none(conn):
    assert store.load_conversation(conn, uuid.uuid4(), None, **_options(FakeClient())) is None


def test_conversations_and_feedback_belong_to_their_user(conn):
    owner, other = verified_user(conn, "owner@drexel.edu")["id"], verified_user(conn, "other@drexel.edu")["id"]
    client = FakeClient([claude_message("Answer.")])
    conversation_id = store.create_conversation(conn, owner, None)
    conversation = store.load_conversation(conn, conversation_id, owner, **_options(client))
    message_id = store.save_turn(conn, conversation_id, "Question?", _ask(conversation, "Question?"))

    assert store.load_conversation(conn, conversation_id, other, **_options(client)) is None
    assert not store.save_feedback(conn, other, message_id, 1, None)
    assert store.save_feedback(conn, owner, message_id, 1, None)


def test_daily_usage_adds_up_and_outlasts_deleted_chats(conn):
    user_id = verified_user(conn, "usage@drexel.edu")["id"]
    store.create_conversation(conn, user_id, None)
    questions_before, cost_before = store.questions_today(conn, user_id), store.cost_today(conn)

    store.record_usage(conn, user_id, 0.015)
    store.record_usage(conn, user_id, 0.02)
    assert conn.execute("DELETE FROM conversations WHERE user_id = %s", (user_id,)).rowcount == 1

    assert store.questions_today(conn, user_id) - questions_before == 2
    assert store.cost_today(conn) - cost_before == pytest.approx(0.035)
