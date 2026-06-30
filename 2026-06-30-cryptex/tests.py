#!/usr/bin/env python3
"""Comprehensive test suite for Cryptex.

Covers:
  - GF(2^8) field arithmetic
  - AES-256 (NIST vectors + round-trip)
  - SHA-256 + HMAC-SHA256 (NIST vectors + cross-check vs stdlib)
  - RSA-2048 OAEP + PSS (round-trip, tamper rejection, serialization)
  - P-256 ECDH + ECDSA (key gen, ECDH consistency, ECDSA vectors)
  - ChaCha20-Poly1305 (RFC 8439 vectors + tamper rejection)
  - CLI error handling (no tracebacks on bad input)

Run:  python3 tests.py
Exit: 0 on all pass, 1 on any failure.
"""

import os
import sys
import random
import hashlib
import hmac as _hmac
import subprocess

# Ensure we're looking in the right directory
sys.path.insert(0, os.path.dirname(__file__))

_FAIL_COUNT = 0
_PASS_COUNT = 0


def ok(name: str) -> None:
    global _PASS_COUNT
    _PASS_COUNT += 1
    print(f"  PASS  {name}")


def fail(name: str, detail: str = "") -> None:
    global _FAIL_COUNT
    _FAIL_COUNT += 1
    msg = f"  FAIL  {name}"
    if detail:
        msg += f"  ({detail})"
    print(msg)


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        ok(name)
    else:
        fail(name, detail)


def section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ---------------------------------------------------------------------------
# GF(2^8) tests
# ---------------------------------------------------------------------------

def test_gf256() -> None:
    section("GF(2^8) Field Arithmetic")
    from gf256 import mul, inv, SBOX, INV_SBOX, RCON

    # Closure: mul result always in [0, 255]
    bad = [(a, b) for a in range(256) for b in range(0, 256, 63)
           if not (0 <= mul(a, b) <= 255)]
    check("mul output in [0,255]", not bad, f"{len(bad)} bad cases" if bad else "")

    # Commutativity: a*b == b*a
    pairs = [(a, b) for a in range(0, 256, 17) for b in range(0, 256, 13)]
    nc = [(a, b) for a, b in pairs if mul(a, b) != mul(b, a)]
    check("mul is commutative", not nc, f"{len(nc)} violations" if nc else "")

    # Associativity: (a*b)*c == a*(b*c)
    triples = [(a, b, c) for a in range(0, 256, 37) for b in range(0, 256, 29) for c in range(0, 256, 41)]
    na = [(a, b, c) for a, b, c in triples if mul(mul(a, b), c) != mul(a, mul(b, c))]
    check("mul is associative", not na, f"{len(na)} violations" if na else "")

    # Multiplicative inverse: a * inv(a) == 1 for a != 0
    bad_inv = [a for a in range(1, 256) if mul(a, inv(a)) != 1]
    check("inv: a * inv(a) == 1 for all non-zero a", not bad_inv,
          f"failed for {bad_inv[:5]}" if bad_inv else "")

    # inv(0) == 0 (convention)
    check("inv(0) == 0", inv(0) == 0)

    # SBOX is a bijection (256 distinct values)
    check("SBOX is a bijection", len(set(SBOX)) == 256)

    # INV_SBOX inverts SBOX
    bad_inv_sbox = [i for i in range(256) if INV_SBOX[SBOX[i]] != i]
    check("INV_SBOX inverts SBOX", not bad_inv_sbox,
          f"failed at {bad_inv_sbox[:3]}" if bad_inv_sbox else "")

    # RCON is 0-indexed: RCON[i] = 2^i in GF(2^8)
    # So RCON[0]=1 (2^0), RCON[1]=2 (2^1), RCON[2]=4 (2^2)
    # The AES key schedule uses RCON[round-1], so Rcon[1] maps to RCON[0]=0x01 ✓
    check("RCON[0] == 0x01", RCON[0] == 0x01)
    check("RCON[1] == 0x02", RCON[1] == 0x02)
    check("RCON[2] == 0x04", RCON[2] == 0x04)


# ---------------------------------------------------------------------------
# AES-256 tests
# ---------------------------------------------------------------------------

def test_aes() -> None:
    section("AES-256")
    from aes import AES256

    # FIPS 197 Appendix C.3: AES-256 known answer test
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    pt  = bytes.fromhex("00112233445566778899aabbccddeeff")
    ct_exp = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")
    cipher = AES256(key)
    ct = cipher.encrypt_block(pt)
    check("FIPS 197 C.3 encrypt", ct == ct_exp, ct.hex() if ct != ct_exp else "")

    pt_dec = cipher.decrypt_block(ct_exp)
    check("FIPS 197 C.3 decrypt", pt_dec == pt, pt_dec.hex() if pt_dec != pt else "")

    # Block round-trip (100 random)
    rng = random.Random(42)
    bad = 0
    for _ in range(100):
        k = os.urandom(32)
        p = os.urandom(16)
        c = AES256(k)
        if c.decrypt_block(c.encrypt_block(p)) != p:
            bad += 1
    check("Block round-trip (100 random)", bad == 0, f"{bad} failures" if bad else "")

    # CBC round-trip (50 random lengths)
    bad = 0
    for _ in range(50):
        k = os.urandom(32)
        iv = os.urandom(16)
        msg = os.urandom(rng.randint(0, 300))
        c = AES256(k)
        if c.decrypt_cbc(c.encrypt_cbc(msg, iv), iv) != msg:
            bad += 1
    check("CBC round-trip (50 random)", bad == 0, f"{bad} failures" if bad else "")

    # CTR round-trip (50 random lengths)
    bad = 0
    for _ in range(50):
        k = os.urandom(32)
        n = os.urandom(8)
        msg = os.urandom(rng.randint(0, 300))
        c = AES256(k)
        if c.decrypt_ctr(c.encrypt_ctr(msg, n), n) != msg:
            bad += 1
    check("CTR round-trip (50 random)", bad == 0, f"{bad} failures" if bad else "")

    # CTR encryption is XOR-symmetric (enc == dec)
    k = os.urandom(32)
    n = os.urandom(8)
    msg = os.urandom(100)
    c = AES256(k)
    ct = c.encrypt_ctr(msg, n)
    check("CTR enc(enc(x))==x", c.encrypt_ctr(ct, n) == msg)

    # Wrong key produces different output
    c2 = AES256(os.urandom(32))
    check("Wrong key gives different decrypt", c2.decrypt_ctr(ct, n) != msg)

    # Empty message
    c = AES256(os.urandom(32))
    check("CTR empty message", c.encrypt_ctr(b"", os.urandom(8)) == b"")
    iv_empty = os.urandom(16)
    check("CBC empty message", c.decrypt_cbc(c.encrypt_cbc(b"", iv_empty), iv_empty) == b"")


# ---------------------------------------------------------------------------
# SHA-256 + HMAC tests
# ---------------------------------------------------------------------------

def test_sha256() -> None:
    section("SHA-256 + HMAC-SHA256")
    from sha256 import sha256, sha256_hex, hmac_sha256, hmac_sha256_hex

    # NIST FIPS 180-4 test vectors
    vectors = [
        (b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        (b"abc", hashlib.sha256(b"abc").hexdigest()),
        (b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
         "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"),
        (b"a" * 56, hashlib.sha256(b"a" * 56).hexdigest()),
        (b"a" * 64, hashlib.sha256(b"a" * 64).hexdigest()),
        (b"a" * 1000, hashlib.sha256(b"a" * 1000).hexdigest()),
    ]
    for i, (msg, exp) in enumerate(vectors):
        got = sha256_hex(msg)
        check(f"SHA-256 vector {i+1} ({len(msg)} bytes)", got == exp,
              f"got {got[:16]}... expected {exp[:16]}..." if got != exp else "")

    # Cross-check 200 random vs hashlib
    rng = random.Random(99)
    mismatches = [
        data for data in [os.urandom(rng.randint(0, 500)) for _ in range(200)]
        if sha256_hex(data) != hashlib.sha256(data).hexdigest()
    ]
    check("SHA-256 vs hashlib (200 random)", not mismatches,
          f"{len(mismatches)} mismatches" if mismatches else "")

    # SHA-256 returns bytes of length 32
    h = sha256(b"test")
    check("sha256() returns 32 bytes", isinstance(h, bytes) and len(h) == 32)

    # HMAC-SHA256 cross-check 200 random vs stdlib
    mismatches = 0
    for _ in range(200):
        k = os.urandom(rng.randint(1, 100))
        m = os.urandom(rng.randint(0, 300))
        if hmac_sha256_hex(k, m) != _hmac.new(k, m, hashlib.sha256).hexdigest():
            mismatches += 1
    check("HMAC-SHA256 vs stdlib (200 random)", mismatches == 0,
          f"{mismatches} mismatches" if mismatches else "")

    # HMAC with key longer than block size (64 bytes)
    long_key = os.urandom(100)
    m = b"test message"
    got_hmac = hmac_sha256_hex(long_key, m)
    exp_hmac = _hmac.new(long_key, m, hashlib.sha256).hexdigest()
    check("HMAC with key > block size", got_hmac == exp_hmac)

    # HMAC with empty message
    k = os.urandom(32)
    got_hmac = hmac_sha256_hex(k, b"")
    exp_hmac = _hmac.new(k, b"", hashlib.sha256).hexdigest()
    check("HMAC with empty message", got_hmac == exp_hmac)


# ---------------------------------------------------------------------------
# RSA-2048 tests
# ---------------------------------------------------------------------------

def test_rsa() -> None:
    section("RSA-2048 OAEP + PSS")
    from rsa import (generate_keypair, rsa_oaep_encrypt, rsa_oaep_decrypt,
                     rsa_pss_sign, rsa_pss_verify,
                     serialize_public_key, deserialize_public_key,
                     serialize_private_key, deserialize_private_key)

    # Key generation
    priv = generate_keypair(2048)
    pub = priv.public_key
    check("n = p * q", priv.p * priv.q == priv.n)
    check("n bit_length >= 2047", priv.n.bit_length() >= 2047)
    check("e = 65537", priv.e == 65537)
    check("CRT: dp = d mod (p-1)", priv.d % (priv.p - 1) == priv.dp % (priv.p - 1))
    check("CRT: dq = d mod (q-1)", priv.d % (priv.q - 1) == priv.dq % (priv.q - 1))

    # OAEP encrypt/decrypt round-trip (10 random messages)
    rng = random.Random(77)
    bad = 0
    for _ in range(10):
        msg = os.urandom(rng.randint(1, 100))
        ct = rsa_oaep_encrypt(pub, msg)
        pt = rsa_oaep_decrypt(priv, ct)
        if pt != msg:
            bad += 1
    check("OAEP round-trip (10 random)", bad == 0, f"{bad} failures" if bad else "")

    # Empty message
    ct = rsa_oaep_encrypt(pub, b"")
    check("OAEP empty message round-trip", rsa_oaep_decrypt(priv, ct) == b"")

    # Tampered ciphertext rejected
    ct = rsa_oaep_encrypt(pub, b"secret")
    tampered = bytearray(ct)
    tampered[10] ^= 0xFF
    try:
        rsa_oaep_decrypt(priv, bytes(tampered))
        check("OAEP tamper rejected", False, "no error raised")
    except ValueError:
        check("OAEP tamper rejected", True)

    # PSS sign/verify
    msg = b"sign this message"
    sig = rsa_pss_sign(priv, msg)
    check("PSS sign and verify", rsa_pss_verify(pub, msg, sig))
    check("PSS tampered message rejected", not rsa_pss_verify(pub, b"different", sig))
    check("PSS truncated sig rejected", not rsa_pss_verify(pub, msg, sig[:-1]))
    tampered_sig = bytearray(sig)
    tampered_sig[5] ^= 0x01
    check("PSS bit-flipped sig rejected", not rsa_pss_verify(pub, msg, bytes(tampered_sig)))

    # Wrong key
    priv2 = generate_keypair(2048)
    check("PSS wrong key rejected", not rsa_pss_verify(priv2.public_key, msg, sig))

    # Key serialization round-trip
    pub_pem = serialize_public_key(pub)
    priv_pem = serialize_private_key(priv)
    pub2 = deserialize_public_key(pub_pem)
    priv2 = deserialize_private_key(priv_pem)
    check("Public key serialization n matches", pub2.n == pub.n)
    check("Public key serialization e matches", pub2.e == pub.e)
    check("Private key serialization n matches", priv2.n == priv.n)
    check("Private key serialization d matches", priv2.d == priv.d)

    # Encrypt with deserialized pub, decrypt with deserialized priv
    msg2 = b"serialization test"
    ct2 = rsa_oaep_encrypt(pub2, msg2)
    check("OAEP with deserialized keys", rsa_oaep_decrypt(priv2, ct2) == msg2)


# ---------------------------------------------------------------------------
# P-256 ECC tests
# ---------------------------------------------------------------------------

def test_ecc() -> None:
    section("P-256 ECDH + ECDSA")
    from ecc import (ECPrivateKey, ECPublicKey, ecdh_exchange,
                     ecdsa_sign, ecdsa_verify, ecdsa_sign_hex, ecdsa_verify_hex)

    # Key generation and public key on curve
    priv = ECPrivateKey.generate()
    pub = priv.public_key
    check("Generated private key scalar in range", 1 <= priv.d < 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551)

    # ECPrivateKey validation
    try:
        ECPrivateKey(0)
        check("d=0 rejected", False, "no error")
    except ValueError:
        check("d=0 rejected", True)

    try:
        ECPrivateKey.from_hex("00" * 32)
        check("from_hex d=0 rejected", False, "no error")
    except ValueError:
        check("from_hex d=0 rejected", True)

    try:
        ECPrivateKey.from_hex("01")  # too short
        check("from_hex too-short rejected", False, "no error")
    except ValueError:
        check("from_hex too-short rejected", True)

    # Uncompressed point encoding round-trip
    hex_uncomp = pub.to_uncompressed_hex()
    check("Uncompressed hex starts with 04", hex_uncomp[:2] == "04")
    pub2 = ECPublicKey.from_hex(hex_uncomp)
    check("Uncompressed round-trip x", pub2.x == pub.x)
    check("Uncompressed round-trip y", pub2.y == pub.y)

    # Compressed point encoding round-trip
    hex_comp = pub.to_compressed_hex()
    check("Compressed hex starts with 02 or 03", hex_comp[:2] in ("02", "03"))
    pub3 = ECPublicKey.from_hex(hex_comp)
    check("Compressed round-trip x", pub3.x == pub.x)
    check("Compressed round-trip y", pub3.y == pub.y)

    # ECDH: alice and bob derive the same secret
    alice = ECPrivateKey.generate()
    bob = ECPrivateKey.generate()
    s_ab = ecdh_exchange(alice, bob.public_key)
    s_ba = ecdh_exchange(bob, alice.public_key)
    check("ECDH shared secrets match", s_ab == s_ba)
    check("ECDH secret is 32 bytes", len(s_ab) == 32)

    # Different pairs give different secrets
    carol = ECPrivateKey.generate()
    s_ac = ecdh_exchange(alice, carol.public_key)
    check("ECDH: different pairs → different secrets", s_ab != s_ac)

    # ECDSA sign and verify
    priv_s = ECPrivateKey.generate()
    pub_s = priv_s.public_key
    msg = b"test message for ECDSA"
    r, s = ecdsa_sign(priv_s, msg)
    check("ECDSA signature values in range", 1 <= r < 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551 and
          1 <= s < 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551)
    check("ECDSA verify valid", ecdsa_verify(pub_s, msg, r, s))
    check("ECDSA tampered message rejected", not ecdsa_verify(pub_s, b"different", r, s))
    check("ECDSA wrong pubkey rejected", not ecdsa_verify(carol.public_key, msg, r, s))
    check("ECDSA r=0 rejected", not ecdsa_verify(pub_s, msg, 0, s))
    check("ECDSA s=0 rejected", not ecdsa_verify(pub_s, msg, r, 0))

    # RFC 6979 deterministic k: same message → same signature
    r2, s2 = ecdsa_sign(priv_s, msg)
    check("RFC 6979: same msg same key → same (r,s)", r == r2 and s == s2)

    # RFC 6979: different message → different signature (almost certainly)
    r3, s3 = ecdsa_sign(priv_s, b"different message")
    check("RFC 6979: different msg → different (r,s)", (r, s) != (r3, s3))

    # RFC 6979 test vector: P-256/SHA-256 "sample" message
    d_test = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721
    exp_r  = 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716
    priv_t = ECPrivateKey(d_test)
    r_t, _ = ecdsa_sign(priv_t, b"sample")
    check("RFC 6979 r vector exact match", r_t == exp_r,
          f"got {r_t:064x}" if r_t != exp_r else "")

    # Hex signature round-trip
    sig_hex = ecdsa_sign_hex(priv_s, msg)
    check("ecdsa_sign_hex length", len(sig_hex) == 128)
    check("ecdsa_verify_hex valid", ecdsa_verify_hex(pub_s, msg, sig_hex))
    check("ecdsa_verify_hex tamper", not ecdsa_verify_hex(pub_s, b"tampered", sig_hex))

    # Low-S form
    _N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
    check("ECDSA s is low-S", s <= _N // 2)

    # Bad point encoding rejected
    try:
        ECPublicKey.from_hex("04" + "ff" * 64)
        check("Off-curve point rejected", False, "no error")
    except ValueError:
        check("Off-curve point rejected", True)


# ---------------------------------------------------------------------------
# ChaCha20-Poly1305 tests
# ---------------------------------------------------------------------------

def test_chacha20() -> None:
    section("ChaCha20-Poly1305")
    from chacha20 import (chacha20_poly1305_encrypt, chacha20_poly1305_decrypt,
                          _chacha20_block, chacha20_encrypt, poly1305_mac)

    # RFC 8439 §2.3.2 ChaCha20 block test vector
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    nonce = bytes.fromhex("000000090000004a00000000")
    block = _chacha20_block(key, 1, nonce)
    exp_first16 = bytes.fromhex("10f1e7e4d13b5915500fdd1fa32071c4")
    check("ChaCha20 block vector (first 16 bytes)", block[:16] == exp_first16)

    # RFC 8439 §2.4.2 ChaCha20 encryption vector
    key2 = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    nonce2 = bytes.fromhex("000000000000004a00000000")
    pt2 = b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it."
    ct2_exp = bytes.fromhex(
        "6e2e359a2568f98041ba0728dd0d6981"
        "e97e7aec1d4360c20a27afccfd9fae0b"
        "f91b65c5524733ab8f593dabcd62b357"
        "1639d624e65152ab8f530c359f0861d8"
        "07ca0dbf500d6a6156a38e088a22b65e"
        "52bc514d16ccf806818ce91ab7793736"
        "5af90bbf74a35be6b40b8eedf2785e42"
        "874d"
    )
    ct2 = chacha20_encrypt(key2, nonce2, pt2, 1)
    check("ChaCha20 encryption vector", ct2 == ct2_exp, f"got {ct2.hex()[:32]}..." if ct2 != ct2_exp else "")

    # RFC 8439 §2.5.2 Poly1305 test vector
    otk = bytes.fromhex("85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b")
    msg_poly = b"Cryptographic Forum Research Group"
    exp_tag = bytes.fromhex("a8061dc1305136c6c22b8baf0c0127a9")
    tag = poly1305_mac(msg_poly, otk)
    check("Poly1305 MAC vector", tag == exp_tag, f"got {tag.hex()}" if tag != exp_tag else "")

    # RFC 8439 §2.8.2 AEAD vector
    key3 = bytes.fromhex("808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f")
    nonce3 = bytes.fromhex("070000004041424344454647")
    aad3 = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
    pt3 = b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it."
    exp_ct3 = bytes.fromhex(
        "d31a8d34648e60db7b86afbc53ef7ec2"
        "a4aded51296e08fea9e2b5a736ee62d6"
        "3dbea45e8ca9671282fafb69da92728b"
        "1a71de0a9e060b2905d6a5b67ecd3b36"
        "92ddbd7f2d778b8c9803aee328091b58"
        "fab324e4fad675945585808b4831d7bc"
        "3ff4def08e4b7a9de576d26586cec64b"
        "6116"
    )
    exp_tag3 = bytes.fromhex("1ae10b594f09e26a7e902ecbd0600691")
    ct3, tag3 = chacha20_poly1305_encrypt(key3, nonce3, pt3, aad3)
    check("AEAD ciphertext vector", ct3 == exp_ct3,
          f"got {ct3.hex()[:32]}..." if ct3 != exp_ct3 else "")
    check("AEAD tag vector", tag3 == exp_tag3,
          f"got {tag3.hex()}" if tag3 != exp_tag3 else "")

    # AEAD round-trip (50 random)
    rng = random.Random(55)
    bad = 0
    for _ in range(50):
        k = os.urandom(32)
        n = os.urandom(12)
        ad = os.urandom(rng.randint(0, 50))
        m = os.urandom(rng.randint(0, 200))
        ct, tag = chacha20_poly1305_encrypt(k, n, m, ad)
        try:
            dec = chacha20_poly1305_decrypt(k, n, ct, tag, ad)
            if dec != m:
                bad += 1
        except ValueError:
            bad += 1
    check("AEAD round-trip (50 random)", bad == 0, f"{bad} failures" if bad else "")

    # Tamper rejection
    k = os.urandom(32)
    n = os.urandom(12)
    m = b"secret message"
    ct, tag = chacha20_poly1305_encrypt(k, n, m, b"")

    for label, ct_t, tag_t in [
        ("modified ciphertext", ct[:-1] + bytes([ct[-1] ^ 1]), tag),
        ("modified tag", ct, tag[:-1] + bytes([tag[-1] ^ 1])),
        ("appended byte", ct + b"x", tag),
        ("truncated ciphertext", ct[:-1], tag),
    ]:
        try:
            chacha20_poly1305_decrypt(k, n, ct_t, tag_t, b"")
            check(f"Tamper rejected: {label}", False, "no error raised")
        except ValueError:
            check(f"Tamper rejected: {label}", True)

    # AAD mismatch rejected
    ct, tag = chacha20_poly1305_encrypt(k, n, m, b"aad")
    try:
        chacha20_poly1305_decrypt(k, n, ct, tag, b"different aad")
        check("AAD mismatch rejected", False, "no error raised")
    except ValueError:
        check("AAD mismatch rejected", True)

    # Empty plaintext
    ct, tag = chacha20_poly1305_encrypt(k, n, b"", b"")
    check("Empty plaintext decrypt", chacha20_poly1305_decrypt(k, n, ct, tag, b"") == b"")


# ---------------------------------------------------------------------------
# CLI error handling tests
# ---------------------------------------------------------------------------

def test_cli() -> None:
    section("CLI Error Handling")
    cli = [sys.executable, os.path.join(os.path.dirname(__file__), "cryptex.py")]

    def run(*args):
        result = subprocess.run(cli + list(args), capture_output=True, text=True)
        return result.returncode, result.stderr

    # C1: Invalid hex should print clean error, not traceback
    rc, err = run("aes", "encrypt", "notvalidhex", "--text", "hello")
    check("C1: bad hex → clean error (no traceback)", rc != 0 and "Traceback" not in err and "Error:" in err,
          f"rc={rc} err={err[:80]}" if rc == 0 or "Traceback" in err else "")

    rc, err = run("sha256", "hmac", "notvalidhex", "--text", "hello")
    check("C1: hmac bad key hex → clean error", rc != 0 and "Traceback" not in err,
          f"rc={rc} err={err[:80]}" if rc == 0 or "Traceback" in err else "")

    # C2: Missing --text or --file
    rc, err = run("sha256", "hash")
    check("C2: sha256 hash with no input → clean error", rc != 0 and "Traceback" not in err,
          f"rc={rc} err={err[:80]}" if rc == 0 or "Traceback" in err else "")

    rc, err = run("aes", "encrypt", "00" * 32)
    check("C2: aes encrypt with no text/file → clean error", rc != 0 and "Traceback" not in err,
          f"rc={rc} err={err[:80]}" if rc == 0 or "Traceback" in err else "")

    # C3: d=0 ECPrivateKey → ValueError, not AssertionError
    rc, err = run("ecdh", "exchange", "00" * 32, "04" + "00" * 64)
    check("C3/C4: invalid ECC keys → clean error", rc != 0 and "Traceback" not in err,
          f"rc={rc} err={err[:80]}" if rc == 0 or "Traceback" in err else "")

    # C4: invalid public key hex
    rc, err = run("ecdsa", "sign", "00" * 32, "--message", "hello")
    check("C4: invalid priv key hex in ecdsa sign → clean error", rc != 0 and "Traceback" not in err,
          f"rc={rc} err={err[:80]}" if rc == 0 or "Traceback" in err else "")

    # Normal operations still work
    rc, err = run("sha256", "hash", "--text", "hello")
    check("CLI: sha256 hash --text works", rc == 0, f"rc={rc} err={err}" if rc != 0 else "")

    rc, err = run("aes", "keygen")
    check("CLI: aes keygen works", rc == 0, f"rc={rc} err={err}" if rc != 0 else "")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> None:
    random.seed(0)  # for reproducibility in random-seeded tests

    test_gf256()
    test_aes()
    test_sha256()
    test_rsa()
    test_ecc()
    test_chacha20()
    test_cli()

    print(f"\n{'='*60}")
    print(f"  TOTAL: {_PASS_COUNT} passed, {_FAIL_COUNT} failed")
    print(f"{'='*60}")
    sys.exit(0 if _FAIL_COUNT == 0 else 1)


if __name__ == "__main__":
    main()
