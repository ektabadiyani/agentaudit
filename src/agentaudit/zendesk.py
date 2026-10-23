"""Pull help-centre articles and AI-handled tickets from Zendesk into AgentAudit's format.

Output is the same layout as the sample data, so `agentaudit grade` works on it unchanged:

    <out>/help_center/<article-id>-<slug>.md
    <out>/conversations.jsonl

How a ticket becomes a conversation:
- question: the requester's public comments before the AI agent first replied
- ai_answer: the AI agent's public replies before any human agent replied
- handed_off: a human agent (anyone other than the requester and the AI) replied publicly
- reopened_within_7d: the ticket's metrics show at least one reopen (Zendesk doesn't record
  when, so this counts any reopen)
- csat: satisfaction "good" -> 5, "bad" -> 1, otherwise empty
- topic: the first tag starting with --topic-tag-prefix, prefix removed
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .htmltext import html_to_text
from .redact import Redactor

Response = tuple[int, dict[str, str], bytes]
Fetch = Callable[[str, dict[str, str]], Response]

SUBDOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
CSAT = {"good": 5, "bad": 1}


class ZendeskError(RuntimeError):
    pass


def urllib_fetch(url: str, headers: dict[str, str]) -> Response:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""


class ZendeskClient:
    def __init__(
        self,
        subdomain: str,
        email: str,
        api_token: str,
        fetch: Fetch = urllib_fetch,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 5,
    ):
        if not SUBDOMAIN.match(subdomain):
            raise ValueError(f"'{subdomain}' doesn't look like a Zendesk subdomain (the 'acme' in acme.zendesk.com)")
        self.base = f"https://{subdomain}.zendesk.com"
        token = base64.b64encode(f"{email}/token:{api_token}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        self.fetch, self.sleep, self.max_retries = fetch, sleep, max_retries

    def get(self, path_or_url: str, params: dict | None = None) -> dict:
        url = path_or_url if path_or_url.startswith("https://") else self.base + path_or_url
        if not url.startswith(self.base + "/"):
            raise ZendeskError(f"Refusing to follow a link outside {self.base}: {url}")
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        for attempt in range(self.max_retries + 1):
            status, headers, body = self.fetch(url, self.headers)
            if status == 429 or status >= 500:
                if attempt == self.max_retries:
                    break
                wait = headers.get("Retry-After") or headers.get("retry-after")
                self.sleep(float(wait) if wait else min(60, 2 ** attempt))
                continue
            if status in (401, 403):
                raise ZendeskError("Zendesk rejected the credentials. Check the email, API token and that token access is enabled.")
            if status == 404:
                raise ZendeskError(f"Not found: {url}")
            if status >= 400:
                raise ZendeskError(f"Zendesk returned {status} for {url}: {body[:200]!r}")
            return json.loads(body)
        raise ZendeskError(f"Zendesk kept returning {status} for {url} after {self.max_retries} retries")

    def paginate(self, path: str, key: str, params: dict | None = None) -> Iterator[dict]:
        """Follow cursor pagination (links.next while meta.has_more), falling back to the
        older offset style (next_page) that some endpoints still return."""
        page = self.get(path, {"page[size]": 100, **(params or {})})
        while True:
            yield from page.get(key, [])
            if page.get("meta", {}).get("has_more") and page.get("links", {}).get("next"):
                page = self.get(page["links"]["next"])
            elif page.get("next_page"):
                page = self.get(page["next_page"])
            else:
                return


# ---------------------------------------------------------------- articles

def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "article"


def pull_articles(client: ZendeskClient, out_dir: Path, locale: str = "en-us") -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for article in client.paginate(f"/api/v2/help_center/{urllib.parse.quote(locale)}/articles", "articles"):
        if article.get("draft"):
            continue
        body = html_to_text(article.get("body") or "")
        source = f"\n\nSource: {article['html_url']}" if article.get("html_url") else ""
        path = out_dir / f"{article['id']}-{_slug(article['title'])}.md"
        path.write_text(f"# {article['title']}\n\n{body}{source}\n", encoding="utf-8")
        count += 1
    return count


# ---------------------------------------------------------------- tickets

@dataclass
class PullStats:
    written: int = 0
    skipped: Counter = field(default_factory=Counter)


def ticket_to_conversation(
    ticket: dict,
    comments: list[dict],
    reopens: int,
    ai_author_ids: set[int],
    topic_tag_prefix: str = "topic_",
) -> tuple[dict | None, str | None]:
    """Return (conversation, None) or (None, reason it was skipped)."""
    requester = ticket.get("requester_id")
    public = sorted((c for c in comments if c.get("public", True)), key=lambda c: c.get("created_at", ""))
    question, answers, handed_off = [], [], False
    for c in public:
        text = (c.get("plain_body") or c.get("body") or "").strip()
        author = c.get("author_id")
        if author in ai_author_ids:
            if not handed_off and text:
                answers.append(text)
        elif author == requester:
            if not answers and text:
                question.append(text)
        else:
            handed_off = True
    if not answers:
        return None, "no AI reply"
    if not question:
        return None, "no customer question before the AI replied"

    tags = ticket.get("tags") or []
    topic = next((t[len(topic_tag_prefix):] for t in tags if t.startswith(topic_tag_prefix)), "uncategorised")
    score = (ticket.get("satisfaction_rating") or {}).get("score")
    return {
        "id": f"zd-{ticket['id']}",
        "topic": topic or "uncategorised",
        "question": "\n\n".join(question),
        "ai_answer": "\n\n".join(answers),
        "handed_off": handed_off,
        "reopened_within_7d": reopens > 0,
        "csat": CSAT.get(score),
    }, None


def pull_conversations(
    client: ZendeskClient,
    out_file: Path,
    ai_author_ids: set[int],
    since: date,
    ai_tag: str | None = None,
    topic_tag_prefix: str = "topic_",
    limit: int | None = None,
    redactor: Redactor | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> PullStats:
    query = f"type:ticket created>={since.isoformat()}" + (f" tags:{ai_tag}" if ai_tag else "")
    stats = PullStats()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        for i, ticket in enumerate(client.paginate("/api/v2/search/export", "results",
                                                   {"query": query, "filter[type]": "ticket"}), start=1):
            if limit and stats.written >= limit:
                break
            comments = list(client.paginate(f"/api/v2/tickets/{ticket['id']}/comments", "comments"))
            metrics = client.get(f"/api/v2/tickets/{ticket['id']}/metrics").get("ticket_metric") or {}
            conversation, reason = ticket_to_conversation(
                ticket, comments, int(metrics.get("reopens") or 0), ai_author_ids, topic_tag_prefix)
            if reason:
                stats.skipped[reason] += 1
                continue
            if redactor:
                conversation["question"] = redactor.redact(conversation["question"])
                conversation["ai_answer"] = redactor.redact(conversation["ai_answer"])
            f.write(json.dumps(conversation) + "\n")
            stats.written += 1
            if on_progress and i % 25 == 0:
                on_progress(i)
    return stats
