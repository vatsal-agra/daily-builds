import dataclasses
import random

import pytest

from veil.group import STANDARD_GROUP as G
from veil import schnorr as S
from veil import membership as M


def _club(n, rng):
    members = [S.generate_keypair(G, rng) for _ in range(n)]
    club = M.Club(group=G, public_keys=[m.y for m in members])
    return club, members


def test_genuine_member_authenticates():
    rng = random.Random(1)
    club, members = _club(5, rng)
    auth = club.authenticate(3, members[3].x, b"withdraw 100", rng)
    ok, msg = club.verify_and_consume(auth)
    assert ok
    assert "accepted" in msg


def test_replay_rejected():
    rng = random.Random(2)
    club, members = _club(5, rng)
    auth = club.authenticate(1, members[1].x, b"withdraw 100", rng)
    ok1, _ = club.verify_and_consume(auth)
    ok2, msg2 = club.verify_and_consume(auth)
    assert ok1
    assert not ok2
    assert "replay" in msg2


def test_outsider_cannot_forge():
    rng = random.Random(3)
    club, members = _club(4, rng)
    outsider = S.generate_keypair(G, rng)
    with pytest.raises(ValueError):
        club.authenticate(0, outsider.x, b"malicious command", rng)


def test_tampered_command_rejected_without_burning_nonce():
    rng = random.Random(4)
    club, members = _club(5, rng)
    auth = club.authenticate(2, members[2].x, b"withdraw 100", rng)
    tampered = dataclasses.replace(auth, command=b"withdraw 999999")

    ok_tampered, msg_tampered = club.verify_and_consume(tampered)
    assert not ok_tampered
    assert "invalid proof" in msg_tampered

    # The original, untouched authentication must still work — a failed
    # forgery attempt must not have consumed the real nonce.
    ok_original, msg_original = club.verify_and_consume(auth)
    assert ok_original


def test_which_member_is_hidden_from_the_verifier():
    # verify_and_consume's success message never reveals the secret index,
    # and the AnonymousAuth object carries no member-identifying field.
    rng = random.Random(5)
    club, members = _club(5, rng)
    auth = club.authenticate(4, members[4].x, b"cmd", rng)
    assert not hasattr(auth, "secret_index")
    assert not hasattr(auth, "member_index")
    ok, msg = club.verify_and_consume(auth)
    assert ok
    assert "4" not in msg.replace("cmd", "")  # crude but effective: index not leaked into the message


def test_two_different_members_can_both_authenticate_independently():
    rng = random.Random(6)
    club, members = _club(5, rng)
    auth_a = club.authenticate(0, members[0].x, b"cmd A", rng)
    auth_b = club.authenticate(4, members[4].x, b"cmd B", rng)
    ok_a, _ = club.verify_and_consume(auth_a)
    ok_b, _ = club.verify_and_consume(auth_b)
    assert ok_a and ok_b
