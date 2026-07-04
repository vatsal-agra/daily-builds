# Adversarial Review — Cryptex

## Issues Found

### CRITICAL / Bug

**C1 — CLI crashes with raw traceback on invalid hex input (multiple locations)**
- File: `cryptex.py`, cmd_aes, cmd_sha256, cmd_chacha
- Scenario: `python3 cryptex.py aes encrypt notvalidhex --text hi` produces a Python traceback, not a clean error. `bytes.fromhex()` throws `ValueError` that propagates to the terminal.
- Fix: wrap hex parsing in `try/except ValueError` and call `_err()`.

**C2 — CLI crashes when `--text` is not provided (AttributeError on `None`)**
- File: `cryptex.py`, cmd_sha256, cmd_aes, cmd_chacha
- Scenario: `python3 cryptex.py sha256 hash` (no --text or --file) crashes with `AttributeError: 'NoneType' object has no attribute 'encode'`.
- Fix: check `args.text is None and args.file is None` and call `_err()` with a helpful message.

**C3 — ECPrivateKey uses `assert` for input validation (AssertionError, not ValueError)**
- File: `ecc.py`, line ~115
- Scenario: `ECPrivateKey.from_hex("00" * 32)` (d=0, invalid scalar) produces `AssertionError` instead of a clean `ValueError`.
- Fix: replace `assert 1 <= d < _N` with `if not (1 <= d < _N): raise ValueError(...)`.

**C4 — CLI does not catch `ValueError` from ECC point parsing**
- File: `cryptex.py`, cmd_ecdh, cmd_ecdsa
- Scenario: `python3 cryptex.py ecdh exchange <privhex> <invalidpubhex>` produces a raw traceback when `ECPublicKey.from_hex()` raises.
- Fix: wrap in `try/except ValueError as e: _err(str(e))`.

### MEDIUM / UX

**M1 — AES-CTR decrypts garbage silently with wrong key (no authentication)**
- File: `cryptex.py`, `aes.py`
- Scenario: AES-256-CTR is a stream cipher with no MAC. Using the wrong key produces corrupted plaintext silently, with exit code 0.
- Fix: Document this limitation prominently. The demo and CLI help text should note that AES-CTR alone does NOT provide integrity. Users who need both should use ChaCha20-Poly1305 (already available).

**M2 — AES encrypt CLI requires `--text` OR `--file` but does not enforce this**
- File: `cryptex.py`, cmd_aes
- Scenario: `python3 cryptex.py aes encrypt <hex> ` (no text or file) produces AttributeError on `args.text.encode()`.
- Fix: Same as C2 — validate that at least one of `args.text` / `args.file` is present.

**M3 — HMAC CLI requires both `key` and message but only key is positional**
- File: `cryptex.py`, sha_hm argparse
- Scenario: `python3 cryptex.py sha256 hmac <key>` (no --text) crashes.
- Fix: Same as C2.

**M4 — RSA keygen silently overwrites existing key files**
- File: `cryptex.py`, cmd_rsa keygen
- Scenario: Running `rsa keygen` twice in a row overwrites the .pem files without warning.
- Fix: Check if files already exist; warn the user (don't hard error, just print a notice).

**M5 — The RFC 6979 test vector note**
- File: test vectors in demo
- Note: The `r` component of the RFC 6979 P-256/SHA-256 "sample" test vector matches exactly (proving our deterministic k is correct), but the `s` value in my initial copy of the test vector was a 63-char hex string (copy error — the actual value has 64 chars). The implementation is correct; this is a documentation note.

### MINOR

**m1 — ChaCha20 keygen output has extra spaces**
- File: `cryptex.py`, cmd_chacha keygen
- Issue: `Key:   <hex>` has three spaces after the colon; inconsistent with other subcommands.
- Fix: Use consistent `f"Key: {key.hex()}"`.

**m2 — ECDH shared secret ties SHA-256 to a specific KDF choice without documenting it**
- File: `ecc.py`, `ecdh_exchange`
- Issue: The function returns `sha256(x_bytes)` instead of the raw x-coordinate. This is a reasonable design (avoids leaking the raw point) but deviates from raw ECDH (RFC 5903 uses the x-coordinate directly). The CLI help should note the KDF.
- Fix: Add a comment explaining the KDF choice.

**m3 — ECPrivateKey.from_hex does not validate hex string length**
- File: `ecc.py`
- Issue: `ECPrivateKey.from_hex("01")` creates a key with d=1 — valid but unusual. No length check forces exactly 64 hex chars.
- Fix: Add length validation (warn or reject strings that aren't 64 hex chars).

**m4 — viz.py: AES JavaScript uses low-8-bit polynomial (0x1B) for GF multiplication**
- File: `viz.py`, gfMul function
- Issue: The JS uses `x ^= 0x1B` (low 8 bits of 0x11B) for the AES reduction polynomial, which is the conventional shortcut. This is correct for AES but could confuse someone studying GF(2^8). Add a comment.
- Status: Not a bug, minor clarity issue.

## Fix Priority

1. C1, C2, C3, C4 — all CLI error handling (highest priority)
2. M1 — document AES-CTR auth warning
3. M4 — warn on key file overwrite
4. m1, m3 — cosmetic / minor validation
