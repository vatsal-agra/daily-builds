# Anvil

A from-scratch web server engine, forged directly on raw TCP sockets: a
hand-rolled HTTP/1.1 parser, a single-threaded non-blocking event loop, a
router with real Range/conditional-GET support, and a real RFC 6455
WebSocket implementation — no `http.server`, no `asyncio`, no third-party
frameworks.

**Status: Phase 5 (verification) complete — `./demo.sh` is green (14/14).** All 4 required features
plus both stretch features are implemented and verified end-to-end against
real running servers (not mocks). 11 real bugs found in adversarial review
— including a genuine `Expect: 100-continue` deadlock and an HTTP
response-splitting gap — are fixed with regression tests. See
[PLAN.md](PLAN.md) for architecture, [REVIEW.md](REVIEW.md) for the full
findings list, `tests/` for the automated suite (104 tests), and
`app_demo/` for a live WebSocket chat app and a live reverse-proxy demo,
both served entirely by Anvil.

## Quickstart

```bash
# the chat app
python3 app_demo/chat_server.py --port 8080
# then open http://127.0.0.1:8080/ in a browser

# the reverse proxy (two backends + a load balancer, one process)
python3 app_demo/run_proxy.py --proxy-port 8888
curl 127.0.0.1:8888/whoami   # repeat it -- watch it alternate A/B

# a concurrency load test against either of the above
python3 loadtest.py --port 8080 --path / --workers 50 --requests 20
```

## Run the tests

```bash
python3 -m unittest discover -s tests   # 104 unit + integration tests
./demo.sh                                # full end-to-end verification (14 checks)
```

## Features

**Required (all 4 implemented, tested end-to-end against a live server):**

1. **Hand-rolled HTTP/1.1 parser** (`anvil/http_parser.py`) — incremental
   byte-stream state machine: split reads, pipelined requests,
   `Content-Length`/chunked bodies with trailers, `Expect: 100-continue`,
   and rejects malformed/smuggling-shaped input with a clean 400.
2. **Single-threaded non-blocking event loop** (`anvil/server.py`) —
   `selectors`-based, one thread serving many concurrent keep-alive
   connections with correct partial-write backpressure handling.
3. **Routing + static file serving** (`anvil/router.py`) — exact/`{param}`
   routes, path-traversal- and symlink-escape-safe static mounts,
   `ETag`/`Last-Modified` conditional GET → 304, `Range` → 206 Partial
   Content.
4. **WebSocket protocol (RFC 6455)** (`anvil/websocket.py`) — real
   handshake, full frame codec (masking, extended lengths, fragmentation,
   ping/pong/close), running on the exact same sockets as the HTTP side.

**Stretch (both implemented):**

5. **Reverse proxy / load balancer** (`anvil/proxy.py`) — round-robin
   over healthy backends, raw byte forwarding (not HTTP-aware — a real
   TCP-level proxy), background health checks with automatic
   failover/recovery. Live demo: `app_demo/run_proxy.py`.
6. **Raw-socket HTTP client** (`anvil/client.py`) — used throughout the
   test suite as an independent protocol implementation, and to power
   `loadtest.py`, a concurrency/throughput tool that proves the
   single-threaded event loop genuinely serves many clients at once.

Still to come: the final ship-quality README pass and a LEDGER.md entry
(Phase 6).
