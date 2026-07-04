# Cryptex — Cryptography Workbench from Scratch

## Concept

A complete, production-quality cryptography toolkit implemented in pure Python
**from the mathematical foundations up** — no `hashlib`, no `hmac`, no `Crypto`
library, no `secrets` module for the actual algorithms (only OS entropy for key
generation). Every algorithm is written from first principles and verified
against published NIST test vectors.

**Why it's interesting:** cryptography lives at the intersection of number theory,
abstract algebra, and engineering security. Implementing AES from GF(2^8)
arithmetic, SHA-256 from scratch, RSA from Miller-Rabin primality, and ECDH/ECDSA
from elliptic-curve point arithmetic reveals *why* these primitives are secure
and how they compose into a complete system. This is the clearest path from
"I know crypto exists" to "I understand how it actually works."

## Architecture

```
cryptex/
├── cryptex.py          # CLI entry point (subcommands)
├── gf256.py            # GF(2^8) field arithmetic (AES foundation)
├── aes.py              # Rijndael AES-256: S-box, key schedule, ECB/CBC/CTR
├── sha256.py           # SHA-256 from scratch: schedule, compression, HMAC
├── rsa.py              # RSA-2048: Miller-Rabin, OAEP, sign/verify
├── ecc.py              # P-256: point arithmetic, ECDH, ECDSA
├── chacha20.py         # ChaCha20 stream cipher + Poly1305 MAC (stretch)
├── viz.py              # Self-contained HTML visualizer generator
└── tests.py            # Full test suite (NIST vectors + property tests)
```

## Feature List

### Required (4)

**F1 — AES-256** (Core symmetric cipher)
- GF(2^8) arithmetic from scratch: irreducible polynomial `x^8+x^4+x^3+x+1`
- S-box construction via multiplicative inverse + affine transform (not hardcoded)
- Full Rijndael round: SubBytes, ShiftRows, MixColumns (GF matrix multiply), AddRoundKey
- AES-256 key schedule (14 rounds, Rcon via GF multiplication)
- ECB mode (test vector validation), CBC mode (PKCS#7 pad/unpad), CTR mode
- File encryption/decryption CLI

**F2 — SHA-256 + HMAC-SHA256** (Cryptographic hash)
- 64 round constants K[i] (first 32 fractional bits of cube roots of primes 2..311)
- Initial hash values H[i] (first 32 fractional bits of square roots of primes 2..19)
- Full message padding (length encoding, big-endian)
- 64-round compression function (σ₀, σ₁, Σ₀, Σ₁, Ch, Maj)
- HMAC-SHA256 as a composition (ipad/opad construction)
- Test vector verified against NIST FIPS 180-4

**F3 — RSA-2048** (Asymmetric cipher + signatures)
- Miller-Rabin probabilistic primality test (20 witnesses)
- Extended Euclidean algorithm for modular inverse
- Fast modular exponentiation (binary right-to-left)
- RSA key generation: two 1024-bit primes, e=65537, CRT parameters
- RSA-OAEP encryption/decryption (using our SHA-256, MGF1 mask generation)
- PKCS#1 v2.1 PSS signature scheme (sign + verify)
- PEM-like ASCII key format with base64 encoding

**F4 — P-256 ECDH + ECDSA** (Elliptic curve cryptography)
- secp256r1 (NIST P-256) curve parameters (p, a, b, Gx, Gy, n, h)
- Jacobian projective coordinates for efficient point arithmetic
- Point doubling, point addition (handles point at infinity)
- Scalar multiplication via double-and-add (Montgomery ladder for const-time)
- ECDH key exchange: private key × peer public key → shared secret
- ECDSA sign/verify: RFC 6979 deterministic k (HMAC-DRBG using our SHA-256)
- Uncompressed + compressed point encoding (SEC1)

### Stretch (2)

**S1 — ChaCha20-Poly1305 AEAD**
- ChaCha20 stream cipher (Bernstein, 20 rounds) with quarter-round and full-block
- Poly1305 one-time MAC (Bernstein) with 130-bit integer arithmetic
- AEAD construction: ChaCha20-Poly1305 (RFC 8439)
- Test vectors from RFC 8439

**S2 — Interactive HTML Visualizer**
- AES S-box: GF inverse lookup table rendered as colored 16×16 grid
- AES key schedule: columns expanding with Rcon/SubWord highlighted
- SHA-256: round-by-round compression with register states displayed
- Interactive encrypt/decrypt demo (runs real AES-256 in JavaScript)
- All self-contained in a single HTML file

## CLI Commands

```
cryptex aes    encrypt <hex_key> <plaintext>          # AES-256-CTR
cryptex aes    decrypt <hex_key> <ciphertext_b64>
cryptex aes    test                                    # Run NIST vectors
cryptex sha256 hash   <text|-f file>                  # SHA-256
cryptex sha256 hmac   <hex_key> <text|-f file>        # HMAC-SHA256
cryptex rsa    keygen [-b bits]                        # Generate key pair
cryptex rsa    encrypt <pub.pem> <plaintext>           # OAEP encrypt
cryptex rsa    decrypt <priv.pem> <ciphertext_b64>
cryptex rsa    sign   <priv.pem> <message>             # PSS sign
cryptex rsa    verify <pub.pem> <sig_b64> <message>
cryptex ecdh   keygen                                  # P-256 key pair
cryptex ecdh   exchange <priv_hex> <peer_pub_hex>      # Shared secret
cryptex ecdsa  sign   <priv_hex> <message>
cryptex ecdsa  verify <pub_hex> <sig_hex> <message>
cryptex chacha encrypt <key_hex> <nonce_hex> <text>   # ChaCha20-Poly1305
cryptex chacha decrypt <key_hex> <nonce_hex> <aad> <ct_b64>
cryptex viz                                            # Open HTML visualizer
cryptex demo                                           # Full feature demo
```

## Test Strategy

- NIST FIPS 197 AES Known-Answer Test (KAT) vectors
- FIPS 180-4 SHA-256 test vectors
- RSA-OAEP round-trip property tests (encrypt→decrypt == original)
- RFC 6979 ECDSA deterministic-k test vector
- ChaCha20-Poly1305 RFC 8439 test vector
- Cross-check SHA-256 against `hashlib.sha256` on 1000 random strings
- Cross-check HMAC against `hmac` module on 1000 random cases
- AES CBC cross-check against `Crypto.Cipher.AES` (if available, else skip)

## Why This Stack

Pure Python 3 stdlib — no external crypto libraries anywhere in the implementation
path. This forces every step to be explicit and auditable. The implementation is
educational-first: correctness is proven by test vectors, not assumed.
