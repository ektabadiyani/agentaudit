"""Turn grades into a Markdown audit report a support leader can forward upward."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .models import Conversation, Grade, Verdict
from .stats import Agreement, Proportion, cohens_kappa, wilson_interval

VERDICT_ORDER = [Verdict.CORRECT, Verdict.PARTIAL, Verdict.INCORRECT, Verdict.UNSUPPORTED]
FAILURES = {Verdict.INCORRECT, Verdict.UNSUPPORTED}


@dataclass
class AuditSummary:
    total: int
    graded: int
    errors: list[Grade]
    deflection: Proportion            # AI kept the conversation (no handoff)
    verified_resolution: Proportion   # no handoff, not reopened, and graded correct
    accuracy: Proportion              # graded correct
    failure_rate: Proportion          # graded incorrect or unsupported
    verdicts: Counter
    by_topic: dict[str, tuple[Proportion, int]]  # topic -> (accuracy, failures)
    agreement: Agreement | None


def summarise(
    conversations: list[Conversation],
    grades: list[Grade],
    human_labels: dict[str, Verdict] | None = None,
) -> AuditSummary:
    by_id = {g.conversation_id: g for g in grades}
    graded = [(c, by_id[c.id]) for c in conversations if c.id in by_id and by_id[c.id].graded]
    errors = [g for g in grades if not g.graded]

    kept = sum(not c.handed_off for c in conversations)
    verified = sum(not c.handed_off and not c.reopened_within_7d and g.verdict is Verdict.CORRECT for c, g in graded)
    correct = sum(g.verdict is Verdict.CORRECT for _, g in graded)
    failed = sum(g.verdict in FAILURES for _, g in graded)

    topics: dict[str, list[Grade]] = defaultdict(list)
    for c, g in graded:
        topics[c.topic].append(g)
    by_topic = {
        topic: (
            wilson_interval(sum(g.verdict is Verdict.CORRECT for g in gs), len(gs)),
            sum(g.verdict in FAILURES for g in gs),
        )
        for topic, gs in sorted(topics.items())
    }

    agreement = None
    if human_labels:
        paired = [(human_labels[g.conversation_id], g.verdict) for _, g in graded if g.conversation_id in human_labels]
        if paired:
            human, machine = zip(*paired)
            agreement = cohens_kappa(human, machine)

    return AuditSummary(
        total=len(conversations),
        graded=len(graded),
        errors=errors,
        deflection=wilson_interval(kept, len(conversations)),
        verified_resolution=wilson_interval(verified, len(graded)),
        accuracy=wilson_interval(correct, len(graded)),
        failure_rate=wilson_interval(failed, len(graded)),
        verdicts=Counter(g.verdict for _, g in graded),
        by_topic=by_topic,
        agreement=agreement,
    )


def pct(p: Proportion) -> str:
    return f"{p.value:.0%} (95% CI {p.low:.0%}–{p.high:.0%}, n={p.total})"


def _short(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_report(
    conversations: list[Conversation],
    grades: list[Grade],
    human_labels: dict[str, Verdict] | None = None,
    title: str = "AI support agent audit",
) -> str:
    s = summarise(conversations, grades, human_labels)
    by_conv = {c.id: c for c in conversations}
    by_grade = {g.conversation_id: g for g in grades}
    out: list[str] = [f"# {title}", ""]

    out += [
        "## Headline",
        "",
        f"- **Deflection rate:** {pct(s.deflection)}. The share of conversations the AI kept without handing off. "
        "This is what most dashboards report.",
        f"- **Verified resolution rate:** {pct(s.verified_resolution)}. Kept by the AI, not reopened within 7 days, "
        "*and* graded correct against the help centre.",
        f"- **Answer accuracy:** {pct(s.accuracy)} graded fully correct.",
        f"- **Wrong or made-up answers:** {pct(s.failure_rate)}.",
        "",
        f"Graded {s.graded} of {s.total} conversations."
        + (f" {len(s.errors)} could not be graded (listed under Method)." if s.errors else ""),
        "",
        "## Verdicts",
        "",
        "| Verdict | Count | Share |",
        "|---|---|---|",
    ]
    for v in VERDICT_ORDER:
        count = s.verdicts.get(v, 0)
        out.append(f"| {v.value} | {count} | {count / s.graded:.0%} |" if s.graded else f"| {v.value} | 0 | – |")

    out += ["", "## Accuracy by topic", "", "| Topic | Correct | 95% CI | Wrong or made up |", "|---|---|---|---|"]
    for topic, (acc, failures) in sorted(s.by_topic.items(), key=lambda kv: kv[1][0].value):
        out.append(f"| {topic} | {acc.successes}/{acc.total} ({acc.value:.0%}) | {acc.low:.0%}–{acc.high:.0%} | {failures} |")

    failures = [g for g in grades if g.verdict in FAILURES]
    out += ["", "## Answers to fix first", ""]
    if not failures:
        out.append("No incorrect or unsupported answers in this sample.")
    for g in failures:
        c = by_conv[g.conversation_id]
        out += [
            f"### {c.id} · {c.topic} · {g.verdict.value}",
            "",
            f"- **Customer asked:** {_short(c.question)}",
            f"- **AI answered:** {_short(c.ai_answer, 220)}",
            f"- **Problem:** {g.explanation}",
        ]
        if g.unsupported_claims:
            out.append("- **Claims not backed by the help centre:** " + "; ".join(f"“{x}”" for x in g.unsupported_claims))
        if g.cited_articles:
            out.append("- **Check against:** " + ", ".join(f"`{a}`" for a in g.cited_articles))
        out.append("")

    article_hits = Counter(a for g in grades if g.verdict in FAILURES | {Verdict.PARTIAL} for a in g.cited_articles)
    out += ["## Help articles involved in weak answers", ""]
    if article_hits:
        out += ["These articles were cited in partial, incorrect or unsupported answers. Review them for gaps, "
                "ambiguity, or content the AI agent is not retrieving.", "", "| Article | Weak answers |", "|---|---|"]
        out += [f"| `{a}` | {n} |" for a, n in article_hits.most_common()]
    else:
        out.append("None.")

    out += ["", "## Can the grader be trusted?", ""]
    if s.agreement:
        a = s.agreement
        out += [
            f"A human graded {a.n} of the same conversations independently. The AI grader agreed on "
            f"**{a.observed:.0%}** of them. Cohen's kappa is **{a.kappa:.2f}** ({a.interpretation} agreement), "
            "which discounts the agreement two raters would reach by chance.",
            "",
            "Rows are the human's verdict, columns the grader's:",
            "",
            "| Human \\ Grader | " + " | ".join(v.value for v in VERDICT_ORDER) + " |",
            "|---" * (len(VERDICT_ORDER) + 1) + "|",
        ]
        for h in VERDICT_ORDER:
            out.append(f"| {h.value} | " + " | ".join(str(a.confusion.get((h, m), 0)) for m in VERDICT_ORDER) + " |")
        disagreements = [
            (cid, label, by_grade[cid]) for cid, label in (human_labels or {}).items()
            if cid in by_grade and by_grade[cid].graded and by_grade[cid].verdict is not label
        ]
        if disagreements:
            out += ["", "Disagreements to review:", "", "| Conversation | Human | Grader | Grader's reason |", "|---|---|---|---|"]
            out += [f"| {cid} | {label.value} | {g.verdict.value} | {_cell(_short(g.explanation, 160))} |" for cid, label, g in disagreements]
    else:
        out.append("No human labels supplied. Grade a sample by hand and pass `--labels` to measure agreement "
                   "before relying on these numbers.")
    low = [g.conversation_id for g in grades if g.graded and g.confidence and g.confidence.value == "low"]
    if low:
        out += ["", f"The grader marked {len(low)} verdict(s) as low confidence; review these by hand: " + ", ".join(low) + "."]

    out += [
        "",
        "## Method and limitations",
        "",
        "- Each answer was graded by an LLM against the supplied help-centre articles only. Precedence: incorrect > "
        "unsupported > partial > correct.",
        "- Confidence intervals are 95% Wilson score intervals. Small samples give wide intervals; read them before "
        "comparing topics.",
        "- The grader checks answers against the help centre, not against reality. If an article is out of date, "
        "an answer that matches it is graded correct.",
        "- Verified resolution relies on the reopen flag in the export. Customers who give up without reopening are "
        "counted as resolved, so this rate is an upper bound.",
    ]
    if grades:
        out.append(f"- Grader model: `{next((g.model for g in grades if g.model), 'unknown')}`.")
    if s.errors:
        out.append("- Not graded: " + ", ".join(f"{g.conversation_id} ({g.error})" for g in s.errors) + ".")
    return "\n".join(out) + "\n"
