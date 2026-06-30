# Cryptex — Cryptography Workbench from Scratch

A complete cryptography toolkit implemented in pure Python from mathematical
foundations — no `hashlib`, no `hmac`, no `Crypto` library. Every algorithm is
built from first principles and verified against published NIST/RFC test vectors.

## What's in it

| Module | Algorithm | Key techniques |
|--------|-----------|----------------|
| `gf256.py` | GF(2⁸) field arithmetic | Russian-peasant mul, Fermat inverse (a²⁵⁴), AES affine transform |
| `aes.py` | AES-256 (ECB/CBC/CTR) | Rijndael S-box from GF, key schedule with RCON, PKCS#7 |
| `sha256.py` | SHA-256 + HMAC-SHA256 | Round constants from prime fractional parts, 64-round compression |
| `rsa.py` | RSA-2048 OAEP + PSS | Miller-Rabin, extended GCD, CRT decryption, MGF1, PSS |
| `ecc.py` | P-256 ECDH + ECDSA | Jacobian coords, Montgomery ladder, RFC 6979 deterministic k |
| `chacha20.py` | ChaCha20-Poly1305 AEAD | Quarter-round, 130-bit Poly1305, RFC 8439 |
| `viz.py` | HTML visualizer | Self-contained single-file, AES S-box heatmap, SHA-256 rounds, live JS encrypt |
| `cryptex.py` | CLI entry point | All algorithms accessible via subcommands |

## Usage

```bash
# Generate keys
python3 cryptex.py aes keygen
python3 cryptex.py rsa keygen
python3 cryptex.py ecdh keygen
python3 cryptex.py chacha keygen

# AES-256-CTR (NOTE: no integrity — use chacha for AEAD)
python3 cryptex.py aes encrypt <hex_key> --text "hello"
python3 cryptex.py aes decrypt <hex_key> <base64_ct>

# SHA-256 / HMAC
python3 cryptex.py sha256 hash --text "hello"
python3 cryptex.py sha256 hmac <hex_key> --text "hello"

# RSA-2048 OAEP + PSS
python3 cryptex.py rsa encrypt rsa_pub.pem --message "secret"
python3 cryptex.py rsa decrypt rsa_priv.pem <base64_ct>
python3 cryptex.py rsa sign rsa_priv.pem --message "sign me"
python3 cryptex.py rsa verify rsa_pub.pem <sig> --message "sign me"

# P-256 ECDH + ECDSA
python3 cryptex.py ecdh exchange <priv_hex> <peer_pub_hex>
python3 cryptex.py ecdsa sign <priv_hex> --message "hello"
python3 cryptex.py ecdsa verify <pub_hex> <sig_hex> --message "hello"

# ChaCha20-Poly1305 AEAD
python3 cryptex.py chacha encrypt <key> <nonce> --text "hello" [--aad "header"]
python3 cryptex.py chacha decrypt <key> <nonce> <json_payload> [--aad "header"]
python3 cryptex.py chacha encrypt <key> <nonce> --file secret.bin -o enc.json

# Visualizer, demo, benchmark
python3 cryptex.py viz
python3 cryptex.py demo
python3 cryptex.py bench
```

## Test results

```
python3 tests.py     →  95/95 tests pass
bash demo.sh         →  24/24 CLI checks pass
python3 cryptex.py demo  →  20/20 demo checks pass
```

## Verified against

- FIPS 197 Appendix C.3 (AES-256 block encrypt)
- FIPS 180-4 (SHA-256 test vectors)
- RFC 8439 §2.3.2, §2.4.2, §2.5.2, §2.8.2 (ChaCha20, Poly1305, AEAD)
- RFC 6979 P-256/SHA-256 "sample" r-vector (ECDSA deterministic k)
- SHA-256 cross-checked vs `hashlib` on 200 random strings
- HMAC-SHA256 cross-checked vs stdlib `hmac` module on 200 random cases
- AES-256 CBC/CTR round-trip on 50+ random lengths/keys

## Build phases

- [x] Phase 1: Plan
- [x] Phase 2: Core build (AES-256, SHA-256/HMAC, RSA-2048, P-256 ECDH/ECDSA, ChaCha20-Poly1305, CLI, viz) — 20/20 demo checks
- [x] Phase 3: Adversarial review — 10 issues found & fixed (4 critical CLI crashes, 4 medium UX, 2 minor)
- [x] Phase 4: Stretch + polish — bench subcommand, chacha file I/O, AES-CTR auth warning, unused import removal
- [x] Phase 5: Verification — tests.py (95/95), demo.sh (24/24 CLI checks)
- [x] Phase 6: Ship

## Interesting bugs found and fixed

- **AES key schedule RCON off-by-one**: `RCON[i//NK]` was wrong; FIPS Rcon[1]=0x01 but our 0-indexed array meant `RCON[1]=0x02`. Fixed to `RCON[i//NK - 1]`.
- **RSA key_bytes truncation**: `n.bit_length()` can be 2047 for a "2048-bit" key. Fixed: `key_bytes = (n.bit_length() + 7) // 8` everywhere.
- **RSA-PSS em_bits**: PSS emLen must use `n.bit_length() - 1`, not `key_bits - 1`, to avoid the EM integer ever exceeding n.
- **CLI crashes**: Raw `bytes.fromhex()` and `str.encode()` calls produced tracebacks on bad hex input or missing `--text`. Fixed with `_parse_hex()` helper and presence checks.
