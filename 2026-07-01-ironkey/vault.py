"""
A real, usable encrypted file vault: password -> PBKDF2-HMAC-SHA256 ->
AES-256-GCM. Every vault file is self-describing (salt, iteration count,
IV, and auth tag are all stored alongside the ciphertext) so it can be
decrypted with nothing but the password. Wrong passwords and corrupted
files both fail the same authenticated-decryption check — there's no
separate "password check" step that could itself leak information.
"""
import os
import struct

import modes
from hmac_kdf import pbkdf2_hmac_sha256

_MAGIC = b"IKVLT01"
_SALT_LEN = 16
_IV_LEN = 12
_TAG_LEN = 16
_KEY_LEN = 32

# A production KDF wants hundreds of thousands of iterations (OWASP 2023
# recommends >=600,000 for PBKDF2-HMAC-SHA256) — but that guidance assumes
# a compiled implementation doing >1M iterations/sec. Ours is pure Python
# at ~2,800 iterations/sec (measured), so 600,000 would mean a ~3.5-minute
# wait to open the vault. We calibrate instead to a bcrypt-like ~1.5 s
# delay (still a real, deliberate cost-to-attacker factor, just smaller
# than a production KDF would use) and say so rather than pretend a
# borrowed-from-elsewhere number is free here. Pass --iterations for more.
_DEFAULT_ITERATIONS = 4096


def encrypt_file(password: str, plaintext: bytes, iterations: int = _DEFAULT_ITERATIONS) -> bytes:
    if not password:
        raise ValueError("password must not be empty")
    salt = os.urandom(_SALT_LEN)
    key = pbkdf2_hmac_sha256(password.encode("utf-8"), salt, iterations, _KEY_LEN)
    iv = os.urandom(_IV_LEN)
    aad = _MAGIC + salt + struct.pack(">Q", iterations) + iv
    ciphertext, tag = modes.gcm_encrypt(key, iv, plaintext, aad=aad)
    return aad + tag + ciphertext


def decrypt_file(password: str, vault_bytes: bytes) -> bytes:
    header_len = len(_MAGIC) + _SALT_LEN + 8 + _IV_LEN
    if len(vault_bytes) < header_len + _TAG_LEN:
        raise ValueError("not a valid Ironkey vault file (too short)")

    magic = vault_bytes[:len(_MAGIC)]
    if magic != _MAGIC:
        raise ValueError("not a valid Ironkey vault file (bad magic)")

    offset = len(_MAGIC)
    salt = vault_bytes[offset:offset + _SALT_LEN]
    offset += _SALT_LEN
    (iterations,) = struct.unpack(">Q", vault_bytes[offset:offset + 8])
    offset += 8
    iv = vault_bytes[offset:offset + _IV_LEN]
    offset += _IV_LEN
    aad = vault_bytes[:offset]
    tag = vault_bytes[offset:offset + _TAG_LEN]
    offset += _TAG_LEN
    ciphertext = vault_bytes[offset:]

    if iterations < 1 or iterations > 50_000_000:
        raise ValueError("not a valid Ironkey vault file (absurd iteration count)")

    key = pbkdf2_hmac_sha256(password.encode("utf-8"), salt, iterations, _KEY_LEN)
    try:
        return modes.gcm_decrypt(key, iv, ciphertext, tag, aad=aad)
    except ValueError:
        # Deliberately generic: this is reached both for a wrong password
        # and for a corrupted/tampered file, and a real attacker should
        # not be able to tell which from the error alone.
        raise ValueError("wrong password, or the vault file is corrupted/tampered")


def encrypt_path(password, in_path, out_path, iterations=_DEFAULT_ITERATIONS):
    with open(in_path, "rb") as f:
        data = f.read()
    vault = encrypt_file(password, data, iterations)
    with open(out_path, "wb") as f:
        f.write(vault)
    return len(vault)


def decrypt_path(password, in_path, out_path):
    with open(in_path, "rb") as f:
        vault = f.read()
    data = decrypt_file(password, vault)
    with open(out_path, "wb") as f:
        f.write(data)
    return len(data)
