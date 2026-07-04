"""
A DELIBERATELY VULNERABLE CBC-only encryption box — no MAC, no
authentication of any kind. It exists for exactly one purpose: to be
the target of the Vaudenay padding-oracle attack in `padding_oracle.py`,
demonstrating concretely why `vault.py`/`session.py` use AES-GCM
(authenticated encryption) instead. Do not model real code on this file.
"""
import os

import modes

_BLOCK = 16


class VulnerableCBCBox:
    """Encrypts with AES-CBC and PKCS#7 padding and nothing else. The
    `padding_oracle` method models a real (bad) server that reveals,
    through a distinct response/error/timing, whether the padding on a
    submitted ciphertext was valid — the exact class of bug behind the
    2002 Vaudenay attack and multiple real CVEs since."""

    def __init__(self, key=None):
        self.key = key if key is not None else os.urandom(32)

    def encrypt(self, plaintext: bytes) -> bytes:
        iv = os.urandom(_BLOCK)
        ciphertext = modes.cbc_encrypt(self.key, iv, plaintext)
        return iv + ciphertext

    def padding_oracle(self, iv_and_ciphertext: bytes) -> bool:
        """Returns True iff the given (iv || ciphertext) decrypts to
        something with valid PKCS#7 padding. This is the ENTIRE
        information an attacker needs — no key, no plaintext, just a
        yes/no — to recover full plaintext byte by byte."""
        if len(iv_and_ciphertext) < 2 * _BLOCK:
            return False
        iv, ciphertext = iv_and_ciphertext[:_BLOCK], iv_and_ciphertext[_BLOCK:]
        try:
            modes.cbc_decrypt(self.key, iv, ciphertext)
            return True
        except ValueError:
            return False
