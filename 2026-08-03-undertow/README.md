# Undertow

*Status: PHASE 1 — planning complete, build starting.*

A reliable, ordered, congestion-controlled byte-stream transport protocol
("MiniTCP") built entirely from scratch on top of raw, lossy UDP — the same
problem TCP/IP solves, proven by streaming a real file through a real relay
that drops, delays, reorders, and duplicates real datagrams, and getting
every byte back identical.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.

This section will be filled in with usage instructions, the complete feature
list, and results as each build phase lands.
