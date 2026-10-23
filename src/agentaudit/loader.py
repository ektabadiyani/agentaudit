"""Read help-centre articles, conversations, grades and human labels from disk."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Article, Conversation, Grade, Verdict


def load_articles(directory: str | Path) -> list[Article]:
    """Load every Markdown file in a directory. The file stem is the article id;
    the first `# ` heading is the title."""
    articles = []
    for path in sorted(Path(directory).glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        first_line, _, rest = text.partition("\n")
        if first_line.startswith("# "):
            title, body = first_line[2:].strip(), rest.strip()
        else:
            title, body = path.stem.replace("-", " ").title(), text
        articles.append(Article(id=path.stem, title=title, body=body))
    if not articles:
        raise ValueError(f"No .md articles found in {directory}")
    return articles


def load_conversations(path: str | Path) -> list[Conversation]:
    conversations = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            try:
                conversations.append(
                    Conversation(
                        id=row["id"],
                        topic=row.get("topic", "uncategorised"),
                        question=row["question"],
                        ai_answer=row["ai_answer"],
                        handed_off=bool(row.get("handed_off", False)),
                        reopened_within_7d=bool(row.get("reopened_within_7d", False)),
                        csat=row.get("csat"),
                    )
                )
            except KeyError as e:
                raise ValueError(f"{path}:{line_no} is missing field {e}") from e
    return conversations


def load_grades(path: str | Path) -> list[Grade]:
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [Grade.from_dict(json.loads(line)) for line in f if line.strip()]


def append_grade(path: str | Path, grade: Grade) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(grade.to_dict()) + "\n")


def load_human_labels(path: str | Path) -> dict[str, Verdict]:
    """CSV with columns `conversation_id,verdict`. Blank verdicts are skipped,
    so a half-finished labelling sheet still loads."""
    labels = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            value = (row.get("verdict") or "").strip().lower()
            if value:
                labels[row["conversation_id"].strip()] = Verdict(value)
    return labels
