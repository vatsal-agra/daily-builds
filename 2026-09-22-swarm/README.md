# Swarm

A from-scratch BitTorrent-style peer-to-peer file-sharing system: real
bencode encoding, real `.torrent` metainfo files, a real HTTP tracker, and
the actual BEP-3 peer wire protocol (handshake, choke/unchoke, bitfield,
have, request, piece) running over real TCP sockets between independent OS
processes — no shared code path, no cheating. Rarest-first piece selection,
tit-for-tat reciprocal choking, and a live browser dashboard round it out.

The flagship demo proves it's a genuine *swarm*, not just a fancy
downloader: two peers, each holding a disjoint half of a file with **no
full copy of that file anywhere else in the demo**, discover each other
through a real tracker and reconstruct it byte-for-byte purely by talking
to each other.

## Why this, today

Every prior "distributed systems" build in this repo picked a *coordinated*
model — Quorum's Raft has a leader and a crash-fault-tolerant vote; Vein's
blockchain ties mutually-distrusting peers together with an expensive
public tie-break (proof of work); Concord's CRDT has no leader but also no
adversary and no scarcity; Matchbook's exchange routes every trade through
one central order book. None of them modeled **content distribution among
cooperating-but-selfish peers with no central point of truth and no global
consensus at all** — the actual problem BitTorrent solves. A torrent swarm
has no leader, no vote, no chain, no matching engine. Peers don't agree on
anything global; each one only tracks what *it* has, what its neighbors
claim to have, and whether reciprocating with a given neighbor has been
worth it lately. The file assembles correctly not because anyone
coordinates it, but because a SHA-1 hash makes every fragment independently
verifiable, and tit-for-tat makes cooperation the locally rational strategy
even with zero trust between peers. That's a genuinely different shape of
distributed problem, and a real, still-widely-used protocol worth
implementing faithfully rather than a toy approximation of one.

## How to run it

```bash
python3 -m swarm.cli demo
```

Starts a real HTTP tracker and a live dashboard, then runs two scenarios:

- **Scenario A** — one seeder + three leechers, discovering each other only
  through the tracker, all converging on a 300 KB file.
- **Scenario B** — two peers, each holding a disjoint half of a *different*
  208 KB file and nothing else. No seed runs in this scenario at all. The
  only way either one can reach 100% is by getting what it's missing from
  the other, over the real wire protocol — a structural guarantee, not a
  probabilistic hope, since there's no third copy anywhere for either of
  them to have pulled from instead.

The demo prints the dashboard URL up front — open it in a browser while
the demo runs to watch the real swarm converge live (a piece-grid heatmap
per peer, a scrolling event log, choke state), or just let it run
headless; the demo's own pass/fail doesn't depend on anyone watching.

Manual usage, as separate long-running processes (what `swarm seed` /
`swarm leech` actually are — one per OS process, like a real client):

```bash
python3 -m swarm.cli dashboard --port 8642                          # optional
python3 -m swarm.cli tracker --port 6969
python3 -m swarm.cli make-torrent myfile.bin --announce http://127.0.0.1:6969/announce
python3 -m swarm.cli seed myfile.bin.torrent myfile.bin --dashboard http://127.0.0.1:8642
python3 -m swarm.cli leech myfile.bin.torrent --out copy.bin --dashboard http://127.0.0.1:8642
```

Run everything at once — the 111-test unit suite, the flagship demo, a
manual `make-torrent`/`tracker`/`seed`/`leech` walkthrough as independent
processes, CLI error-handling checks, and a headless-Chromium pass over the
dashboard: `bash demo.sh`

## Feature list

**Required (all 4 shipped):**
1. **Bencode + `.torrent` metainfo** — a from-scratch bencode codec
   (int/bytes/list/dict, strict decoding that rejects leading zeros,
   negative zero, out-of-order dict keys, and truncated input) and a
   torrent-file builder that splits a file into SHA-1-hashed pieces and
   derives the protocol-correct `info_hash`.
2. **Real peer wire protocol over TCP** — the actual 68-byte BEP-3
   handshake and full message set (choke/unchoke/interested/not-interested/
   have/bitfield/request/piece/cancel) between independent OS processes
   that share no in-memory state.
3. **Rarest-first piece manager with block pipelining** — a peer requests
   whichever piece the fewest known peers have, in 16 KiB blocks, and only
   marks a piece "have" after an independent SHA-1 check passes; a
   mismatch discards it and reassigns it rather than trusting the sender.
4. **Multi-peer swarm convergence with real peer-to-peer transfer** — a
   seeder and several leechers, discovering each other only through a real
   HTTP tracker, converge to a byte-identical file; proven to be a genuine
   swarm (not just parallel downloads from one seed) via Scenario B's
   no-seed-present topology.

**Stretch (both shipped):**
5. **Tit-for-tat reciprocal choking** (`swarm/choking.py`) — peers rank
   connections by recent download rate *from* them, reciprocally unchoke
   the best few, and rotate one optimistic slot so a brand-new peer with no
   track record can still get a first chance. This is Node's real default
   choking policy now, not a toggle — every demo run above uses it.
   Demonstrated adversarially: a peer that never reciprocates measurably
   stays choked while one that does gets served, over a real socket
   connection with a hand-rolled fake-peer wire client, not just the pure
   ranking function in isolation.
6. **Live swarm dashboard** (`swarm/dashboard.py`, `swarm/dashboard.html`)
   — any `seed`/`leech` process can fire-and-forget report its real events
   to an SSE hub, which re-broadcasts them to any browser watching. It
   plays no role in the swarm itself (peers never need it running); it's
   there purely so a human — or a headless-browser test — can watch a
   real, decentralized, multi-process swarm converge live. Screenshot-
   verified at a 390px mobile viewport with zero horizontal overflow and
   zero console errors.

## Adversarial review

10 real issues found and fixed across Phases 3–4 — full writeup in
[REVIEW.md](./REVIEW.md). Two stand out:

- A **cross-thread socket-close race**: a leecher that finished downloading
  used to tear down every connection immediately, which could race another
  peer still mid-transfer *from* it and disconnect them before they got
  their last piece. Fixed by having `close()` call `shutdown()` (safe from
  another thread) before `close()`, and by having a just-completed peer
  keep seeding for a short grace period instead of vanishing — the same
  transition a real BitTorrent client makes.
- A **piece-bookkeeping bug**: a piece that finished downloading and passed
  its SHA-1 check could get silently un-counted later if the peer that
  supplied it disconnected, because the "who's this piece downloading
  from" pointer was never cleared on success and a cleanup path reset it
  unconditionally. The on-disk data was always correct — `verify_full_file()`
  never lied — but a node's own `have_count()`/`is_complete()` could. Found
  by re-running the peer-to-peer demo repeatedly and noticing the reported
  counts didn't always add up, not by reading the code.

## Verification

`demo.sh` runs the whole thing end to end and exits non-zero on the first
failure: the 111-test unit suite, the flagship multi-process demo (both
scenarios), a from-scratch manual walkthrough (`make-torrent` → `tracker`
→ `seed` → `leech`, each a genuinely separate OS process, verified
byte-for-byte against the original file), a CLI error-handling check (bad
input produces a clean `error: ...`, never a raw traceback), and a
headless-Chromium pass over the live dashboard. Green on repeated runs.

## Architecture

```
swarm/bencode.py       bencode encode/decode -- the wire format .torrent
                        files and the tracker protocol both use
swarm/torrentfile.py   piece splitting, SHA-1 hashing, info_hash derivation
swarm/protocol.py      BEP-3 wire messages: handshake + the 9 message types
swarm/tracker.py       real HTTP tracker (/announce, /scrape), compact and
                        non-compact peer lists
swarm/piecemanager.py  per-piece state machine, rarest-first selection,
                        block pipelining, on-disk assembly + verification
swarm/choking.py       tit-for-tat: compute_unchoke_set() (pure, tested in
                        isolation) + TitForTatChokePolicy (the stateful
                        wrapper a running Node actually uses)
swarm/peer.py          one peer wire connection: handshake already done,
                        runs the real message loop
swarm/node.py          ties it together: listen socket, outbound
                        connections, piece manager, choke loop, tracker loop
swarm/dashboard.py     SSE hub; swarm/dashboard.html the page it serves
swarm/cli.py           make-torrent / tracker / dashboard / seed / leech / demo
swarm/demo.py          the flagship two-scenario end-to-end demo
```

## Where a human could take this next

- **A real DHT** (Kademlia) for trackerless peer discovery — the biggest
  scope cut from PLAN.md's non-goals. Would let peers find each other with
  no tracker at all, the way modern BitTorrent actually mostly works.
- **Multi-file torrents** and the real BEP-3 `files` list in the info dict,
  instead of this build's single-file-only metainfo.
- **The extension protocol (BEP 10)** and peer exchange (PEX), so peers
  can learn about other peers from each other, not just the tracker.
- **Endgame mode** — request the last few pieces from multiple peers at
  once near completion, the real optimization for avoiding a slow final
  peer stalling the whole download.
- **Piece-level multi-source downloading** — this build assigns a whole
  piece to one peer connection at a time (a deliberate, documented
  simplification in `piecemanager.py`); real clients interleave blocks of
  the same piece across multiple peers for better throughput on flaky
  connections.
- **Persistence across restarts** — resume state (`.torrent` + partial
  bitfield) is fully in-memory today; a `.resume` file would let `swarm
  leech` pick back up after being killed mid-download instead of starting
  over.
