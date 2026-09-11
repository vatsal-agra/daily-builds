"""A minimal, Bitcoin-Script-style stack machine for locking/unlocking coins.

Vein transactions don't move coins by simply naming an owner — each output
carries a small *program* (the locking script / scriptPubKey) that the
spending transaction's *unlocking script* (scriptSig) must satisfy when
both are concatenated and run on one shared stack. This is deliberately
the real mechanism (not a shortcut "check owner == signer" comparison):
it is what lets the same primitive express a plain pay-to-pubkey-hash
spend and an m-of-n multisig spend with no special-casing in the ledger
code, exactly as it does in real Bitcoin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Union

OP_0 = 0x00
OP_DUP = 0x76
OP_EQUAL = 0x87
OP_EQUALVERIFY = 0x88
OP_HASH160 = 0xA9
OP_CHECKSIG = 0xAC
OP_CHECKMULTISIG = 0xAE
OP_PUSHDATA1 = 0x4C
OP_MAX_SINGLE_PUSH = 0x4B

_OPCODE_NAMES = {
    OP_0: "OP_0",
    OP_DUP: "OP_DUP",
    OP_EQUAL: "OP_EQUAL",
    OP_EQUALVERIFY: "OP_EQUALVERIFY",
    OP_HASH160: "OP_HASH160",
    OP_CHECKSIG: "OP_CHECKSIG",
    OP_CHECKMULTISIG: "OP_CHECKMULTISIG",
}

# An "op" in our in-memory representation is either raw push-data (bytes)
# or an opcode (int).
Op = Union[bytes, int]

SigChecker = Callable[[bytes, bytes], bool]


class ScriptError(Exception):
    """Raised for any script execution failure (invalid, not just false)."""


def _small_int(n: int) -> bytes:
    if not (0 <= n <= 16):
        raise ValueError("small int out of range")
    return bytes([n])


def _decode_small_int(data: bytes) -> int:
    if len(data) == 0:
        return 0
    if len(data) != 1:
        raise ScriptError("expected a small integer push")
    return data[0]


@dataclass
class Script:
    ops: List[Op] = field(default_factory=list)

    def serialize(self) -> bytes:
        out = bytearray()
        for op in self.ops:
            if isinstance(op, (bytes, bytearray)):
                n = len(op)
                if n == 0:
                    out.append(OP_0)
                elif n <= OP_MAX_SINGLE_PUSH:
                    out.append(n)
                    out += op
                elif n <= 0xFF:
                    out.append(OP_PUSHDATA1)
                    out.append(n)
                    out += op
                else:
                    raise ValueError("push data too large for this toy VM")
            elif isinstance(op, int):
                out.append(op)
            else:
                raise TypeError(f"bad script op: {op!r}")
        return bytes(out)

    @staticmethod
    def deserialize(data: bytes) -> "Script":
        ops: List[Op] = []
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            i += 1
            if b == OP_0:
                ops.append(b"")
            elif 1 <= b <= OP_MAX_SINGLE_PUSH:
                if i + b > n:
                    raise ScriptError("truncated push")
                ops.append(bytes(data[i:i + b]))
                i += b
            elif b == OP_PUSHDATA1:
                if i >= n:
                    raise ScriptError("truncated OP_PUSHDATA1 length")
                length = data[i]
                i += 1
                if i + length > n:
                    raise ScriptError("truncated OP_PUSHDATA1 payload")
                ops.append(bytes(data[i:i + length]))
                i += length
            else:
                ops.append(b)
        return Script(ops)

    def __repr__(self) -> str:
        parts = []
        for op in self.ops:
            if isinstance(op, (bytes, bytearray)):
                parts.append(op.hex() if op else "OP_0")
            else:
                parts.append(_OPCODE_NAMES.get(op, f"OP_UNKNOWN({op:#x})"))
        return f"Script[{' '.join(parts)}]"

    # -- convenience constructors -----------------------------------------

    @staticmethod
    def p2pkh_lock(pubkey_hash: bytes) -> "Script":
        assert len(pubkey_hash) == 20
        return Script([OP_DUP, OP_HASH160, pubkey_hash, OP_EQUALVERIFY, OP_CHECKSIG])

    @staticmethod
    def p2pkh_unlock(der_sig_with_type: bytes, pubkey: bytes) -> "Script":
        return Script([der_sig_with_type, pubkey])

    def is_p2pkh(self) -> bool:
        return (
            len(self.ops) == 5
            and self.ops[0] == OP_DUP
            and self.ops[1] == OP_HASH160
            and isinstance(self.ops[2], (bytes, bytearray))
            and len(self.ops[2]) == 20
            and self.ops[3] == OP_EQUALVERIFY
            and self.ops[4] == OP_CHECKSIG
        )

    @staticmethod
    def multisig_lock(m: int, pubkeys: List[bytes]) -> "Script":
        n = len(pubkeys)
        if not (1 <= m <= n <= 16):
            raise ValueError("invalid m-of-n multisig parameters")
        return Script([_small_int(m), *pubkeys, _small_int(n), OP_CHECKMULTISIG])

    @staticmethod
    def multisig_unlock(sigs: List[bytes]) -> "Script":
        # OP_0 placeholder mirrors real Bitcoin's CHECKMULTISIG off-by-one
        # quirk in spirit (an extra stack item is consumed and discarded)
        # without replicating the bug itself.
        return Script([b"", *sigs])


def execute(script_sig: Script, script_pubkey: Script, sig_checker: SigChecker) -> bool:
    """Run scriptSig then scriptPubKey on one shared stack (Satoshi-style).

    Returns True iff execution completes with a single truthy value left
    on the stack. Raises ScriptError for a structurally invalid script
    (stack underflow, unknown opcode, failed EQUALVERIFY) rather than
    quietly returning False, so a hostile locking script can't be
    confused with a normal "wrong signature" rejection.
    """
    stack: List[bytes] = []

    for op in (*script_sig.ops, *script_pubkey.ops):
        if isinstance(op, (bytes, bytearray)):
            stack.append(bytes(op))
            continue

        if op == OP_DUP:
            if not stack:
                raise ScriptError("OP_DUP: stack underflow")
            stack.append(stack[-1])

        elif op == OP_HASH160:
            if not stack:
                raise ScriptError("OP_HASH160: stack underflow")
            from ..crypto.hashes import hash160
            stack.append(hash160(stack.pop()))

        elif op == OP_EQUAL:
            if len(stack) < 2:
                raise ScriptError("OP_EQUAL: stack underflow")
            a, b = stack.pop(), stack.pop()
            stack.append(b"\x01" if a == b else b"")

        elif op == OP_EQUALVERIFY:
            if len(stack) < 2:
                raise ScriptError("OP_EQUALVERIFY: stack underflow")
            a, b = stack.pop(), stack.pop()
            if a != b:
                raise ScriptError("OP_EQUALVERIFY failed")

        elif op == OP_CHECKSIG:
            if len(stack) < 2:
                raise ScriptError("OP_CHECKSIG: stack underflow")
            pubkey = stack.pop()
            sig = stack.pop()
            stack.append(b"\x01" if sig_checker(pubkey, sig) else b"")

        elif op == OP_CHECKMULTISIG:
            if not stack:
                raise ScriptError("OP_CHECKMULTISIG: stack underflow")
            n = _decode_small_int(stack.pop())
            if len(stack) < n:
                raise ScriptError("OP_CHECKMULTISIG: stack underflow (pubkeys)")
            pubkeys = [stack.pop() for _ in range(n)][::-1]
            if not stack:
                raise ScriptError("OP_CHECKMULTISIG: stack underflow (m)")
            m = _decode_small_int(stack.pop())
            if len(stack) < m:
                raise ScriptError("OP_CHECKMULTISIG: stack underflow (sigs)")
            sigs = [stack.pop() for _ in range(m)][::-1]
            if stack:  # the OP_0 off-by-one placeholder
                stack.pop()
            stack.append(b"\x01" if _check_multisig(pubkeys, sigs, sig_checker) else b"")

        else:
            raise ScriptError(f"unknown opcode {op:#x}")

    if not stack:
        return False
    top = stack[-1]
    return top not in (b"", b"\x00")


def _check_multisig(pubkeys: List[bytes], sigs: List[bytes], sig_checker: SigChecker) -> bool:
    """Each signature must match pubkeys in order (standard algorithm)."""
    if len(sigs) == 0:
        return False
    si = 0
    for pk in pubkeys:
        if si >= len(sigs):
            break
        if sig_checker(pk, sigs[si]):
            si += 1
    return si == len(sigs)
