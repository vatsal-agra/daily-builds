"""
A two-party encrypted messaging session: ephemeral X25519 ECDH key
exchange derives a shared secret, HMAC-SHA256 (as a simple HKDF-style
KDF) derives two direction-specific keys from it, and every message is
sealed with AES-256-GCM using a strictly-increasing per-direction
counter as the nonce.

Because both parties generate a *fresh* X25519 keypair for the session
and never persist the private scalar, this gives session-level forward
secrecy: even if a long-term identity were compromised later, an
attacker who only recorded the wire traffic cannot recompute a shared
secret without the (discarded) ephemeral private keys. This is not a
full Signal-style Double Ratchet (there is no per-message re-keying
within a session) — that distinction is called out here rather than
oversold.
"""
from dataclasses import dataclass, field

import modes
import x25519
from hmac_kdf import hmac_sha256

_KDF_SALT = b"ironkey-session-kdf-v1"
_AAD = b"ironkey-msg-v1"


@dataclass
class SessionMessage:
    counter: int
    ciphertext: bytes
    tag: bytes

    def to_bytes(self):
        return self.counter.to_bytes(8, "big") + self.tag + self.ciphertext

    @classmethod
    def from_bytes(cls, data):
        if len(data) < 8 + 16:
            raise ValueError("malformed session message: too short")
        counter = int.from_bytes(data[:8], "big")
        tag = data[8:24]
        ciphertext = data[24:]
        return cls(counter, ciphertext, tag)


class Party:
    """One side's identity for a session: a freshly generated, ephemeral
    X25519 keypair. Never write `private_key` to disk if you actually
    want forward secrecy — that's the entire point of it being ephemeral."""

    def __init__(self, name):
        self.name = name
        self.private_key = x25519.generate_private_key()
        self.public_key = x25519.derive_public_key(self.private_key)


@dataclass
class _Counters:
    send: int = 0
    recv: int = 0


class SecureSession:
    """One party's view of an established session, after both sides
    have exchanged ephemeral public keys out of band."""

    def __init__(self, me: Party, peer_public_key: bytes):
        shared = x25519.compute_shared_secret(me.private_key, peer_public_key)
        prk = hmac_sha256(_KDF_SALT, shared)
        key_low_to_high = hmac_sha256(prk, b"low2high")
        key_high_to_low = hmac_sha256(prk, b"high2low")

        if me.public_key < peer_public_key:
            self._send_key, self._recv_key = key_low_to_high, key_high_to_low
        elif me.public_key > peer_public_key:
            self._send_key, self._recv_key = key_high_to_low, key_low_to_high
        else:
            raise ValueError("cannot start a session with yourself (identical public keys)")

        self._counters = _Counters()

    def encrypt(self, plaintext: bytes) -> SessionMessage:
        counter = self._counters.send
        nonce = counter.to_bytes(12, "big")
        ct, tag = modes.gcm_encrypt(self._send_key, nonce, plaintext, aad=_AAD)
        self._counters.send += 1
        return SessionMessage(counter, ct, tag)

    def decrypt(self, msg: SessionMessage) -> bytes:
        if msg.counter != self._counters.recv:
            raise ValueError(
                f"replay or reordering detected: expected message #{self._counters.recv}, "
                f"got #{msg.counter}"
            )
        nonce = msg.counter.to_bytes(12, "big")
        pt = modes.gcm_decrypt(self._recv_key, nonce, msg.ciphertext, msg.tag, aad=_AAD)
        self._counters.recv += 1
        return pt


def run_demo(verbose_print=print):
    """Exercises the whole session lifecycle: handshake, back-and-forth
    messaging, tamper detection, and replay detection. Returns True if
    every check behaved as expected (used by demo.sh / the test suite)."""
    alice = Party("Alice")
    bob = Party("Bob")

    alice_session = SecureSession(alice, bob.public_key)
    bob_session = SecureSession(bob, alice.public_key)

    verbose_print(f"Alice ephemeral pubkey: {alice.public_key.hex()}")
    verbose_print(f"Bob   ephemeral pubkey: {bob.public_key.hex()}")

    msg1 = alice_session.encrypt(b"hey bob, it's alice")
    plaintext1 = bob_session.decrypt(msg1)
    assert plaintext1 == b"hey bob, it's alice"
    verbose_print(f"Alice -> Bob  #{msg1.counter}: {plaintext1!r}  (decrypted OK)")

    msg2 = bob_session.encrypt(b"hi alice, loud and clear")
    plaintext2 = alice_session.decrypt(msg2)
    assert plaintext2 == b"hi alice, loud and clear"
    verbose_print(f"Bob -> Alice  #{msg2.counter}: {plaintext2!r}  (decrypted OK)")

    msg3 = alice_session.encrypt(b"here's a second message")

    # tamper detection: flip a ciphertext byte in transit, same counter
    # bob is expecting next, so this isolates a GCM auth failure from a
    # counter/replay failure.
    tampered_bytes = bytearray(msg3.ciphertext)
    tampered_bytes[0] ^= 0xFF
    tampered = SessionMessage(msg3.counter, bytes(tampered_bytes), msg3.tag)
    try:
        bob_session.decrypt(tampered)
        verbose_print("FAIL: tampered message was accepted")
        return False
    except ValueError as e:
        verbose_print(f"tampered message correctly rejected: {e}")

    # the real (untampered) msg3 still decrypts fine afterward
    plaintext3 = bob_session.decrypt(msg3)
    assert plaintext3 == b"here's a second message"
    verbose_print(f"Alice -> Bob  #{msg3.counter}: {plaintext3!r}  (decrypted OK)")

    # replay detection: Bob has already consumed #0 and #1 — replaying
    # Alice's first message (#0) after the counter has moved on must fail
    try:
        bob_session.decrypt(msg1)
        verbose_print("FAIL: replayed message was accepted")
        return False
    except ValueError as e:
        verbose_print(f"replayed message correctly rejected: {e}")

    verbose_print("session demo: all checks passed")
    return True
