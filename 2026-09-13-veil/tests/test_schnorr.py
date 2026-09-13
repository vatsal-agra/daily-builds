import random

import pytest

from veil.group import STANDARD_GROUP as G
from veil import schnorr as S


def test_completeness_honest_proof_always_accepts():
    rng = random.Random(1)
    for _ in range(30):
        kp = S.generate_keypair(G, rng)
        tr = S.run_interactive_proof(G, kp, rng)
        assert S.verify(G, kp.y, tr.t, tr.c, tr.s)


def test_soundness_wrong_secret_almost_never_accepts():
    rng = random.Random(2)
    kp = S.generate_keypair(G, rng)
    wrong_x = (kp.x + 1) % G.q
    accepted = 0
    trials = 200
    for _ in range(trials):
        t, r = S.commit(G, rng)
        c = S.challenge(G, rng)
        s = S.respond(G, wrong_x, r, c)
        if S.verify(G, kp.y, t, c, s):
            accepted += 1
    assert accepted == 0  # wrong_x fails deterministically for a fixed offset from x


def test_special_soundness_extraction_recovers_real_secret():
    rng = random.Random(3)
    kp = S.generate_keypair(G, rng)
    t, r = S.commit(G, rng)
    c1 = S.challenge(G, rng)
    s1 = S.respond(G, kp.x, r, c1)
    c2 = S.challenge(G, rng)
    while c2 == c1:
        c2 = S.challenge(G, rng)
    s2 = S.respond(G, kp.x, r, c2)
    tr1, tr2 = S.Transcript(t, c1, s1), S.Transcript(t, c2, s2)
    assert S.verify(G, kp.y, tr1.t, tr1.c, tr1.s)
    assert S.verify(G, kp.y, tr2.t, tr2.c, tr2.s)
    extracted = S.extract_witness(G, kp.y, tr1, tr2)
    assert extracted == kp.x


def test_extract_witness_requires_shared_commitment():
    rng = random.Random(4)
    kp = S.generate_keypair(G, rng)
    tr1 = S.run_interactive_proof(G, kp, rng)
    tr2 = S.run_interactive_proof(G, kp, rng)  # different t (fresh commit)
    with pytest.raises(ValueError):
        S.extract_witness(G, kp.y, tr1, tr2)


def test_extract_witness_requires_different_challenges():
    rng = random.Random(5)
    kp = S.generate_keypair(G, rng)
    tr = S.run_interactive_proof(G, kp, rng)
    with pytest.raises(ValueError):
        S.extract_witness(G, kp.y, tr, tr)


def test_extract_witness_rejects_non_accepting_transcripts():
    # REVIEW.md Finding 6.
    rng = random.Random(6)
    kp = S.generate_keypair(G, rng)
    t, r = S.commit(G, rng)
    c1 = S.challenge(G, rng)
    s1 = S.respond(G, kp.x, r, c1)
    c2 = S.challenge(G, rng)
    while c2 == c1:
        c2 = S.challenge(G, rng)
    s2 = S.respond(G, kp.x, r, c2)
    good1 = S.Transcript(t, c1, s1)
    good2 = S.Transcript(t, c2, s2)
    garbage = S.Transcript(t, c2, (s2 + 1) % G.q)  # doesn't actually verify

    with pytest.raises(ValueError):
        S.extract_witness(G, kp.y, good1, garbage)
    with pytest.raises(ValueError):
        S.extract_witness(G, kp.y, garbage, good2)
    # sanity: the correct pair still works
    assert S.extract_witness(G, kp.y, good1, good2) == kp.x


def test_degenerate_public_key_rejected():
    # REVIEW.md Finding 1: a witness-less prover exploiting a public key
    # of small order (p-1, order 2) used to succeed ~50% of the time.
    # After the fix, it must be rejected unconditionally.
    rng = random.Random(7)
    bogus_y = G.p - 1
    trials = 500
    fooled = 0
    for _ in range(trials):
        r = G.random_exponent(rng)
        t = G.pow_g(r)
        c = S.challenge(G, rng)
        s = r  # the exploit: claims x=0, works whenever y^c == 1 (c even)
        if S.verify(G, bogus_y, t, c, s):
            fooled += 1
    assert fooled == 0


def test_verify_rejects_other_degenerate_keys():
    assert not S.verify(G, 1, 0, 0, 0)  # identity
    assert not S.verify(G, 0, 0, 0, 0)
    assert not S.verify(G, G.p, 0, 0, 0)


def test_keypairs_are_independent():
    rng = random.Random(8)
    kp1 = S.generate_keypair(G, rng)
    kp2 = S.generate_keypair(G, rng)
    assert kp1.x != kp2.x
    assert kp1.y != kp2.y


def test_default_rng_is_cryptographically_backed():
    # REVIEW.md Finding 2: no default should silently be a bare
    # random.Random() — generate_keypair with no rng must still work and
    # produce a valid, verifiable keypair using the CSPRNG default.
    kp = S.generate_keypair(G)
    tr = S.run_interactive_proof(G, kp)
    assert S.verify(G, kp.y, tr.t, tr.c, tr.s)
