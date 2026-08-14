# Cascade — a DNS resolver and authoritative nameserver, built from the wire format up

## Concept

The Domain Name System is the one piece of internet infrastructure everyone
depends on and almost nobody has actually implemented. It sits at a genuinely
unusual intersection: a tiny, tightly-specified binary wire protocol (RFC
1035, 1996-vintage but still exactly what real DNS servers speak today) glued
to a distributed, delegated database (root → TLD → authoritative) that has to
tolerate lossy UDP, truncation, and caching with real time-to-live semantics.

Cascade implements both halves from scratch in pure Python, with zero use of
`dnspython`, `socket.getaddrinfo`, or any other library that does DNS logic
for us:

1. A byte-exact RFC 1035 message codec — the same wire format `dig`, `bind`,
   `unbound`, and every OS resolver on earth speaks — including the fiddly
   part almost every toy implementation gets wrong: DNS name compression
   (pointers into earlier occurrences of a name, both reading them on decode
   and *writing* them on encode to keep responses under the UDP-safe size).
2. An authoritative nameserver that loads real BIND-style zone files and
   answers UDP/TCP queries for them correctly — NXDOMAIN, NODATA, CNAME
   chasing, wildcards, glue records.
3. A recursive resolver that does the *actual* algorithm every recursive
   resolver on the internet runs: start at the root, get referred down through
   TLD to the authoritative server, follow delegations, use glue records to
   avoid a chicken-and-egg lookup loop — not "forward to 8.8.8.8", the real
   thing.
4. A caching layer with correct TTL countdown and RFC 2308 negative caching
   (a NXDOMAIN gets cached too, bounded by the zone's SOA `minimum`).

## Why this is interesting

- **A genuinely new domain for this repo.** Every prior "protocol-shaped"
  build here has been either a language/VM (Coil, Kiln, Ember, Unify) or an
  offline algorithm (compression, crypto, search, physics, SAT). Nothing so
  far has implemented an actual *network wire protocol* with a client and a
  server that talk real UDP/TCP to each other, or a *distributed* delegation
  algorithm (root → TLD → auth) rather than a single self-contained engine.
- **A protocol most engineers use hourly and have never looked inside.**
  Watching an actual root → `.com` → `example.com` referral chain resolve,
  byte for byte, demystifies something that normally just "works" invisibly.
- **Real independent verification is available on this box.** `dnspython`
  isn't installed by default, but `pip install dnspython` works here, which
  gives Cascade the same "differential oracle" pattern this repo leans on
  everywhere else (Graft/Strata vs real `git`, Ember vs `gcc`/`objdump`,
  Kiln vs Node's WASM engine, Trove vs NLTK): dnspython's message codec and
  its real UDP query client become an independent, spec-compliant judge of
  whether Cascade's wire bytes are actually correct DNS — not just
  internally self-consistent. It is a dev/test-only dependency, never
  imported by any shipped `cascade/` code.
- **No internet access required for a legitimate demo.** Real recursive
  resolution can't be demoed against the real root servers in a sandboxed,
  reproducible way — so Cascade builds its own tiny "fake internet": a root
  server, a `.com` TLD server, and a couple of authoritative servers, all
  real Cascade server processes talking real UDP to each other on
  localhost. The recursive resolver has no idea it isn't talking to the
  actual internet — it runs the identical delegation algorithm either way.

## Architecture

```
cascade/
  wire.py       — RFC 1035 header/question/RR codec, name compression (encode + decode)
  rdata.py      — per-type rdata encode/decode: A, AAAA, NS, CNAME, MX, TXT, SOA, PTR
  message.py    — DNSMessage: ties header+question+RRs together, truncation-aware encode
  zonefile.py   — BIND-style zone file parser ($ORIGIN, $TTL, SOA, all supported RR types)
  cache.py      — TTL-aware answer cache + RFC 2308 negative (NXDOMAIN/NODATA) cache
  server.py     — authoritative UDP+TCP server: loads a zone, answers queries correctly
  resolver.py   — iterative/recursive resolver: root hints → follow referrals → glue → answer
  trace.py      — records every query/response of a resolution for the HTML visualizer
  cli.py        — `cascade serve|dig|resolve|demo`
zones/          — the fake-internet zone files: root, com (TLD), example.com, wobsite.example
tests/          — unit + dnspython-oracle differential tests + end-to-end CLI tests
visualizer/     — generates a self-contained HTML page tracing a real resolution
demo.sh         — spins up the fake internet, runs real lookups, runs the test suite
```

Nothing here shells out to a real DNS resolver or the real internet at
runtime; the "fake internet" is a handful of real `cascade serve` processes
bound to different localhost ports, wired together purely through each
zone's own NS/glue records, exactly like real DNS delegation.

## Feature list

**Required (core, must fully work end-to-end):**

1. **RFC 1035 wire codec with name compression** — encode and decode DNS
   messages (header, question, answer/authority/additional sections) for A,
   AAAA, NS, CNAME, MX, TXT, SOA, and PTR records; message-level name
   compression on both the read and write path. Verified byte-for-byte
   against `dnspython`'s own codec in both directions (Cascade encodes →
   dnspython decodes and agrees; dnspython encodes → Cascade decodes and
   agrees), plus hand-checked against the textbook example packet from RFC
   1035 §4.1.4.
2. **Authoritative nameserver** — loads a real zone file and serves real
   UDP (and TCP fallback for responses that don't fit in 512 bytes, with the
   TC bit set correctly on the UDP response) queries against it: exact
   matches, CNAME chasing, wildcard (`*.`) records, correct NXDOMAIN /
   NODATA / REFUSED behavior, case-insensitive name matching.
3. **Recursive resolver with real delegation** — implements the actual
   internet resolution algorithm (start at root hints, follow NS referrals
   through TLD to the authoritative server, use glue A records to resolve
   nameservers that live inside the zone being delegated, detect and bail
   out on referral loops) against Cascade's own fake-internet server farm,
   with a `dig`-style CLI client to drive it.
4. **TTL-respecting cache with RFC 2308 negative caching** — successful
   answers are cached and expire on their real TTL (demonstrated with a
   short-TTL record actually expiring and being re-fetched); NXDOMAIN/NODATA
   results are negative-cached, bounded by the zone's SOA `minimum` field,
   and a cache-hit is measurably faster and produces zero extra wire
   traffic to the authoritative chain versus a cache-miss.

**Stretch (2+, implement at least 1):**

5. **EDNS0 + TCP fallback on truncation** — advertise/honor EDNS0 (OPT
   pseudo-RR, larger UDP payload size), and when a real authoritative
   answer still doesn't fit even with EDNS0, correctly set TC=1 over UDP and
   have the resolver transparently retry over TCP and get the complete
   answer.
6. **Interactive HTML resolution-trace visualizer** — feed it a domain name
   and it renders the actual root → TLD → authoritative referral chain that
   played out on the wire for that lookup (each hop's query/response,
   glue records used, cache hits highlighted), generated from a real
   recorded trace, not a canned diagram.

## Verification strategy

- `dnspython` (pip-installed, dev/test-only, never imported by shipped code)
  as an external differential oracle for the wire codec in both directions,
  and as an independent real DNS client to query Cascade's authoritative
  server over actual UDP sockets.
- The RFC 1035 §4.1.4 worked example packet as a fixed byte-for-byte test
  vector for name compression.
- A real multi-process (or multi-thread, one per fake server) "fake
  internet" — root, `.com` TLD, `example.com`, and one delegated subdomain
  with glue records — so recursive resolution is exercised end-to-end over
  real sockets, not mocked.
- `demo.sh`: boots the whole fake internet, runs real lookups through the
  CLI (A/AAAA/CNAME/MX/TXT/NXDOMAIN/wildcard/delegated-with-glue/TTL
  expiry/negative-cache), and runs the full test suite, exiting non-zero on
  any failure.
