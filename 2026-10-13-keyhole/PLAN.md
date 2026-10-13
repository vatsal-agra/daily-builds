# Keyhole — PLAN

## Concept
A from-scratch **TLS 1.3 (RFC 8446) implementation** in Go. The protocol logic — record layer,
HKDF key schedule, handshake message codecs, client and server state machines, alerts,
HelloRetryRequest, resumption — is hand-written. Only *primitives* come from the standard library
(AES-GCM / ChaCha20-Poly1305 AEADs, SHA-2, X25519 / P-256 ECDH, ECDSA / Ed25519 / RSA-PSS signatures,
and `crypto/x509` for certificate parsing). `crypto/tls` is never used in the library; it appears only in
tests as an independent oracle, alongside `openssl s_client` / `s_server` and `curl`.

## Why it's interesting
The repo has DNS, TCP, crypto primitives, a torrent client and a Chord DHT, but never the protocol that
protects all of them. TLS 1.3 is a perfect "has a real oracle" problem: RFC 8448 publishes a complete
byte-level handshake trace (every secret, every key, every ciphertext), and OpenSSL / Go's `crypto/tls` are
sitting in the sandbox to interoperate with in both directions. Interop failures are unambiguous.

## Architecture
```
tls13/            library (package tls13)
  hkdf.go           HKDF-Extract/Expand, HKDF-Expand-Label, Derive-Secret
  keysched.go       early/handshake/master secret ladder, traffic keys, Finished, resumption PSK
  record.go         record layer: TLSInnerPlaintext, padding, per-record nonce, AEAD, fragmentation
  msgs.go           handshake message structs + marshal/unmarshal, extensions
  conn.go           Conn: Read/Write/Close, alert handling, KeyUpdate, post-handshake messages
  client.go         client handshake state machine
  server.go         server handshake state machine
  sig.go            CertificateVerify construction/verification, signature schemes
  ticket.go         NewSessionTicket, PSK binders, session cache (resumption)
  trace.go          structured handshake event recorder
cmd/keyhole/      CLI: server, client, get, inspect (trace), certgen
tests/            interop with openssl/curl/crypto-tls oracle, RFC 8448 vectors
verify.sh         full runnable verification
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **Key schedule + record layer** — HKDF, full secret ladder, AEAD records, inner content-type + padding, nonce construction. Verified byte-for-byte against RFC 8448 §3 | **required** |
| 2 | **Full 1-RTT handshake, client and server** — ClientHello/ServerHello/EncryptedExtensions/Certificate/CertificateVerify/Finished, X25519 + P-256, TLS_AES_128_GCM / AES_256_GCM / CHACHA20_POLY1305, SNI, ALPN, certificate chain + hostname verification, transcript hash | **required** |
| 3 | **Interop in both directions** — keyhole client ↔ openssl s_server / crypto/tls server; keyhole server ↔ openssl s_client / curl / crypto/tls client; ECDSA, Ed25519 and RSA-PSS certs | **required** |
| 4 | **Alerts + hostile input handling** — correct alert for each failure (bad MAC, unexpected message, illegal parameter, protocol_version, handshake_failure, decode_error), downgrade sentinel check, HelloRetryRequest, record-size limits, fuzz-clean parsers | **required** |
| 5 | **PSK resumption via NewSessionTicket** (stateless encrypted tickets, binders, psk_dhe_ke) interoperating with openssl | stretch |
| 6 | **KeyUpdate** (both directions, update_requested) + close_notify truncation detection | stretch |
| 7 | **Mutual TLS** (CertificateRequest / client Certificate) | stretch |
| 8 | **Handshake inspector** — `keyhole inspect` records and pretty-prints every flight, with decryption using an SSLKEYLOGFILE-style log; also text/HTML timeline | stretch |
| 9 | **Native Go fuzzers** for the record layer and each handshake parser | stretch |

## Non-goals
TLS ≤1.2, 0-RTT early data (replay protection is out of scope), OCSP stapling, certificate transparency.
