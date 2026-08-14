# Cascade

A DNS resolver and authoritative nameserver, built from the RFC 1035 wire
format up. Pure Python, no `dnspython`/`socket.getaddrinfo`/library DNS logic
in shipped code. See [`PLAN.md`](PLAN.md) for the full concept, architecture,
and feature list.

**Status: Phase 4 (stretch + polish) complete.**

All 4 required features work end-to-end against a real self-contained "fake
internet" (root → `.com` TLD → authoritative servers, real UDP/TCP sockets on
localhost):

- RFC 1035 wire codec (name compression both ways, A/AAAA/NS/CNAME/SOA/MX/TXT/PTR)
- Authoritative nameserver (exact match, CNAME chase, wildcard, NODATA/NXDOMAIN, delegation+glue)
- Recursive resolver (real root → TLD → authoritative referral chain, nested NS resolution when glue is missing)
- TTL-respecting cache with RFC 2308 negative caching

Both stretch features are implemented and demonstrated: EDNS0 (OPT
pseudo-RR, larger UDP payload negotiation) + transparent TCP retry on
truncation, and an interactive HTML resolution-trace visualizer (a checked-in
example lives at [`visualizer/example-trace.html`](visualizer/example-trace.html),
screenshot-verified in both light and dark mode with zero console errors via
headless Chromium).

`python3 -m cascade.cli demo` runs a full scripted walkthrough with live
assertions against every feature above.

Adversarial review (Phase 3, see [`REVIEW.md`](REVIEW.md)) found and fixed 4
real bugs: a wildcard that could override a legitimate NODATA answer, a
single bad query that could permanently kill the whole UDP listener, silent
TXT-record data corruption from quote-unaware zone-file parsing, and raw
Python tracebacks on ordinary user mistakes — plus a 1,000-case differential
fuzz of the wire codec against `dnspython` (clean) and one suspected bug that
was run down and found to be a test-methodology artifact, not a real one.
Phase 4's polish pass then caught a fifth issue while eyeballing the
rendered visualizer, not just reading the code: a failed-query step was
mislabeled as a cache lookup.

Verification (Phase 5) is next.
