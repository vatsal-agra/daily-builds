import random

import pytest

from veil.group import (
    STANDARD_GROUP,
    generate_safe_prime_group,
    is_prime,
    is_safe_prime_group,
    is_valid_group_element,
)


def test_standard_group_is_valid():
    g = STANDARD_GROUP
    assert is_safe_prime_group(g.p, g.q, g.g)


def _trial_division_is_prime(n: int) -> bool:
    """Independent reference oracle (not the code under test)."""
    if n < 2:
        return False
    for d in range(2, int(n**0.5) + 1):
        if n % d == 0:
            return False
    return True


def test_is_prime_small_values():
    for n in range(2, 500):
        assert is_prime(n) == _trial_division_is_prime(n), n


def test_is_prime_rejects_non_positive_and_one():
    assert not is_prime(-5)
    assert not is_prime(0)
    assert not is_prime(1)


def test_is_prime_large_known_prime_and_composite():
    # A larger known prime (2^61 - 1, a Mersenne prime) and a large composite.
    assert is_prime(2**61 - 1)
    assert not is_prime((2**61 - 1) * (2**31 - 1))


def test_pow_g_reduces_exponent_mod_q():
    g = STANDARD_GROUP
    assert g.pow_g(5) == g.pow_g(5 + g.q)
    assert g.pow_g(-1) == g.pow_g(g.q - 1)


def test_random_exponent_in_range():
    g = STANDARD_GROUP
    rng = random.Random(1)
    for _ in range(200):
        x = g.random_exponent(rng)
        assert 1 <= x < g.q


def test_is_valid_group_element_accepts_real_keys():
    g = STANDARD_GROUP
    rng = random.Random(2)
    for _ in range(50):
        x = g.random_exponent(rng)
        y = g.pow_g(x)
        assert is_valid_group_element(g, y)


def test_is_valid_group_element_rejects_identity_and_order_two_element():
    # REVIEW.md Finding 1: y=1 (identity) and y=p-1 (order-2 element) must
    # both be rejected — neither is a genuine member of <g>.
    g = STANDARD_GROUP
    assert not is_valid_group_element(g, 1)
    assert not is_valid_group_element(g, g.p - 1)


def test_is_valid_group_element_rejects_out_of_range():
    g = STANDARD_GROUP
    assert not is_valid_group_element(g, 0)
    assert not is_valid_group_element(g, -5)
    assert not is_valid_group_element(g, g.p)
    assert not is_valid_group_element(g, g.p + 100)


def test_generate_safe_prime_group_produces_valid_group():
    for seed in range(5):
        group = generate_safe_prime_group(bits=32, seed=seed)
        assert is_safe_prime_group(group.p, group.q, group.g)
        assert group.p.bit_length() == 32
        assert group.q.bit_length() == 31


def test_generate_safe_prime_group_rejects_tiny_bits():
    # REVIEW.md Finding 3: bits < 8 used to hang forever.
    for bits in (0, 1, 2, 3, 7):
        with pytest.raises(ValueError):
            generate_safe_prime_group(bits=bits, seed=1)


def test_schnorr_group_rejects_invalid_construction():
    from veil.group import SchnorrGroup

    with pytest.raises(ValueError):
        SchnorrGroup(p=15, q=7, g=2)  # 15 is not prime
