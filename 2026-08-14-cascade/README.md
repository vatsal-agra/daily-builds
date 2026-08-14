# Cascade

A DNS resolver and authoritative nameserver, built from the RFC 1035 wire
format up. Pure Python, no `dnspython`/`socket.getaddrinfo`/library DNS logic
in shipped code.

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end against a real self-contained "fake internet" (root → `.com` TLD
→ authoritative servers, real UDP/TCP sockets on localhost):

- RFC 1035 wire codec (name compression both ways, A/AAAA/NS/CNAME/SOA/MX/TXT/PTR)
- Authoritative nameserver (exact match, CNAME chase, wildcard, NODATA/NXDOMAIN, delegation+glue)
- Recursive resolver (real root → TLD → authoritative referral chain, nested NS resolution when glue is missing)
- TTL-respecting cache with RFC 2308 negative caching

`python3 -m cascade.cli demo` runs a full scripted walkthrough with live
assertions against all of the above, plus the two stretch features
(EDNS0 + TCP truncation fallback, HTML resolution-trace visualizer) that
were built alongside the wire/transport layer since they're inseparable
from it. See [`PLAN.md`](PLAN.md) for the full concept and feature list.
**Status: Phase 3 (adversarial review) complete.** See [`REVIEW.md`](REVIEW.md)
for the full hostile-testing pass: 4 real bugs found and fixed (a wildcard
that could override a legitimate NODATA answer, a single bad query that
could permanently kill the whole UDP listener, silent TXT-record data
corruption from quote-unaware zone-file parsing, and raw Python tracebacks
on ordinary user mistakes), plus a 1,000-case differential fuzz of the wire
codec against `dnspython` (clean) and one suspected bug that was run down
and found to be a test-methodology artifact, not a real one. Stretch
features + polish (Phase 4) are next.
