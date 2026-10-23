import pytest

from agentaudit.estimate import estimate_cost
from agentaudit.models import Article, Conversation

ARTICLES = [Article("a", "Refunds", "x" * 8000)]           # ~2,000 tokens
CONVERSATIONS = [Conversation(f"c{i}", "billing", "q" * 400, "a" * 400) for i in range(10)]


def test_cost_range_brackets_caching_and_output_uncertainty():
    e = estimate_cost(ARTICLES, CONVERSATIONS, "claude-opus-5-5", "medium")
    assert e.conversations == 10
    assert e.cached_prefix_tokens > 2000
    low, high = e.cost_range
    assert 0 < low < high
    # Low end: one cache write, nine cache reads, 300 output tokens each.
    prefix = e.cached_prefix_tokens
    expected_low = (prefix * 5.00 + 9 * prefix * 0.20 + 10 * (100 + 100 + 40) * 4.00 + 10 * 300 * 20.00) / 1e6
    assert low == pytest.approx(expected_low)


def test_higher_effort_costs_more():
    low = estimate_cost(ARTICLES, CONVERSATIONS, "claude-opus-5-5", "low").cost_range[1]
    high = estimate_cost(ARTICLES, CONVERSATIONS, "claude-opus-5-5", "high").cost_range[1]
    assert high > low


def test_unknown_model_is_rejected():
    with pytest.raises(ValueError):
        estimate_cost(ARTICLES, CONVERSATIONS, "some-other-model", "medium")
