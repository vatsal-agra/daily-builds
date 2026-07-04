"""
Vaudenay's padding-oracle attack (2002): given nothing but a "was this
ciphertext's PKCS#7 padding valid?" oracle, recover the full plaintext
of any CBC ciphertext without ever learning the key. This is a real
implementation of the attack (not a toy that peeks at the key) run
against `vulnerable_cbc.VulnerableCBCBox` — and then, for contrast,
run against `vault.py`'s real AES-GCM vault, where it correctly fails
because there's no padding-validity signal to exploit at all.
"""
from modes import pkcs7_unpad

_BLOCK = 16


def _recover_block(oracle, prev_block, target_block, on_guess=None):
    """Recover the plaintext of one ciphertext block, given the oracle
    and the preceding 16 bytes used as its IV (either the real IV, for
    the first block, or the preceding ciphertext block otherwise)."""
    intermediate = bytearray(_BLOCK)  # AES_decrypt(target_block) before XOR with prev_block
    plaintext = bytearray(_BLOCK)

    for pad_val in range(1, _BLOCK + 1):
        pos = _BLOCK - pad_val
        test_iv = bytearray(_BLOCK)
        for i in range(pos + 1, _BLOCK):
            test_iv[i] = intermediate[i] ^ pad_val

        found = False
        for guess in range(256):
            # Skip the trivial case where our forged byte reproduces the
            # real IV byte with pad_val == 1: that would form a genuine
            # ...\x01 padding via the *real* plaintext, not our forgery,
            # which is a correct hit, not a false positive, so no special
            # case is needed there — the real risk is the reverse (a
            # false-positive *other* than the correct byte for pad_val==1,
            # handled below by a disambiguation probe).
            test_iv[pos] = guess
            if on_guess is not None:
                on_guess(pos, guess)
            if oracle(bytes(test_iv) + target_block):
                if pad_val == 1 and pos > 0:
                    # Disambiguate: a hit at pad_val==1 could mean the
                    # forged byte accidentally created "\x02\x02" (i.e.
                    # the byte before also happens to satisfy it) rather
                    # than genuine "\x01" padding. Perturb the previous
                    # byte; if the oracle still says valid, this guess
                    # was a false positive that happened to create
                    # different-but-still-valid padding — reject it.
                    probe = bytearray(test_iv)
                    probe[pos - 1] ^= 0xFF
                    if not oracle(bytes(probe) + target_block):
                        continue
                intermediate[pos] = guess ^ pad_val
                plaintext[pos] = intermediate[pos] ^ prev_block[pos]
                found = True
                break
        if not found:
            raise RuntimeError(
                f"padding-oracle attack failed to recover byte at position {pos} "
                f"(pad_val={pad_val}) — oracle may be inconsistent"
            )

    return bytes(plaintext)


def recover_plaintext(oracle, iv_and_ciphertext, unpad=True, on_progress=None):
    """Recover the full plaintext of `iv_and_ciphertext` using only
    `oracle(candidate_iv_and_ciphertext) -> bool`. `on_progress(block_index,
    n_blocks)` is called after each block, if given."""
    if len(iv_and_ciphertext) < 2 * _BLOCK or len(iv_and_ciphertext) % _BLOCK != 0:
        raise ValueError("input must be an IV followed by one or more full 16-byte blocks")

    iv = iv_and_ciphertext[:_BLOCK]
    cipher_blocks = [
        iv_and_ciphertext[i:i + _BLOCK]
        for i in range(_BLOCK, len(iv_and_ciphertext), _BLOCK)
    ]

    plaintext = b""
    prev = iv
    for i, block in enumerate(cipher_blocks):
        plaintext += _recover_block(oracle, prev, block)
        prev = block
        if on_progress is not None:
            on_progress(i + 1, len(cipher_blocks))

    return pkcs7_unpad(plaintext) if unpad else plaintext
