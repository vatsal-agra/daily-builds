import random

from veil.stats import chi_square_sf, two_sample_chi_square


def test_chi_square_sf_matches_known_critical_values():
    # Standard textbook critical values at alpha=0.05.
    known = [(1, 3.841), (2, 5.991), (3, 7.815), (5, 11.070), (10, 18.307)]
    for df, crit in known:
        p = chi_square_sf(crit, df)
        assert abs(p - 0.05) < 0.001


def test_chi_square_sf_of_zero_is_one():
    assert chi_square_sf(0, 5) == 1.0


def test_chi_square_sf_decreases_with_statistic():
    df = 4
    p_small = chi_square_sf(1.0, df)
    p_large = chi_square_sf(20.0, df)
    assert p_small > p_large


def test_two_sample_chi_square_identical_distributions_high_p_value():
    rng = random.Random(1)
    categories = 6
    counts_a = [0] * categories
    counts_b = [0] * categories
    for _ in range(5000):
        counts_a[rng.randrange(categories)] += 1
        counts_b[rng.randrange(categories)] += 1
    stat, df, p = two_sample_chi_square(counts_a, counts_b)
    assert df == categories - 1
    assert p > 0.01  # should not look distinguishable


def test_two_sample_chi_square_obviously_different_distributions_low_p_value():
    # counts_a is uniform, counts_b is massively skewed to one category
    counts_a = [1000, 1000, 1000, 1000]
    counts_b = [10, 10, 10, 3970]
    stat, df, p = two_sample_chi_square(counts_a, counts_b)
    assert p < 1e-6


def test_two_sample_chi_square_requires_matching_categories():
    import pytest

    with pytest.raises(ValueError):
        two_sample_chi_square([1, 2, 3], [1, 2])
