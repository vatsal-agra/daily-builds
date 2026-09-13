import random

from veil.group import STANDARD_GROUP as G
from veil import fiatshamir as FS


def test_sign_and_verify_roundtrip():
    rng = random.Random(1)
    kp = FS.generate_keypair(G, rng)
    msg = b"transfer 10 veil-coins to bob"
    sig = FS.sign(G, kp, msg, rng)
    assert FS.verify(G, kp.y, msg, sig)


def test_tamper_detected():
    rng = random.Random(2)
    kp = FS.generate_keypair(G, rng)
    msg = b"transfer 10 veil-coins to bob"
    sig = FS.sign(G, kp, msg, rng)
    assert not FS.verify(G, kp.y, b"transfer 99 veil-coins to bob", sig)
    assert not FS.verify(G, kp.y, msg + b" ", sig)  # even a trailing space


def test_wrong_public_key_rejected():
    rng = random.Random(3)
    kp = FS.generate_keypair(G, rng)
    other = FS.generate_keypair(G, rng)
    msg = b"hello"
    sig = FS.sign(G, kp, msg, rng)
    assert not FS.verify(G, other.y, msg, sig)


def test_two_signatures_of_same_message_differ():
    # Each signing draws a fresh random nonce, so replays of the *signing*
    # operation look different even for an identical message.
    rng = random.Random(4)
    kp = FS.generate_keypair(G, rng)
    msg = b"same message"
    sig1 = FS.sign(G, kp, msg, rng)
    sig2 = FS.sign(G, kp, msg, rng)
    assert sig1 != sig2
    assert FS.verify(G, kp.y, msg, sig1)
    assert FS.verify(G, kp.y, msg, sig2)


def test_bare_nizk_proof_of_knowledge():
    rng = random.Random(5)
    kp = FS.generate_keypair(G, rng)
    proof = FS.prove(G, kp, rng)
    assert FS.verify_proof(G, kp.y, proof)


def test_degenerate_public_key_rejected():
    # REVIEW.md Finding 1, applied to the Fiat-Shamir path too.
    rng = random.Random(6)
    kp = FS.generate_keypair(G, rng)
    msg = b"anything"
    sig = FS.sign(G, kp, msg, rng)
    assert not FS.verify(G, G.p - 1, msg, sig)
    assert not FS.verify(G, 1, msg, sig)


def test_empty_message_signs_and_verifies():
    rng = random.Random(7)
    kp = FS.generate_keypair(G, rng)
    sig = FS.sign(G, kp, b"", rng)
    assert FS.verify(G, kp.y, b"", sig)
