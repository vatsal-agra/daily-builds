# Swarm

**Status: Phase 2 — core build complete.**

A from-scratch BitTorrent-style peer-to-peer file-sharing system: bencode
codec, `.torrent` metainfo files, a real HTTP tracker, the actual BEP-3 peer
wire protocol over TCP between independent processes, rarest-first piece
selection, and (coming in Phase 4) tit-for-tat reciprocal choking.

See [PLAN.md](./PLAN.md) for the full concept, architecture, and feature
list.

## What works right now

All 4 required features are implemented and demonstrated end-to-end:

1. **Bencode + `.torrent` metainfo** (`swarm/bencode.py`, `swarm/torrentfile.py`)
2. **Real peer wire protocol over TCP** (`swarm/protocol.py`, `swarm/peer.py`)
3. **Rarest-first piece manager with block pipelining** (`swarm/piecemanager.py`)
4. **Multi-peer swarm convergence with real peer-to-peer transfer**
   (`swarm/node.py`, `swarm/tracker.py`, `swarm/demo.py`)

## Try it

```
python3 -m swarm.cli demo
```

Runs the full flagship demo: a real HTTP tracker, a seeder + 3 leechers
converging on a file (Scenario A), and two peers each holding a disjoint
half of a *different* file with **no seed present at all**, proving they
can only complete by talking to each other over the real wire protocol
(Scenario B).

Manual usage:

```
python3 -m swarm.cli make-torrent myfile.bin --announce http://127.0.0.1:6969/announce
python3 -m swarm.cli tracker --port 6969                 # in one terminal
python3 -m swarm.cli seed myfile.bin.torrent myfile.bin   # in another
python3 -m swarm.cli leech myfile.bin.torrent --out copy.bin
```

Run the unit tests: `python3 -m unittest discover -s tests`

## Notes found during development

`Node.stop()` used to be called the instant a leecher finished downloading.
On localhost that occasionally raced another peer that was mid-transfer
*from* that node, disconnecting them before they got their last piece
(surfacing as an ECONNRESET/EBADF race between the closing thread and the
peer's blocked `recv()`). Fixed two ways: `PeerConnection.close()` now
calls `shutdown()` before `close()` so a concurrent close is safe, and
`swarm leech` stays up for a short grace period after completing (matching
how a real client keeps seeding after its own download finishes) instead
of tearing the swarm down out from under anyone still relying on it.

Remaining work: adversarial review (Phase 3), tit-for-tat choking + a live
dashboard (Phase 4, stretch), full verification pass (Phase 5), final
polish and this README (Phase 6).
