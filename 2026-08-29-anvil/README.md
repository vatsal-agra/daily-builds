# Anvil

A from-scratch web server engine, forged directly on raw TCP sockets: a
hand-rolled HTTP/1.1 parser, a single-threaded non-blocking event loop, a
router with real Range/conditional-GET support, and a real RFC 6455
WebSocket implementation — no `http.server`, no `asyncio`, no third-party
frameworks.

**Status: Phase 1 (planning) complete.** See [PLAN.md](PLAN.md) for the
full architecture and feature list. Implementation starts next phase —
this README will grow a real "how to run it" section as soon as there's
something to run.
