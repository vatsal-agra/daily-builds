# Conduit

*Status: Phase 1 — planning complete. Implementation starts next.*

A TCP-like reliable transport protocol built entirely from scratch on raw
UDP sockets, exercised under active packet loss/reorder/duplication by a
from-scratch network simulator, carrying a from-scratch HTTP/1.1 server
that interoperates end-to-end with the box's real `curl` binary.

See [PLAN.md](PLAN.md) for the full design, architecture, and feature
list.

This section will be filled in with usage instructions, the full feature
list, and results as each phase completes.
