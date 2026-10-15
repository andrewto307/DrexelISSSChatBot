from datetime import date

import anthropic
import httpx
import pytest

from isss_bot.answer import (
    SYSTEM_PROMPT,
    Answer,
    AnswerError,
    Conversation,
    ConversationFull,
    TextDelta,
    build_user_message,
    concat_query,
    content_as_sent,
    retrieve,
    search_queries_for,
)
from tests.fakes import CPT_URL, REQUEST, FakeClient
from tests.fakes import claude_message as _message
from tests.fakes import search_result as _result


def _conversation(client, searched=None, **options):
    def fake_search(conn, query, limit=6):
        if searched is not None:
            searched.append(query)
        return [_result()]

    options.setdefault("followup_search", "concat")
    options.setdefault("find_updates", lambda conn, results: [])
    return Conversation(conn=None, client=client, search=fake_search, today=lambda: date(2026, 10, 12), **options)


def _ask(conversation, question):
    events = list(conversation.ask(question))
    answer = events[-1]
    assert isinstance(answer, Answer)
    return "".join(event.text for event in events[:-1] if isinstance(event, TextDelta)), answer


def test_build_user_message_groups_sources_by_page():
    results = [
        _result(index=2, content="Second section", heading_path="CPT › Procedure"),
        _result(
            url="https://drexel.edu/x/announcement",
            title='Rule "D/S" ends',
            page_type="announcement",
            announcement_date=date(2026, 7, 17),
            content="Announcement text",
        ),
        _result(index=0, content="First section"),
    ]
    message = build_user_message("Can I do CPT?", results, date(2026, 10, 12))

    assert message.count(f'<source url="{CPT_URL}"') == 1
    assert message.index("First section") < message.index("Second section")
    assert (
        'title="Rule &quot;D/S&quot; ends" type="announcement" published="2026-07-17" retrieved="2026-10-12"' in message
    )
    assert "Section: CPT › Procedure\nSecond section" in message
    assert message.endswith("Today's date: October 12, 2026\n\nStudent question: Can I do CPT?")


def test_concat_query_adds_the_two_most_recent_questions():
    previous = ["What is OPT?", "Can I work off campus in my first year?", "Is CPT paid?"]
    assert concat_query("How do I apply for it?", previous) == (
        "How do I apply for it? | Is CPT paid? | Can I work off campus in my first year?"
    )


def test_first_question_is_searched_as_is():
    client = FakeClient(rewrite_reply=_message("unused"))
    assert search_queries_for("Can I do CPT?", [], "rewrite", client) == (["Can I do CPT?"], 0.0)
    assert client.messages.create_calls == []


def test_rewrite_mode_searches_the_rewritten_and_the_combined_question():
    client = FakeClient(rewrite_reply=_message("How do I apply for CPT?"))
    queries, cost = search_queries_for("How do I apply for it?", ["Can I work off campus?"], "rewrite", client)
    assert queries == ["How do I apply for CPT?", "How do I apply for it? | Can I work off campus?"]
    assert cost > 0
    request = client.messages.create_calls[0]
    assert request["model"] == "claude-haiku-4-5"
    assert "Can I work off campus?" in request["messages"][0]["content"]
    assert "<last_answer_start>" not in request["messages"][0]["content"]


def test_rewrite_sees_the_start_of_the_last_answer():
    client = FakeClient(rewrite_reply=_message("How do I apply for CPT?"))
    search_queries_for("How do I apply for it?", ["Can I work off campus?"], "rewrite", client, "Only with CPT. " * 100)
    content = client.messages.create_calls[0]["messages"][0]["content"]
    assert "<last_answer_start>\nOnly with CPT." in content
    assert len(content) < 1000


@pytest.mark.parametrize(
    "rewrite_reply",
    [anthropic.APIConnectionError(request=REQUEST), _message(""), _message("partial", stop_reason="max_tokens")],
)
def test_rewrite_falls_back_to_concat(rewrite_reply):
    client = FakeClient(rewrite_reply=rewrite_reply)
    queries, cost = search_queries_for("How do I apply for it?", ["Can I work off campus?"], "rewrite", client)
    assert queries == ["How do I apply for it? | Can I work off campus?"]
    assert cost == 0.0


def test_retrieve_merges_the_results_of_several_queries():
    results = {
        "rewritten": [
            _result(index=1, url="https://x.invalid/cpt-procedure"),
            _result(index=2, url="https://x.invalid/a"),
        ],
        "combined": [
            _result(index=3, url="https://x.invalid/b"),
            _result(index=1, url="https://x.invalid/cpt-procedure"),
        ],
    }
    limits = []

    def fake_search(conn, query, limit):
        limits.append(limit)
        return results[query]

    merged = retrieve(None, ["rewritten", "combined"], fake_search)
    assert [result.url for result in merged] == [
        "https://x.invalid/cpt-procedure",
        "https://x.invalid/b",
        "https://x.invalid/a",
    ]
    assert limits == [12, 12]
    assert [result.url for result in retrieve(None, ["combined"], fake_search)][0] == "https://x.invalid/b"


def test_rewrite_mode_conversation_searches_both_queries():
    client = FakeClient([_message("CPT needs one year."), _message("Apply in the portal.")], _message("Apply for CPT"))
    searched = []
    conversation = _conversation(client, searched, followup_search="rewrite")
    _ask(conversation, "Can I work off campus in my first year?")
    _, answer = _ask(conversation, "How do I apply for it?")
    assert answer.search_queries == [
        "Apply for CPT",
        "How do I apply for it? | Can I work off campus in my first year?",
    ]
    assert searched[1:] == answer.search_queries
    assert "<last_answer_start>\nCPT needs one year." in client.messages.create_calls[0]["messages"][0]["content"]


def test_ask_streams_the_answer_and_keeps_history_append_only():
    first, second = _message("You can do CPT after one year."), _message("Apply through the ISSS Student Portal.")
    client = FakeClient([first, second])
    searched = []
    conversation = _conversation(client, searched)

    streamed, answer = _ask(conversation, "Can I do CPT in my first year?")
    assert streamed == answer.text == "You can do CPT after one year."
    assert answer.sources[0].url == CPT_URL
    assert answer.cost_usd == pytest.approx((1000 * 2 + 100 * 10) / 1_000_000)

    _, follow_up = _ask(conversation, "How do I apply for it?")
    first_request, second_request = client.messages.stream_calls
    assert searched == ["Can I do CPT in my first year?", "How do I apply for it? | Can I do CPT in my first year?"]
    assert second_request["messages"][:2] == first_request["messages"] + [
        {"role": "assistant", "content": content_as_sent(first.content)}
    ]
    assert second_request["messages"][0]["content"] == answer.user_content
    assert second_request["messages"][1]["content"] == answer.assistant_content
    assert follow_up.assistant_content == [{"type": "text", "text": "Apply through the ISSS Student Portal."}]
    assert "Student question: How do I apply for it?" in second_request["messages"][2]["content"]
    for request in (first_request, second_request):
        assert request["system"] == SYSTEM_PROMPT
        assert request["output_config"] == {"effort": "low"}
        assert request["cache_control"] == {"type": "ephemeral"}
    assert conversation.questions == ["Can I do CPT in my first year?", "How do I apply for it?"]


def test_newer_updates_are_shown_to_claude_with_what_they_update():
    rule = "https://drexel.edu/x/announcements/2026/July/rule"
    update = _result(
        url="https://drexel.edu/x/announcements/2026/September/postponed",
        title="Court postpones the rule",
        page_type="announcement",
        announcement_date=date(2026, 9, 14),
        content="A court postponed the rule.",
        updates=rule,
    )
    seen = []

    def find_updates(conn, results):
        seen.append([result.url for result in results])
        return [update]

    client = FakeClient([_message("Answer.")])
    conversation = _conversation(client, find_updates=find_updates)
    _, answer = _ask(conversation, "How do I apply for CPT?")

    assert seen == [[CPT_URL]]
    assert answer.sources[-1] is update
    message = client.messages.stream_calls[0]["messages"][0]["content"]
    assert f'published="2026-09-14" retrieved="2026-10-12" updates="{rule}">' in message
    assert client.messages.stream_calls[0]["system"] == SYSTEM_PROMPT


def test_thinking_blocks_are_kept_with_their_signature():
    client = FakeClient([_message("One year first.", thinking="cpt rule"), _message("Use the portal.")])
    conversation = _conversation(client)
    _, answer = _ask(conversation, "Can I do CPT now?")
    _ask(conversation, "How?")
    resent = client.messages.stream_calls[1]["messages"][1]["content"]
    assert resent == answer.assistant_content
    assert resent[0] == {"type": "thinking", "thinking": "cpt rule", "signature": "signature-for-cpt rule"}


def test_refusal_is_not_kept_in_history():
    client = FakeClient([_message("", stop_reason="refusal")])
    conversation = _conversation(client)
    _, answer = _ask(conversation, "Something odd")
    assert answer.refused
    assert conversation.messages == []
    assert conversation.questions == []


@pytest.mark.parametrize(
    "error",
    [
        anthropic.RateLimitError("rate limited", response=httpx.Response(429, request=REQUEST), body=None),
        anthropic.APIConnectionError(request=REQUEST),
        anthropic.InternalServerError("overloaded", response=httpx.Response(529, request=REQUEST), body=None),
    ],
)
def test_api_errors_roll_back_the_question(error):
    conversation = _conversation(FakeClient([error]))
    with pytest.raises(AnswerError):
        _ask(conversation, "Can I do CPT?")
    assert conversation.messages == []


def test_abandoned_stream_rolls_back_the_question():
    conversation = _conversation(FakeClient([_message("A long answer")]))
    events = conversation.ask("Can I do CPT?")
    next(events)
    events.close()
    assert conversation.messages == []


def test_conversation_stops_at_the_question_limit():
    conversation = _conversation(FakeClient([_message("One."), _message("Two.")]), max_questions=2)
    _ask(conversation, "First?")
    _ask(conversation, "Second?")
    assert conversation.is_full
    with pytest.raises(ConversationFull):
        _ask(conversation, "Third?")
