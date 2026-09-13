"""Zero-knowledge simulators, and a real statistical test of what they
prove.

"Zero-knowledge" doesn't mean "the verifier learns something, but it's
encrypted" — it has a precise, checkable definition: EVERYTHING an honest
verifier sees during a real proof can be reproduced by a simulator that
does NOT know the witness at all. If a simulator can fake a transcript
that looks exactly like a real one, then the real transcript cannot be
carrying any information the simulator didn't already have — because the
simulator, with nothing but public information, could have produced the
exact same thing.

This module builds two such simulators for real (not sketched):

- `simulate_schnorr_transcript`: for a public key y with NO known discrete
  log, produce an ACCEPTING (t, c, s) triple anyway, by picking the
  challenge and response first and solving for the commitment
  (`t = g^s * y^-c mod p`) — the reverse order from a real prover, who
  must commit before seeing the challenge. This works because Schnorr
  verification is a single equation in three unknowns; fixing any two
  determines the third.
- `simulate_coloring_round`: for a graph with NO known valid coloring
  (or an invalid one), a rewinding simulator that GUESSES which edge the
  verifier will challenge, colors only that edge's two endpoints correctly
  (with two random distinct colors — everything else is filler that will
  never be opened), and retries with a fresh guess whenever the guess
  turns out wrong. Expected number of attempts before success: |E|.

Neither simulator is a toy: `run_statistical_indistinguishability_test`
below runs a real two-sample chi-squared test (veil/stats.py, itself built
from scratch) comparing the actual distribution of real, honest transcripts
against the actual distribution of these simulators' output, and reports
the p-value. A LOW p-value would mean the two are distinguishable — i.e.
zero-knowledge is broken. Every run of this module's demo produces a fresh
p-value from fresh randomness; see tests/test_simulator.py for the
assertion that it stays comfortably high across repeated runs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from veil.coloring import Graph, RoundOpening, RoundTranscript, run_round
from veil.group import SchnorrGroup, default_rng
from veil.schnorr import Transcript, verify
from veil.stats import two_sample_chi_square


def simulate_schnorr_transcript(
    group: SchnorrGroup, y: int, rng: random.Random | None = None
) -> Transcript:
    """Produce an accepting Schnorr transcript for public key `y` with NO
    knowledge of its discrete log. Picks c and s first (both uniform, same
    as in a real proof), then solves the verification equation for t.
    """
    rng = rng or default_rng()
    c = rng.randrange(0, group.q)
    s = rng.randrange(0, group.q)
    y_inv_c = pow(y, (-c) % group.q, group.p)
    t = (group.pow_g(s) * y_inv_c) % group.p
    transcript = Transcript(t=t, c=c, s=s)
    assert verify(group, y, transcript.t, transcript.c, transcript.s), "simulator produced a non-accepting transcript"
    return transcript


@dataclass(frozen=True)
class SimulatedColoringResult:
    transcript: RoundTranscript
    attempts: int


def simulate_coloring_round(
    graph: Graph, rng: random.Random | None = None, max_attempts: int = 1_000_000
) -> SimulatedColoringResult:
    """Produce an accepting graph-coloring round transcript with NO
    knowledge of any valid coloring (or knowledge of an invalid one) —
    only the graph's structure. Guesses the challenge edge in advance,
    colors just its two endpoints with two random distinct colors, colors
    every other vertex arbitrarily (never opened, so it doesn't matter),
    and retries with a fresh guess + fresh commitments whenever the guess
    misses. Expected attempts ~= |E|.
    """
    rng = rng or default_rng()
    n = graph.num_vertices
    for attempt in range(1, max_attempts + 1):
        guessed_edge = rng.randrange(0, len(graph.edges))
        u, v = graph.edges[guessed_edge]
        color_u, color_v = rng.sample([0, 1, 2], 2)
        filler = [rng.randrange(3) for _ in range(n)]
        filler[u] = color_u
        filler[v] = color_v
        # A fresh, real round (fresh permutation, fresh commitments) —
        # the simulator has no special access to the verifier's tape, it
        # simply "gets lucky" whenever the real random challenge matches
        # its own prior guess.
        transcript = run_round(graph, filler, rng)
        if transcript.edge_index == guessed_edge and transcript.accepted:
            return SimulatedColoringResult(transcript=transcript, attempts=attempt)
    raise RuntimeError(f"simulator did not converge within {max_attempts} attempts")


def collect_real_schnorr_samples(
    group: SchnorrGroup, x: int, y: int, rng: random.Random, n_samples: int
) -> list[Transcript]:
    from veil.schnorr import commit, challenge, respond

    samples = []
    for _ in range(n_samples):
        t, r = commit(group, rng)
        c = challenge(group, rng)
        s = respond(group, x, r, c)
        samples.append(Transcript(t=t, c=c, s=s))
    return samples


def collect_simulated_schnorr_samples(
    group: SchnorrGroup, y: int, rng: random.Random, n_samples: int
) -> list[Transcript]:
    return [simulate_schnorr_transcript(group, y, rng) for _ in range(n_samples)]


def _bucket_schnorr(transcripts: list[Transcript], group: SchnorrGroup, buckets: int) -> list[int]:
    """Bin transcripts by (c mod buckets) — under both the real distribution
    (c uniform, chosen by the verifier/challenge()) and the simulated one
    (c uniform, chosen by the simulator itself), this should be close to
    a uniform histogram, and the two histograms should match each other."""
    counts = [0] * buckets
    for tr in transcripts:
        counts[tr.c % buckets] += 1
    return counts


def schnorr_indistinguishability_test(
    group: SchnorrGroup, x: int, y: int, rng: random.Random, n_samples: int = 4000, buckets: int = 16
):
    """Run the actual statistical test: are real Schnorr transcripts and
    simulated ones distinguishable by challenge-value distribution? Returns
    (statistic, df, p_value)."""
    real = collect_real_schnorr_samples(group, x, y, rng, n_samples)
    simulated = collect_simulated_schnorr_samples(group, y, rng, n_samples)
    counts_real = _bucket_schnorr(real, group, buckets)
    counts_sim = _bucket_schnorr(simulated, group, buckets)
    return two_sample_chi_square(counts_real, counts_sim)


_COLOR_PAIRS = [(a, b) for a in range(3) for b in range(3) if a != b]  # 6 ordered pairs


def _bucket_coloring_pairs(openings: list[RoundOpening]) -> list[int]:
    counts = [0] * len(_COLOR_PAIRS)
    index = {pair: i for i, pair in enumerate(_COLOR_PAIRS)}
    for o in openings:
        counts[index[(o.color_u, o.color_v)]] += 1
    return counts


def coloring_indistinguishability_test(
    graph: Graph, coloring: list[int], rng: random.Random, n_samples: int = 4000
):
    """Are real graph-coloring round openings and simulated ones
    distinguishable by their (color_u, color_v) distribution? Under a
    genuinely random per-round color permutation, a real round's revealed
    pair is uniform over the 6 ordered pairs of distinct colors regardless
    of the true underlying coloring — exactly what makes the protocol zero
    knowledge — and the simulator (with no coloring at all) produces the
    exact same uniform distribution by construction. Returns
    (statistic, df, p_value).
    """
    real_openings = []
    while len(real_openings) < n_samples:
        t = run_round(graph, coloring, rng)
        real_openings.append(t.opening)

    sim_openings = []
    while len(sim_openings) < n_samples:
        result = simulate_coloring_round(graph, rng)
        sim_openings.append(result.transcript.opening)

    counts_real = _bucket_coloring_pairs(real_openings)
    counts_sim = _bucket_coloring_pairs(sim_openings)
    return two_sample_chi_square(counts_real, counts_sim)
