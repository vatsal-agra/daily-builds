# Swarm

**Status: Phase 4 — stretch features + polish complete.**

A from-scratch BitTorrent-style peer-to-peer file-sharing system: bencode
codec, `.torrent` metainfo files, a real HTTP tracker, the actual BEP-3 peer
wire protocol over TCP between independent processes, rarest-first piece
selection, tit-for-tat reciprocal choking, and a live SSE dashboard.

See [PLAN.md](./PLAN.md) for the full concept, architecture, and feature
list.

## What works right now

All 4 required features, plus both planned stretch features, implemented
and demonstrated end-to-end:

1. **Bencode + `.torrent` metainfo** (`swarm/bencode.py`, `swarm/torrentfile.py`)
2. **Real peer wire protocol over TCP** (`swarm/protocol.py`, `swarm/peer.py`)
3. **Rarest-first piece manager with block pipelining** (`swarm/piecemanager.py`)
4. **Multi-peer swarm convergence with real peer-to-peer transfer**
   (`swarm/node.py`, `swarm/tracker.py`, `swarm/demo.py`)
5. **Tit-for-tat reciprocal choking** (`swarm/choking.py`) — Node's real
   default choke policy now, not just a naive "unchoke everyone"
6. **Live swarm dashboard** (`swarm/dashboard.py`, `swarm/dashboard.html`) —
   an SSE hub any `seed`/`leech` process can report its real events to

## Try it

```
python3 -m swarm.cli demo
```

Runs the full flagship demo: a real HTTP tracker, a live dashboard hub, a
seeder + 3 leechers converging on a file (Scenario A), and two peers each
holding a disjoint half of a *different* file with **no seed present at
all** (Scenario B), proving they can only complete by talking to each
other over the real wire protocol. The demo prints the dashboard URL up
front — open it in a browser while the demo runs to watch the real,
multi-process swarm converge live (piece-grid heatmap per peer, transfer
log, choke state).

Manual usage:

```
python3 -m swarm.cli dashboard --port 8642                          # optional, in a terminal
python3 -m swarm.cli tracker --port 6969                            # in another
python3 -m swarm.cli make-torrent myfile.bin --announce http://127.0.0.1:6969/announce
python3 -m swarm.cli seed myfile.bin.torrent myfile.bin --dashboard http://127.0.0.1:8642
python3 -m swarm.cli leech myfile.bin.torrent --out copy.bin --dashboard http://127.0.0.1:8642
```

Run the unit tests: `python3 -m unittest discover -s tests`

Run the dashboard's headless-browser smoke test:
`NODE_PATH=/opt/node22/lib/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node tests/dashboard_browser_test.cjs`

## Adversarial review

Phase 3 attacked Swarm's own work as a hostile reviewer -- a malicious
peer, a hand-crafted `.torrent`, bad CLI input -- and found and fixed 8
real issues. Phase 4, while wiring in the stretch features, turned up a
9th and 10th: a critical bookkeeping bug where a completed piece could get
silently un-counted if its supplying peer later disconnected (found by
re-running the demo repeatedly and noticing `have` counts didn't always
match reality), and an import-time `NameError` that `py_compile` couldn't
have caught. Full writeup: [REVIEW.md](./REVIEW.md).

111/111 unit tests green; `python3 -m swarm.cli demo` passes both
scenarios consistently across repeated runs, now reliably reporting
`13/13` pieces on both sides of Scenario B every time.

Remaining work: a full verification pass (Phase 5) and final ship-ready
polish (Phase 6).
