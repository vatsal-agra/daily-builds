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

See [PLAN.md](./PLAN.md) for the full architecture and feature list.
Adversarial review, stretch features (X25519 messaging, AES/SHA
visualizer, padding-oracle demo), and a full test suite are still to
come — this README will be filled in fully once the build ships.
