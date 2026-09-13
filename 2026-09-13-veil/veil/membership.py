"""The flagship product: an anonymous membership/authentication system.

A `Club` registers N members' public keys. Any member can anonymously
authenticate a command — "I am SOME registered member, and I authorize
this exact command" — without revealing which member they are, by
combining two of this toolkit's building blocks:

- **OR-composition** (`orproof.py`) proves "I know the secret key for one
  of these N public keys" without saying which one.
- **Fiat-Shamir binding** ties that proof to a specific `(nonce, command)`
  context, so the proof is worthless for any other command, and a
  **replay log** of already-seen nonces (real replay protection, not just
  "the signature has a timestamp field nobody checks") stops the exact
  same authentication from being replayed to re-trigger the same command
  twice.

This is a real security boundary, not a toy: `test_outsider_cannot_forge`
in tests/test_membership.py has someone with NO registered key attempt to
authenticate and confirms it is rejected, and `test_replay_rejected`
confirms a captured, perfectly valid authentication cannot be replayed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from veil.group import SchnorrGroup, default_rng
from veil import orproof as OR

NONCE_BYTES = 16


def _context(nonce: bytes, command: bytes) -> bytes:
    return nonce + b"|" + command


@dataclass(frozen=True)
class AnonymousAuth:
    nonce: bytes
    command: bytes
    proof: OR.ORProof


@dataclass
class Club:
    group: SchnorrGroup
    public_keys: list[int]
    _used_nonces: set[bytes] = field(default_factory=set)

    def authenticate(
        self,
        secret_index: int,
        x: int,
        command: bytes,
        rng: random.Random | None = None,
    ) -> AnonymousAuth:
        """A real member (who knows the discrete log of
        public_keys[secret_index]) anonymously authorizes `command`."""
        rng = rng or default_rng()
        nonce = rng.randbytes(NONCE_BYTES)
        proof = OR.prove_or(
            self.group, secret_index, x, self.public_keys, _context(nonce, command), rng
        )
        return AnonymousAuth(nonce=nonce, command=command, proof=proof)

    def verify(self, auth: AnonymousAuth) -> bool:
        """Pure cryptographic check — does NOT consume the nonce, so this
        alone is not replay-safe. Use `verify_and_consume` for that."""
        return OR.verify_or(
            self.group, self.public_keys, _context(auth.nonce, auth.command), auth.proof
        )

    def verify_and_consume(self, auth: AnonymousAuth) -> tuple[bool, str]:
        """The real verifier entrypoint: checks the proof AND replay
        protection, and only marks the nonce used on success (a failed
        proof must not burn the nonce, or a network glitch that garbles one
        valid attempt would permanently lock the member out)."""
        if auth.nonce in self._used_nonces:
            return False, "rejected: nonce already used (replay)"
        if not self.verify(auth):
            return False, "rejected: invalid proof"
        self._used_nonces.add(auth.nonce)
        return True, f"accepted: some registered member authorized {auth.command!r}"
