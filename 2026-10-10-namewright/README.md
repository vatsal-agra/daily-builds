# Namewright

A **from-scratch DNS stack in Go** (standard library only, ~6.7 k lines + ~2.6 k lines of tests): the wire
protocol, master-file zones, an authoritative name server, a recursive caching resolver that walks the hierarchy
from the root, and DNSSEC signing + validation. Everything talks real DNS over real UDP/TCP sockets on loopback
and is cross-checked against an independent implementation (dnspython).

```
$ namewright resolve blog.example.com A
;; zone .: 1 nameserver(s)
;; query 198.51.100.1 for blog.example.com. A
;; referral to com. (a.gtld-servers.net.)
;; query 198.51.100.2 for blog.example.com. A
;; referral to example.com. (ns1.example.com.)
;; query 198.51.100.10 for blog.example.com. A
;; follow CNAME -> blog.glueless.com.
;; glueless NS ns.dnshost.net.: resolving address
;;    …(nested walk root → net. → dnshost.net.)…
blog.example.com.   3600  IN  CNAME  blog.glueless.com.
blog.glueless.com.  3600  IN  A      192.0.2.201
```

## Run it

```bash
go build -o namewright ./cmd/namewright        # Go 1.24+, no dependencies

./demo.sh                                       # 48 end-to-end checks through the real CLI (≈ 1 min)
go test -race ./...                             # 90 tests
python3 -I tests/crosscheck.py                  # dnspython oracle (pip install dnspython cryptography)
go test ./dns -run xxx -fuzz FuzzUnpack         # fuzz the wire decoder
```

| Command | What it does |
|---|---|
| `namewright resolve [-signed] name [type]` | Iterative resolution through a built-in mini internet (root, `com.`, `net.`, 5 name servers on loopback) with a step-by-step trace. `-signed` signs root/`com.`/`example.com.` and validates. `-real` uses the real root servers. |
| `namewright testnet [-signed]` | Starts that mini internet plus a **recursive resolver on a real port** — point `dig`, `dnspython`, or anything else at it. |
| `namewright serve -zone origin=file …` | Authoritative server (UDP+TCP). Also: `-secondary origin=host:port`, `-axfr-allow CIDRs`, `-rate N -burst M`, `-policy file`, `-recursive [-validate -anchor file]`. |
| `namewright dig [@server] [type] name [+tcp +dnssec +cd +norec +short]` | dig-style client. |
| `namewright check [-print] file.zone` | Parse + validate a zone, with `file:line` errors. |
| `namewright axfr @host:port zone` | Zone transfer client. |
| `namewright keygen / sign / verify` | DNSSEC key generation (Ed25519, ECDSA-P256), zone signing (DNSKEY + NSEC + RRSIG), offline verification of signed zones. |
| `namewright decode` | Decode a hex DNS message from stdin (debugging). |

Library use is just as direct — `dns.NewServer`, `dns.NewResolver`, `dns.Client`, `dns.SignZone`; see the tests.

## Feature list

**Required (core)**
1. **Wire codec** (`dns/wire.go`, `rdata.go`, `names.go`) — header/flags, A AAAA NS CNAME SOA MX TXT PTR SRV CAA DNSKEY DS RRSIG NSEC OPT and opaque RFC 3597 types; name compression on encode (case-insensitive suffix sharing), hostile-input-safe decode (pointer loops, forward pointers, overlong names, absurd counts, truncated rdata → errors, never panics); escaped labels (`\.`, `\DDD`); EDNS0 incl. DO bit, BADVERS; TC-aware size-limited packing.
2. **Zone-file parser** (`dns/zonefile.go`) — `$ORIGIN`, `$TTL`, `@`, relative names, owner/TTL/class omission, `( )` continuation, comments, quoted strings with escapes, TTL units (`1h30m`), RFC 3597 `\#` form, BOM; line-numbered errors; zone validation (single SOA, CNAME exclusivity, out-of-zone data, occluded data below cuts, RRset TTL harmonisation, duplicates). Output identical to dnspython's parse on all sample zones.
3. **Authoritative server** (`dns/zone.go`, `server.go`) — RFC 1034 §4.3.2 lookup with referrals + glue, in-zone CNAME chasing, RFC 4592 wildcards, empty non-terminals, NXDOMAIN vs NODATA with negative-TTL SOA, AA/RA/RD handling, EDNS0 buffer sizes with TC truncation, TCP with pipelining and connection cap, REFUSED outside zones, AXFR with ACL, CHAOS `version.bind`, FORMERR/NOTIMP/BADVERS handling, never answers responses.
4. **Iterative caching resolver** (`dns/resolver.go`, `cache.go`, `client.go`) — root hints → referrals → answer; glueless NS resolution; CNAME chains across zones; loop/depth/query-budget guards; bailiwick filtering (poisoning attempts are dropped); TTL cache with RFC 2308 negative caching and RFC 2181 trust ranking; 0x20 case randomisation with fallback; failed-server demotion; singleflight coalescing; TCP retry on truncation; usable as a recursive server front end.

**Stretch (all four shipped)**
5. **DNSSEC** (`dns/dnssec.go`, `validate.go`) — Ed25519 + ECDSA-P256 signing, RSA/SHA-256 verification; NSEC chains; DS (SHA-1/256/384); canonical RR ordering and wildcard-label handling; validating resolver with a chain of trust from a root anchor (DNSKEY or DS), secure/insecure/bogus states, NSEC denial proofs (NXDOMAIN + wildcard denial, NODATA, wildcard-NODATA, empty non-terminals, insecure-delegation proofs), signature-lifetime-bounded caching, CD and AD bits, downgrade (stripped RRSIG) detection.
6. **Secondary server** (`dns/secondary.go`) — SOA polling, AXFR, RFC 1982 serial arithmetic, serial-regression protection, SOA-driven refresh/retry/**expire** (zone withdrawn when the primary is gone too long).
7. **Rate limiting + response policy** (`dns/policy.go`) — per-client token bucket (IPv4-mapped aware) on UDP; blocklist/redirect policy (`NXDOMAIN`, `NODATA`, `A/AAAA addr`, `*.suffix`).
8. **Fuzzing** — native Go fuzz targets for the decoder (decode → re-encode → decode invariant) and the zone parser; ~1.5 M executions each pass clean.

## How it is verified

* `go test -race ./...` — 90 tests: byte-exact RFC-style vectors, hostile packets, every lookup rule, server/resolver integration over real sockets, regression tests for every review finding, DNSSEC positive and *attack* cases (tampered/expired/not-yet-valid/stripped signatures, wrong DS, missing NSEC proofs, wrong trust anchor, CD-cache leak).
* `tests/crosscheck.py` — **dnspython as the oracle, both directions**: dnspython validates our RRSIGs (Ed25519, ECDSA, wildcard, NSEC), recomputes our DS digests, parses our wire output and talks to our servers (including TC → TCP fallback); our `verify` accepts zones signed *by dnspython*; our decoder reads dnspython-built messages. 28/28.
* `demo.sh` — 48 assertions through the CLI.
* [REVIEW.md](REVIEW.md) — the adversarial review: 17 defects found and fixed (5 high), each with a test that failed first.

Measured on 4 vCPUs: zone lookup ≈ 6.8 µs, full authoritative handle+encode ≈ 14.7 µs (≈ 68 k queries/s/core before the socket).

## Why I chose this today

DNS is the one protocol every other build in this repo silently depends on, and none of the 80+ earlier entries touched it.
It is also a better test of care than most "from scratch" projects: it *looks* trivial and is full of sharp edges —
compression pointers, wildcard rules that were rewritten in RFC 4592, NXDOMAIN vs NODATA, truncation, glueless
delegations, negative caching, trust ranking, canonical ordering for signatures. Because DNS has independent
implementations, "it works" can be *proven* against an oracle rather than claimed. The adversarial review paid off:
the worst bugs (concurrent resolutions failing each other, a glue/NS race, a panic when signatures were present) only
showed up under `-race` and a validating run — exactly the kind of thing a happy-path demo hides.

## Where a human could take this next

* **NSEC3** (hashed denial) and opt-out — the biggest gap for validating real-world zones; also RSA signing and ECDSA-P384.
* **Qname minimisation (RFC 9156)**, DNS cookies (RFC 7873), aggressive NSEC caching (RFC 8198), serve-stale (RFC 8767).
* **DNS-over-TLS/HTTPS/QUIC** listeners and upstreams; DNS over TCP keepalive tuning.
* **Dynamic UPDATE + TSIG + NOTIFY/IXFR** to turn the secondary into a real replication system; zone journalling.
* A **web dashboard** over the server's stats and the resolver trace (the trace hook already emits structured steps).
* Run `namewright serve -recursive` against the real internet (the root hints for `-real` are baked in) and compare
  with `unbound` on a query corpus; fuzz the resolver against a generated hostile "internet".
* Packet-capture-driven regression tests (pcap replay into the codec).
