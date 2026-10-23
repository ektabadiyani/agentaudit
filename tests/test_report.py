from pathlib import Path

from agentaudit.loader import load_articles, load_conversations, load_human_labels
from agentaudit.models import Grade, Verdict
from agentaudit.report import render_report, summarise

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


def grades_from(labels):
    return [Grade(cid, v, explanation=f"graded {v.value}", cited_articles=["refunds-and-cancellation"])
            for cid, v in labels.items()]


def test_sample_data_loads():
    assert len(load_articles(SAMPLE / "help_center")) == 10
    assert len(load_conversations(SAMPLE / "conversations.jsonl")) == 34


def test_verified_resolution_is_lower_than_deflection():
    conversations = load_conversations(SAMPLE / "conversations.jsonl")
    labels = load_human_labels(SAMPLE / "reference_labels.csv")
    s = summarise(conversations, grades_from(labels), labels)
    assert s.deflection.successes == 32           # 2 of 34 handed off
    assert s.accuracy.successes == 18
    assert s.verified_resolution.successes == 17  # c14 is correct but was a handoff
    assert s.verified_resolution.value < s.deflection.value
    assert s.agreement.kappa == 1.0               # grades equal the labels


def test_report_lists_failures_and_disagreements():
    conversations = load_conversations(SAMPLE / "conversations.jsonl")
    labels = load_human_labels(SAMPLE / "reference_labels.csv")
    grades = grades_from(labels)
    grades[0] = Grade("c01", Verdict.PARTIAL, explanation="Grader thought tax note was missing")
    report = render_report(conversations, grades, labels)
    assert "## Answers to fix first" in report
    assert "### c02 · billing · incorrect" in report
    assert "| c01 | correct | partial |" in report
    assert "`refunds-and-cancellation`" in report


def test_report_without_labels_asks_for_calibration():
    conversations = load_conversations(SAMPLE / "conversations.jsonl")
    labels = load_human_labels(SAMPLE / "reference_labels.csv")
    report = render_report(conversations, grades_from(labels))
    assert "No human labels supplied" in report
