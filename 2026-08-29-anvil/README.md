# Anvil

A from-scratch web server engine, forged directly on raw TCP sockets: a
hand-rolled HTTP/1.1 parser, a single-threaded non-blocking event loop, a
router with real Range/conditional-GET support, and a real RFC 6455
WebSocket implementation — no `http.server`, no `asyncio`, no third-party
frameworks.

**Status: Phase 2 (core build) complete.** All 4 required features are
implemented and verified end-to-end against a real running server (not
mocks): see [PLAN.md](PLAN.md) for architecture, `tests/` for the
automated suite, and `app_demo/` for a live WebSocket chat app served
entirely by Anvil.

## Quickstart

```bash
python3 app_demo/chat_server.py --port 8080
# then open http://127.0.0.1:8080/ in a browser
```

## Run the tests

```bash
python3 -m unittest discover -s tests
```

## What's implemented so far

1. **Hand-rolled HTTP/1.1 parser** (`anvil/http_parser.py`) — incremental
   byte-stream state machine, handles split reads, pipelined requests,
   `Content-Length` and `Transfer-Encoding: chunked` bodies (with
   trailers), rejects malformed/smuggling-shaped input with a clean 400.
2. **Single-threaded non-blocking event loop** (`anvil/server.py`) —
   `selectors`-based, one thread serving many concurrent keep-alive
   connections with correct partial-write backpressure handling.
3. **Routing + static file serving** (`anvil/router.py`) — exact/`{param}`
   routes, path-traversal-safe static mounts, `ETag`/`Last-Modified`
   conditional GET → 304, `Range` → 206 Partial Content.
4. **WebSocket protocol (RFC 6455)** (`anvil/websocket.py`) — real
   handshake, full frame codec (masking, extended lengths, fragmentation,
   ping/pong/close), running on the exact same sockets as the HTTP side.

Still to come: adversarial review (Phase 3), the reverse-proxy/load-balancer
and raw-socket HTTP client stretch features (Phase 4), and a full
verification pass (Phase 5).
