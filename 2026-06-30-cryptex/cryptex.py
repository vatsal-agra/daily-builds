#!/usr/bin/env python3
"""Cryptex — a from-scratch cryptography workbench.

Usage:
    python3 cryptex.py <command> [options]

Commands:
    aes      AES-256 encryption (CTR and CBC modes)
    sha256   SHA-256 hashing and HMAC
    rsa      RSA-2048 key generation, OAEP encryption, PSS signatures
    ecdh     P-256 ECDH key exchange
    ecdsa    P-256 ECDSA signatures
    chacha   ChaCha20-Poly1305 AEAD encryption
    viz      Generate interactive HTML visualizer
    demo     Run all features with test vectors
"""

import sys
import os
import base64
import argparse
import textwrap
import json
import time


def _err(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _unb64(s: str) -> bytes:
    try:
        return base64.b64decode(s.strip())
    except Exception:
        _err("Invalid base64 input")


def _parse_hex(hex_str: str, name: str = "hex input") -> bytes:
    try:
        return bytes.fromhex(hex_str.strip())
    except ValueError:
        _err(f"Invalid hex for {name}: {hex_str!r}")


# ---------------------------------------------------------------------------
# AES subcommands
# ---------------------------------------------------------------------------

def cmd_aes(args: argparse.Namespace) -> None:
    from aes import AES256
    import os as _os

    if args.aes_cmd == "encrypt":
        key_b = _parse_hex(args.key, "AES key")
        if len(key_b) != 32:
            _err(f"AES key must be 64 hex chars (32 bytes), got {len(key_b)*2}")
        if args.text is None and args.file is None:
            _err("Provide input via --text or --file")
        cipher = AES256(key_b)
        nonce = _os.urandom(8)
        if args.file:
            with open(args.file, "rb") as f:
                plaintext = f.read()
        else:
            plaintext = args.text.encode()
        ct = cipher.encrypt_ctr(plaintext, nonce)
        payload = _b64(nonce + ct)
        if args.output:
            with open(args.output, "w") as f:
                f.write(payload)
            print(f"Encrypted to {args.output}")
        else:
            print(payload)

    elif args.aes_cmd == "decrypt":
        key_b = _parse_hex(args.key, "AES key")
        if len(key_b) != 32:
            _err(f"AES key must be 64 hex chars (32 bytes)")
        cipher = AES256(key_b)
        if args.file:
            with open(args.file) as f:
                payload = f.read().strip()
        else:
            payload = args.ciphertext
        raw = _unb64(payload)
        if len(raw) < 8:
            _err("Ciphertext too short (missing nonce)")
        nonce, ct = raw[:8], raw[8:]
        pt = cipher.decrypt_ctr(ct, nonce)
        if args.output:
            with open(args.output, "wb") as f:
                f.write(pt)
            print(f"Decrypted to {args.output}")
        else:
            try:
                print(pt.decode())
            except UnicodeDecodeError:
                print(_b64(pt))

    elif args.aes_cmd == "test":
        from aes import AES256, key_schedule, aes256_encrypt_block
        failures = 0

        # FIPS 197 Appendix C.3 AES-256
        tests = [
            ("FIPS C.3 block 1",
             "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
             "00112233445566778899aabbccddeeff",
             "8ea2b7ca516745bfeafc49904b496089"),
            ("NIST 800-38A CBC1 block 1",
             "603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4",
             "6bc1bee22e409f96e93d7e117393172a",
             None),  # CBC is tested separately
        ]
        for name, key_hex, pt_hex, ct_hex in tests:
            if ct_hex:
                key_b = bytes.fromhex(key_hex)
                pt = bytes.fromhex(pt_hex)
                ct_exp = bytes.fromhex(ct_hex)
                cipher = AES256(key_b)
                ct = cipher.encrypt_block(pt)
                status = "OK" if ct == ct_exp else "FAIL"
                if ct != ct_exp:
                    failures += 1
                print(f"  {name}: {status}")

        # CBC round-trip
        import random
        rt_fail = 0
        for _ in range(50):
            k = os.urandom(32)
            iv = os.urandom(16)
            msg = os.urandom(random.randint(0, 200))
            c = AES256(k)
            if c.decrypt_cbc(c.encrypt_cbc(msg, iv), iv) != msg:
                rt_fail += 1
        status = "OK" if rt_fail == 0 else f"FAIL ({rt_fail})"
        if rt_fail:
            failures += 1
        print(f"  AES-256-CBC round-trip (50 random): {status}")

        # CTR round-trip
        rt_fail = 0
        for _ in range(50):
            k = os.urandom(32)
            n = os.urandom(8)
            msg = os.urandom(random.randint(0, 200))
            c = AES256(k)
            if c.decrypt_ctr(c.encrypt_ctr(msg, n), n) != msg:
                rt_fail += 1
        status = "OK" if rt_fail == 0 else f"FAIL ({rt_fail})"
        if rt_fail:
            failures += 1
        print(f"  AES-256-CTR round-trip (50 random): {status}")

        print(f"\nAES tests: {'PASSED' if failures == 0 else f'{failures} FAILURES'}")
        sys.exit(0 if failures == 0 else 1)

    elif args.aes_cmd == "keygen":
        key = os.urandom(32)
        print(f"AES-256 key (keep secret): {key.hex()}")


# ---------------------------------------------------------------------------
# SHA-256 subcommands
# ---------------------------------------------------------------------------

def cmd_sha256(args: argparse.Namespace) -> None:
    from sha256 import sha256_hex, hmac_sha256_hex

    if args.sha_cmd == "hash":
        if args.text is None and args.file is None:
            _err("Provide input via --text or --file")
        if args.file:
            with open(args.file, "rb") as f:
                data = f.read()
        else:
            data = args.text.encode()
        print(sha256_hex(data))

    elif args.sha_cmd == "hmac":
        key_b = _parse_hex(args.key, "HMAC key")
        if args.text is None and args.file is None:
            _err("Provide input via --text or --file")
        if args.file:
            with open(args.file, "rb") as f:
                data = f.read()
        else:
            data = args.text.encode()
        print(hmac_sha256_hex(key_b, data))

    elif args.sha_cmd == "test":
        from sha256 import sha256_hex, hmac_sha256_hex
        import hashlib, hmac as hmac_mod
        import random

        failures = 0
        # NIST test vectors
        vectors = [
            ("empty string", b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
            ("abc", b"abc", hashlib.sha256(b"abc").hexdigest()),
            ("448 bits", b"a" * 56, hashlib.sha256(b"a" * 56).hexdigest()),
            ("512 bits", b"a" * 64, hashlib.sha256(b"a" * 64).hexdigest()),
        ]
        for name, msg, exp in vectors:
            got = sha256_hex(msg)
            status = "OK" if got == exp else "FAIL"
            if got != exp:
                failures += 1
            print(f"  SHA-256({name}): {status}")

        # Cross-check 100 random
        mismatch = 0
        for _ in range(100):
            data = os.urandom(random.randint(0, 500))
            if sha256_hex(data) != hashlib.sha256(data).hexdigest():
                mismatch += 1
        status = "OK" if mismatch == 0 else f"FAIL ({mismatch} mismatches)"
        if mismatch:
            failures += 1
        print(f"  SHA-256 vs hashlib (100 random): {status}")

        # HMAC cross-check 100 random
        mismatch = 0
        for _ in range(100):
            k = os.urandom(random.randint(1, 80))
            m = os.urandom(random.randint(0, 300))
            if hmac_sha256_hex(k, m) != hmac_mod.new(k, m, hashlib.sha256).hexdigest():
                mismatch += 1
        status = "OK" if mismatch == 0 else f"FAIL ({mismatch} mismatches)"
        if mismatch:
            failures += 1
        print(f"  HMAC-SHA256 vs hmac module (100 random): {status}")
        print(f"\nSHA-256 tests: {'PASSED' if failures == 0 else f'{failures} FAILURES'}")
        sys.exit(0 if failures == 0 else 1)


# ---------------------------------------------------------------------------
# RSA subcommands
# ---------------------------------------------------------------------------

def cmd_rsa(args: argparse.Namespace) -> None:
    import rsa as _rsa

    if args.rsa_cmd == "keygen":
        bits = getattr(args, "bits", 2048)
        print(f"Generating RSA-{bits} key pair (this may take a moment)...", file=sys.stderr)
        t0 = time.time()
        priv = _rsa.generate_keypair(bits)
        elapsed = time.time() - t0
        pub = priv.public_key

        pub_pem = _rsa.serialize_public_key(pub)
        priv_pem = _rsa.serialize_private_key(priv)

        pub_path = getattr(args, "out_pub", None) or "rsa_pub.pem"
        priv_path = getattr(args, "out_priv", None) or "rsa_priv.pem"
        for p in (pub_path, priv_path):
            if os.path.exists(p):
                print(f"Warning: overwriting existing file {p}", file=sys.stderr)
        with open(pub_path, "w") as f:
            f.write(pub_pem)
        with open(priv_path, "w") as f:
            f.write(priv_pem)
        print(f"Generated RSA-{bits} key in {elapsed:.2f}s")
        print(f"  Public key:  {pub_path}")
        print(f"  Private key: {priv_path}")

    elif args.rsa_cmd == "encrypt":
        with open(args.pubkey) as f:
            pub = _rsa.deserialize_public_key(f.read())
        plaintext = args.message.encode()
        ct = _rsa.rsa_oaep_encrypt(pub, plaintext)
        print(_b64(ct))

    elif args.rsa_cmd == "decrypt":
        with open(args.privkey) as f:
            priv = _rsa.deserialize_private_key(f.read())
        ct = _unb64(args.ciphertext)
        try:
            pt = _rsa.rsa_oaep_decrypt(priv, ct)
            print(pt.decode())
        except ValueError as e:
            _err(f"Decryption failed: {e}")

    elif args.rsa_cmd == "sign":
        with open(args.privkey) as f:
            priv = _rsa.deserialize_private_key(f.read())
        msg = args.message.encode()
        sig = _rsa.rsa_pss_sign(priv, msg)
        print(_b64(sig))

    elif args.rsa_cmd == "verify":
        with open(args.pubkey) as f:
            pub = _rsa.deserialize_public_key(f.read())
        sig = _unb64(args.signature)
        msg = args.message.encode()
        ok = _rsa.rsa_pss_verify(pub, msg, sig)
        print("VALID" if ok else "INVALID")
        sys.exit(0 if ok else 1)


# ---------------------------------------------------------------------------
# ECDH subcommands
# ---------------------------------------------------------------------------

def cmd_ecdh(args: argparse.Namespace) -> None:
    from ecc import ECPrivateKey, ECPublicKey, ecdh_exchange

    if args.ecdh_cmd == "keygen":
        priv = ECPrivateKey.generate()
        pub = priv.public_key
        print(f"Private key: {priv.to_hex()}")
        print(f"Public key:  {pub.to_uncompressed_hex()}")

    elif args.ecdh_cmd == "exchange":
        try:
            priv = ECPrivateKey.from_hex(args.privkey)
            peer_pub = ECPublicKey.from_hex(args.peerpub)
            shared = ecdh_exchange(priv, peer_pub)
        except ValueError as e:
            _err(str(e))
        print(f"Shared secret (SHA-256 of x): {shared.hex()}")


# ---------------------------------------------------------------------------
# ECDSA subcommands
# ---------------------------------------------------------------------------

def cmd_ecdsa(args: argparse.Namespace) -> None:
    from ecc import ECPrivateKey, ECPublicKey, ecdsa_sign_hex, ecdsa_verify_hex

    if args.ecdsa_cmd == "keygen":
        priv = ECPrivateKey.generate()
        pub = priv.public_key
        print(f"Private key: {priv.to_hex()}")
        print(f"Public key:  {pub.to_uncompressed_hex()}")

    elif args.ecdsa_cmd == "sign":
        try:
            priv = ECPrivateKey.from_hex(args.privkey)
        except ValueError as e:
            _err(str(e))
        msg = args.message.encode()
        sig = ecdsa_sign_hex(priv, msg)
        print(sig)

    elif args.ecdsa_cmd == "verify":
        try:
            pub = ECPublicKey.from_hex(args.pubkey)
        except ValueError as e:
            _err(str(e))
        msg = args.message.encode()
        ok = ecdsa_verify_hex(pub, msg, args.signature)
        print("VALID" if ok else "INVALID")
        sys.exit(0 if ok else 1)


# ---------------------------------------------------------------------------
# ChaCha20 subcommands
# ---------------------------------------------------------------------------

def cmd_chacha(args: argparse.Namespace) -> None:
    from chacha20 import chacha20_poly1305_encrypt, chacha20_poly1305_decrypt

    if args.chacha_cmd == "keygen":
        key = os.urandom(32)
        nonce = os.urandom(12)
        print(f"Key: {key.hex()}")
        print(f"Nonce: {nonce.hex()}")

    elif args.chacha_cmd == "encrypt":
        key = _parse_hex(args.key, "ChaCha20 key")
        nonce = _parse_hex(args.nonce, "nonce")
        if len(key) != 32:
            _err("Key must be 64 hex chars (32 bytes)")
        if len(nonce) != 12:
            _err("Nonce must be 24 hex chars (12 bytes)")
        aad = args.aad.encode() if args.aad else b""
        plaintext = args.text.encode()
        ct, tag = chacha20_poly1305_encrypt(key, nonce, plaintext, aad)
        result = {"ct": _b64(ct), "tag": _b64(tag)}
        print(json.dumps(result))

    elif args.chacha_cmd == "decrypt":
        key = _parse_hex(args.key, "ChaCha20 key")
        nonce = _parse_hex(args.nonce, "nonce")
        if len(key) != 32:
            _err("Key must be 64 hex chars (32 bytes)")
        if len(nonce) != 12:
            _err("Nonce must be 24 hex chars (12 bytes)")
        aad = args.aad.encode() if args.aad else b""
        payload = json.loads(args.payload)
        ct = _unb64(payload["ct"])
        tag = _unb64(payload["tag"])
        try:
            pt = chacha20_poly1305_decrypt(key, nonce, ct, tag, aad)
            print(pt.decode())
        except ValueError as e:
            _err(str(e))

    elif args.chacha_cmd == "test":
        from chacha20 import _chacha20_block, chacha20_encrypt, poly1305_mac
        from chacha20 import chacha20_poly1305_encrypt, chacha20_poly1305_decrypt
        import random

        failures = 0

        # RFC 8439 §2.3.2 block test vector
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
        nonce = bytes.fromhex("000000090000004a00000000")
        block = _chacha20_block(key, 1, nonce)
        exp = bytes.fromhex("10f1e7e4d13b5915500fdd1fa32071c4")
        ok = block[:16] == exp
        if not ok:
            failures += 1
        print(f"  ChaCha20 block vector: {'OK' if ok else 'FAIL'}")

        # RFC 8439 §2.5.2 Poly1305 vector
        otk = bytes.fromhex("85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b")
        msg = b"Cryptographic Forum Research Group"
        exp_tag = bytes.fromhex("a8061dc1305136c6c22b8baf0c0127a9")
        tag = poly1305_mac(msg, otk)
        ok = tag == exp_tag
        if not ok:
            failures += 1
        print(f"  Poly1305 MAC vector: {'OK' if ok else 'FAIL'}")

        # RFC 8439 §2.8.2 AEAD vector
        key3 = bytes.fromhex("808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f")
        nonce3 = bytes.fromhex("070000004041424344454647")
        aad3 = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
        pt3 = b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it."
        exp_ct3 = bytes.fromhex("d31a8d34648e60db7b86afbc53ef7ec2a4aded51296e08fea9e2b5a736ee62d63dbea45e8ca9671282fafb69da92728b1a71de0a9e060b2905d6a5b67ecd3b3692ddbd7f2d778b8c9803aee328091b58fab324e4fad675945585808b4831d7bc3ff4def08e4b7a9de576d26586cec64b6116")
        exp_tag3 = bytes.fromhex("1ae10b594f09e26a7e902ecbd0600691")
        ct3, tag3 = chacha20_poly1305_encrypt(key3, nonce3, pt3, aad3)
        ok = ct3 == exp_ct3 and tag3 == exp_tag3
        if not ok:
            failures += 1
        print(f"  ChaCha20-Poly1305 AEAD vector: {'OK' if ok else 'FAIL'}")

        # Round-trip 50 random
        rt_fail = 0
        for _ in range(50):
            k = os.urandom(32)
            n = os.urandom(12)
            ad = os.urandom(random.randint(0, 50))
            m = os.urandom(random.randint(0, 200))
            ct, tag = chacha20_poly1305_encrypt(k, n, m, ad)
            try:
                dec = chacha20_poly1305_decrypt(k, n, ct, tag, ad)
                if dec != m:
                    rt_fail += 1
                # tamper
                chacha20_poly1305_decrypt(k, n, ct + b'x', tag, ad)
                rt_fail += 1  # should have raised
            except ValueError:
                pass
        if rt_fail:
            failures += 1
        print(f"  ChaCha20-Poly1305 round-trip (50 random): {'OK' if not rt_fail else f'FAIL ({rt_fail})'}")

        print(f"\nChaCha20 tests: {'PASSED' if failures == 0 else f'{failures} FAILURES'}")
        sys.exit(0 if failures == 0 else 1)


# ---------------------------------------------------------------------------
# Visualizer
# ---------------------------------------------------------------------------

def cmd_viz(args: argparse.Namespace) -> None:
    from viz import generate_viz
    out = args.output or "cryptex_viz.html"
    generate_viz(out)
    print(f"Visualizer written to {out}")
    if not args.no_open:
        import webbrowser
        webbrowser.open(f"file://{os.path.abspath(out)}")


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def cmd_demo(args: argparse.Namespace) -> None:
    import random

    PASS = "✓"
    FAIL = "✗"

    results = []

    def check(name: str, cond: bool) -> None:
        status = PASS if cond else FAIL
        print(f"  {status} {name}")
        results.append(cond)

    print("=" * 60)
    print("CRYPTEX DEMO — From-Scratch Cryptography")
    print("=" * 60)

    # ---- AES-256 ----
    print("\n[AES-256]")
    from aes import AES256
    key = os.urandom(32)
    nonce = os.urandom(8)
    msg = b"AES-256-CTR demo message"
    c = AES256(key)
    ct = c.encrypt_ctr(msg, nonce)
    pt = c.decrypt_ctr(ct, nonce)
    check("CTR round-trip", pt == msg)

    iv = os.urandom(16)
    ct_cbc = c.encrypt_cbc(msg, iv)
    pt_cbc = c.decrypt_cbc(ct_cbc, iv)
    check("CBC round-trip", pt_cbc == msg)

    # FIPS vector
    k = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    p = bytes.fromhex("00112233445566778899aabbccddeeff")
    exp_ct = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")
    check("FIPS 197 C.3 vector", AES256(k).encrypt_block(p) == exp_ct)

    # ---- SHA-256 ----
    print("\n[SHA-256 + HMAC]")
    from sha256 import sha256_hex, hmac_sha256_hex
    import hashlib, hmac as _hmac

    check("SHA-256 empty string",
          sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    mismatch = sum(1 for _ in range(100)
                   if sha256_hex(os.urandom(random.randint(0, 200)))
                   != hashlib.sha256(os.urandom(0)).hexdigest()  # placeholder
                   )
    matches = sum(
        sha256_hex(d) == hashlib.sha256(d).hexdigest()
        for d in [os.urandom(random.randint(0, 200)) for _ in range(100)]
    )
    check("SHA-256 matches hashlib (100 random)", matches == 100)

    hmac_ok = all(
        hmac_sha256_hex(k, m) == _hmac.new(k, m, hashlib.sha256).hexdigest()
        for k, m in [(os.urandom(random.randint(1, 80)), os.urandom(random.randint(0, 200)))
                     for _ in range(100)]
    )
    check("HMAC-SHA256 matches hmac module (100 random)", hmac_ok)

    # ---- RSA-2048 ----
    print("\n[RSA-2048]")
    from rsa import generate_keypair, rsa_oaep_encrypt, rsa_oaep_decrypt
    from rsa import rsa_pss_sign, rsa_pss_verify
    from rsa import serialize_public_key, deserialize_public_key, serialize_private_key, deserialize_private_key
    import time

    t0 = time.time()
    priv = generate_keypair(2048)
    pub = priv.public_key
    print(f"  Key generation: {time.time()-t0:.2f}s")

    msg_rsa = b"RSA-OAEP from scratch!"
    ct_rsa = rsa_oaep_encrypt(pub, msg_rsa)
    pt_rsa = rsa_oaep_decrypt(priv, ct_rsa)
    check("OAEP encrypt/decrypt", pt_rsa == msg_rsa)

    sig_rsa = rsa_pss_sign(priv, msg_rsa)
    check("PSS sign valid", rsa_pss_verify(pub, msg_rsa, sig_rsa))
    check("PSS tamper rejected", not rsa_pss_verify(pub, b"tampered", sig_rsa))

    pub2 = deserialize_public_key(serialize_public_key(pub))
    priv2 = deserialize_private_key(serialize_private_key(priv))
    ct2 = rsa_oaep_encrypt(pub2, msg_rsa)
    check("Key serialization round-trip", rsa_oaep_decrypt(priv2, ct2) == msg_rsa)

    # ---- P-256 ECDH ----
    print("\n[P-256 ECDH]")
    from ecc import ECPrivateKey, ECPublicKey, ecdh_exchange

    alice = ECPrivateKey.generate()
    bob = ECPrivateKey.generate()
    alice_shared = ecdh_exchange(alice, bob.public_key)
    bob_shared = ecdh_exchange(bob, alice.public_key)
    check("ECDH shared secret match", alice_shared == bob_shared)

    pub_hex = alice.public_key.to_uncompressed_hex()
    pub_restored = ECPublicKey.from_hex(pub_hex)
    check("Uncompressed point encoding", pub_restored.x == alice.public_key.x)

    compressed = alice.public_key.to_compressed_hex()
    pub_comp = ECPublicKey.from_hex(compressed)
    check("Compressed point encoding", pub_comp.x == alice.public_key.x)

    # ---- ECDSA ----
    print("\n[P-256 ECDSA]")
    from ecc import ecdsa_sign, ecdsa_verify, ecdsa_sign_hex, ecdsa_verify_hex

    priv_ec = ECPrivateKey.generate()
    pub_ec = priv_ec.public_key
    msg_ec = b"ECDSA from scratch!"
    r, s = ecdsa_sign(priv_ec, msg_ec)
    check("ECDSA sign/verify", ecdsa_verify(pub_ec, msg_ec, r, s))
    check("ECDSA tamper rejected", not ecdsa_verify(pub_ec, b"tampered", r, s))

    r2, s2 = ecdsa_sign(priv_ec, msg_ec)
    check("RFC 6979 deterministic k (same msg → same sig)", r == r2 and s == s2)

    # RFC 6979 r vector
    d_test = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721
    exp_r  = 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716
    priv_t = ECPrivateKey(d_test)
    r_t, _ = ecdsa_sign(priv_t, b"sample")
    check("RFC 6979 r vector exact match", r_t == exp_r)

    # ---- ChaCha20-Poly1305 ----
    print("\n[ChaCha20-Poly1305]")
    from chacha20 import chacha20_poly1305_encrypt, chacha20_poly1305_decrypt

    key_c = os.urandom(32)
    nonce_c = os.urandom(12)
    aad_c = b"authenticated but not encrypted"
    msg_c = b"ChaCha20-Poly1305 from scratch!"
    ct_c, tag_c = chacha20_poly1305_encrypt(key_c, nonce_c, msg_c, aad_c)
    pt_c = chacha20_poly1305_decrypt(key_c, nonce_c, ct_c, tag_c, aad_c)
    check("AEAD round-trip", pt_c == msg_c)
    try:
        chacha20_poly1305_decrypt(key_c, nonce_c, ct_c + b"x", tag_c, aad_c)
        check("Tamper rejected", False)
    except ValueError:
        check("Tamper rejected", True)

    # RFC 8439 test vector
    key3 = bytes.fromhex("808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f")
    nonce3 = bytes.fromhex("070000004041424344454647")
    aad3 = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
    pt3 = b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it."
    exp_tag3 = bytes.fromhex("1ae10b594f09e26a7e902ecbd0600691")
    _, tag3 = chacha20_poly1305_encrypt(key3, nonce3, pt3, aad3)
    check("RFC 8439 §2.8.2 tag vector", tag3 == exp_tag3)

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"RESULT: {passed}/{total} checks passed")
    print("=" * 60)
    sys.exit(0 if passed == total else 1)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cryptex",
        description="From-scratch cryptography workbench",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              # Generate and use AES key
              python3 cryptex.py aes keygen
              python3 cryptex.py aes encrypt <hex_key> --text "hello"
              python3 cryptex.py aes decrypt <hex_key> <b64_ciphertext>

              # SHA-256 / HMAC
              python3 cryptex.py sha256 hash --text "hello"
              python3 cryptex.py sha256 hmac <hex_key> --text "hello"

              # RSA key pair and encryption
              python3 cryptex.py rsa keygen
              python3 cryptex.py rsa encrypt rsa_pub.pem --message "secret"
              python3 cryptex.py rsa sign rsa_priv.pem --message "sign me"

              # P-256 ECDH and ECDSA
              python3 cryptex.py ecdh keygen
              python3 cryptex.py ecdsa sign <priv_hex> --message "hello"

              # ChaCha20-Poly1305 AEAD
              python3 cryptex.py chacha keygen
              python3 cryptex.py chacha encrypt <key> <nonce> --text "hello"

              # Visualizer and demo
              python3 cryptex.py viz
              python3 cryptex.py demo
        """),
    )
    sub = parser.add_subparsers(dest="command")

    # AES
    aes_p = sub.add_parser("aes", help="AES-256 encryption")
    aes_sub = aes_p.add_subparsers(dest="aes_cmd")
    aes_kg = aes_sub.add_parser("keygen", help="Generate random AES-256 key")
    aes_enc = aes_sub.add_parser("encrypt", help="Encrypt with AES-256-CTR")
    aes_enc.add_argument("key", help="64 hex chars (32 bytes)")
    aes_enc.add_argument("--text", "-t", help="Plaintext string")
    aes_enc.add_argument("--file", "-f", help="Plaintext file")
    aes_enc.add_argument("--output", "-o", help="Output file for ciphertext")
    aes_dec = aes_sub.add_parser("decrypt", help="Decrypt AES-256-CTR ciphertext")
    aes_dec.add_argument("key", help="64 hex chars (32 bytes)")
    aes_dec.add_argument("ciphertext", nargs="?", help="Base64 ciphertext")
    aes_dec.add_argument("--file", "-f", help="Ciphertext file")
    aes_dec.add_argument("--output", "-o", help="Output file for plaintext")
    aes_sub.add_parser("test", help="Run NIST AES-256 test vectors")

    # SHA-256
    sha_p = sub.add_parser("sha256", help="SHA-256 and HMAC")
    sha_sub = sha_p.add_subparsers(dest="sha_cmd")
    sha_h = sha_sub.add_parser("hash", help="Compute SHA-256")
    sha_h.add_argument("--text", "-t", help="Input string")
    sha_h.add_argument("--file", "-f", help="Input file")
    sha_hm = sha_sub.add_parser("hmac", help="Compute HMAC-SHA256")
    sha_hm.add_argument("key", help="Hex key")
    sha_hm.add_argument("--text", "-t", help="Input string")
    sha_hm.add_argument("--file", "-f", help="Input file")
    sha_sub.add_parser("test", help="Run SHA-256 test vectors")

    # RSA
    rsa_p = sub.add_parser("rsa", help="RSA-2048 encryption and signatures")
    rsa_sub = rsa_p.add_subparsers(dest="rsa_cmd")
    rsa_kg = rsa_sub.add_parser("keygen", help="Generate RSA key pair")
    rsa_kg.add_argument("--bits", "-b", type=int, default=2048)
    rsa_kg.add_argument("--out-pub", default="rsa_pub.pem")
    rsa_kg.add_argument("--out-priv", default="rsa_priv.pem")
    rsa_enc = rsa_sub.add_parser("encrypt", help="Encrypt with RSA-OAEP")
    rsa_enc.add_argument("pubkey", help="Public key PEM file")
    rsa_enc.add_argument("--message", "-m", required=True)
    rsa_dec = rsa_sub.add_parser("decrypt", help="Decrypt RSA-OAEP")
    rsa_dec.add_argument("privkey", help="Private key PEM file")
    rsa_dec.add_argument("ciphertext", help="Base64 ciphertext")
    rsa_sg = rsa_sub.add_parser("sign", help="Sign with RSA-PSS")
    rsa_sg.add_argument("privkey", help="Private key PEM file")
    rsa_sg.add_argument("--message", "-m", required=True)
    rsa_vf = rsa_sub.add_parser("verify", help="Verify RSA-PSS signature")
    rsa_vf.add_argument("pubkey", help="Public key PEM file")
    rsa_vf.add_argument("signature", help="Base64 signature")
    rsa_vf.add_argument("--message", "-m", required=True)

    # ECDH
    ecdh_p = sub.add_parser("ecdh", help="P-256 ECDH key exchange")
    ecdh_sub = ecdh_p.add_subparsers(dest="ecdh_cmd")
    ecdh_sub.add_parser("keygen", help="Generate P-256 key pair")
    ecdh_ex = ecdh_sub.add_parser("exchange", help="ECDH key exchange")
    ecdh_ex.add_argument("privkey", help="My private key hex")
    ecdh_ex.add_argument("peerpub", help="Peer public key hex")

    # ECDSA
    ecdsa_p = sub.add_parser("ecdsa", help="P-256 ECDSA signatures")
    ecdsa_sub = ecdsa_p.add_subparsers(dest="ecdsa_cmd")
    ecdsa_sub.add_parser("keygen", help="Generate P-256 key pair")
    ecdsa_sg = ecdsa_sub.add_parser("sign", help="Sign with ECDSA")
    ecdsa_sg.add_argument("privkey", help="Private key hex")
    ecdsa_sg.add_argument("--message", "-m", required=True)
    ecdsa_vf = ecdsa_sub.add_parser("verify", help="Verify ECDSA signature")
    ecdsa_vf.add_argument("pubkey", help="Public key hex")
    ecdsa_vf.add_argument("signature", help="Signature hex (r||s)")
    ecdsa_vf.add_argument("--message", "-m", required=True)

    # ChaCha20
    cc_p = sub.add_parser("chacha", help="ChaCha20-Poly1305 AEAD")
    cc_sub = cc_p.add_subparsers(dest="chacha_cmd")
    cc_sub.add_parser("keygen", help="Generate ChaCha20 key and nonce")
    cc_enc = cc_sub.add_parser("encrypt", help="ChaCha20-Poly1305 encrypt")
    cc_enc.add_argument("key", help="64 hex chars")
    cc_enc.add_argument("nonce", help="24 hex chars")
    cc_enc.add_argument("--text", "-t", required=True)
    cc_enc.add_argument("--aad", "-a", help="Additional authenticated data")
    cc_dec = cc_sub.add_parser("decrypt", help="ChaCha20-Poly1305 decrypt")
    cc_dec.add_argument("key", help="64 hex chars")
    cc_dec.add_argument("nonce", help="24 hex chars")
    cc_dec.add_argument("payload", help='JSON: {"ct": "...", "tag": "..."}')
    cc_dec.add_argument("--aad", "-a", help="Additional authenticated data")
    cc_sub.add_parser("test", help="Run RFC 8439 test vectors")

    # Visualizer
    viz_p = sub.add_parser("viz", help="Generate HTML visualizer")
    viz_p.add_argument("--output", "-o", default="cryptex_viz.html")
    viz_p.add_argument("--no-open", action="store_true")

    # Demo
    sub.add_parser("demo", help="Run full feature demo")

    args = parser.parse_args()

    dispatch = {
        "aes": cmd_aes,
        "sha256": cmd_sha256,
        "rsa": cmd_rsa,
        "ecdh": cmd_ecdh,
        "ecdsa": cmd_ecdsa,
        "chacha": cmd_chacha,
        "viz": cmd_viz,
        "demo": cmd_demo,
    }

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
