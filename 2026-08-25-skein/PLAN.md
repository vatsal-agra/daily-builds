# Skein

## Concept

A from-scratch, real peer-to-peer file distribution system — the same
core machinery that makes BitTorrent work — implemented in pure Python
with zero third-party networking or bencode libraries. Skein can take an
arbitrary file, produce a real `.torrent`-format descriptor for it, run
an HTTP tracker that peers announce to, and run peer processes that
speak the actual BitTorrent peer wire protocol (handshake, bitfield,
have/interested/choke, request/piece) over real TCP sockets to
reconstruct the file byte-for-byte from a swarm of other peers — with
no central server ever holding or forwarding the file's bytes itself.

## Why this is interesting

Every prior project in this repo's history that resembles "protocol
engineering" is either a compiler/VM (Coil, Ember, Kiln, Silicon), a
solver (five separate CDCL SAT solvers), a renderer (two path tracers),
or a single-machine data structure (Strata's KV store, Trove/Sift's
search index). None of them touch **distributed, multi-process
networking**: multiple independent OS processes, each with a partial
view of the world, coordinating over real sockets to solve a problem
neither could solve alone. Quorum came closest (Raft consensus) but
that's agreement over an ordered log, not swarm-based bulk data
transfer. Skein is a genuinely new domain for this repo: real TCP
peer connections, a real wire protocol with a byte-exact handshake and
framed messages, and swarm-intelligence piece-selection algorithms
(rarest-first, tit-for-tat choking) — verified the only way that
actually proves anything: spin up N independent local processes talking
only over sockets, and check the reassembled file's SHA-1 matches the
original bit-for-bit.

## Architecture

```
skein/bencode.py      bencode encode/decode (spec-exact: ints, byte
                       strings, lists, dicts with sorted-key encoding)
skein/torrent.py       .torrent file creation (piece hashing, info-hash)
                       and parsing
skein/tracker.py       HTTP tracker: /announce (compact peer list),
                       /scrape, in-memory swarm registry with peer
                       timeout/expiry
skein/piecemanager.py  bitfield, block-level bookkeeping, rarest-first
                       piece selection, SHA-1 piece verification,
                       on-disk sparse-file writing
skein/choke.py         tit-for-tat choking/unchoking algorithm
skein/wire.py          peer wire protocol: handshake + length-prefixed
                       message framing (choke/unchoke/interested/
                       uninterested/have/bitfield/request/piece/cancel)
skein/node.py          a Skein node: talks to the tracker, accepts
                       incoming peer connections, dials outgoing peer
                       connections, drives download + upload
skein/cli.py           `skein` CLI: create-torrent, tracker, seed,
                       leech, swarm (multi-peer local demo), viz
tests/                 unit + integration tests (incl. a real
                       multi-process swarm transfer test)
viz/                   generated HTML swarm visualizer (from a real
                       captured event log, not synthetic data)
```

Data flow for the swarm demo: `skein create-torrent` hashes a source
file into fixed-size pieces and writes a real bencoded `.torrent`.
`skein tracker` starts an HTTP server. One `skein seed` process holds
the complete file. Several `skein leech` processes start with nothing,
announce to the tracker, connect to each other and the seeder over raw
TCP, exchange bitfields, and pull pieces using rarest-first selection,
verifying every piece's SHA-1 against the torrent's piece hash before
accepting it. Leechers also seed pieces to each other once they have
them (tit-for-tat), so the file can fully propagate through the swarm
without every leecher ever touching the original seeder.

## Feature list

**Required (core, must work end-to-end with no stubs):**

1. **Bencode codec** — encode/decode integers, byte strings, lists, and
   dictionaries per the exact BitTorrent bencode spec (dict keys sorted
   as raw byte strings), round-trip exact on arbitrary nested data and
   on real `.torrent`-shaped structures.
2. **Torrent file creation & parsing** — split an arbitrary file into
   fixed-size pieces, SHA-1 each piece, build a real bencoded `.torrent`
   file (info dict, piece-hash concatenation, computed info-hash), and
   parse one back losslessly.
3. **HTTP tracker** — a real `http.server`-based tracker implementing
   `/announce` (registers a peer, returns a compact peer list, tracks
   uploaded/downloaded/left, expires stale peers) and `/scrape`.
4. **Peer wire protocol swarm transfer** — real TCP peer connections
   implementing the actual BitTorrent handshake and message framing;
   a seeder and 3+ leecher processes (independent OS processes) that
   fully reconstruct the source file via piece exchange, each piece
   SHA-1-verified on receipt, with the final leecher output file
   byte-identical to the source.

**Stretch:**

5. **Rarest-first piece selection + tit-for-tat choking** — leechers
   prioritize the globally rarest piece across their known peers
   (not sequential order) and each peer chokes/unchokes based on
   measured reciprocal upload rate, with periodic optimistic unchoke —
   real swarm-intelligence algorithms, not a placeholder "download in
   order."
6. **Live swarm visualizer** — an interactive self-contained HTML page
   that replays a real captured event log from a swarm run: per-peer
   piece-availability heatmap over time, download-rate graph, and
   choke/unchoke state, driven by actual recorded events (no synthetic
   data).

**Extra (implemented beyond the 2 stretch minimum):**

7. **Resume support** — a leecher that's killed mid-download and
   restarted against the same dest_file re-hash-checks whatever is
   already on disk and picks up from there instead of starting over.
   Verified with a real kill-and-restart of a real leecher process.
