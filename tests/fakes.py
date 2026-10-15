from datetime import UTC, datetime
from pathlib import Path

import httpx
from anthropic.types import Message, TextBlock, ThinkingBlock, Usage

from isss_bot.search import SearchResult

CPT_URL = "https://drexel.edu/studentlife/student-success/international-student-support/current-students/employment/cpt"
CPT_TEXT = (Path(__file__).parent / "fixtures" / "cpt.txt").read_text()
REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def search_result(url=CPT_URL, title="Curricular Practical Training (CPT)", index=0, content=CPT_TEXT, **extra):
    values = {
        "chunk_id": index,
        "chunk_index": index,
        "url": url,
        "title": title,
        "page_type": "page",
        "announcement_date": None,
        "fetched_at": datetime(2026, 10, 12, 14, 0, tzinfo=UTC),
        "heading_path": title,
        "content": content,
        "score": 0.03,
        "vector_rank": 1,
        "keyword_rank": 1,
    }
    return SearchResult(**{**values, **extra})


def claude_message(text: str, stop_reason: str = "end_turn", thinking: str | None = None) -> Message:
    content = [TextBlock(type="text", text=text)]
    if thinking is not None:
        content.insert(0, ThinkingBlock(type="thinking", thinking=thinking, signature=f"signature-for-{thinking}"))
    return Message.model_construct(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-sonnet-5-5",
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )


class FakeStream:
    def __init__(self, message: Message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    @property
    def text_stream(self):
        text = "".join(block.text for block in self.message.content if block.type == "text")
        yield from (text[: len(text) // 2], text[len(text) // 2 :])

    def get_final_message(self) -> Message:
        return self.message


class FakeMessages:
    def __init__(self, replies, rewrite_reply=None, default_reply=None):
        self.replies = list(replies)
        self.rewrite_reply = rewrite_reply
        self.default_reply = default_reply
        self.stream_calls = []
        self.create_calls = []

    def stream(self, **request):
        self.stream_calls.append({**request, "messages": list(request["messages"])})
        reply = self.replies.pop(0) if self.replies else self.default_reply
        if isinstance(reply, Exception):
            raise reply
        return FakeStream(reply)

    def create(self, **request):
        self.create_calls.append(request)
        if isinstance(self.rewrite_reply, Exception):
            raise self.rewrite_reply
        return self.rewrite_reply


class FakeClient:
    def __init__(self, replies=(), rewrite_reply=None, default_reply=None):
        self.messages = FakeMessages(replies, rewrite_reply, default_reply)
