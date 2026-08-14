# Adversarial review

Hostile self-review of Cascade: constructed zones and inputs specifically
intended to break the parser, the answer logic, and the server, plus a
1,000-case differential fuzz of the wire codec against `dnspython`. Four real
issues found and fixed below; one suspected issue investigated and found to
be a test artifact, not a Cascade bug (also documented, since a false alarm
that isn't run down is exactly the kind of thing that erodes trust in the
rest of the review).

## Found and fixed

### 1. Wildcard synthesis could override a real (empty non-terminal) name — wrong NODATA became a wrong answer

**Repro:** a zone with `*.test.` → `127.0.0.20` and `a.b.test.` → `127.0.0.30`
(so `b.test.` has no data of its own but is a real node in the name tree,
because something exists *below* it). Querying `b.test.` directly:

```
exact node for b.test.:            None
is_empty_non_terminal(b.test.):    True
wildcard_match(b.test.):           [A 127.0.0.20]   <-- this is what got returned
```

Per RFC 1034 §4.3.2/§4.3.3, a wildcard only applies when there is **no
existing name** at the query name — and "existing name" includes empty
non-terminals, not just names with their own RRset. `answer_in_zone` checked
the wildcard *before* checking whether the name was an empty non-terminal, so
a legitimate `b.test.` (NODATA, because `a.b.test.` exists beneath it) was
silently answered with the wildcard's IP instead — a real, wrong DNS answer,
not just a wrong error code.

**Fix:** reordered the checks in `answer_in_zone` (`cascade/server.py`) so
"does this exact name exist as an empty non-terminal" is checked *before*
wildcard matching; only queries against genuinely-absent names now reach the
wildcard logic.

### 2. A single query that trips an internal bug permanently kills the whole UDP listener

**Repro:** monkeypatched `answer_in_zone` to raise on one query (simulating
any latent bug in future answer logic, not a hypothetical — the wildcard bug
above would have had exactly this effect before it was fixed) and sent one
UDP query, then a completely normal second query:

```
FIRST query after bug:  QueryTimeout: no response ...
SECOND (normal) query FAILED (server thread died!): QueryTimeout: no response ...
```

`_udp_loop`'s `except DNSFormatError` only caught malformed *wire bytes*.
Any other exception raised while building or encoding a response (a bug in
`answer_in_zone`, a bug in a future RR encoder, anything) propagated out of
the loop body and killed the whole thread — the listening socket stays open,
`recvfrom` never gets called again, and the server is permanently deaf to
every future client for the rest of the process's life. One bad query is a
full, silent denial of service, and there is no logged indication anything
went wrong short of noticing the server stopped answering.

**Fix:** `_udp_loop` and `_handle_tcp` (`cascade/server.py`) now catch any
`Exception` while building a response (not just `DNSFormatError`), log it to
stderr, and return a `SERVFAIL` response instead of letting the thread die —
exactly what a hardened real nameserver does with an unexpected internal
error. Also fixed a related resource leak found while fixing this:
`AuthoritativeServer.start()` left the UDP socket open if the *subsequent*
TCP bind failed (e.g. port already in use); it now closes whatever it
already opened before re-raising.

### 3. Zone-file parenthesis handling wasn't quote-aware — could silently corrupt TXT records

**Repro:** a zone file with `note IN TXT "call us at (555) 123-4567"`:

```
parsed TXT string: b'call us at  555  123-4567'
expected:          b'call us at (555) 123-4567'
```

The BIND multi-line-record convention lets `(` `)` span an SOA (or any
record) across several physical lines; `_logical_lines` counted parens with a
plain `line.count('(')` / `line.count(')')`, and after joining, blanket-
replaced every `(`/`)` in the joined text with a space — neither step
excluded characters inside a quoted string. A `(` inside a TXT string wasn't
just mishandled, it was **silently deleted** from the record's actual data,
with no error of any kind.

**Fix:** both the per-line paren-depth delta and the final paren-stripping
in `_logical_lines` (`cascade/zonefile.py`) are now quote-aware (mirroring
the quote-tracking `_strip_comment` already did correctly), so `(`/`)`
inside a quoted string are left alone.

### 4. Expected-but-invalid CLI input produced raw Python tracebacks

**Repro:** `cascade dig "bad..name.com" A` (an empty label) and running
`cascade serve` twice on the same port both dumped a full Python traceback
ending in `cascade.name.DNSFormatError: empty label in name 'bad..name.com'`
/ `OSError: [Errno 98] Address already in use` — no indication to a user
that this was *their* mistake rather than a Cascade crash.

**Fix:** `main()` (`cascade/cli.py`) now wraps dispatch in a single
`try/except` for the exception types a user can actually trigger by hand
(`DNSFormatError`, `ZoneFileError`, `OSError`, `ResolutionError`,
`transport.QueryTimeout`/`QueryError`), printing `cascade: error: ...` and
exiting 1. Genuinely unexpected exceptions (real Cascade bugs) still surface
a full traceback rather than being swallowed — silently hiding those would
just trade this bug for a worse one.

## Investigated, not a bug

**Differential fuzz "failures" against dnspython on multi-SOA test data.**
The first fuzz run (500 random messages, RR fields fully independent-random)
reported 20 "answer count mismatch" failures — Cascade's wire bytes claimed
N records, `dnspython` only parsed N-1. Before writing this off as a
dnspython quirk, tracked one down by hand and found the fuzzer had generated
**two different SOA records at the same owner name** in one message — which
is not valid DNS in the first place (RFC 2181 §5 requires SOA, among a few
other types, be a "singleton" — at most one per name). Confirmed directly
against `dns.rdataset` that `dnspython` deliberately collapses a second SOA
added to the same rdataset (last-write-wins), which is exactly why the
record count didn't match: the fuzzer's test data was invalid, not
Cascade's output. Re-ran the fuzz (1,000 messages) generating at most one
RRset per (name, type) — the only constraint an honest fuzzer needs, since
no real Cascade code path (zone loading, referral building, EDNS) ever emits
two RRsets for the same name+type either — and all 1,000 round-tripped
through `dnspython` byte-for-byte-equivalent with zero failures. The wire
codec itself has no bug here; the first run's failures were entirely test
methodology.

## Known, intentional scope limits (not bugs)

Carried over from `PLAN.md` and worth restating after actually building the
thing: wildcard matching is the common single-label case (`*.parent` matches
a direct child of `parent`), not the fully general RFC 1034 closest-encloser
algorithm; the zone-file parser doesn't support `$INCLUDE`, `$GENERATE`, or
backslash-escaped characters in labels; query IDs use `random.randint`, not
a CSPRNG, and there's no 0x20-encoding or source-port hardening — Cascade is
built to demonstrate the real protocol and algorithms correctly, not to
resist an on-path spoofing attacker. None of these came up as a surprise
during review; they're listed here so "not fixed" reads as a decision, not
an oversight.
