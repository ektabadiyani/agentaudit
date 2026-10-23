"""Statistics for reporting accuracy honestly: confidence intervals and grader agreement."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Proportion:
    successes: int
    total: int
    low: float
    high: float

    @property
    def value(self) -> float:
        return self.successes / self.total if self.total else 0.0


def wilson_interval(successes: int, total: int, z: float = 1.96) -> Proportion:
    """95% Wilson score interval. Unlike the textbook p ± z·√(p(1-p)/n), it stays
    inside [0, 1] and behaves sensibly for small samples and rates near 0% or 100%."""
    if total == 0:
        return Proportion(0, 0, 0.0, 0.0)
    p = successes / total
    denominator = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator
    return Proportion(successes, total, max(0.0, centre - margin), min(1.0, centre + margin))


@dataclass(frozen=True)
class Agreement:
    n: int
    observed: float          # share of items where both raters agree
    kappa: float             # Cohen's kappa: agreement beyond what chance alone would produce
    confusion: dict[tuple[Hashable, Hashable], int]  # (human, grader) -> count

    @property
    def interpretation(self) -> str:
        # Landis & Koch (1977) bands, the conventional reading of kappa.
        k = self.kappa
        if k < 0:
            return "worse than chance"
        for upper, label in [(0.2, "slight"), (0.4, "fair"), (0.6, "moderate"), (0.8, "substantial")]:
            if k <= upper:
                return label
        return "almost perfect"


def cohens_kappa(human: Sequence[Hashable], grader: Sequence[Hashable]) -> Agreement:
    if len(human) != len(grader):
        raise ValueError("Both raters must label the same items")
    n = len(human)
    if n == 0:
        return Agreement(0, 0.0, 0.0, {})
    observed = sum(h == g for h, g in zip(human, grader)) / n
    human_counts, grader_counts = Counter(human), Counter(grader)
    expected = sum(human_counts[c] * grader_counts[c] for c in human_counts) / n**2
    kappa = 1.0 if expected == 1 else (observed - expected) / (1 - expected)
    return Agreement(n, observed, kappa, dict(Counter(zip(human, grader))))
