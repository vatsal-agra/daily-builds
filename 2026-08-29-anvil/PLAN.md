# Anvil — a from-scratch web server engine, forged on raw sockets

## Concept

Every server-shaped thing anyone runs — a REST API, a chat app, a reverse
proxy, a CDN edge — ultimately rests on the same three layers: a TCP byte
stream, an HTTP/1.1 (or WebSocket) framing on top of it, and a concurrency
model that lets one process serve many connections at once. Almost nobody
who *uses* `Flask`/`aiohttp`/`nginx` has actually built any of those three
layers themselves. Anvil builds all three from nothing but the `socket` and
`selectors` modules: a hand-rolled incremental HTTP/1.1 parser (no
`http.server`, no `socketserver`, no `BaseHTTPRequestHandler` anywhere), a
single-threaded non-blocking event loop that multiplexes many concurrent
keep-alive connections through one OS thread (the same `epoll`/`kqueue`
readiness model real event-driven servers use), a real RFC 6455 WebSocket
implementation running on the exact same sockets, and — because a protocol
stack is only proven by round-tripping through an independent client — a
raw-socket HTTP client and a reverse-proxy/load-balancer built on the same
core, so Anvil talks to itself, an external `curl`, and a real browser.

## Why it's interesting

This repo has built compilers, CPU pipelines, path tracers, SAT solvers,
git, nine transformers, and four search engines from scratch — but never a
network protocol stack. Networking looks "easy" (`socket.connect()`, done)
right up until you have to handle: a request that arrives split across
three `recv()` calls, two pipelined requests that arrive in *one* `recv()`,
a client that sends one byte per second (slow-loris), chunked
`Transfer-Encoding` with trailers, a `Range: bytes=-500` suffix request, a
WebSocket frame whose payload spans multiple TCP segments, and 200
simultaneous keep-alive clients — served by a single thread with zero
blocking calls. That's the actual hard part of building a server, and it's
a genuinely new domain for this ledger.

## Architecture

```
                      ┌─────────────────────────────┐
  TCP bytes  ───────▶ │   selectors event loop        │  server.py
                      │   (one thread, EVENT_READ/    │
                      │    WRITE readiness per fd)    │
                      └──────────────┬───────────────┘
                                     │ per-connection recv buffer
                                     ▼
                      ┌─────────────────────────────┐
                      │  incremental HTTP/1.1 parser  │  http_parser.py
                      │  (byte-stream state machine:  │
                      │   request-line → headers →    │
                      │   body via Content-Length or   │
                      │   chunked)                     │
                      └──────────────┬───────────────┘
                                     │ Request object
                                     ▼
                      ┌─────────────────────────────┐
                      │  router (exact/param routes,  │  router.py
                      │  static files + Range/ETag,   │
                      │  handler functions)           │
                      └──────────────┬───────────────┘
                          │ HTTP response      │ 101 Upgrade
                          ▼                    ▼
                 response bytes         ┌──────────────┐
                 written back           │  WebSocket    │  websocket.py
                 through the same       │  framing on   │
                 non-blocking fd        │  the same fd  │
                                        └──────────────┘

  raw-socket HTTP client (client.py) ─┐
  reverse proxy / load balancer      ─┼─▶ all built on the same
  (proxy.py, forwards raw bytes)     ─┘   send()/recv() primitives
```

No `asyncio`, no `http.server`, no third-party frameworks. Pure Python 3
stdlib: `socket`, `selectors`, `hashlib` (SHA-1 for the WS handshake),
`base64`, `struct` (WS frame headers), `os`/`mimetypes` (static file
serving — MIME lookup only, not the protocol).

## Feature list

**Required (core, must work end-to-end with zero stubs):**

1. **Hand-rolled HTTP/1.1 parser + response writer on raw sockets.**
   Incremental byte-stream state machine (handles split reads, pipelined
   requests in one read, `Content-Length` bodies, `Transfer-Encoding:
   chunked` request *and* response bodies with trailers), strict-enough
   parsing to reject malformed requests with a clean `400` instead of
   crashing or hanging.

2. **Single-threaded non-blocking event loop** using `selectors`
   (`DefaultSelector`, level-triggered), a per-connection state machine
   (reading / processing / writing), correct partial-write handling
   (never blocks on a slow client, re-arms `EVENT_WRITE` until the send
   buffer drains), and real keep-alive connection reuse — one thread
   genuinely serving many concurrent clients.

3. **Routing + static file serving**, with the parts that are usually
   skipped in a toy server: exact and `{param}` routes, directory
   traversal protection, real MIME-type detection, `ETag`/
   `Last-Modified` conditional `GET` → `304 Not Modified`, and `Range:
   bytes=...` → `206 Partial Content` (including open-ended and suffix
   ranges), matching what `curl -r` / a browser's `<video>` seek expects.

4. **WebSocket protocol (RFC 6455) on the same raw sockets.** HTTP
   Upgrade handshake (`Sec-WebSocket-Accept` = base64(SHA-1(key +
   magic GUID))), full frame codec (FIN/opcode/mask/payload-length
   incl. 16-bit and 64-bit extended lengths, client-frame unmasking,
   server frames sent unmasked per spec), text/binary/ping/pong/close
   opcodes, and continuation-frame (fragmented message) reassembly.

**Stretch:**

5. **Reverse proxy / load balancer.** A second Anvil mode that accepts
   client connections and round-robins them across a pool of backend
   Anvil servers, forwarding raw HTTP bytes both ways (streaming, not
   buffering the whole body), with a health check that pulls a
   misbehaving backend out of rotation and puts it back once it
   recovers.

6. **Raw-socket HTTP client + a live WebSocket chat demo.** A client
   library built on the same primitives (not `urllib`/`requests`) used
   to write the integration tests and a small load-test tool; a
   browser-facing chat room app (`app_demo/`) whose HTML/JS talks to
   Anvil's real WebSocket server, proving the whole stack end-to-end
   with an actual UI, not just curl output.

## Verification strategy

- Unit tests for the parser against deliberately adversarial byte
  streams (split mid-header, split mid-chunk-size, pipelined requests,
  zero-length body, huge header line, malformed chunk trailer).
- Integration tests that open **real TCP sockets** against a running
  Anvil instance (not mocks) and assert on real response bytes.
- Real `curl` invocations in `demo.sh` (GET, HEAD, `-r` range, chunked
  POST, `-H "Connection: keep-alive"` reuse) cross-checking Anvil's
  bytes against what `curl` itself reports it received.
- A raw-socket WebSocket client script driving the handshake + framing
  end to end against the live server.
- A concurrency/load test opening many simultaneous slow/fast clients
  against the single-threaded event loop to prove it never blocks.
