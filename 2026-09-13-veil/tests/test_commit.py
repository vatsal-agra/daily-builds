from veil.commit import commit, open_commitment


def test_commit_open_roundtrip():
    cm, nonce = commit(b"hello")
    assert open_commitment(cm, b"hello", nonce)


def test_wrong_message_fails_to_open():
    cm, nonce = commit(b"hello")
    assert not open_commitment(cm, b"goodbye", nonce)


def test_wrong_nonce_fails_to_open():
    cm, nonce = commit(b"hello")
    other_nonce = bytes((b + 1) % 256 for b in nonce)
    assert not open_commitment(cm, b"hello", other_nonce)


def test_explicit_nonce_is_used():
    nonce = b"\x00" * 32
    cm1, n1 = commit(b"x", nonce=nonce)
    cm2, n2 = commit(b"x", nonce=nonce)
    assert n1 == n2 == nonce
    assert cm1.digest == cm2.digest  # same message+nonce -> same commitment


def test_different_nonces_hide_same_message_differently():
    cm1, _ = commit(b"same message")
    cm2, _ = commit(b"same message")
    assert cm1.digest != cm2.digest  # fresh random nonce each call
