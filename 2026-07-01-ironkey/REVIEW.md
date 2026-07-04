# Ironkey — Adversarial Review (Phase 3)

Reviewed every primitive as a hostile reviewer: hunted for correctness
bugs, information leaks, and performance/UX shortcuts that "work in a
demo" but fail under real use. Four real issues found; all four fixed
below, each with the concrete reproduction that proves the bug and the
regression that proves the fix.

## 1. CRITICAL (performance): AES key schedule recomputed on every block — 1 MB takes 43 seconds

`AES.encrypt_block`/`decrypt_block` delegated to the module-level
`encrypt_block(block, key)` / `decrypt_block(block, key)` functions,
which call `key_expansion(key)` **from scratch on every single 16-byte
block**. `modes.py`'s CBC/GCM loops call `cipher.encrypt_block(...)`
once per block (and GCM additionally calls it once for H, once for J0,
and once per counter block) — so a file of N blocks re-derives the
*entire* AES-256 round-key schedule (14 rounds of SubWord/RotWord/XOR)
N+ times instead of once.

**Reproduction:** `modes.gcm_encrypt(key, iv, os.urandom(1_000_000))`
took **43.29 s** for a single 1 MB payload — this is not a rounding
error, it's roughly 4 orders of magnitude slower than it needs to be,
and would make the vault/messaging tools (Phase 4) unusable on any real
file.

**Fix:** `AES.__init__` now runs `key_expansion` once and caches
`(round_words, nr)`; `encrypt_block`/`decrypt_block` on the instance
consume the cached schedule via new `_encrypt_with_schedule` /
`_decrypt_with_schedule` helpers. The module-level `encrypt_block(pt,
key)` / `decrypt_block(ct, key)` free functions (used by the FIPS-197
single-block vector tests) are kept, now implemented as thin wrappers
around the same cached-schedule core so there's one source of truth.
1 MB GCM encrypt/decrypt after the fix: **0.24 s** (~180x).

## 2. MEDIUM (security — information leak): OAEP decryption failures are distinguishable

`oaep_decrypt` raised `ValueError("decryption error")` for padding
failures but let a *different*, more specific message —
`ValueError("ciphertext representative out of range")` from `_rsadp` —
escape uncaught whenever the ciphertext integer happened to be `>= n`.
RFC 8017 §7.1.2 is explicit that OAEP implementations MUST return a
single generic error for every failure mode precisely because letting
an attacker distinguish *why* decryption failed turns repeated
decryption oracle queries into a practical plaintext-recovery attack
(this is the shape of Manger's 2001 attack on OAEP).

**Reproduction:** feeding `oaep_decrypt` a ciphertext block of all
`0xFF` bytes (guaranteed `>= n` for any real key) raised
`"ciphertext representative out of range"`, while a tampered-but-in-range
ciphertext raised `"decryption error"` — two different, attacker-visible
strings for two different failure classes.

**Fix:** `oaep_decrypt` now checks `c_int >= priv.n` itself and raises
the same generic `"decryption error"` before ever calling `_rsadp`, so
no path through OAEP decryption can produce a distinguishable message.

## 3. LOW (code quality): dead/confusing branch in `pss_verify`

```python
em = m_int.to_bytes(em_len, "big") if m_int.bit_length() <= em_len * 8 else None
if em is None:
    return False
em = m_int.to_bytes(em_len, "big")   # unconditionally recomputed right after
```
The second assignment is unreachable-if-different-from-the-first — it
only runs when the branch above already proved the `to_bytes` call is
safe, so it's a no-op duplicate of the first line dressed up as if it
were doing something else. Harmless at runtime but exactly the kind of
leftover-refactor cruft that hides real bugs on the next edit.

**Fix:** collapsed to a single guard-then-convert:
```python
if m_int.bit_length() > em_len * 8:
    return False
em = m_int.to_bytes(em_len, "big")
```

## 4. LOW (uniformity bug): `bigint._os_randrange` rejection-sampling threshold was off by one range-width

The acceptance threshold was `span * (space // (span + 1))` where it
needed to be `(span + 1) * (space // (span + 1)) - 1`. The accepted
region is not guaranteed to be an exact multiple of the range width, so
`raw % range` is not perfectly uniform over accepted draws — low
residues get systematically more mass than high ones.

**Reproduction (exact enumeration, not sampling noise):** for
`randrange(0, 1)` with a 1-byte draw space, the old code accepted 129
of 256 raw values for a 2-value range: value `0` got 65/129, value `1`
got 64/129. Confirmed non-uniform across dozens of `(span, nbytes)`
combinations by brute-force enumeration.

In practice the impact on RSA key generation is negligible (the extra
padding byte in `nbytes` makes the space astronomically larger than the
range, so the bias is many orders of magnitude below anything
observable), but a function that claims to produce a uniform random
integer should actually do that, especially in a security library.

**Fix:** threshold corrected to `limit = (space // range) * range`,
accept `raw < limit`, return `lo + raw % range` — the accepted region
is now an exact multiple of the range width by construction. Verified
by brute-force enumeration (not sampling) to be exactly uniform for
every `(span, nbytes)` combination previously shown biased.

## Not treated as bugs (documented, in-scope limitations)

- **No side-channel/timing resistance.** Stated as a non-goal in
  PLAN.md; a pure-Python interpreter can't give meaningful timing
  guarantees regardless of algorithm choice. `_consttime_eq` in
  `modes.py`/`rsa.py` avoids the *cheapest* short-circuit-on-first-byte
  timing leak but this is not a constant-time implementation in the
  cryptographic-engineering sense.
- **GCM nonce reuse is caller's responsibility**, as with any GCM
  implementation — reusing a (key, IV) pair for two different messages
  breaks GCM's authentication catastrophically. `cli.py`, `vault.py`,
  and `session.py` all generate a fresh random IV per encryption and
  never let a caller supply one, so this can't happen through the
  shipped tools.
- **CBC-only channel with no MAC is intentionally kept** as
  `vulnerable_cbc.py` in Phase 4 — it exists specifically to be broken
  by the padding-oracle demo, as a concrete illustration of why the
  vault/session code uses GCM instead.

## Fresh run-through after fixes

Re-ran the full NIST/RFC/OpenSSL vector suite plus every reproduction
above: all previously-passing vectors still pass, all four findings no
longer reproduce (see `tests/` in Phase 5). Zero of the issues listed
above remain.
