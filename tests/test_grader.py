import json
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from agentaudit.grader import Grader
from agentaudit.models import Article, Conversation, Verdict

ARTICLES = [Article("refunds", "Refunds", "Annual plans are refundable within 14 days.")]
CONVERSATION = Conversation("c1", "billing", "Refund after 3 weeks?", "Yes, within 30 days.")


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def fake_client(*responses):
    messages = FakeMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def reply(payload, stop_reason="end_turn"):
    text = json.dumps(payload) if isinstance(payload, dict) else payload
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
    )


GOOD = {
    "verdict": "incorrect",
    "confidence": "high",
    "cited_articles": ["refunds", "made-up-article"],
    "unsupported_claims": ["refundable within 30 days"],
    "explanation": "Policy allows refunds within 14 days, not 30.",
}


def test_grade_parses_structured_output_and_drops_phantom_citations():
    client, messages = fake_client(reply(GOOD))
    grade = Grader(ARTICLES, client=client).grade(CONVERSATION)
    assert grade.verdict is Verdict.INCORRECT
    assert grade.cited_articles == ["refunds"]
    assert grade.unsupported_claims == ["refundable within 30 days"]


def test_request_caches_help_centre_and_uses_schema():
    client, messages = fake_client(reply(GOOD))
    Grader(ARTICLES, client=client).grade(CONVERSATION)
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "Annual plans are refundable" in call["system"][-1]["text"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"


def test_refusal_is_recorded_not_raised():
    client, _ = fake_client(reply("", stop_reason="refusal"))
    grade = Grader(ARTICLES, client=client).grade(CONVERSATION)
    assert not grade.graded
    assert "declined" in grade.error


def test_grade_all_records_api_errors_and_keeps_going():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    overloaded = anthropic.InternalServerError(
        "overloaded", response=httpx.Response(529, request=request), body=None
    )
    second = Conversation("c2", "billing", "q", "a")
    client, _ = fake_client(overloaded, reply(GOOD))
    grades = Grader(ARTICLES, client=client).grade_all([CONVERSATION, second], workers=1)
    assert [g.conversation_id for g in grades] == ["c1", "c2"]
    assert not grades[0].graded and "529" in grades[0].error
    assert grades[1].verdict is Verdict.INCORRECT


def test_grade_all_stops_on_authentication_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    bad_key = anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)
    client, _ = fake_client(bad_key)
    with pytest.raises(anthropic.AuthenticationError):
        Grader(ARTICLES, client=client).grade_all([CONVERSATION], workers=1)
