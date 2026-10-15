import uuid
from datetime import date

from isss_bot import store
from isss_bot.answer import Answer, Conversation
from tests.fakes import CPT_URL, FakeClient, claude_message, search_result

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
    conversation_id = store.create_conversation(conn, "iphash")
    conversation = store.load_conversation(conn, conversation_id, **_options(client))
    store.save_turn(conn, conversation_id, "Can I do CPT now?", _ask(conversation, "Can I do CPT now?"))

    reloaded = store.load_conversation(conn, conversation_id, **_options(client))
    assert reloaded.messages == conversation.messages
    assert reloaded.messages[1]["content"][0]["signature"] == "signature-for-cpt rule"
    assert reloaded.questions == ["Can I do CPT now?"]
    assert reloaded.answers == ["One academic year first."]

    store.save_turn(conn, conversation_id, "How?", _ask(reloaded, "How?"))
    second_request = client.messages.stream_calls[1]
    assert second_request["messages"][:2] == conversation.messages


def test_refused_turns_are_kept_for_review_but_not_resent(conn):
    client = FakeClient([claude_message("", stop_reason="refusal"), claude_message("Answer.")])
    conversation_id = store.create_conversation(conn, None)
    conversation = store.load_conversation(conn, conversation_id, **_options(client))
    store.save_turn(conn, conversation_id, "Odd question", _ask(conversation, "Odd question"))

    stored = conn.execute("SELECT role, in_history FROM messages WHERE conversation_id = %s", (conversation_id,))
    assert [(row["role"], row["in_history"]) for row in stored] == [("user", False), ("assistant", False)]
    reloaded = store.load_conversation(conn, conversation_id, **_options(client))
    assert reloaded.messages == []
    assert store.visible_messages(conn, conversation_id) == []


def test_visible_messages_show_questions_answers_cited_sources_and_ratings(conn):
    client = FakeClient([claude_message(f"One academic year first. See [CPT]({CPT_URL}).")])
    conversation_id = store.create_conversation(conn, None)
    conversation = store.load_conversation(conn, conversation_id, **_options(client))
    message_id = store.save_turn(conn, conversation_id, "Can I do CPT now?", _ask(conversation, "Can I do CPT now?"))
    assert store.save_feedback(conn, message_id, 1, None)

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
    conversation_id = store.create_conversation(conn, None)
    conversation = store.load_conversation(conn, conversation_id, **_options(client))
    message_id = store.save_turn(conn, conversation_id, "Question?", _ask(conversation, "Question?"))

    assert store.save_feedback(conn, message_id, 1, None)
    assert store.save_feedback(conn, message_id, -1, "Missing the deadline")
    row = conn.execute("SELECT rating, comment FROM feedback WHERE message_id = %s", (message_id,)).fetchone()
    assert row == {"rating": -1, "comment": "Missing the deadline"}
    assert not store.save_feedback(conn, message_id - 1, 1, None)
    assert not store.save_feedback(conn, 999_999_999, 1, None)


def test_unknown_conversations_load_as_none(conn):
    assert store.load_conversation(conn, uuid.uuid4(), **_options(FakeClient())) is None
