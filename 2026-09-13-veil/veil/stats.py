"""A from-scratch chi-squared test, used to empirically check whether two
sample sets could plausibly come from the same distribution — the actual
statistical tool `simulator.py` uses to check "are real ZK transcripts and
simulated ZK transcripts distinguishable?"

No SciPy: the regularized incomplete gamma function (needed for the
chi-squared distribution's CDF) is computed here via the standard
series/continued-fraction algorithm (Numerical Recipes §6.2), using only
`math.lgamma` for the log-gamma normalizing term. This is the same
"hand-derive the actual numerical method, don't just call someone else's
implementation of it" standard the rest of this toolkit's cryptography is
held to.
"""

from __future__ import annotations

import math

_ITMAX = 200
_EPS = 3e-12


def _gamma_series(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) via its series expansion
    (valid/fast-converging for x < a + 1)."""
    if x == 0.0:
        return 0.0
    gln = math.lgamma(a)
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(_ITMAX):
        ap += 1
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - gln)


def _gamma_continued_fraction(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) via Lentz's continued
    fraction (valid/fast-converging for x >= a + 1)."""
    gln = math.lgamma(a)
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, _ITMAX + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi_square_sf(statistic: float, df: int) -> float:
    """Survival function of the chi-squared distribution: P(X >= statistic)
    for X ~ chi2(df). This is the p-value for a chi-squared test."""
    if statistic <= 0:
        return 1.0
    a = df / 2.0
    x = statistic / 2.0
    if x < a + 1.0:
        return 1.0 - _gamma_series(a, x)
    return _gamma_continued_fraction(a, x)


def two_sample_chi_square(counts_a: list[int], counts_b: list[int]) -> tuple[float, int, float]:
    """Pearson's chi-squared test of homogeneity between two samples binned
    into the same categories. Returns (statistic, degrees_of_freedom,
    p_value). A high p-value means the two samples are NOT statistically
    distinguishable from being drawn from the same distribution — this is
    the honest-verifier zero-knowledge property, made falsifiable.
    """
    if len(counts_a) != len(counts_b):
        raise ValueError("counts_a and counts_b must have the same number of categories")
    n_a = sum(counts_a)
    n_b = sum(counts_b)
    if n_a == 0 or n_b == 0:
        raise ValueError("both samples must be non-empty")
    n_total = n_a + n_b

    statistic = 0.0
    k = 0
    for oa, ob in zip(counts_a, counts_b):
        total = oa + ob
        if total == 0:
            continue  # a category nobody landed in contributes nothing
        k += 1
        expected_a = total * n_a / n_total
        expected_b = total * n_b / n_total
        if expected_a > 0:
            statistic += (oa - expected_a) ** 2 / expected_a
        if expected_b > 0:
            statistic += (ob - expected_b) ** 2 / expected_b

    df = max(k - 1, 1)
    p_value = chi_square_sf(statistic, df)
    return statistic, df, p_value
