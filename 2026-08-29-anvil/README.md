# Anvil

A from-scratch web server engine, forged directly on raw TCP sockets: a
hand-rolled HTTP/1.1 parser, a single-threaded non-blocking event loop, a
router with real Range/conditional-GET support, and a real RFC 6455
WebSocket implementation — no `http.server`, no `asyncio`, no third-party
frameworks. Two stretch features round it out: a reverse proxy/load
balancer and a raw-socket HTTP client used throughout the test suite and a
concurrency load-test tool.

**Status: shipped.** 4/4 required features + 2/2 stretch features, all
verified end-to-end against real running servers (not mocks). 11 real bugs
found in adversarial review — including a genuine `Expect: 100-continue`
deadlock and an HTTP response-splitting gap — fixed with regression tests.
104 unit/integration tests, plus `./demo.sh` (14 checks, real curl + a
from-scratch raw-socket WebSocket client + the proxy + the load tool),
all green.

## What it is

Every server-shaped thing anyone runs rests on the same three layers: a
TCP byte stream, HTTP/1.1 (or WebSocket) framing on top of it, and a
concurrency model that serves many connections at once. Anvil builds all
three from nothing but Python's `socket` and `selectors` modules:

- an incremental HTTP/1.1 parser that handles a request split across many
  `recv()` calls, several pipelined requests in one `recv()` call,
  `Content-Length` and `Transfer-Encoding: chunked` bodies (with
  trailers), and `Expect: 100-continue`;
- a single OS thread multiplexing many concurrent keep-alive connections
  through a `selectors`-based readiness loop — the same model
  nginx/Node/Redis use, not a thread (or process) per connection;
- a router with `{param}` paths and static file serving that actually
  implements `ETag`/`Last-Modified` conditional GET and `Range` requests,
  not just "read the whole file and send 200";
- a real RFC 6455 WebSocket implementation (handshake, masking,
  fragmentation, ping/pong/close) running on the exact same sockets as
  the HTTP side;
- a reverse proxy/load balancer that round-robins raw bytes across
  backends with health-check-driven failover; and
- a raw-socket HTTP client, so the test suite talks to the server through
  an independent implementation rather than round-tripping through
  itself.

The flagship demo is a live WebSocket chat room (`app_demo/`) served
entirely by Anvil — static HTML/CSS/JS over HTTP, chat protocol over a
real WebSocket, zero other web framework anywhere in the stack.

## How to run it

```bash
# the chat app
python3 app_demo/chat_server.py --port 8080
# then open http://127.0.0.1:8080/ in a browser — join a room, chat with
# yourself in two tabs, watch the live member/message counters update

# the reverse proxy (two backends + a load balancer, one process)
python3 app_demo/run_proxy.py --proxy-port 8888
curl 127.0.0.1:8888/whoami   # repeat it -- watch it alternate A/B

# a concurrency load test against either of the above
python3 loadtest.py --port 8080 --path / --workers 50 --requests 20

# the automated test suite
python3 -m unittest discover -s tests    # 104 unit + integration tests

# full end-to-end verification against live servers
./demo.sh                                 # 14 checks, all green
```

No dependencies beyond the Python 3 standard library to *run* Anvil
itself; `demo.sh`/tests use `curl` (present on the box) and the repo's own
`anvil.client`/`anvil.websocket` modules as independent test oracles.

## Full feature list

**Required:**

1. **HTTP/1.1 parser + response writer on raw sockets** (`anvil/http_parser.py`,
   `anvil/http_message.py`) — incremental byte-stream state machine (split
   reads, pipelined requests, `Content-Length`/chunked bodies with
   trailers, `Expect: 100-continue`), strict enough to reject malformed
   or request-smuggling-shaped input with a clean 400 instead of hanging
   or crashing.
2. **Single-threaded non-blocking event loop** (`anvil/server.py`) —
   `selectors.DefaultSelector`, a per-connection state machine, correct
   partial-write backpressure handling, real keep-alive reuse. Proven
   concurrent (not just "doesn't crash with many clients") by
   `loadtest.py` and a dedicated integration test that races a slow
   endpoint against 20 fast ones.
3. **Routing + static file serving** (`anvil/router.py`) — exact and
   `{param}` routes, path-traversal- *and* symlink-escape-safe static
   mounts, real MIME detection, `ETag`/`Last-Modified` conditional GET →
   304, `Range: bytes=...` → 206 Partial Content (open-ended and suffix
   ranges too).
4. **WebSocket protocol (RFC 6455)** (`anvil/websocket.py`) — handshake
   (`Sec-WebSocket-Accept` = base64(SHA1(key+GUID))), full frame codec
   (FIN/opcode/mask/16- and 64-bit extended lengths), text/binary/
   ping/pong/close, continuation-frame reassembly, running on the same
   raw sockets as the HTTP side.

**Stretch:**

5. **Reverse proxy / load balancer** (`anvil/proxy.py`) — round-robin
   over healthy backends, raw TCP-level byte forwarding (streaming, not
   buffering full bodies), background health checks with automatic
   failover and recovery. Live demo: `app_demo/run_proxy.py`.
6. **Raw-socket HTTP client** (`anvil/client.py`) — no `urllib`/`requests`;
   used as an independent protocol implementation throughout the test
   suite and to power `loadtest.py`.

**Plus, from the adversarial-review and polish passes** (see
[REVIEW.md](REVIEW.md) for the full writeup):

- `Expect: 100-continue` support (without it, any RFC 7231-compliant
  large-body client would deadlock against Anvil).
- HTTP response-splitting protection (rejects CR/LF in header values).
- Symlink-escape protection on static file mounts (`os.path.realpath`
  double-check, not just a lexical `..` guard).
- Transfer-Encoding smuggling protection (rejects any layered coding
  other than exactly `chunked`, rather than silently mis-decoding it).
- Clean CLI error messages (port-in-use, invalid `--port`) instead of raw
  tracebacks; server-side rejection of empty/whitespace-only chat
  messages regardless of what the client UI allows.
- A genuinely styled dark-mode chat UI (not default browser styling) —
  screenshot-verified in headless Chromium.

## Why this today

This repo has built compilers, a CPU pipeline, path tracers, five SAT
solvers, git (three times), spreadsheets, and nine Transformers from
scratch — but never a network protocol stack. Networking looks easy
(`socket.connect()`, done) right up until a request arrives split across
three `recv()` calls, or two requests arrive in one, or a client waits for
permission before sending its body and you have to notice and grant it, or
200 keep-alive clients need serving by one thread with zero blocking
calls. That's the actual hard part of building a server, and it was a
genuinely open domain for this ledger.

## Where a human could take this next

- **HTTP/2 or HTTP/3** — the framing changes completely (binary frames,
  multiplexed streams, HPACK header compression) but the event-loop
  architecture underneath would carry over almost unchanged.
- **TLS** — terminate real HTTPS. The `ssl` module can wrap Anvil's
  non-blocking sockets, but doing it *correctly* inside a `selectors` loop
  (handling `SSLWantReadError`/`SSLWantWriteError` mid-handshake and
  mid-record) is its own small project.
- **A slow-loris defense** — a real "total time since connection opened
  without a completed request" budget on top of the existing idle timer
  (deliberately scoped out this round; see REVIEW.md finding #11).
- **A middleware chain** — auth, request logging, gzip response encoding,
  rate limiting — as composable wrappers around the router's dispatch,
  the way most production frameworks structure it.
- **Multi-process scaling** — `SO_REUSEPORT` and a handful of Anvil
  processes behind the OS's own load balancing would use every core
  without touching the single-threaded event loop's design at all.
