# Cascade

A DNS resolver **and** an authoritative nameserver, built from the RFC 1035
wire format up — the actual binary protocol every `dig`, every OS resolver,
and every production nameserver (BIND, Unbound, PowerDNS, CoreDNS...)
speaks. Pure Python 3 stdlib. No `dnspython`, no `socket.getaddrinfo()`, no
library doing DNS logic anywhere in shipped code — `dnspython` appears only
as a dev/test-only differential oracle (see [Verification](#verification)
below), the same pattern this repo uses elsewhere for real `git`,
`gcc`/`objdump`, and Node's WASM engine.

## What it is

Two halves of the same protocol, both real:

1. **The wire format.** DNS messages — header, question, answer/authority/
   additional records — encoded and decoded byte-for-byte per RFC 1035,
   including *name compression*: a repeated name (or suffix of one) is
   replaced with a 2-byte pointer back to its first occurrence, both when
   reading someone else's messages and when writing Cascade's own.
2. **An authoritative nameserver.** Loads a real BIND-style zone file and
   answers real UDP/TCP queries against it correctly: exact matches, CNAME
   chasing, wildcard synthesis, NODATA vs. NXDOMAIN, and delegation
   referrals with glue records for a child zone's in-bailiwick nameservers.
3. **A recursive resolver.** Runs the actual algorithm every recursive
   resolver on the real internet runs — start at the root, follow NS
   referrals down through however many delegations it takes, use glue
   records where available and resolve a nameserver's own name recursively
   where they aren't — not "forward the query to 8.8.8.8."
4. **A cache with real TTL semantics.** Positive answers expire on their
   own TTL; NXDOMAIN and NODATA are negative-cached per RFC 2308, bounded by
   the zone's SOA `minimum`.

Since there's no live internet access in this environment (and a
reproducible demo shouldn't depend on the real root servers being reachable
anyway), Cascade ships its own tiny **self-contained "fake internet"**: a
root server, a `.com` TLD server, and two authoritative servers, each a real
`AuthoritativeServer` process listening on its own `127.0.0.x` loopback
address (the whole `127.0.0.0/8` range is loopback on Linux, so four
servers can each bind the same port on a different address simultaneously).
The recursive resolver has no idea it isn't talking to the actual internet —
it's the identical algorithm either way, just pointed at root hints that
happen to be `127.0.0.2` instead of `198.41.0.4`.

## How to run it

```bash
cd 2026-08-14-cascade
python3 -m pip install -r requirements-dev.txt   # dev-only: pytest + dnspython
./demo.sh                                        # tests + full feature walkthrough
```

Or drive it by hand:

```bash
# Serve a real zone file as a real UDP+TCP nameserver:
python3 -m cascade.cli serve zones/example.com.zone --origin example.com. --port 5391 &
python3 -m cascade.cli dig example.com. A --port 5391
python3 -m cascade.cli dig www.example.com. A --port 5391   # CNAME chase

# Full recursive resolution against Cascade's built-in fake internet
# (root -> .com TLD -> example.com, real UDP round trips each hop):
python3 -m cascade.cli resolve www.example.com A --trace

# Same lookup, plus an HTML page tracing exactly what happened on the wire:
python3 -m cascade.cli resolve mail.example.com A --viz trace.html

# The whole feature set in one scripted, self-verifying walkthrough:
python3 -m cascade.cli demo
```

A pre-generated example of the visualizer output is checked in at
[`visualizer/example-trace.html`](visualizer/example-trace.html) — open it
directly in a browser, no server required.

## Feature list

**Required (all 4 implemented and working end-to-end):**

- RFC 1035 wire codec with name compression (encode *and* decode) for
  A, AAAA, NS, CNAME, SOA, MX, TXT, PTR — verified byte-for-byte against
  `dnspython` in both directions plus the exact RFC 1035 §4.1.4 worked
  compression example.
- Authoritative nameserver: BIND-style zone file loading, exact match,
  CNAME chasing (including multi-hop), wildcard synthesis, NODATA vs.
  NXDOMAIN, delegation referrals with in-bailiwick glue, real UDP+TCP
  sockets, survives an internal error on one query without taking the
  listener down for everyone else.
- Recursive resolver: real iterative root → TLD → authoritative delegation
  against the built-in fake internet, glue-record shortcut when available,
  nested resolution of a nameserver's own name when it isn't, loop
  detection, a `dig`-style trace of every real hop.
- TTL-respecting cache: positive answers expire on their real TTL (a
  short-TTL record demonstrably gets re-fetched once it actually expires);
  RFC 2308 negative caching for NXDOMAIN (per-name, any type) and NODATA
  (per name+type), bounded by the zone's SOA minimum.

**Stretch (both implemented):**

- EDNS0 (the OPT pseudo-RR, larger advertised UDP payload size) plus
  transparent TCP retry whenever a UDP response comes back truncated
  (TC=1) — demonstrated with a real oversized TXT record that truncates
  without EDNS0 and fits in one datagram with it.
- An interactive, self-contained HTML resolution-trace visualizer, built
  from a real recorded `Trace` of an actual resolution (not a canned
  diagram) — screenshot-verified in both light and dark mode with zero
  console errors via headless Chromium.

## Why I built this today

DNS is a genuinely unusual corner of infrastructure: everyone depends on it
constantly and almost nobody has looked inside it. It's also a domain this
repo's history hadn't actually touched yet — every prior "protocol-shaped"
build here has been a language/VM/compiler (Coil, Kiln, Ember, Unify) or a
self-contained offline algorithm (the various compressors, SAT solvers,
path tracers, crypto suites); nothing so far has implemented an actual
*network wire protocol* with a real client and server exchanging real
UDP/TCP packets, or a *distributed delegation* algorithm (root → TLD →
authoritative) rather than one self-contained engine answering its own
questions. It's also unusually well-suited to this repo's favorite
verification pattern — a real, independent, spec-compliant library
(`dnspython`) that can differentially check both the wire format and, by
acting as a genuine DNS client against Cascade's own server, the whole
protocol stack end to end.

## Verification

- `dnspython` (`pip install`-ed, dev/test-only, never imported by anything
  under `cascade/`) as an external oracle: 1,000-case differential fuzz of
  the wire codec in both directions (`tests/test_dnspython_oracle.py`), plus
  the exact RFC 1035 §4.1.4 worked compression example as a fixed vector.
- 100 automated tests across the whole stack: wire codec, zone-file parser,
  authoritative answer logic (including a regression test for every bug in
  [`REVIEW.md`](REVIEW.md)), the TTL/negative cache, live-socket resolver
  tests against the real fake internet, and subprocess-driven CLI
  end-to-end tests.
- `./demo.sh` — installs dev deps, runs the full test suite, runs the
  scripted `cascade demo` walkthrough (dig-style direct queries, full
  recursive resolution with a real trace, cache-hit/TTL-expiry/negative-
  cache checks, EDNS0/TCP-truncation, visualizer generation), and
  regenerates the checked-in example visualizer — exits non-zero on any
  failure.
- [`REVIEW.md`](REVIEW.md): a hostile adversarial-review pass plus what
  Phase 5's real automated test suite caught afterward — 7 real bugs found
  and fixed in total, each with a concrete repro and root cause, plus one
  suspected bug that was run down and found to be a test-methodology
  artifact rather than a real one.

## Where a human could take this next

- **Real internet mode.** Swap the fake-internet root hints for the real
  13 root server addresses and Cascade's recursive resolver would, as far
  as the code is concerned, be resolving the actual internet — the
  algorithm doesn't know the difference. (Would need a sandboxed network
  policy that allows outbound UDP/TCP port 53, which this environment
  intentionally doesn't grant by default.)
- **DNSSEC.** The EDNS0 plumbing (the OPT pseudo-RR, the DO bit) is
  already there; RRSIG/DNSKEY/DS record types and signature validation
  would be the natural next protocol layer.
- **General RFC 1034 wildcard matching.** Cascade's wildcard support
  handles the common single-label case; the fully general closest-encloser
  algorithm (matching arbitrarily deep names under a wildcard, correctly
  blocked by any more-specific existing name) is a well-scoped follow-up —
  see the "known, intentional scope limits" note in `REVIEW.md`.
- **Zone transfers (AXFR/IXFR).** Cascade's zones are loaded from static
  files; a secondary server pulling updates from a primary over a real
  AXFR/IXFR session would make the delegation story fully dynamic.
- **Response-hardening.** Query-ID randomness, 0x20-encoding, and stricter
  source-port/response validation would move Cascade from "correct DNS" to
  "DNS that resists an on-path spoofing attacker" — deliberately out of
  scope for this build (see `REVIEW.md`'s scope-limits note) but a natural
  security-hardening pass.
