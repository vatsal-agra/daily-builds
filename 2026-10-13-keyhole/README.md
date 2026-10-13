# Keyhole — TLS 1.3 from scratch (Go)

Status: **Phase 2 (core build) complete.** See [PLAN.md](PLAN.md).

Done so far: HKDF key schedule, AEAD record layer (AES-GCM, ChaCha20-Poly1305 written from RFC 8439),
full 1-RTT client + server handshake, X25519/P-256, Ed25519/ECDSA/RSA-PSS certificates, interop with
`crypto/tls` and `openssl` in both directions with secret-for-secret key-log comparison.
