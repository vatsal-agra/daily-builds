# Swarm — a from-scratch BitTorrent-style peer-to-peer file-sharing system

## Concept

Every prior "distributed systems" build in this repo picked a *coordinated*
model: Quorum's Raft has a leader and a crash-fault-tolerant vote among
trusted members; Concord's RGA CRDT has no leader but no adversary and no
scarcity either — every op just merges by construction; Vein's blockchain
has mutually distrusting pseudonymous participants tied together by a
public, expensive-to-fake tie-break (proof of work); Matchbook's exchange
has one central authority (the order book) that every agent trades through.

None of them has modeled **content distribution among cooperating-but-
selfish peers with no central point of truth and no global consensus at
all** — the actual problem BitTorrent solves. A torrent swarm has no leader,
no vote, no chain, no matching engine. Peers don't agree on anything global;
each one only tracks what *it* has, what its neighbors claim to have, and
whether reciprocating with a given neighbor has been worth it lately. The
file assembles correctly not because anyone coordinates it, but because a
piece-hash check makes every fragment independently verifiable, and a
tit-for-tat incentive (upload to get downloaded from) makes cooperation the
locally rational strategy even with zero trust. That's a genuinely
different shape of distributed problem from anything shipped here before.

Swarm implements the real BitTorrent wire protocol (BEP 3) from scratch:
bencode encoding, `.torrent` metainfo files with per-piece SHA-1 hashes, a
minimal HTTP tracker for peer discovery, the actual peer wire handshake and
message set (choke/unchoke/interested/have/bitfield/request/piece/cancel)
over real TCP sockets between independent OS processes, rarest-first piece
selection, and reciprocal tit-for-tat choking with periodic optimistic
unchoking. The flagship demo starts one seeder and several leecher
processes as real independent OS processes (same "real subprocesses talking
only over their real network interface" pattern as Vein's partition demo),
lets them discover each other via a real tracker, and proves the file
reassembles byte-identical **and** that pieces genuinely flow
leecher-to-leecher, not just seed-to-leecher — the one behavior that makes
it a swarm and not just a slow multi-client HTTP download.

## Why it's interesting

- It's a protocol-correctness problem, not a pure-algorithm one: the wire
  format has to interoperate with itself across independent processes with
  no shared code path, closer to Concord's two-tab browser test or Vein's
  multi-process gossip than to a single-process simulator.
- The incentive mechanism (tit-for-tat choking) is a real, measurable,
  adversarially-testable claim: a peer that never uploads should end up
  starved by peers who reciprocate with others instead. That's a concrete,
  falsifiable behavior to build a test around, not just "it doesn't crash."
- Ground truth is cheap and strong: SHA-1 piece hashes make every fragment
  independently self-certifying, so correctness of a fully decentralized,
  no-coordinator system can still be checked byte-for-byte against the
  original file, no oracle needed beyond `hashlib`.

## Architecture

```
swarm/bencode.py       bencode encode/decode (int, bytes, list, dict) — the
                        wire format .torrent files and the tracker protocol
                        both use; round-trips real BitTorrent-produced
                        bencoded structures.
swarm/torrentfile.py    split a file into fixed-size pieces, SHA-1 each
                        piece, build + bencode the metainfo dict, compute
                        the info_hash (SHA-1 of the bencoded info dict —
                        the swarm's real, protocol-defined identity).
swarm/protocol.py       BEP-3 wire messages: 68-byte handshake, length-
                        prefixed keep-alive/choke/unchoke/interested/
                        not-interested/have/bitfield/request/piece/cancel.
                        Pure encode/decode, no I/O — independently testable
                        and independently fuzzable.
swarm/tracker.py        a real HTTP tracker (stdlib http.server): bencoded
                        GET /announce (info_hash, peer_id, port -> compact
                        peer list) and GET /scrape (swarm stats), an
                        in-memory peer table with announce-interval expiry.
swarm/piecemanager.py   per-piece state machine (missing/requested/have),
                        block-level (16 KiB) request pipelining within a
                        piece, rarest-first next-piece selection from
                        peers' advertised bitfields, on-disk piece assembly
                        with SHA-1 verification before a piece counts as
                        "have" (a corrupt/mismatched piece is discarded and
                        re-requested, never trusted).
swarm/choking.py         tit-for-tat: peers ranked by recent download rate
                        from them, top-K reciprocally unchoked, plus one
                        rotating optimistic unchoke so new/unproven peers
                        can ever get a first chance; recomputed on a timer.
swarm/node.py           a Node = TCP listen socket (accepts incoming peer
                        connections) + outbound connections to peers learned
                        from the tracker + the piece manager + the choking
                        policy, wired together over blocking sockets with a
                        thread per connection (matches this repo's existing
                        real-socket style from Vein/Concord, not a from-
                        scratch async reactor — the wire protocol and swarm
                        behavior are the point, not a bespoke event loop).
swarm/dashboard.py       a live SSE-driven swarm-state feed + a single
                        self-contained HTML/JS page (no build step) that
                        renders, per peer, a piece-grid heatmap, choke
                        state, and live transfer rate — the same
                        server-computes/browser-only-renders pattern as
                        Matchbook/Concord's visualizers.
swarm/cli.py             `swarm` CLI: make-torrent / tracker / seed / leech
                        / swarm-demo / demo.
```

## Feature list

**Required (core, 4):**
1. **Bencode + `.torrent` metainfo** — from-scratch bencode codec and
   torrent-file builder: piece splitting, per-piece SHA-1, protocol-correct
   info_hash derivation, verified by round-tripping real BitTorrent-shaped
   bencoded fixtures (not just our own output).
2. **Real peer wire protocol over TCP** — the actual BEP-3 handshake and
   message set between independent OS processes: two peers that have never
   shared code state establish a connection, exchange bitfields, and
   transfer verified pieces.
3. **Piece manager with rarest-first selection + block pipelining** — a
   peer prioritizes the piece that the fewest known peers have (the actual
   algorithm that keeps a swarm healthy instead of everyone hammering one
   popular piece), requests it in 16 KiB blocks, and only marks it "have"
   after an independent SHA-1 check passes.
4. **Multi-peer swarm convergence with real peer-to-peer transfer** — one
   seeder + several leecher **processes** (not threads in one process),
   discovering each other through a real HTTP tracker, converge to a
   byte-identical file; proven not just to work but to genuinely be a
   *swarm* by showing pieces flowing leecher→leecher (a leecher completes
   pieces the seed was never asked for, sourced from another leecher).

**Stretch (2+):**
5. **Tit-for-tat reciprocal choking** — peers rank connections by recent
   download-from-them rate, reciprocally unchoke the best few, and rotate
   one optimistic unchoke slot; demonstrated adversarially — a
   never-uploads "leech-only" peer measurably gets worse service than a
   peer that reciprocates.
6. **Live swarm dashboard** — an SSE-fed, dependency-free HTML page
   visualizing real swarm state as the demo runs: a piece-grid heatmap per
   peer, live transfer rates, and choke/unchoke edges, screenshot-verified
   in headless Chromium with zero console errors.

## Non-goals / scope

No DHT, no magnet links, no encryption/extension protocol, no UDP tracker,
no multi-file torrents. The goal is a correct, real implementation of the
core BEP-3 mechanics end to end, not full protocol-suite coverage.
