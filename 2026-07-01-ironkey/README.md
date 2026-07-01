# Ironkey

A cryptography suite built entirely from scratch in pure Python — no
`hashlib`, `hmac`, `Crypto`/`cryptography`, or `ssl` involved in any
actual crypto math. Every primitive is implemented from its
specification and checked bit-for-bit against official NIST/RFC test
vectors and, where applicable, cross-checked against OpenSSL. On top of
the primitives sits a real encrypted file vault, a forward-secure
two-party messaging session, and a working implementation (and
counter-demonstration) of a classic real-world attack.

## Why this, today

Every prior daily build in this repo has been a simulator, solver, or
renderer (SAT solvers, path tracers, chess engines, a DB, a regex
engine, a compression toolkit, a language VM, a physics engine, a music
synth...). Cryptography is a different kind of "from scratch": there's
no partial credit. A reasonable-looking AES implementation that's off
by one bit in the key schedule produces ciphertext that looks totally
fine and is completely wrong — the only way to know you got it right is
exact agreement with a published test vector. That made it an
unusually strict test of this build style's "no stubs, no shortcuts"
rule, and the adversarial-review phase actually found a critical bug
(see below) instead of rubber-stamping the code. It's also genuinely
useful output: the vault and messaging tool are things you can actually
point at a real file or a real conversation.

## How to run it

```bash
python3 cli.py demo              # exercise every feature end to end
./demo.sh                        # full test suite (122 tests) + CLI walkthrough
python3 cli.py --help            # every subcommand
python3 cli.py viz               # generates ironkey_viz.html — open it in a browser
```

Common commands:

```bash
# Hash / MAC / KDF
python3 cli.py hash --text "hello"
python3 cli.py hmac --key secret --text "hello"
python3 cli.py kdf --password "correct horse" --iterations 4096

# AES-256-GCM (default) or CBC
python3 cli.py aes encrypt --key-hex $(python3 -c "import os;print(os.urandom(32).hex())") \
    --text "secret message" --out msg.bin
python3 cli.py aes decrypt --key-hex <same key> --in msg.bin

# RSA: keygen, OAEP encryption, PSS signatures
python3 cli.py rsa genkey --bits 2048 --pub-out pub.json --priv-out priv.json
python3 cli.py rsa encrypt --pub pub.json --text "secret" --out ct.bin
python3 cli.py rsa decrypt --priv priv.json --in ct.bin
python3 cli.py rsa sign --priv priv.json --text "msg" --out sig.bin
python3 cli.py rsa verify --pub pub.json --text "msg" --sig sig.bin

# X25519 handshake / encrypted session
python3 cli.py dh demo
python3 cli.py session demo

# Password-based file vault (PBKDF2 + AES-256-GCM)
python3 cli.py vault encrypt --password "hunter2" --in notes.txt --out notes.vault
python3 cli.py vault decrypt --password "hunter2" --in notes.vault --out notes.txt

# Padding-oracle attack demo (recovers plaintext with NO key access)
python3 cli.py attack demo --text "attack this secret"
```

## Feature list

**Required (all 4 implemented and independently verified):**
1. **SHA-256** (`sha256.py`) — FIPS 180-4, bit-exact vs `hashlib` across
   boundary lengths, the empty string, and 1M `"a"` characters.
2. **HMAC-SHA256 + PBKDF2-HMAC-SHA256** (`hmac_kdf.py`) — RFC 2104 / RFC
   8018, verified against RFC 4231 HMAC vectors and `hashlib.pbkdf2_hmac`.
3. **AES-256 with CBC and GCM** (`aes.py` + `modes.py`) — FIPS 197
   (all 3 key sizes), cross-checked against OpenSSL for CBC and (via a
   small libcrypto/EVP harness, since OpenSSL's `enc` CLI doesn't do
   AEAD) for GCM, including AAD and tamper rejection.
4. **RSA: keygen + OAEP encryption + PSS signatures** (`rsa.py`) —
   RFC 8017, Miller-Rabin key generation, round-tripped and
   boundary/tamper/cross-key tested.

**Stretch (all 3 implemented, plus the vault promised in the plan):**
5. **X25519 ECDH-based encrypted messaging** (`x25519.py` + `session.py`)
   — RFC 7748 Curve25519, cross-checked against OpenSSL-derived
   keypairs and shared secrets; ephemeral per-session keys give
   session-level forward secrecy; messages are AES-256-GCM with
   strictly-increasing per-direction counters (tamper + replay detection).
6. **Interactive HTML visualizer** (`viz.py`) — animates real AES
   round-by-round state and the SHA-256 compression function step by
   step, generated directly from execution traces of the real code (not
   a separate, possibly-diverging JS reimplementation).
7. **Padding-oracle attack** (`vulnerable_cbc.py` + `padding_oracle.py`)
   — a real implementation of Vaudenay's 2002 attack: recovers full
   plaintext from a deliberately unauthenticated CBC box using only a
   padding-valid/invalid oracle and zero key access, then fails cleanly
   against the real AES-GCM vault, concretely demonstrating why the
   required features are built the way they are.
8. **Password-based file vault** (`vault.py`) — PBKDF2 + AES-256-GCM,
   self-describing container, wrong-password and corrupted-file
   failures are deliberately indistinguishable.

## Adversarial review (Phase 3 — see [REVIEW.md](./REVIEW.md))

Reviewing the code as a hostile reviewer caught 4 real issues, the
first a genuine bug rather than a style nit:
1. **Critical performance bug** — AES re-derived its entire round-key
   schedule from scratch on every 16-byte block. A 1 MB GCM encrypt
   took **43 seconds**. Fixed by caching the schedule per key and
   switching MixColumns/SubBytes to precomputed lookup tables: now
   ~5.5 s/MB (~8x).
2. **OAEP decryption oracle** — an out-of-range ciphertext raised a
   different error message than a bad-padding one, exactly the
   distinguishable-failure class RFC 8017 warns against (Manger's
   attack). Unified to one generic message.
3. Dead/confusing leftover-refactor branch in `pss_verify` — cleaned up.
4. The hand-written uniform-random-integer helper in `bigint.py` had an
   off-by-one in its rejection-sampling threshold, proven non-uniform
   by exact enumeration. Fixed and re-proven uniform.

## Known, stated limitations

- **No side-channel/timing hardening.** Documented non-goal — a Python
  interpreter can't give real timing guarantees regardless of
  algorithm. This is an educational/functional implementation, not a
  hardened production crypto library.
- **Modest throughput.** ~180 KB/s for AES-256-GCM, ~2,800 PBKDF2
  iterations/sec. Fine for messages, config files, and small-to-medium
  files; a multi-MB file or a 600,000-iteration KDF (the OWASP-recommended
  minimum, calibrated for compiled implementations doing >1M iter/sec)
  would take real wall-clock time here. `vault.py`/`cli.py kdf` default
  to 4,096 iterations (~1.5s, a deliberate bcrypt-like delay) instead;
  `--iterations` lets you trade speed for a larger margin.
- **GCM nonce reuse** is the caller's responsibility, as with any GCM
  implementation. Every shipped tool (`cli.py`, `vault.py`, `session.py`)
  generates a fresh random IV/uses a strictly-increasing counter per
  encryption and never accepts a caller-supplied one, so this can't
  happen through the shipped surface.

## Verification

122 unit tests across 12 files in `tests/`, plus `demo.sh` (test suite +
16-check CLI walkthrough). Run `./demo.sh` — both are green.

## Stack

Pure Python 3 stdlib only for every cryptographic primitive (`os` for
CSPRNG bytes via `os.urandom`, nothing else). `openssl`/`gcc` are used
*only* in tests, as an independent oracle to cross-check the from-scratch
implementations — those tests skip gracefully if the tools aren't
present. `viz.py` generates self-contained HTML/CSS/JS with no
external dependencies or CDN links.

## Where a human could take this next

- **Argon2id** for the vault's KDF (memory-hard, resists GPU/ASIC
  attacks far better than PBKDF2) — would need a from-scratch BLAKE2b
  first.
- **Full Double Ratchet** (Signal-style) for `session.py` — per-message
  DH re-keying instead of one shared secret for the whole session, so
  compromising one message key doesn't affect any other message.
- **Ed25519 signatures** to pair with X25519 for a complete identity +
  key-exchange story (right now PSS/RSA and X25519 are separate; a real
  secure-messaging app wants one signing scheme).
- **Speed**: a C extension (or `ctypes` binding to libsodium/OpenSSL)
  for the hot loops — AES rounds and PBKDF2 in particular — would close
  the ~1000x gap to production throughput while keeping the pure-Python
  version as the reference/teaching implementation.
- **A browser demo of the vault/session** using the same AES/SHA
  visualizer scaffolding, so encryption/decryption of a real message can
  be watched happening live instead of only via the CLI.
