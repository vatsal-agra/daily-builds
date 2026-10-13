# Keyhole — adversarial review

Method: (1) my own hostile pass while building (probes in `review_test.go`, `hostile_test.go`,
`tamper_test.go`); (2) an independent reviewer with no access to my conclusions read the whole
`tls13` package and wrote reproductions. Every item below was turned into a failing test first
(where the behaviour is observable) and then fixed; a fresh run of the whole suite under `-race`
plus `verify.sh` hits none of them.

## Findings (all fixed unless marked)

| # | Sev | Finding | Fix / regression test |
|---|-----|---------|-----------------------|
| 1 | **High** | **Resumption skipped certificate verification across configs sharing a `SessionCache`.** A ticket from an `InsecureSkipVerify` (or different-RootCAs) handshake was reused by a verifying client, which then never saw a certificate. | `ClientSession` now records `Verified` + the peer chain; a verifying client re-runs `x509.Verify` (its roots, name, clock) before offering a ticket, and a resumed connection reports the re-verified chain. `TestResumptionCannotBypassCertificateVerification` |
| 2 | **Med** | **Tickets didn't bind client authentication or SNI.** A ticket from an anonymous session resumed on a `RequireClientCert` server sharing the ticket key (mTLS bypass); resumed sessions lost the client identity; SNI was compared only if both sides had one. | Ticket now seals the authenticated client leaf; `RequireClientCert` refuses tickets without one; identity restored into `PeerCertificates` on resume; SNI must match exactly. `TestTicketsDoNotBypassMutualTLSOrSNI` |
| 3 | Med | **`Close()` hung behind a `Write()` blocked on a stalled peer** (`Close` took `outMu` first). | Write deadline is set *before* contending for the lock. `TestCloseUnblocksStuckWriter` |
| 4 | Med | **A read-deadline timeout killed the connection** and lost the partially-read record. | Records are reassembled in a persistent buffer; timeouts are returned without poisoning state. `TestReadTimeoutIsRetryable` |
| 5 | Low-Med | **Data race on shared `Certificate.leaf`** (lazy cache written by every handshake using a shared Config). | Cache removed (parse per use). `TestManyConcurrentHandshakesShareOneConfig` under `-race` |
| 6 | Low | **Nil-pointer panics on API misuse**: `Dial(addr, nil)`, `GetCertificate` returning `(nil,nil)`, `Certificate` without key. | Guarded; all three now yield handshake errors. `TestAPIMisuseDoesNotPanic` |
| 7 | Low | `ExportKeyingMaterial` accepted negative / >255·HashLen / >65535 lengths and over-long labels (panic, counter wrap, silent truncation). | Validated. same test |
| 8 | Low | Wrong alert for a wrong-length `KeyUpdate` (`illegal_parameter`; RFC 8446 §4.6.3/§6 → `decode_error`). | Fixed in `parseKeyUpdate` |
| 9 | Low | `TicketKey` of the wrong length was silently replaced by a random per-process key (breaking multi-server resumption); `Rand` failure produced an all-zero key. | Wrong length → handshake error; `Rand` failure → error. `TestAPIMisuseDoesNotPanic` |
| 10 | Low | `DescribeHandshake` (incl. `x509.ParseCertificate`) ran on every message even with tracing off — doubled pre-auth parse cost. | Guarded by `Config.Trace != nil` |
| 11 | Low | **Handshake message fragments interleaved with other record types** (alert / app data inside a split message) were accepted (RFC 8446 §5.1). | `unexpected_message`, both during and after the handshake. `TestServerRejectsInterleavedRecordInsideHandshakeMessage` |
| 12 | Low | **KeyUpdate flood**: each `update_requested` forced key derivation + a reply, unbounded. (found by me) | Max 32 consecutive KeyUpdates without data. `TestKeyUpdateFloodIsRejected` |
| 13 | Low | Zero-length `Write` emitted an empty application record. (found by me) | No-op. `TestZeroLengthWriteSendsNothing` |
| 14 | Test bug | `echoServer` helper deadlocked past 16 connections (looked like a library hang under concurrency). | Buffer enlarged — recorded because it cost time to rule out as a library bug. |

## Not fixed (deliberate, documented)

* **No ticket anti-replay / obfuscated-age check.** A ticket works for 24 h and may be replayed.
  Acceptable *because 0-RTT is not implemented* (replay only matters for early data); each resume
  issues a fresh ticket. Would need a single-use store to add 0-RTT.
* No NSEC-style "insufficient_security" policy for SHA-1 / small RSA beyond Go's own X.509 rules and a 2048-bit floor for CertificateVerify keys.
* ECDSA P-384 *certificates* are supported; P-384 *key exchange* is not (X25519 and P-256 only).

## What the reviewer checked and found sound
Transcript hashing (HRR `message_hash`, PSK binder truncation), key schedule/exporter, nonce &
sequence handling, signature-scheme ↔ key-type binding, Finished/CertificateVerify alert codes,
and ~2 M mutated messages through every parser with no panic.

## Process note on verification
Secrets are not just "tests passed": `TestClientAgainstGoServer`, `TestServerAgainstGoClient`,
`TestClientAgainstOpenSSLServer` and `TestServerAgainstOpenSSLClient` compare every derived traffic
secret line-for-line with the key logs written by `crypto/tls` and OpenSSL, and the exporter output
with `openssl s_client -keymatexport`. RFC 8448's full trace could not be downloaded (sandbox has no
route to rfc-editor.org), so that RFC's byte-level vectors are *not* used; known-answer constants
for the key schedule (early secret, `derived`), HKDF (RFC 5869 A.1) and ChaCha20-Poly1305 (RFC 8439
§2.8.2, plus 308 vectors from OpenSSL via Python) are.
