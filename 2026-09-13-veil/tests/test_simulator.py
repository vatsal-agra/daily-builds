import random

from veil.group import STANDARD_GROUP as G
from veil import schnorr as S
from veil import coloring as C
from veil import simulator as SIM


def test_simulated_schnorr_transcript_is_accepting():
    rng = random.Random(1)
    kp = S.generate_keypair(G, rng)
    for _ in range(20):
        tr = SIM.simulate_schnorr_transcript(G, kp.y, rng)
        assert S.verify(G, kp.y, tr.t, tr.c, tr.s)


def test_simulated_coloring_round_is_accepting():
    rng = random.Random(2)
    for _ in range(10):
        result = SIM.simulate_coloring_round(C.HOUSE_GRAPH, rng)
        assert result.transcript.accepted
        assert result.attempts >= 1


def test_schnorr_indistinguishability_p_value_not_tiny():
    # A correct simulator should not be distinguishable from real
    # transcripts. Run with a large sample so the test is stable.
    rng = random.Random(3)
    kp = S.generate_keypair(G, rng)
    stat, df, p = SIM.schnorr_indistinguishability_test(G, kp.x, kp.y, rng, n_samples=3000, buckets=16)
    assert p > 0.01, f"unexpectedly low p-value {p} (stat={stat}, df={df})"


def test_coloring_indistinguishability_p_value_not_tiny():
    rng = random.Random(4)
    stat, df, p = SIM.coloring_indistinguishability_test(
        C.HOUSE_GRAPH, C.HOUSE_COLORING, rng, n_samples=3000
    )
    assert p > 0.01, f"unexpectedly low p-value {p} (stat={stat}, df={df})"


def test_simulator_actually_needs_no_witness():
    # Sanity: the simulator function signature never takes x/coloring — it
    # is structurally impossible for it to use a witness it isn't given.
    import inspect

    sig1 = inspect.signature(SIM.simulate_schnorr_transcript)
    assert "x" not in sig1.parameters

    sig2 = inspect.signature(SIM.simulate_coloring_round)
    assert "coloring" not in sig2.parameters
