import pytest

from agentaudit.stats import cohens_kappa, wilson_interval


def test_wilson_interval_known_value():
    # 8 of 10: the Wilson 95% interval is about 49%–94%.
    p = wilson_interval(8, 10)
    assert p.value == 0.8
    assert p.low == pytest.approx(0.490, abs=0.001)
    assert p.high == pytest.approx(0.943, abs=0.001)


def test_wilson_interval_stays_in_bounds_at_extremes():
    assert wilson_interval(0, 5).low == 0.0
    assert wilson_interval(5, 5).high == 1.0
    assert wilson_interval(0, 0).total == 0


def test_kappa_perfect_agreement():
    a = cohens_kappa(["x", "y", "x", "z"], ["x", "y", "x", "z"])
    assert a.observed == 1.0
    assert a.kappa == 1.0
    assert a.interpretation == "almost perfect"


def test_kappa_discounts_chance_agreement():
    # Both raters say "x" 90% of the time, so 82% agreement is roughly what chance gives.
    human = ["x"] * 9 + ["y"]
    grader = ["x"] * 8 + ["y", "x"]
    a = cohens_kappa(human, grader)
    assert a.observed == pytest.approx(0.8)
    assert a.kappa < 0  # no better than chance despite 80% raw agreement
    assert a.confusion[("y", "x")] == 1


def test_kappa_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        cohens_kappa(["x"], ["x", "y"])
