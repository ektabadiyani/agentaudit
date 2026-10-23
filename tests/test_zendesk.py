import base64
import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from agentaudit.loader import load_articles, load_conversations
from agentaudit.redact import Redactor
from agentaudit.zendesk import ZendeskClient, ZendeskError, pull_articles, pull_conversations, ticket_to_conversation

AI, CUSTOMER, AGENT = 900, 100, 555
BASE = "https://acme.zendesk.com"


class FakeZendesk:
    """Serves canned Zendesk API responses keyed by path, and records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, url, headers):
        self.requests.append((url, headers))
        parsed = urlparse(url)
        key = parsed.path + ("?cursor=" + parse_qs(parsed.query)["page[after]"][0] if "page[after]" in url else "")
        response = self.routes.get(key)
        if response is None:
            return 404, {}, b"{}"
        if callable(response):
            return response()
        return 200, {}, json.dumps(response).encode()


def page(key, items, next_cursor=None, path=None):
    body = {key: items, "meta": {"has_more": bool(next_cursor)}, "links": {}}
    if next_cursor:
        body["links"]["next"] = f"{BASE}{path}?page[size]=100&page[after]={next_cursor}"
    return body


def comment(author, body, at, public=True):
    return {"author_id": author, "plain_body": body, "public": public, "created_at": at}


TICKET = {"id": 42, "requester_id": CUSTOMER, "tags": ["ai_agent", "topic_billing"], "satisfaction_rating": {"score": "bad"}}


def test_ticket_mapping_question_answer_and_handoff():
    comments = [
        comment(CUSTOMER, "Can I get a refund after 3 weeks?", "2026-10-01T10:00:00Z"),
        comment(CUSTOMER, "It's an annual plan.", "2026-10-01T10:00:05Z"),
        comment(AI, "Yes, within 30 days.", "2026-10-01T10:00:10Z"),
        comment(AGENT, "Internal note", "2026-10-01T11:00:00Z", public=False),
        comment(CUSTOMER, "Great, how?", "2026-10-01T10:01:00Z"),
        comment(AI, "Go to Settings > Billing.", "2026-10-01T10:01:10Z"),
        comment(AGENT, "Correction: it's 14 days.", "2026-10-02T09:00:00Z"),
        comment(AI, "Anything else?", "2026-10-02T09:05:00Z"),
    ]
    conv, reason = ticket_to_conversation(TICKET, comments, reopens=1, ai_author_ids={AI})
    assert reason is None
    assert conv == {
        "id": "zd-42", "topic": "billing",
        "question": "Can I get a refund after 3 weeks?\n\nIt's an annual plan.",
        "ai_answer": "Yes, within 30 days.\n\nGo to Settings > Billing.",   # AI replies after the handoff are excluded
        "handed_off": True, "reopened_within_7d": True, "csat": 1,
    }


def test_ticket_without_ai_reply_is_skipped():
    conv, reason = ticket_to_conversation(TICKET, [comment(CUSTOMER, "Hi", "1"), comment(AGENT, "Hello", "2")], 0, {AI})
    assert conv is None and reason == "no AI reply"


def test_pull_articles_follows_cursor_pages_and_skips_drafts(tmp_path):
    path = "/api/v2/help_center/en-us/articles"
    fake = FakeZendesk({
        path: page("articles", [{"id": 1, "title": "Refunds & Cancellation", "body": "<p>Within <b>14</b> days.</p>",
                                 "html_url": f"{BASE}/hc/articles/1", "draft": False}], "abc", path),
        path + "?cursor=abc": page("articles", [{"id": 2, "title": "Draft", "body": "<p>x</p>", "draft": True},
                                                {"id": 3, "title": "SSO", "body": "<p>Use Okta.</p>", "draft": False}]),
    })
    client = ZendeskClient("acme", "admin@acme.example", "secret", fetch=fake)
    assert pull_articles(client, tmp_path) == 2
    articles = load_articles(tmp_path)
    assert [a.title for a in articles] == ["Refunds & Cancellation", "SSO"]
    assert "Within **14** days." in articles[0].body and "Source: https://acme.zendesk.com" in articles[0].body
    expected = "Basic " + base64.b64encode(b"admin@acme.example/token:secret").decode()
    assert fake.requests[0][1]["Authorization"] == expected


def test_pull_conversations_end_to_end_with_redaction(tmp_path):
    fake = FakeZendesk({
        "/api/v2/search/export": page("results", [TICKET, {**TICKET, "id": 43}]),
        "/api/v2/tickets/42/comments": page("comments", [
            comment(CUSTOMER, "Refund? I'm jane@harbor.example", "1"), comment(AI, "Yes, 30 days.", "2")]),
        "/api/v2/tickets/42/metrics": {"ticket_metric": {"reopens": 0}},
        "/api/v2/tickets/43/comments": page("comments", [comment(CUSTOMER, "Hello?", "1")]),
        "/api/v2/tickets/43/metrics": {"ticket_metric": {"reopens": 0}},
    })
    client = ZendeskClient("acme", "a@acme.example", "t", fetch=fake)
    out = tmp_path / "conversations.jsonl"
    stats = pull_conversations(client, out, {AI}, date(2026, 10, 1), ai_tag="ai_agent", redactor=Redactor())
    assert stats.written == 1 and stats.skipped == {"no AI reply": 1}
    [conv] = load_conversations(out)
    assert conv.question == "Refund? I'm [EMAIL]" and conv.topic == "billing" and conv.csat == 1
    query = parse_qs(urlparse(fake.requests[0][0]).query)["query"][0]
    assert query == "type:ticket created>=2026-10-01 tags:ai_agent"


def test_rate_limit_waits_for_retry_after():
    calls, waits = [], []

    def limited():
        calls.append(1)
        return (429, {"Retry-After": "7"}, b"") if len(calls) == 1 else (200, {}, b'{"ok": true}')

    client = ZendeskClient("acme", "a", "t", fetch=FakeZendesk({"/api/v2/x": limited}), sleep=waits.append)
    assert client.get("/api/v2/x") == {"ok": True}
    assert waits == [7.0]


def test_bad_credentials_and_bad_subdomain():
    client = ZendeskClient("acme", "a", "t", fetch=FakeZendesk({"/api/v2/x": lambda: (401, {}, b"")}))
    with pytest.raises(ZendeskError, match="credentials"):
        client.get("/api/v2/x")
    with pytest.raises(ValueError):
        ZendeskClient("acme.evil.com/x", "a", "t")


def test_refuses_to_follow_links_to_other_hosts():
    client = ZendeskClient("acme", "a", "t", fetch=FakeZendesk({}))
    with pytest.raises(ZendeskError, match="outside"):
        client.get("https://evil.example/api")
