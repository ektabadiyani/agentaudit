"""Estimate what a grading run will cost before spending anything.

Token counts are approximated offline as characters / 4, which is close for English text.
Output per grade varies with the effort setting, so the estimate is a low-high range.
"""

from __future__ import annotations

from dataclasses import dataclass

from .grader import INSTRUCTIONS, format_knowledge_base
from .models import Article, Conversation

# USD per million tokens: input, output, cache write (5-minute), cache read.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}
# Output tokens per grade (reasoning plus the JSON verdict), by effort level.
OUTPUT_TOKENS = {"low": (150, 600), "medium": (300, 1500), "high": (600, 3000), "xhigh": (1000, 5000), "max": (1500, 8000)}
PROMPT_OVERHEAD_TOKENS = 40  # XML tags around the question and answer


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class Estimate:
    conversations: int
    cached_prefix_tokens: int
    per_conversation_input_tokens: int
    output_range: tuple[int, int]
    cost_range: tuple[float, float]
    model: str
    effort: str


def estimate_cost(
    articles: list[Article], conversations: list[Conversation], model: str, effort: str
) -> Estimate:
    if model not in PRICES:
        raise ValueError(f"No price table for {model}. Known: {', '.join(PRICES)}")
    price_in, price_out, price_write, price_read = PRICES[model]
    prefix = approx_tokens(INSTRUCTIONS) + approx_tokens(format_knowledge_base(articles))
    n = len(conversations)
    variable = sum(approx_tokens(c.question) + approx_tokens(c.ai_answer) + PROMPT_OVERHEAD_TOKENS for c in conversations)
    low_out, high_out = OUTPUT_TOKENS[effort]

    # Best case: the help centre is written to the cache once and read on every later call.
    # Worst case: it isn't cached at all (a small help centre can be below the model's minimum
    # cacheable length), so every call pays full input price for it.
    def cost(output_per_grade: int, cached: bool) -> float:
        prefix_cost = (prefix * price_write + (n - 1) * prefix * price_read) if cached and n else n * prefix * price_in
        return (prefix_cost + variable * price_in + n * output_per_grade * price_out) / 1_000_000

    return Estimate(
        conversations=n,
        cached_prefix_tokens=prefix,
        per_conversation_input_tokens=variable // max(n, 1),
        output_range=(low_out, high_out),
        cost_range=(cost(low_out, True), cost(high_out, False)),
        model=model,
        effort=effort,
    )
