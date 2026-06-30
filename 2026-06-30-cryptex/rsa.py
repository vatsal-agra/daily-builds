"""RSA-2048 from scratch.

Implements:
  - Miller-Rabin probabilistic primality test
  - Extended Euclidean algorithm (modular inverse)
  - Fast modular exponentiation (binary method)
  - RSA-2048 key generation (e=65537, CRT parameters)
  - RSA-OAEP encryption/decryption (PKCS#1 v2.1, using our SHA-256 + MGF1)
  - RSA-PSS signature scheme (sign + verify)
  - PEM-like ASCII key serialization

No stdlib crypto (no hashlib, no hmac, no ssl, no Crypto) used in the
implementation.  OS entropy (os.urandom) is used only for key generation
and OAEP label seed.
"""

import os
import struct
import base64
import math
from sha256 import sha256, hmac_sha256


# ---------------------------------------------------------------------------
# Integer arithmetic
# ---------------------------------------------------------------------------

def mod_exp(base: int, exp: int, mod: int) -> int:
    """Binary right-to-left modular exponentiation."""
    if mod == 1:
        return 0
    result = 1
    base %= mod
    while exp > 0:
        if exp & 1:
            result = result * base % mod
        base = base * base % mod
        exp >>= 1
    return result


def egcd(a: int, b: int) -> tuple[int, int, int]:
    """Extended Euclidean algorithm. Returns (g, x, y) with a*x + b*y = g."""
    if a == 0:
        return b, 0, 1
    g, x, y = egcd(b % a, a)
    return g, y - (b // a) * x, x


def mod_inv(a: int, m: int) -> int:
    """Modular multiplicative inverse of a mod m. Raises if gcd != 1."""
    g, x, _ = egcd(a % m, m)
    if g != 1:
        raise ValueError(f"No modular inverse: gcd({a},{m}) = {g}")
    return x % m


# ---------------------------------------------------------------------------
# Primality
# ---------------------------------------------------------------------------

# Small primes for quick composite filtering
_SMALL_PRIMES = [
    2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53,
    59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113,
    127, 131, 137, 139, 149, 151, 157, 163, 167, 173, 179, 181,
    191, 193, 197, 199, 211, 223, 227, 229, 233, 239, 241, 251,
]


def _miller_rabin_witness(n: int, a: int) -> bool:
    """Return True if a is a Miller-Rabin witness for compositeness of n."""
    # Write n-1 = 2^r * d
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    x = mod_exp(a, d, n)
    if x == 1 or x == n - 1:
        return False
    for _ in range(r - 1):
        x = x * x % n
        if x == n - 1:
            return False
    return True  # a IS a witness → n is composite


def is_prime(n: int, rounds: int = 20) -> bool:
    """Probabilistic Miller-Rabin primality test with `rounds` random witnesses.

    Error probability: < 4^(-rounds) ≈ 10^(-12) for rounds=20.
    """
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n == p:
            return True
        if n % p == 0:
            return False
    # Miller-Rabin rounds
    for _ in range(rounds):
        a = 2 + int.from_bytes(os.urandom(n.bit_length() // 8 + 1), "big") % (n - 3)
        if _miller_rabin_witness(n, a):
            return False
    return True


def gen_prime(bits: int) -> int:
    """Generate a random prime of exactly `bits` bits."""
    while True:
        # Ensure high bit set (exact bit length) and odd
        candidate = int.from_bytes(os.urandom(bits // 8), "big")
        candidate |= (1 << (bits - 1)) | 1  # set MSB and LSB
        if is_prime(candidate):
            return candidate


# ---------------------------------------------------------------------------
# RSA key generation
# ---------------------------------------------------------------------------

class RSAPublicKey:
    def __init__(self, n: int, e: int):
        self.n = n
        self.e = e
        # key_bytes is the byte length of the modulus (RFC standard "k")
        self.key_bytes = (n.bit_length() + 7) // 8
        self.key_bits = self.key_bytes * 8  # nominal bit length for OAEP/PSS


class RSAPrivateKey:
    def __init__(self, n: int, e: int, d: int, p: int, q: int):
        self.n = n
        self.e = e
        self.d = d
        self.p = p
        self.q = q
        # CRT parameters for faster decryption
        self.dp = d % (p - 1)
        self.dq = d % (q - 1)
        self.qinv = mod_inv(q, p)
        self.key_bytes = (n.bit_length() + 7) // 8
        self.key_bits = self.key_bytes * 8

    @property
    def public_key(self) -> RSAPublicKey:
        return RSAPublicKey(self.n, self.e)

    def decrypt_raw(self, c: int) -> int:
        """Raw RSA operation using CRT for ~4× speedup."""
        m1 = mod_exp(c % self.p, self.dp, self.p)
        m2 = mod_exp(c % self.q, self.dq, self.q)
        h = self.qinv * (m1 - m2) % self.p
        return m2 + h * self.q


def generate_keypair(bits: int = 2048) -> RSAPrivateKey:
    """Generate an RSA key pair of `bits` total (p and q are bits//2 each)."""
    half = bits // 2
    while True:
        p = gen_prime(half)
        q = gen_prime(half)
        if p == q:
            continue
        n = p * q
        phi = (p - 1) * (q - 1)
        e = 65537
        if math.gcd(e, phi) != 1:
            continue
        d = mod_inv(e, phi)
        return RSAPrivateKey(n, e, d, p, q)


# ---------------------------------------------------------------------------
# MGF1 (mask generation function) using our SHA-256
# ---------------------------------------------------------------------------

_HASH_LEN = 32  # SHA-256 output length


def mgf1(seed: bytes, length: int) -> bytes:
    """MGF1 mask generation function (PKCS#1 v2.1 §B.2.1) using SHA-256."""
    if length > 2**32 * _HASH_LEN:
        raise ValueError("MGF1 output too long")
    output = bytearray()
    counter = 0
    while len(output) < length:
        c = struct.pack(">I", counter)
        output.extend(sha256(seed + c))
        counter += 1
    return bytes(output[:length])


# ---------------------------------------------------------------------------
# RSA-OAEP (PKCS#1 v2.1 §7.1)
# ---------------------------------------------------------------------------

def _oaep_pad(message: bytes, key_bits: int, label: bytes = b"") -> bytes:
    """OAEP encode message for key of key_bits bits."""
    k = key_bits // 8  # modulus size in bytes
    mlen = len(message)
    h_label = sha256(label)
    max_mlen = k - 2 * _HASH_LEN - 2
    if mlen > max_mlen:
        raise ValueError(f"Message too long for OAEP: {mlen} > {max_mlen}")

    # DB = lHash || PS || 0x01 || M
    ps = b"\x00" * (max_mlen - mlen)
    db = h_label + ps + b"\x01" + message
    seed = os.urandom(_HASH_LEN)

    db_mask = mgf1(seed, len(db))
    masked_db = bytes(d ^ m for d, m in zip(db, db_mask))
    seed_mask = mgf1(masked_db, _HASH_LEN)
    masked_seed = bytes(s ^ m for s, m in zip(seed, seed_mask))

    return b"\x00" + masked_seed + masked_db


def _oaep_unpad(em: bytes, key_bits: int, label: bytes = b"") -> bytes:
    """OAEP decode; raises ValueError on invalid padding."""
    k = key_bits // 8
    if len(em) != k:
        raise ValueError("Decryption error (length)")
    h_label = sha256(label)

    # Constant-time comparison to avoid timing oracles
    y = em[0]
    masked_seed = em[1: 1 + _HASH_LEN]
    masked_db = em[1 + _HASH_LEN:]
    seed_mask = mgf1(masked_db, _HASH_LEN)
    seed = bytes(s ^ m for s, m in zip(masked_seed, seed_mask))
    db_mask = mgf1(seed, len(masked_db))
    db = bytes(d ^ m for d, m in zip(masked_db, db_mask))

    # Verify label hash and locate message
    errors = y  # must be 0
    for a, b_ in zip(h_label, db[:_HASH_LEN]):
        errors |= a ^ b_

    # Scan past PS (zeros) to find 0x01 separator
    msg_start = None
    for i in range(_HASH_LEN, len(db)):
        if db[i] == 0x01:
            msg_start = i + 1
            break
        elif db[i] != 0x00:
            errors |= 1

    if errors or msg_start is None:
        raise ValueError("Decryption error (padding)")
    return db[msg_start:]


def rsa_oaep_encrypt(public_key: RSAPublicKey, plaintext: bytes,
                     label: bytes = b"") -> bytes:
    """Encrypt plaintext with RSA-OAEP using SHA-256."""
    em = _oaep_pad(plaintext, public_key.key_bits, label)
    m = int.from_bytes(em, "big")
    if m >= public_key.n:
        raise ValueError("Message representative out of range")
    c = mod_exp(m, public_key.e, public_key.n)
    return c.to_bytes(public_key.key_bytes, "big")


def rsa_oaep_decrypt(private_key: RSAPrivateKey, ciphertext: bytes,
                     label: bytes = b"") -> bytes:
    """Decrypt RSA-OAEP ciphertext."""
    k = private_key.key_bytes
    if len(ciphertext) != k:
        raise ValueError(f"Ciphertext must be {k} bytes")
    c = int.from_bytes(ciphertext, "big")
    if c >= private_key.n:
        raise ValueError("Ciphertext representative out of range")
    m = private_key.decrypt_raw(c)
    em = m.to_bytes(k, "big")
    return _oaep_unpad(em, private_key.key_bits, label)


# ---------------------------------------------------------------------------
# RSA-PSS signatures (PKCS#1 v2.1 §8.1)
# ---------------------------------------------------------------------------

_SALT_LEN = 32  # same as hash length


def _pss_encode(message: bytes, em_bits: int) -> bytes:
    """PSS encoding of message for `em_bits`-bit modulus."""
    em_len = math.ceil(em_bits / 8)
    m_hash = sha256(message)
    if em_len < _HASH_LEN + _SALT_LEN + 2:
        raise ValueError("Encoding error")

    salt = os.urandom(_SALT_LEN)
    m_prime = b"\x00" * 8 + m_hash + salt
    h = sha256(m_prime)

    ps_len = em_len - _SALT_LEN - _HASH_LEN - 2
    db = b"\x00" * ps_len + b"\x01" + salt
    db_mask = mgf1(h, em_len - _HASH_LEN - 1)
    masked_db = bytearray(d ^ m for d, m in zip(db, db_mask))

    # Clear bits above emBits
    top_bits = 8 * em_len - em_bits
    if top_bits > 0:
        masked_db[0] &= (0xFF >> top_bits)

    return bytes(masked_db) + h + b"\xbc"


def _pss_verify(message: bytes, em: bytes, em_bits: int) -> bool:
    """Return True if PSS encoding is valid."""
    em_len = math.ceil(em_bits / 8)
    if len(em) != em_len:
        return False
    if em[-1] != 0xBC:
        return False
    m_hash = sha256(message)
    masked_db = bytearray(em[:em_len - _HASH_LEN - 1])
    h = em[em_len - _HASH_LEN - 1: em_len - 1]

    top_bits = 8 * em_len - em_bits
    if top_bits > 0 and (masked_db[0] >> (8 - top_bits)):
        return False

    db_mask = mgf1(h, em_len - _HASH_LEN - 1)
    db = bytearray(d ^ m for d, m in zip(masked_db, db_mask))
    if top_bits > 0:
        db[0] &= (0xFF >> top_bits)

    # Check PS (zeros) then 0x01 then salt
    ps_len = em_len - _SALT_LEN - _HASH_LEN - 2
    if any(db[i] != 0 for i in range(ps_len)):
        return False
    if db[ps_len] != 0x01:
        return False
    salt = bytes(db[ps_len + 1:ps_len + 1 + _SALT_LEN])

    m_prime = b"\x00" * 8 + m_hash + salt
    h_prime = sha256(m_prime)
    return h == h_prime


def rsa_pss_sign(private_key: RSAPrivateKey, message: bytes) -> bytes:
    """Sign message with RSA-PSS (RFC 3447 §8.1.1).

    emBits = modBits - 1 ensures the PSS integer is always < n.
    """
    em_bits = private_key.n.bit_length() - 1  # actual modulus bits - 1
    em = _pss_encode(message, em_bits)
    m = int.from_bytes(em, "big")
    if m >= private_key.n:
        raise ValueError("PSS encoding error: message representative >= n")
    s = private_key.decrypt_raw(m)
    return s.to_bytes(private_key.key_bytes, "big")


def rsa_pss_verify(public_key: RSAPublicKey, message: bytes,
                   signature: bytes) -> bool:
    """Verify RSA-PSS signature. Returns True if valid."""
    k = public_key.key_bytes
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= public_key.n:
        return False
    m = mod_exp(s, public_key.e, public_key.n)
    em_bits = public_key.n.bit_length() - 1
    em_len = math.ceil(em_bits / 8)
    em = m.to_bytes(em_len, "big")
    return _pss_verify(message, em, em_bits)


# ---------------------------------------------------------------------------
# PEM-like key serialization (minimal, base64-encoded DER-ish format)
# ---------------------------------------------------------------------------
# We use a simple custom format since full DER/ASN.1 is out of scope:
#   -----BEGIN CRYPTEX RSA PUBLIC KEY-----
#   base64(n_bytes || e_bytes) where each field is 4-byte-len-prefixed big-endian
#   -----END CRYPTEX RSA PUBLIC KEY-----

def _encode_int(n: int) -> bytes:
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return struct.pack(">I", len(b)) + b


def _decode_int(data: bytes, offset: int) -> tuple[int, int]:
    length = struct.unpack(">I", data[offset:offset + 4])[0]
    n = int.from_bytes(data[offset + 4:offset + 4 + length], "big")
    return n, offset + 4 + length


def serialize_public_key(key: RSAPublicKey) -> str:
    raw = _encode_int(key.n) + _encode_int(key.e)
    b64 = base64.b64encode(raw).decode()
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return ("-----BEGIN CRYPTEX RSA PUBLIC KEY-----\n" +
            "\n".join(lines) +
            "\n-----END CRYPTEX RSA PUBLIC KEY-----\n")


def deserialize_public_key(pem: str) -> RSAPublicKey:
    lines = [l for l in pem.strip().splitlines()
             if not l.startswith("-----")]
    raw = base64.b64decode("".join(lines))
    n, off = _decode_int(raw, 0)
    e, _ = _decode_int(raw, off)
    return RSAPublicKey(n, e)


def serialize_private_key(key: RSAPrivateKey) -> str:
    raw = (
        _encode_int(key.n) + _encode_int(key.e) + _encode_int(key.d)
        + _encode_int(key.p) + _encode_int(key.q)
    )
    b64 = base64.b64encode(raw).decode()
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return ("-----BEGIN CRYPTEX RSA PRIVATE KEY-----\n" +
            "\n".join(lines) +
            "\n-----END CRYPTEX RSA PRIVATE KEY-----\n")


def deserialize_private_key(pem: str) -> RSAPrivateKey:
    lines = [l for l in pem.strip().splitlines()
             if not l.startswith("-----")]
    raw = base64.b64decode("".join(lines))
    n, off = _decode_int(raw, 0)
    e, off = _decode_int(raw, off)
    d, off = _decode_int(raw, off)
    p, off = _decode_int(raw, off)
    q, _ = _decode_int(raw, off)
    return RSAPrivateKey(n, e, d, p, q)
