# Namewright

A from-scratch **DNS stack in Go** (stdlib only): wire codec, zone-file parser, authoritative
server, iterative caching resolver — all speaking real DNS over real sockets.

**Status: Phase 4 (stretch + polish) complete — see [PLAN.md](PLAN.md), [REVIEW.md](REVIEW.md).**

## Quick look

```
go build -o namewright ./cmd/namewright
./namewright resolve blog.example.com A      # iterative walk through a built-in mini internet, with trace
./namewright testnet &                        # mini internet + recursive resolver on 127.0.0.1:5353
./namewright dig @127.0.0.1:5353 www2.example.com A
./namewright check testdata/internet/example.com.zone
```

## Implemented so far

1. **Wire codec** — all common RR types + RFC 3597 unknown types, name compression, hostile-input-safe decode, EDNS0.
2. **Zone-file parser** — `$ORIGIN`/`$TTL`, parentheses, quoted strings, TTL units, owner/TTL/class omission, line-numbered errors, zone validation.
3. **Authoritative server** — UDP+TCP, referrals with glue, CNAME chasing, wildcards, ENTs, NXDOMAIN/NODATA, truncation, AXFR.
4. **Iterative resolver** — root hints → referrals, glueless NS, CNAME chains, TTL + negative cache, bailiwick filtering, query budget.

## Review outcome (Phase 3)

14 defects found and fixed (3 high: concurrent-resolution failures, unreachable-after-failure, glue/NS race),
plus 4 UX fixes; every defect has a regression test in `dns/review_test.go`.

## Stretch features shipped (Phase 4)

* **DNSSEC** — Ed25519 + ECDSA-P256 zone signing (`keygen`/`sign`/`verify`), NSEC chains, DS records, and a
  validating resolver (chain of trust from a root trust anchor; secure / insecure / bogus; NSEC denial proofs
  incl. wildcard and empty-non-terminal cases; CD and AD bits). Cross-checked against dnspython in both directions.
* **Secondary server** — SOA polling + AXFR with RFC 1982 serial arithmetic and EXPIRE handling.
* **Rate limiting + response policy** — per-client token bucket and a blocklist/redirect policy.
* **Fuzzing** — native Go fuzzers for the wire decoder and zone parser.
