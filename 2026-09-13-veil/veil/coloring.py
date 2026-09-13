"""Zero-knowledge proof of graph 3-colorability (Goldreich-Micali-Wigderson,
1986) — the canonical proof that ZK exists for an NP-complete problem, not
just for algebraic discrete-log relations like Schnorr's. Since every NP
statement reduces to graph 3-colorability, this single protocol is (in
principle) enough to build a ZK proof for *any* statement whose witness you
can check in polynomial time.

Per round:

1. Prover picks a uniformly random permutation of the 3 colors and applies
   it to their real coloring, then commits (hash-based, see commit.py) to
   every vertex's permuted color with a fresh random nonce, and sends all
   `n` commitments to the verifier.
2. Verifier picks one edge (u, v) uniformly at random from the graph.
3. Prover opens only the two commitments for u and v.
4. Verifier checks both openings are valid, and that the two revealed
   colors differ.

**Completeness**: if the coloring is genuinely proper, every edge's
endpoints always have different colors, so every round accepts.

**Soundness**: if there is no valid 3-coloring of the graph (or the prover
doesn't know one), *any* coloring the prover commits to — proper or not —
must have at least one "bad" edge whose endpoints share a color (else it
would be a proper coloring, contradiction). The verifier catches a bad
edge only if it happens to challenge exactly one of the bad edges, so the
prover escapes a single round with probability at most `1 - 1/|E|`. Since
every round uses fresh, independent commitments (the whole point of
re-permuting and re-committing every round instead of reusing one
commitment set), escaping ALL `t` independent rounds happens with
probability at most `(1 - 1/|E|)^t` — soundness amplifies exponentially in
the round count. `soundness_error_bound` computes this, and
tests/test_coloring.py empirically confirms the measured catch rate against
it over thousands of trials, for both a non-3-colorable graph (K4) and a
prover with a coloring that has exactly one bad edge (the theoretical
worst case for the prover, where the bound is met with equality).

**Zero-knowledge**: because the permutation is re-randomized every round,
whatever two colors get revealed for the challenged edge are always two
uniformly random *distinct* colors out of {0,1,2}, regardless of what the
real underlying colors were — see simulator.py for the actual simulator
this justifies, and the statistical indistinguishability test built on it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from veil.commit import NONCE_BYTES, Commitment, commit, open_commitment


@dataclass(frozen=True)
class Graph:
    num_vertices: int
    edges: tuple[tuple[int, int], ...]

    def __post_init__(self):
        for u, v in self.edges:
            if not (0 <= u < self.num_vertices and 0 <= v < self.num_vertices):
                raise ValueError(f"edge ({u},{v}) references a vertex out of range")
            if u == v:
                raise ValueError(f"self-loop ({u},{v}) can never be properly colored")


def is_valid_coloring(graph: Graph, coloring: list[int]) -> bool:
    if len(coloring) != graph.num_vertices:
        return False
    if any(c not in (0, 1, 2) for c in coloring):
        return False
    return all(coloring[u] != coloring[v] for u, v in graph.edges)


def count_bad_edges(graph: Graph, coloring: list[int]) -> int:
    return sum(1 for u, v in graph.edges if coloring[u] == coloring[v])


def soundness_error_bound(num_edges: int, rounds: int) -> float:
    """Upper bound on the probability a prover with no valid coloring
    (or an invalid one) escapes detection across all `rounds` rounds."""
    if num_edges == 0:
        return 1.0
    return (1 - 1.0 / num_edges) ** rounds


@dataclass
class RoundCommitState:
    """Prover-side secret state for one round, kept until the challenge
    edge is known and the two relevant commitments are opened.

    `opened` guards against a single committed round being opened against
    more than one edge (REVIEW.md Finding 5): the soundness/zero-knowledge
    argument for this protocol depends on exactly one edge being revealed
    per fresh random relabeling — opening a second edge from the same
    permutation leaks strictly more about the real coloring than the
    protocol is supposed to allow.
    """

    permuted_coloring: list[int]
    nonces: list[bytes]
    commitments: tuple[Commitment, ...]
    opened: bool = False


def commit_round(graph: Graph, coloring: list[int], rng: random.Random) -> RoundCommitState:
    """Prover's move 1: random relabeling + fresh commitment per vertex.

    Nonces are drawn from `rng` itself (REVIEW.md Finding 4), not from
    `os.urandom` behind the scenes — the whole round's randomness comes
    from one source, so a run is fully reproducible under a seeded `rng`
    and still cryptographically fresh whenever `rng` is (the default
    everywhere in this toolkit is `secrets.SystemRandom`).
    """
    perm = [0, 1, 2]
    rng.shuffle(perm)
    permuted = [perm[c] for c in coloring]
    commitments: list[Commitment] = []
    nonces: list[bytes] = []
    for c in permuted:
        nonce = rng.randbytes(NONCE_BYTES)
        cm, nonce = commit(bytes([c]), nonce=nonce)
        commitments.append(cm)
        nonces.append(nonce)
    return RoundCommitState(permuted_coloring=permuted, nonces=nonces, commitments=tuple(commitments))


def challenge_edge(graph: Graph, rng: random.Random) -> int:
    """Verifier's move: pick one edge index uniformly at random."""
    return rng.randrange(0, len(graph.edges))


@dataclass(frozen=True)
class RoundOpening:
    color_u: int
    nonce_u: bytes
    color_v: int
    nonce_v: bytes


def open_round(graph: Graph, state: RoundCommitState, edge_index: int) -> RoundOpening:
    """Prover's move 2: reveal only the two challenged vertices.

    Raises if this commitment round has already been opened once (REVIEW.md
    Finding 5) — a fresh `commit_round` (new permutation, new commitments)
    is required for every edge challenge.
    """
    if state.opened:
        raise RuntimeError(
            "this commitment round has already been opened once; "
            "call commit_round again for a fresh round before opening another edge"
        )
    u, v = graph.edges[edge_index]
    opening = RoundOpening(
        color_u=state.permuted_coloring[u],
        nonce_u=state.nonces[u],
        color_v=state.permuted_coloring[v],
        nonce_v=state.nonces[v],
    )
    state.opened = True
    return opening


def verify_round(
    graph: Graph,
    commitments: tuple[Commitment, ...],
    edge_index: int,
    opening: RoundOpening,
) -> bool:
    u, v = graph.edges[edge_index]
    if opening.color_u not in (0, 1, 2) or opening.color_v not in (0, 1, 2):
        return False
    if not open_commitment(commitments[u], bytes([opening.color_u]), opening.nonce_u):
        return False
    if not open_commitment(commitments[v], bytes([opening.color_v]), opening.nonce_v):
        return False
    return opening.color_u != opening.color_v


@dataclass(frozen=True)
class RoundTranscript:
    commitments: tuple[Commitment, ...]
    edge_index: int
    opening: RoundOpening
    accepted: bool


def run_round(graph: Graph, coloring: list[int], rng: random.Random) -> RoundTranscript:
    """Run one full round end-to-end (both parties) and return the
    transcript, for demos/visualization/testing."""
    state = commit_round(graph, coloring, rng)
    edge_index = challenge_edge(graph, rng)
    opening = open_round(graph, state, edge_index)
    accepted = verify_round(graph, state.commitments, edge_index, opening)
    return RoundTranscript(
        commitments=state.commitments, edge_index=edge_index, opening=opening, accepted=accepted
    )


def run_protocol(
    graph: Graph, coloring: list[int], rounds: int, rng: random.Random
) -> list[RoundTranscript]:
    """Run `rounds` independent rounds; the proof as a whole is accepted
    only if every single round is accepted."""
    return [run_round(graph, coloring, rng) for _ in range(rounds)]


# A small, genuinely 3-colorable demo graph: the classic "house" graph
# (a square with a triangular roof) — 5 vertices, 6 edges.
HOUSE_GRAPH = Graph(
    num_vertices=5,
    edges=((0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4)),
)
HOUSE_COLORING = [0, 1, 0, 1, 2]  # verified proper below at import time

# K4, the complete graph on 4 vertices: requires 4 colors by the pigeonhole
# principle (every pair of vertices is adjacent, so all 4 must differ) —
# genuinely NOT 3-colorable, used as the "no valid witness exists" case for
# soundness testing.
K4_GRAPH = Graph(num_vertices=4, edges=((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)))

assert is_valid_coloring(HOUSE_GRAPH, HOUSE_COLORING), "HOUSE_COLORING must be a proper 3-coloring"
