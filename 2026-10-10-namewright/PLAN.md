# Namewright — Plan

## Concept
A from-scratch **DNS stack in Go (stdlib only)**: RFC 1035 wire codec, master-file zone parser,
an authoritative name server (UDP + TCP + EDNS0), an iterative caching recursive resolver that
walks the hierarchy from root hints, and DNSSEC signing/validation. Everything speaks real DNS over
real sockets on loopback, so independent tools (dnspython, used only as a test oracle) can talk to it.

## Why it's interesting
DNS is the one protocol every other build in this repo silently depends on, and none has implemented it.
It is full of sharp corners that make a "toy" version wrong: name compression with pointer loops,
truncation and TCP fallback, CNAME chains, wildcard synthesis rules (RFC 4592), NXDOMAIN vs NODATA,
referrals with glue vs glueless delegations, negative caching (RFC 2308), and DNSSEC canonical
ordering. Getting these right and proving it against an independent implementation is the point.

## Architecture
```
cmd/namewright      CLI: serve | dig | resolve (+trace) | zone check | sign | verify
dns/                wire.go     message/RR codec, name compression, RFC 3597 unknown types
                    zonefile.go master-file parser ($ORIGIN/$TTL/$INCLUDE-less, parens, quoted TXT)
                    zone.go     in-memory zone, lookup algorithm (delegation/CNAME/wildcard/NXDOMAIN/NODATA)
                    server.go   UDP+TCP listeners, EDNS0, truncation, AXFR
                    resolver.go iterative resolver, cache, negative cache, loop/depth guards, trace
                    cache.go    TTL cache (injectable clock)
                    dnssec.go   key gen, RRSIG sign, NSEC chain, DS, validator (Ed25519 + ECDSA P-256)
testdata/           zone files for a miniature internet (root, com, example.com ...)
tests/ + demo.sh    unit + integration tests, dnspython cross-check script
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Wire codec: header flags, questions, RRs; A AAAA NS CNAME SOA MX TXT PTR SRV CAA + opaque unknown types; name compression on encode, pointer-loop / bounds-safe decode, OPT/EDNS0 | **required** |
| 2 | Master-file zone parser: `$ORIGIN`, `$TTL`, `@`, relative names, owner/TTL/class omission, `( )` continuation, comments, quoted strings, TTL units (1h30m), line-numbered errors, zone validation (SOA, CNAME coexistence, out-of-zone) | **required** |
| 3 | Authoritative server: UDP+TCP, AA flag, referrals + glue, CNAME chasing, wildcards (RFC 4592), NXDOMAIN/NODATA with SOA, EDNS0 buffer size + TC truncation, REFUSED outside zones, AXFR | **required** |
| 4 | Iterative caching resolver: root hints → referrals → answer, glueless NS resolution, CNAME chains, TTL cache + negative cache, loop/depth limits, `+trace` output, TCP retry on TC | **required** |
| 5 | DNSSEC: Ed25519 / ECDSA-P256 zone signing (RRSIG, DNSKEY, NSEC, DS), canonical RR ordering, validating resolver with chain of trust from a trust anchor, NSEC denial proofs | stretch (ship ≥1) |
| 6 | Zone transfer client + secondary server (AXFR pull, serial check via SOA) | stretch |
| 7 | Query-rate limiting / response policy zone (RPZ-like blocklist) in the server | stretch |
| 8 | Fuzzing of the decoder (Go native fuzz) with invariants: no panic, re-encode round trip | stretch |
