# Ironkey — Plan

## Concept

A cryptography suite built entirely from scratch in pure Python — no
`hashlib`, no `hmac`, no `Crypto`/`cryptography` packages, no `ssl` for
any actual crypto math. Every primitive (hash function, block cipher,
big-integer modular arithmetic, elliptic curve) is implemented by hand
from its specification and checked bit-for-bit against official NIST /
RFC test vectors. On top of the primitives sits a real command-line tool:
an encrypted file vault and a forward-secure two-party messaging session,
so the primitives aren't just passing unit tests — they're doing actual
work end to end.

## Why this is interesting

Every daily build so far in this repo has been a simulator, solver, or
renderer (SAT solvers ×8, path tracers ×4, chess engines ×2, physics/DSP
engines, a DB, a regex engine, a compression toolkit, a language VM).
Cryptography is a different kind of "from scratch": correctness isn't a
matter of taste (a reasonable-looking implementation of AES that's off
by one bit in the key schedule produces *ciphertext that looks fine and
is completely wrong* — there is no partial credit, and the only way to
know you got it right is exact agreement with a published test vector).
That makes it an unusually strong test of the "no stubs, no shortcuts"
discipline this build style demands, and it's genuinely useful output —
the vault and messaging tool at the end are things a human could
actually point at a real file.

It also lets the interactive-visualizer tradition apply somewhere new:
animating the AES round transformations and the SHA-256 compression
function on real bytes, instead of another graph/tree/canvas viewer.

## Architecture

```
ironkey/
  bigint.py        modular exponentiation, extended Euclid, Miller-Rabin
                    primality, CRT — all big-integer math needed downstream
  sha256.py         SHA-256 from the FIPS 180-4 spec (message schedule,
                    compression function, padding)
  hmac_kdf.py       HMAC-SHA256 (RFC 2104) + PBKDF2-HMAC-SHA256 (RFC 8018)
  aes.py            AES-128/192/256 block cipher (FIPS 197): key
                    expansion, SubBytes/ShiftRows/MixColumns/AddRoundKey
                    and inverses, GF(2^8) arithmetic from scratch
  modes.py          CBC (w/ PKCS#7) and GCM (Galois/Counter Mode: CTR +
                    GHASH over GF(2^128)) built on the raw AES block cipher
  rsa.py            RSA key generation (Miller-Rabin primes), OAEP
                    encryption (RFC 8017 §7.1), PSS signatures (§8.1)
  x25519.py         Curve25519 Montgomery-ladder scalar multiplication
                    (RFC 7748) for Diffie-Hellman key exchange
  vault.py          CLI file vault: password -> PBKDF2 -> AES-256-GCM
                    encrypt/decrypt of arbitrary files, authenticated
  session.py        two-party encrypted messaging session: X25519 ECDH ->
                    HKDF-ish key derivation (HMAC-based) -> per-message
                    AES-256-GCM with a ratcheting counter/nonce
  vulnerable_cbc.py deliberately naive CBC-only channel (no MAC) used
                    ONLY as the target of the padding-oracle attack demo,
                    to make concrete *why* GCM/AEAD is required
  padding_oracle.py implements the Vaudenay padding-oracle attack against
                    vulnerable_cbc.py — recovers plaintext byte-by-byte
                    using only a padding-valid/invalid oracle, no key
  cli.py            top-level CLI: hash/hmac/kdf/aes/rsa/dh/vault/
                     session/attack/viz/demo subcommands
  viz.py            generates a self-contained interactive HTML page
                     animating AES round-by-round state and the SHA-256
                     compression function step-by-step on real input
tests/              unit + NIST/RFC test-vector suite
demo.sh             runs every feature end-to-end
```

Big-integer arithmetic, modular exponentiation, and primality testing are
written by hand in `bigint.py`; Python's native arbitrary-precision `int`
is used as the underlying storage (reimplementing schoolbook long
division in pure Python would make RSA keygen impractically slow without
adding any real teaching value) but every *algorithm* — modexp, extended
Euclid, Miller-Rabin, CRT — is hand-written, not delegated to a library.

## Feature list

**Required:**
1. **SHA-256** implemented from the FIPS 180-4 spec, verified against
   official NIST short/long message test vectors (empty string,
   "abc", 1M "a" chars, etc.) with bit-exact digests.
2. **HMAC-SHA256 + PBKDF2-HMAC-SHA256**, verified against RFC 4231 HMAC
   test vectors and RFC 7914 / manually-cross-checked PBKDF2 vectors.
3. **AES-256 block cipher with CBC and GCM modes**, verified against
   official NIST AES-CBC and AES-GCM (McGrew/Viega) test vectors —
   including GCM authentication-tag rejection of tampered ciphertext.
4. **RSA (keygen + OAEP encryption + PSS signatures)** from scratch —
   Miller-Rabin prime generation, correct OAEP/PSS padding per RFC 8017,
   round-trip verified and cross-checked for parameter-boundary cases.

**Stretch:**
5. **X25519 ECDH-based encrypted messaging session** — two parties derive
   a shared secret via Curve25519 Diffie-Hellman (RFC 7748 test vectors),
   derive per-message keys, and exchange authenticated (AES-256-GCM)
   messages over a simulated channel with replay/tamper detection.
6. **Interactive HTML visualizer** animating AES encryption round-by-round
   (state matrix after each transform) and the SHA-256 compression
   function step-by-step on real user-supplied input.
7. **Padding-oracle attack demo**: a deliberately vulnerable CBC-only
   "vault" plus a from-scratch implementation of the Vaudenay padding
   oracle attack that recovers plaintext without the key, followed by
   the same file protected with our real AES-GCM vault where the attack
   fails — a concrete, runnable demonstration of *why* the required
   features exist the way they do.

## Non-goals

Not trying to be constant-time / side-channel-resistant (that's a much
deeper rabbit hole requiring careful low-level timing control that a
pure-Python interpreter can't reliably provide anyway) — this is an
educational/functional implementation, not a production crypto library,
and the README will say so explicitly. All correctness claims are about
functional correctness against published test vectors, not timing safety.
