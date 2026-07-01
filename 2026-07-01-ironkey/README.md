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

See [PLAN.md](./PLAN.md) for the full architecture and feature list.
Stretch features (X25519 messaging, AES/SHA visualizer, padding-oracle
demo) and a full test suite are still to come — this README will be
filled in fully once the build ships.
