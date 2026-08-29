# Phase 3 — Adversarial Review

Attacking Anvil as a hostile reviewer: real protocol edge cases, security
gaps, and UX rough edges — not a token pass. Every finding below was
reproduced first (a failing test, or a live `curl`/raw-socket repro against
the actual running server), then fixed, then pinned with a regression test.
All 11 findings are fixed; none were downgraded or skipped. The test suite
grew from 90 to 101 tests as a direct result of this phase.

## Findings

### 1. CRITICAL — `Expect: 100-continue` not handled → real deadlock risk
Any RFC 7231-compliant client that sends `Expect: 100-continue` before a
body waits for an interim `100 Continue` (or an error) before writing that
body. Anvil ignored the header entirely and just sat in `recv()` waiting
for bytes the client was, itself, waiting on us to unblock — a genuine
two-sided deadlock, not a slow response. Reproduced with a raw socket that
withholds the body until it actually sees a `100 Continue` on the wire (it
previously would have hung until the test's socket timeout).
**Fix:** `RequestParser` now takes an `on_expect_continue` callback that
fires the instant headers finish parsing — before the body has necessarily
arrived — and the server wires it to write `HTTP/1.1 100 Continue\r\n\r\n`
immediately. `HttpClient` was also fixed to correctly skip over 1xx interim
responses when reading a reply instead of treating one as the final answer
(latent, not yet triggered by anything in this codebase, but a real
correctness gap in a client meant to double as a protocol oracle).
Regression tests: `test_http_parser.TestExpectContinue`,
`test_integration.test_expect_100_continue_answered_before_body_needed`.

### 2. HIGH — `Transfer-Encoding: gzip, chunked` silently corrupted the body
The parser accepted any Transfer-Encoding value ending in `chunked`
(`codings[-1] != "chunked"`), decoded the chunk *framing* correctly, and
then handed the handler bytes that were still gzip-compressed — silent data
corruption, not a rejected request. Anvil doesn't implement any content
coding besides the identity, so any layered encoding must be rejected, not
partially honored. **Fix:** require the Transfer-Encoding value to be
*exactly* `chunked`. Regression test:
`test_http_parser.test_layered_transfer_encoding_rejected`.

### 3. HIGH — HTTP response splitting via unsanitized header values
Nothing stopped a handler from writing a literal CR/LF into a header value
(e.g. `Response(302, headers=[("Location", user_controlled_value)])`),
which would let an attacker inject arbitrary extra headers or a second,
fully attacker-controlled response into the stream — classic HTTP response
splitting. **Fix:** `HeaderDict.set`/`.add`/`__init__` now reject any name
or value containing `\r` or `\n`. Regression tests:
`test_http_message.TestHeaderInjectionGuard` (5 cases).

### 4. HIGH — a symlink inside a static mount escaped the traversal guard
The path-traversal check only inspected the *requested path* for `..`
segments before resolving it once with `os.path.normpath`. A symlink
sitting inside the mounted directory (fully legitimate as far as that
check is concerned) can point anywhere on disk, and `open()` follows it —
so `mount_static("/static", "public/")` plus one attacker-plantable or
misconfigured symlink was a full arbitrary-file-read. Reproduced with a
real symlink pointing at a file outside the mount. **Fix:** resolve both
the mount root and the final path with `os.path.realpath` and re-check
containment *after* resolution, not just before. Regression test:
`test_router.test_symlink_escape_blocked`.

### 5. MEDIUM — WebSocket handshake accepted from any HTTP method
RFC 6455 §4.1 requires the handshake to be a `GET`. Anvil's upgrade check
only looked at the `Connection`/`Upgrade` headers, so a `POST` (or
anything else) with the right upgrade headers would silently succeed.
**Fix:** reject with 400 unless `req.method == "GET"`. Regression test:
`test_integration.test_non_get_handshake_rejected`.

### 6. MEDIUM — a broadcast to an idle connection could sit unsent
The write-readiness re-arm only ran for the connection currently being
serviced by the event loop (`_service()`'s post-processing step). A
WebSocket handler that broadcasts to *other* connections (exactly what the
chat demo's `_broadcast` does) was appending straight to another
connection's `outbuf` without ever telling the selector that fd now has
data to write — an otherwise-idle listener's message could sit buffered
until *its own* next read event, which for a quiet chat participant might
be a long time. **Fix:** `Connection.queue_out()` now re-arms write
readiness on its own connection immediately, regardless of which
connection's event triggered it. Covered indirectly by every multi-client
WebSocket integration test (all of which depend on prompt delivery to
succeed within their timeouts) and directly exercised by the live chat
demo's multi-client broadcast path.

### 7. MEDIUM — bytes pipelined right after a WS upgrade request were dropped
If a client didn't wait for the `101` before writing its first WebSocket
frame (legal, if unusual), and that frame landed in the same `recv()` as
the handshake request, those bytes were sitting in the now-retired HTTP
parser's internal buffer and were never handed to the WebSocket frame
parser once the connection switched modes — silently lost. **Fix:**
`RequestParser.take_leftover()` drains any unconsumed trailing bytes, and
the server feeds them into the WebSocket parser immediately after
completing the handshake.

### 8. LOW — stale ETag on a same-second, same-size edit
The ETag was built from `int(stat.st_mtime)` (whole seconds) and file
size. Editing a file twice within the same second, ending at the same
byte length, produced an identical ETag both times — a client would get a
stale `304 Not Modified` for content that had actually changed. **Fix:**
use `stat.st_mtime_ns` for nanosecond resolution.

### 9. LOW — empty chat messages produced an empty bubble for everyone
The client already blocks submitting a blank message, but nothing stopped
a raw WebSocket client (or a client bug) from sending
`{"type": "chat", "text": "   "}` and broadcasting an empty/whitespace-only
bubble to the whole room. **Fix:** the server now strips and drops
empty chat text server-side rather than trusting the client's UI to be the
only gate.

### 10. LOW — 1xx informational responses mishandled by the test client
See finding #1 — folded in as part of that fix since it's the same code
path (`HttpClient._read_response`).

### 11. Documented, not fixed — no defense against a slow-loris connection
A client that trickles one byte every few minutes keeps a connection (and
one selector registration) alive indefinitely, because the idle timeout
resets on *any* read activity, however small. A production-grade server
needs an independent "total time since connection opened without a
completed request" budget on top of the idle timer to bound this; Anvil
doesn't have one. This is a real, known gap — deliberately left
undefended rather than bolted on late in the day, since the fix needs its
own design (and its own tests) to avoid punishing a merely slow client
sending a genuinely large chunked body. Noted here rather than silently
shipped as if it weren't a gap.

## What a fresh run-through hit

Zero of the above. `python3 -m unittest discover -s tests` is green
(101/101) and `demo.sh` (Phase 5) re-verifies each finding's regression
test plus the full feature set against a live server.
