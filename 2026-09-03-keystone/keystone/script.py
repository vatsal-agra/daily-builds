"""A tiny stack-based scripting VM for transaction output locking, in the
spirit of Bitcoin Script — enough to express both plain single-key P2PKH
spends and m-of-n multisig, as two different locking scripts interpreted by
the *same* generic executor rather than two special-cased code paths.

A script is a list of tokens. A token is either:
  - a string opcode, e.g. "OP_DUP"
  - a bytes/hex-string literal to push onto the stack (data push)

Executing a spend runs `script_sig + script_pubkey` (unlocking then locking)
against one shared stack, exactly like real Bitcoin Script. Spend succeeds
iff execution doesn't fail and the final stack has exactly one truthy item.
"""
from __future__ import annotations

from .crypto import hash160, sign as ec_sign, verify as ec_verify


class ScriptError(Exception):
    pass


def _truthy(item) -> bool:
    if isinstance(item, (bytes, bytearray)):
        return any(b != 0 for b in item)
    if isinstance(item, int):
        return item != 0
    return bool(item)


def _as_bytes(item) -> bytes:
    if isinstance(item, (bytes, bytearray)):
        return bytes(item)
    if isinstance(item, str):
        return bytes.fromhex(item)
    raise ScriptError(f"cannot coerce {item!r} to bytes")


def execute(script_sig: list, script_pubkey: list, sighash: bytes) -> bool:
    """Run script_sig then script_pubkey over one stack. `sighash` is the
    32-byte transaction-signing digest OP_CHECKSIG/OP_CHECKMULTISIG verify
    signatures against."""
    stack = []
    try:
        for token in list(script_sig) + list(script_pubkey):
            _step(token, stack, sighash)
    except (ScriptError, IndexError, ValueError):
        return False
    if len(stack) != 1:
        return False
    return _truthy(stack[-1])


def _step(token, stack: list, sighash: bytes) -> None:
    if not isinstance(token, str) or not token.startswith("OP_"):
        # data push: hex string or raw bytes literal
        stack.append(_as_bytes(token))
        return

    op = token
    if op == "OP_DUP":
        if not stack:
            raise ScriptError("OP_DUP on empty stack")
        stack.append(stack[-1])
    elif op == "OP_HASH160":
        top = stack.pop()
        stack.append(hash160(top))
    elif op == "OP_EQUAL":
        b = stack.pop()
        a = stack.pop()
        stack.append(b"\x01" if a == b else b"\x00")
    elif op == "OP_EQUALVERIFY":
        b = stack.pop()
        a = stack.pop()
        if a != b:
            raise ScriptError("OP_EQUALVERIFY failed")
    elif op == "OP_VERIFY":
        top = stack.pop()
        if not _truthy(top):
            raise ScriptError("OP_VERIFY failed")
    elif op == "OP_CHECKSIG":
        pubkey_bytes = stack.pop()
        sig_bytes = stack.pop()
        ok = _checksig(pubkey_bytes, sig_bytes, sighash)
        stack.append(b"\x01" if ok else b"\x00")
    elif op == "OP_CHECKMULTISIG":
        n = int.from_bytes(stack.pop(), "big")
        pubkeys = [stack.pop() for _ in range(n)]
        m = int.from_bytes(stack.pop(), "big")
        sigs = [stack.pop() for _ in range(m)]
        ok = _checkmultisig(m, pubkeys, sigs, sighash)
        stack.append(b"\x01" if ok else b"\x00")
    else:
        raise ScriptError(f"unknown opcode {op}")


def _checksig(pubkey_bytes: bytes, sig_bytes: bytes, sighash: bytes) -> bool:
    from .crypto import decompress_pubkey
    try:
        pub = decompress_pubkey(pubkey_bytes)
        r = int.from_bytes(sig_bytes[:32], "big")
        s = int.from_bytes(sig_bytes[32:], "big")
        return ec_verify(pub, sighash, (r, s))
    except (ValueError, IndexError):
        return False


def _checkmultisig(m: int, pubkeys: list, sigs: list, sighash: bytes) -> bool:
    """m-of-n: each of the `sigs` (in order) must match a *distinct*,
    increasing-index pubkey among `pubkeys` — the same "sigs and keys both
    walked left-to-right, no reuse" rule real OP_CHECKMULTISIG uses, so a
    single stolen signature can't be replayed against multiple key slots."""
    if m > len(sigs) or m == 0:
        return False
    key_idx = 0
    matched = 0
    for sig in sigs:
        found = False
        while key_idx < len(pubkeys):
            if _checksig(pubkeys[key_idx], sig, sighash):
                key_idx += 1
                found = True
                break
            key_idx += 1
        if found:
            matched += 1
    return matched >= m


def encode_sig(r: int, s: int) -> bytes:
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def p2pkh_lock(pubkey_hash: bytes) -> list:
    return ["OP_DUP", "OP_HASH160", pubkey_hash.hex(), "OP_EQUALVERIFY", "OP_CHECKSIG"]


def p2pkh_unlock(privkey: int, sighash: bytes, pubkey_compressed: bytes) -> list:
    r, s = ec_sign(privkey, sighash)
    return [encode_sig(r, s).hex(), pubkey_compressed.hex()]


def multisig_lock(m: int, pubkeys_compressed: list) -> list:
    return (
        [m.to_bytes(1, "big").hex()]
        + [pk.hex() for pk in pubkeys_compressed]
        + [len(pubkeys_compressed).to_bytes(1, "big").hex(), "OP_CHECKMULTISIG"]
    )


def multisig_unlock(sigs: list) -> list:
    return [s.hex() for s in sigs]
