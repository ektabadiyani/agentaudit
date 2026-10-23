"""Command-line interface: `agentaudit grade` and `agentaudit report`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anthropic

from .grader import DEFAULT_EFFORT, DEFAULT_MODEL, Grader
from .loader import append_grade, load_articles, load_conversations, load_grades, load_human_labels
from .report import render_report


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
    g.set_defaults(func=cmd_grade)

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
