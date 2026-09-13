import random

import pytest

from veil import coloring as C


def test_house_coloring_is_valid():
    assert C.is_valid_coloring(C.HOUSE_GRAPH, C.HOUSE_COLORING)


def test_invalid_coloring_detected():
    bad = [0, 0, 1, 1, 2]  # vertex 0 and 1 share a color but are adjacent
    assert not C.is_valid_coloring(C.HOUSE_GRAPH, bad)


def test_completeness_honest_prover_always_accepts():
    rng = random.Random(1)
    transcripts = C.run_protocol(C.HOUSE_GRAPH, C.HOUSE_COLORING, 200, rng)
    assert all(t.accepted for t in transcripts)


def test_soundness_empirical_catch_rate_meets_theoretical_bound():
    rng = random.Random(2)
    trials = 20000
    caught = 0
    for _ in range(trials):
        coloring = [rng.randrange(3) for _ in range(C.K4_GRAPH.num_vertices)]
        t = C.run_round(C.K4_GRAPH, coloring, rng)
        if not t.accepted:
            caught += 1
    empirical_catch_rate = caught / trials
    min_catch_rate = 1 - C.soundness_error_bound(len(C.K4_GRAPH.edges), 1)
    # Allow a small statistical margin around the theoretical minimum.
    assert empirical_catch_rate >= min_catch_rate - 0.03


def test_soundness_worst_case_one_bad_edge_matches_bound_exactly():
    # A coloring with EXACTLY one bad edge is the worst case for the
    # prover: catch probability should be exactly 1/|E| per round.
    rng = random.Random(3)
    graph = C.Graph(num_vertices=4, edges=((0, 1), (1, 2), (2, 3), (3, 0)))
    coloring = [0, 0, 1, 2]  # only edge (0,1) is bad
    assert C.count_bad_edges(graph, coloring) == 1
    trials = 40000
    caught = 0
    for _ in range(trials):
        t = C.run_round(graph, coloring, rng)
        if not t.accepted:
            caught += 1
    empirical = caught / trials
    expected = 1 / len(graph.edges)
    assert abs(empirical - expected) < 0.02


def test_soundness_error_bound_amplifies_with_rounds():
    b1 = C.soundness_error_bound(6, 1)
    b10 = C.soundness_error_bound(6, 10)
    b50 = C.soundness_error_bound(6, 50)
    assert b1 > b10 > b50 > 0


def test_soundness_error_bound_zero_edges_is_one():
    assert C.soundness_error_bound(0, 100) == 1.0


def test_reproducibility_under_seed():
    # REVIEW.md Finding 4: nonces must come from the passed-in rng so a
    # seeded run reproduces byte-for-byte.
    rng1 = random.Random(42)
    t1 = C.run_protocol(C.HOUSE_GRAPH, C.HOUSE_COLORING, 10, rng1)
    rng2 = random.Random(42)
    t2 = C.run_protocol(C.HOUSE_GRAPH, C.HOUSE_COLORING, 10, rng2)
    for a, b in zip(t1, t2):
        assert a.commitments == b.commitments
        assert a.edge_index == b.edge_index
        assert a.opening == b.opening


def test_double_open_rejected():
    # REVIEW.md Finding 5.
    rng = random.Random(4)
    state = C.commit_round(C.HOUSE_GRAPH, C.HOUSE_COLORING, rng)
    C.open_round(C.HOUSE_GRAPH, state, 0)
    with pytest.raises(RuntimeError):
        C.open_round(C.HOUSE_GRAPH, state, 1)


def test_graph_rejects_self_loop():
    with pytest.raises(ValueError):
        C.Graph(num_vertices=3, edges=((0, 0),))


def test_graph_rejects_out_of_range_vertex():
    with pytest.raises(ValueError):
        C.Graph(num_vertices=3, edges=((0, 5),))


def test_commitment_hides_the_color():
    # A commitment's raw digest must not equal a trivial hash of the color
    # alone — the nonce must actually be mixed in (hiding property).
    import hashlib

    rng = random.Random(5)
    state = C.commit_round(C.HOUSE_GRAPH, C.HOUSE_COLORING, rng)
    for i, cm in enumerate(state.commitments):
        naive = hashlib.sha256(bytes([state.permuted_coloring[i]])).digest()
        assert cm.digest != naive
