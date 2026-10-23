"""Command-line interface: `pull-zendesk`, `estimate`, `grade` and `report`."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import anthropic

from .grader import DEFAULT_EFFORT, DEFAULT_MODEL, Grader
from .loader import append_grade, load_articles, load_conversations, load_grades, load_human_labels
from .estimate import PRICES, estimate_cost
from .redact import Redactor
from .report import render_report
from .zendesk import ZendeskClient, ZendeskError, pull_articles, pull_conversations


def cmd_grade(args: argparse.Namespace) -> int:
    articles = load_articles(args.kb)
    conversations = load_conversations(args.conversations)
    out = Path(args.out)

    # Resume: skip conversations that already have a successful grade in the output file.
    done = {g.conversation_id for g in load_grades(out) if g.graded}
    todo = [c for c in conversations if c.id not in done]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print(f"All {len(conversations)} conversations already graded in {out}.")
        return 0

    if not args.no_redact:
        redactor = Redactor()
        todo = [replace(c, question=redactor.redact(c.question), ai_answer=redactor.redact(c.ai_answer)) for c in todo]
        if redactor.counts:
            print("Removed personal data before grading: " + ", ".join(f"{n} {k.lower()}" for k, n in redactor.counts.items()))

    if args.model in PRICES:
        e = estimate_cost(articles, todo, args.model, args.effort)
        print(f"Estimated cost: ${e.cost_range[0]:.2f}–${e.cost_range[1]:.2f} for {len(todo)} conversations.")
    if not args.yes:
        if not sys.stdin.isatty():
            print("Add --yes to confirm grading when not running interactively.", file=sys.stderr)
            return 1
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled. Nothing was sent.")
            return 0

    print(f"Grading {len(todo)} conversations against {len(articles)} articles with {args.model}…")
    grader = Grader(articles, model=args.model, effort=args.effort)

    def record(grade):
        append_grade(out, grade)
        status = grade.verdict.value if grade.graded else f"ERROR: {grade.error}"
        print(f"  {grade.conversation_id}: {status}")

    try:
        grader.grade_all(todo, workers=args.workers, on_result=record)
    except anthropic.AuthenticationError:
        print("Authentication failed: the API key was rejected. Check ANTHROPIC_API_KEY.", file=sys.stderr)
        return 2
    except TypeError as e:
        # The SDK raises TypeError when no credentials are configured at all.
        if "authentication method" not in str(e):
            raise
        print("No Anthropic credentials found. Set ANTHROPIC_API_KEY or run `ant auth login`.", file=sys.stderr)
        return 2
    print(f"Grades written to {out}")
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    articles = load_articles(args.kb)
    conversations = load_conversations(args.conversations)
    if args.limit:
        conversations = conversations[: args.limit]
    try:
        e = estimate_cost(articles, conversations, args.model, args.effort)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    print(f"Model {e.model}, effort {e.effort}, {e.conversations} conversations, {len(articles)} articles")
    print(f"  Help centre + instructions: ~{e.cached_prefix_tokens:,} tokens per call (cached after the first when long enough)")
    print(f"  Question + answer: ~{e.per_conversation_input_tokens:,} tokens per conversation")
    print(f"  Output: ~{e.output_range[0]:,}–{e.output_range[1]:,} tokens per grade")
    print(f"  Estimated cost: ${e.cost_range[0]:.2f}–${e.cost_range[1]:.2f}")
    print("Token counts are approximate (characters / 4). Nothing was sent to the API.")
    return 0


def cmd_pull_zendesk(args: argparse.Namespace) -> int:
    subdomain = args.subdomain or os.environ.get("ZENDESK_SUBDOMAIN")
    email = args.email or os.environ.get("ZENDESK_EMAIL")
    token = os.environ.get("ZENDESK_API_TOKEN")
    missing = [name for name, value in [("--subdomain or ZENDESK_SUBDOMAIN", subdomain),
                                        ("--email or ZENDESK_EMAIL", email), ("ZENDESK_API_TOKEN", token)] if not value]
    if missing:
        print("Missing: " + ", ".join(missing) + ". The API token is read only from the environment, "
              "so it never ends up in your shell history.", file=sys.stderr)
        return 1
    out = Path(args.out)
    since = date.fromisoformat(args.since) if args.since else date.today() - timedelta(days=30)
    try:
        client = ZendeskClient(subdomain, email, token)
        if not args.skip_articles:
            n = pull_articles(client, out / "help_center", args.locale)
            print(f"Saved {n} published articles to {out / 'help_center'}")
        redactor = None if args.no_redact else Redactor()
        stats = pull_conversations(
            client, out / "conversations.jsonl", ai_author_ids=set(args.ai_author_id), since=since,
            ai_tag=args.ai_tag, topic_tag_prefix=args.topic_tag_prefix, limit=args.limit, redactor=redactor,
            on_progress=lambda i: print(f"  …checked {i} tickets"),
        )
    except (ZendeskError, ValueError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    print(f"Saved {stats.written} AI conversations to {out / 'conversations.jsonl'}")
    for reason, count in stats.skipped.most_common():
        print(f"  skipped {count}: {reason}")
    if redactor and redactor.counts:
        print("Removed personal data: " + ", ".join(f"{n} {k.lower()}" for k, n in redactor.counts.items()))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    conversations = load_conversations(args.conversations)
    grades = load_grades(args.grades)
    if not grades:
        print(f"No grades found in {args.grades}. Run `agentaudit grade` first.", file=sys.stderr)
        return 1
    # If a conversation was graded more than once (e.g. a failed attempt then a retry), keep the latest.
    latest = {g.conversation_id: g for g in grades}
    labels = load_human_labels(args.labels) if args.labels else None
    report = render_report(conversations, list(latest.values()), labels, title=args.title)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report, encoding="utf-8")
    print(f"Report written to {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentaudit", description="Audit an AI support agent's answers against its help centre.")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("grade", help="Grade AI answers against help-centre articles")
    g.add_argument("--kb", required=True, help="Directory of help-centre articles (.md)")
    g.add_argument("--conversations", required=True, help="JSONL file of conversations")
    g.add_argument("--out", required=True, help="JSONL file to append grades to (re-running resumes)")
    g.add_argument("--model", default=DEFAULT_MODEL)
    g.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    g.add_argument("--workers", type=int, default=4)
    g.add_argument("--limit", type=int, help="Grade at most this many (useful for a cheap first run)")
    g.add_argument("--no-redact", action="store_true", help="Send conversations without removing personal data")
    g.add_argument("--yes", action="store_true", help="Skip the cost confirmation prompt")
    g.set_defaults(func=cmd_grade)

    e = sub.add_parser("estimate", help="Estimate what grading will cost, without calling the API")
    e.add_argument("--kb", required=True)
    e.add_argument("--conversations", required=True)
    e.add_argument("--model", default=DEFAULT_MODEL)
    e.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    e.add_argument("--limit", type=int)
    e.set_defaults(func=cmd_estimate)

    z = sub.add_parser("pull-zendesk", help="Download help-centre articles and AI-handled tickets from Zendesk")
    z.add_argument("--out", required=True, help="Folder to write help_center/ and conversations.jsonl into")
    z.add_argument("--subdomain", help="The 'acme' in acme.zendesk.com (or set ZENDESK_SUBDOMAIN)")
    z.add_argument("--email", help="Zendesk user the API token belongs to (or set ZENDESK_EMAIL)")
    z.add_argument("--ai-author-id", type=int, action="append", required=True,
                   help="Zendesk user id the AI agent posts as. Repeat for several bots.")
    z.add_argument("--ai-tag", help="Only tickets with this tag, e.g. the tag your AI agent adds")
    z.add_argument("--since", help="Tickets created on or after YYYY-MM-DD (default: 30 days ago)")
    z.add_argument("--topic-tag-prefix", default="topic_", help="Tag prefix that names the topic (default topic_)")
    z.add_argument("--locale", default="en-us", help="Help-centre locale (default en-us)")
    z.add_argument("--limit", type=int, help="Stop after this many AI conversations")
    z.add_argument("--skip-articles", action="store_true", help="Only download tickets")
    z.add_argument("--no-redact", action="store_true", help="Keep personal data in the saved conversations")
    z.set_defaults(func=cmd_pull_zendesk)

    r = sub.add_parser("report", help="Build the Markdown audit report")
    r.add_argument("--conversations", required=True)
    r.add_argument("--grades", required=True)
    r.add_argument("--labels", help="CSV of human verdicts (conversation_id,verdict) to measure grader agreement")
    r.add_argument("--out", required=True)
    r.add_argument("--title", default="AI support agent audit")
    r.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
