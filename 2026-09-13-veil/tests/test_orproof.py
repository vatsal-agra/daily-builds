import random

import pytest

from veil.group import STANDARD_GROUP as G
from veil import schnorr as S
from veil import orproof as OR


def _members(n, rng):
    return [S.generate_keypair(G, rng) for _ in range(n)]


def test_or_proof_verifies_for_the_real_member():
    rng = random.Random(1)
    members = _members(5, rng)
    pubkeys = [m.y for m in members]
    for secret_index in range(5):
        proof = OR.prove_or(G, secret_index, members[secret_index].x, pubkeys, b"msg", rng)
        assert OR.verify_or(G, pubkeys, b"msg", proof)


def test_or_proof_single_member_reduces_to_plain_schnorr():
    rng = random.Random(2)
    kp = S.generate_keypair(G, rng)
    proof = OR.prove_or(G, 0, kp.x, [kp.y], b"solo", rng)
    assert OR.verify_or(G, [kp.y], b"solo", proof)
    assert len(proof.t_list) == 1


def test_or_proof_rejects_tampered_context():
    rng = random.Random(3)
    members = _members(4, rng)
    pubkeys = [m.y for m in members]
    proof = OR.prove_or(G, 1, members[1].x, pubkeys, b"vote:yes", rng)
    assert not OR.verify_or(G, pubkeys, b"vote:no", proof)


def test_outsider_cannot_construct_a_proof():
    rng = random.Random(4)
    members = _members(3, rng)
    pubkeys = [m.y for m in members]
    outsider = S.generate_keypair(G, rng)
    with pytest.raises(ValueError):
        OR.prove_or(G, 0, outsider.x, pubkeys, b"msg", rng)


def test_pure_forgery_without_any_witness_fails():
    rng = random.Random(5)
    members = _members(5, rng)
    pubkeys = [m.y for m in members]
    n = len(pubkeys)
    fake_c = [rng.randrange(0, G.q) for _ in range(n)]
    fake_s = [rng.randrange(0, G.q) for _ in range(n)]
    fake_t = [
        (G.pow_g(fake_s[i]) * pow(pubkeys[i], (-fake_c[i]) % G.q, G.p)) % G.p for i in range(n)
    ]
    forged = OR.ORProof(tuple(fake_t), tuple(fake_c), tuple(fake_s))
    assert not OR.verify_or(G, pubkeys, b"msg", forged)


def test_degenerate_public_key_in_list_rejected_at_construction():
    # REVIEW.md Finding 1.
    rng = random.Random(6)
    members = _members(3, rng)
    pubkeys = [m.y for m in members]
    pubkeys[1] = G.p - 1  # inject a degenerate key
    with pytest.raises(ValueError):
        OR.prove_or(G, 0, members[0].x, pubkeys, b"msg", rng)


def test_degenerate_public_key_in_list_rejected_at_verification():
    rng = random.Random(7)
    members = _members(3, rng)
    pubkeys = [m.y for m in members]
    proof = OR.prove_or(G, 0, members[0].x, pubkeys, b"msg", rng)
    tampered_pubkeys = list(pubkeys)
    tampered_pubkeys[2] = G.p - 1
    assert not OR.verify_or(G, tampered_pubkeys, b"msg", proof)


def test_wrong_length_proof_rejected():
    rng = random.Random(8)
    members = _members(3, rng)
    pubkeys = [m.y for m in members]
    proof = OR.prove_or(G, 0, members[0].x, pubkeys, b"msg", rng)
    truncated = OR.ORProof(proof.t_list[:-1], proof.c_list[:-1], proof.s_list[:-1])
    assert not OR.verify_or(G, pubkeys, b"msg", truncated)


def test_anonymity_all_branches_look_structurally_identical():
    # Every branch is an accepting Schnorr transcript against its own key
    # regardless of which index was real — that's what anonymity rests on.
    rng = random.Random(9)
    members = _members(4, rng)
    pubkeys = [m.y for m in members]
    proof = OR.prove_or(G, 2, members[2].x, pubkeys, b"msg", rng)
    for i in range(4):
        assert S.verify(G, pubkeys[i], proof.t_list[i], proof.c_list[i], proof.s_list[i])
