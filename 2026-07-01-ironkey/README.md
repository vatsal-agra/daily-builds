# Ironkey

A cryptography suite built entirely from scratch in pure Python — SHA-256,
HMAC/PBKDF2, AES-256 (CBC + GCM), RSA (OAEP + PSS), and X25519 ECDH — each
verified against official NIST/RFC test vectors, powering a real encrypted
file vault and a forward-secure messaging session.

**Status: Phase 2 (Core build) complete.** All 4 required primitives are
implemented and independently verified:

- `sha256.py` — SHA-256, bit-exact vs `hashlib` (empty string, "abc", 1M
  `"a"` chars, arbitrary text).
- `hmac_kdf.py` — HMAC-SHA256 (RFC 4231 vectors incl. keys longer than
  the block size) + PBKDF2-HMAC-SHA256, both bit-exact vs `hmac`/`hashlib`.
- `aes.py` + `modes.py` — AES-128/192/256 exact vs the FIPS 197 Appendix
  B/C test vectors; CBC and GCM cross-checked byte-for-byte against
  OpenSSL (`openssl enc` for CBC, a small libcrypto/EVP harness for GCM,
  since OpenSSL's `enc` CLI doesn't do AEAD) including AAD and tamper
  rejection.
- `rsa.py` — RSA key generation (Miller-Rabin), OAEP encryption, and PSS
  signatures per RFC 8017; round-tripped, boundary-length-tested, and
  tamper/cross-key rejection tested.

`cli.py` exposes all of it (`hash`, `hmac`, `kdf`, `aes encrypt/decrypt`,
`rsa genkey/encrypt/decrypt/sign/verify`) and every command has been run
by hand end to end.

**Status: Phase 3 (Adversarial review) complete.** Reviewed as a hostile
reviewer; found and fixed 4 real issues (full writeup in
[REVIEW.md](./REVIEW.md)):
1. **Critical performance bug** — AES re-expanded its full round-key
   schedule on every 16-byte block, making a 1 MB GCM encrypt take
   43 seconds. Fixed by caching the schedule per key and switching
   MixColumns/SubBytes to precomputed lookup tables: **1 MB now
   encrypts in ~5.5 s** (~8x), with headroom documented honestly below
   rather than pretended away.
2. **OAEP decryption oracle** — a ciphertext representative `>= n`
   raised a different, distinguishable error message than a padding
   failure, which is exactly the kind of oracle RFC 8017 tells
   implementers to avoid. Unified to a single generic message.
3. Dead/confusing branch in `pss_verify` left over from an earlier
   refactor — cleaned up.
4. `bigint`'s hand-written uniform-random-integer helper had an
   off-by-one in its rejection-sampling threshold, proven non-uniform
   by exact enumeration (not just sampling noise) for a range of small
   cases. Fixed and re-proven uniform by the same enumeration.

**Known limitation, stated plainly:** this is a pure-Python
implementation with no side-channel/timing hardening (a documented
non-goal — a Python interpreter can't give real timing guarantees
regardless of algorithm) and modest throughput (~180 KB/s for AES-GCM).
Fine for messages, config files, and small-to-medium files; a multi-MB
file will take real wall-clock time. This is disclosed, not hidden.

**Status: Phase 4 (Stretch + polish) complete.** All 3 stretch features
shipped, plus the file vault promised in PLAN.md's architecture:

- `x25519.py` — Curve25519/X25519 (RFC 7748 Montgomery ladder), verified
  against real OpenSSL-generated keypairs and derived shared secrets
  (both directions agree, and match OpenSSL's own derivation byte for
  byte).
- `session.py` — ephemeral-X25519 + AES-256-GCM two-party messaging with
  strictly-increasing per-direction counters; demo exercises handshake,
  bidirectional messaging, tamper detection, and replay detection.
- `vault.py` — a real password-based file vault (PBKDF2-HMAC-SHA256 +
  AES-256-GCM), self-describing container format, wrong-password and
  corrupted-file failures deliberately indistinguishable.
- `vulnerable_cbc.py` + `padding_oracle.py` — a from-scratch
  implementation of Vaudenay's 2002 padding-oracle attack, run against a
  deliberately unauthenticated CBC box (full plaintext recovered with
  zero key access), then run again against the real GCM vault where it
  correctly fails — there's no padding-validity signal to exploit at all.
- `viz.py` — a self-contained interactive HTML page animating real AES
  round-by-round state and the SHA-256 compression function step by
  step, generated from actual execution traces (not a separate,
  possibly-diverging JS reimplementation).

**Performance, stated honestly:** this is pure Python with no C
extensions. AES-256-GCM does ~180 KB/s (fine for messages/config/small
files; a multi-MB file will take real wall-clock time — see REVIEW.md
finding #1 for the 43s→5.5s/MB fix). PBKDF2 runs at ~2,800 iterations/s,
which is why `vault.py`/the `kdf` command default to 4,096 iterations
(~1.5s, a deliberate bcrypt-like delay) rather than the 600,000+ OWASP
recommends for a fast compiled KDF — that number assumes >1M iter/s and
would mean a ~3.5-minute vault open here. `--iterations` is exposed for
anyone who wants to trade speed for a larger margin.

See [PLAN.md](./PLAN.md) for the full architecture and [REVIEW.md](./REVIEW.md)
for the adversarial review. A full test suite is still to come — this
README will be filled in completely once the build ships.
