"""
RSA from scratch: Miller-Rabin key generation (bigint.py), textbook
RSAEP/RSADP (RSADP accelerated with the Chinese Remainder Theorem),
OAEP encryption and PSS signatures per RFC 8017, both built on MGF1
over our from-scratch SHA-256.
"""
import json
import os
from dataclasses import dataclass

import bigint
from sha256 import sha256

_HLEN = 32  # SHA-256 digest length


@dataclass
class RSAPublicKey:
    n: int
    e: int

    @property
    def k(self):
        """Modulus length in bytes."""
        return (self.n.bit_length() + 7) // 8


@dataclass
class RSAPrivateKey:
    n: int
    e: int
    d: int
    p: int
    q: int
    dp: int
    dq: int
    qinv: int

    @property
    def k(self):
        return (self.n.bit_length() + 7) // 8

    @property
    def public_key(self):
        return RSAPublicKey(self.n, self.e)


def save_public_key(pub, path):
    with open(path, "w") as f:
        json.dump({"n": hex(pub.n), "e": hex(pub.e)}, f, indent=2)


def load_public_key(path):
    with open(path) as f:
        d = json.load(f)
    return RSAPublicKey(int(d["n"], 16), int(d["e"], 16))


def save_private_key(priv, path):
    with open(path, "w") as f:
        json.dump({
            "n": hex(priv.n), "e": hex(priv.e), "d": hex(priv.d),
            "p": hex(priv.p), "q": hex(priv.q),
            "dp": hex(priv.dp), "dq": hex(priv.dq), "qinv": hex(priv.qinv),
        }, f, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_private_key(path):
    with open(path) as f:
        d = json.load(f)
    return RSAPrivateKey(
        int(d["n"], 16), int(d["e"], 16), int(d["d"], 16),
        int(d["p"], 16), int(d["q"], 16),
        int(d["dp"], 16), int(d["dq"], 16), int(d["qinv"], 16),
    )


def generate_keypair(bits=2048, e=65537):
    """Generate an RSA keypair with an n of exactly `bits` bits."""
    if bits % 2 != 0:
        raise ValueError("bits must be even (split evenly between p and q)")
    half = bits // 2
    while True:
        p = bigint.gen_prime(half)
        q = bigint.gen_prime(half)
        if p == q:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue  # top-bit alignment can occasionally land one bit short
        phi = (p - 1) * (q - 1)
        try:
            d = bigint.modinv(e, phi)
        except ValueError:
            continue  # gcd(e, phi) != 1 — vanishingly rare, just retry
        dp = d % (p - 1)
        dq = d % (q - 1)
        qinv = bigint.modinv(q, p)
        return RSAPublicKey(n, e), RSAPrivateKey(n, e, d, p, q, dp, dq, qinv)


def _rsaep(pub, m):
    if not (0 <= m < pub.n):
        raise ValueError("message representative out of range")
    return bigint.modexp(m, pub.e, pub.n)


def _rsadp(priv, c):
    if not (0 <= c < priv.n):
        raise ValueError("ciphertext representative out of range")
    m1 = bigint.modexp(c, priv.dp, priv.p)
    m2 = bigint.modexp(c, priv.dq, priv.q)
    return bigint.crt([m1, m2], [priv.p, priv.q])


# ----------------------------------------------------------------------
# MGF1 (RFC 8017 Appendix B.2.1)
# ----------------------------------------------------------------------

def mgf1(seed, mask_len, hash_fn=sha256, hlen=_HLEN):
    if mask_len > hlen * (2 ** 32):
        raise ValueError("mask too long")
    t = bytearray()
    counter = 0
    while len(t) < mask_len:
        t += hash_fn(seed + counter.to_bytes(4, "big"))
        counter += 1
    return bytes(t[:mask_len])


def _xor_bytes(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


# ----------------------------------------------------------------------
# OAEP (RFC 8017 section 7.1) — encryption
# ----------------------------------------------------------------------

def oaep_encrypt(pub, message, label=b""):
    k = pub.k
    if len(message) > k - 2 * _HLEN - 2:
        raise ValueError("message too long for this RSA modulus and OAEP overhead")

    l_hash = sha256(label)
    ps = b"\x00" * (k - len(message) - 2 * _HLEN - 2)
    db = l_hash + ps + b"\x01" + message

    seed = os.urandom(_HLEN)
    db_mask = mgf1(seed, k - _HLEN - 1)
    masked_db = _xor_bytes(db, db_mask)

    seed_mask = mgf1(masked_db, _HLEN)
    masked_seed = _xor_bytes(seed, seed_mask)

    em = b"\x00" + masked_seed + masked_db
    m_int = int.from_bytes(em, "big")
    c_int = _rsaep(pub, m_int)
    return c_int.to_bytes(k, "big")


def oaep_decrypt(priv, ciphertext, label=b""):
    k = priv.k
    if len(ciphertext) != k or k < 2 * _HLEN + 2:
        raise ValueError("decryption error")

    c_int = int.from_bytes(ciphertext, "big")
    m_int = _rsadp(priv, c_int)
    em = m_int.to_bytes(k, "big")

    l_hash = sha256(label)
    y = em[0]
    masked_seed = em[1:1 + _HLEN]
    masked_db = em[1 + _HLEN:]

    seed_mask = mgf1(masked_db, _HLEN)
    seed = _xor_bytes(masked_seed, seed_mask)
    db_mask = mgf1(seed, k - _HLEN - 1)
    db = _xor_bytes(masked_db, db_mask)

    l_hash_prime = db[:_HLEN]
    rest = db[_HLEN:]
    sep_index = rest.find(b"\x01")

    valid = (y == 0) and _consttime_eq(l_hash, l_hash_prime) and sep_index != -1
    if valid and sep_index != -1:
        valid = valid and all(b == 0 for b in rest[:sep_index])

    if not valid:
        # Deliberately generic message: a distinct error per failed check
        # is exactly the oracle that broke early OAEP/PKCS#1 deployments.
        raise ValueError("decryption error")

    return rest[sep_index + 1:]


def _consttime_eq(a, b):
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= x ^ y
    return diff == 0


# ----------------------------------------------------------------------
# PSS (RFC 8017 section 9.1) — signatures
# ----------------------------------------------------------------------

def pss_sign(priv, message, salt_len=_HLEN):
    mod_bits = priv.n.bit_length()
    em_len = (mod_bits - 1 + 7) // 8
    if em_len < _HLEN + salt_len + 2:
        raise ValueError("RSA modulus too small for this hash/salt length")

    m_hash = sha256(message)
    salt = os.urandom(salt_len)
    m_prime = b"\x00" * 8 + m_hash + salt
    h = sha256(m_prime)

    ps = b"\x00" * (em_len - salt_len - _HLEN - 2)
    db = ps + b"\x01" + salt
    db_mask = mgf1(h, em_len - _HLEN - 1)
    masked_db = bytearray(_xor_bytes(db, db_mask))

    extra_bits = 8 * em_len - (mod_bits - 1)
    masked_db[0] &= 0xFF >> extra_bits

    em = bytes(masked_db) + h + b"\xbc"
    m_int = int.from_bytes(em, "big")
    s_int = _rsadp(priv, m_int)  # signing uses the private-key exponent
    return s_int.to_bytes((mod_bits + 7) // 8, "big")


def pss_verify(pub, message, signature, salt_len=_HLEN):
    mod_bits = pub.n.bit_length()
    em_len = (mod_bits - 1 + 7) // 8
    k = pub.k
    if len(signature) != k:
        return False

    s_int = int.from_bytes(signature, "big")
    if s_int >= pub.n:
        return False
    m_int = _rsaep(pub, s_int)
    em = m_int.to_bytes(em_len, "big") if m_int.bit_length() <= em_len * 8 else None
    if em is None:
        return False
    # m_int.to_bytes may be shorter than em_len if there are leading zero
    # bytes in EM; re-pad explicitly to be safe.
    em = m_int.to_bytes(em_len, "big")

    if len(em) < _HLEN + salt_len + 2 or em[-1] != 0xBC:
        return False

    extra_bits = 8 * em_len - (mod_bits - 1)
    if em[0] & (0xFF << (8 - extra_bits) & 0xFF) != 0:
        return False

    masked_db = em[:em_len - _HLEN - 1]
    h = em[em_len - _HLEN - 1:em_len - 1]

    db_mask = mgf1(h, em_len - _HLEN - 1)
    db = bytearray(_xor_bytes(masked_db, db_mask))
    db[0] &= 0xFF >> extra_bits

    zero_len = em_len - _HLEN - salt_len - 2
    if any(b != 0 for b in db[:zero_len]):
        return False
    if db[zero_len] != 0x01:
        return False
    salt = bytes(db[zero_len + 1:])
    if len(salt) != salt_len:
        return False

    m_hash = sha256(message)
    m_prime = b"\x00" * 8 + m_hash + salt
    h_prime = sha256(m_prime)
    return _consttime_eq(h, h_prime)
