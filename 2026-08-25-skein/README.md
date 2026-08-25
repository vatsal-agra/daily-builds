# Skein

*Status: Phase 5 (verification) complete — `demo.sh` exercises every
required, stretch, and extra feature end-to-end against real
multi-process runs and passes 12/12 checks, on top of the 97-test
suite. Shipped.*

A from-scratch peer-to-peer file distribution system — real bencode, a
real HTTP tracker, and the real BitTorrent peer wire protocol over TCP
sockets — implemented in pure Python 3 stdlib, no third-party
networking or torrent libraries. See [`PLAN.md`](PLAN.md) for the full
concept and architecture, and [`REVIEW.md`](REVIEW.md) for the
adversarial-review findings and fixes.

## Quick start

```bash
cd 2026-08-25-skein

# The all-in-one demo: spins up a real tracker, a seeder, and 4
# leechers as SEPARATE OS PROCESSES, transfers a file purely over
# TCP peer connections, and verifies every leecher's output is
# byte-identical to the source.
python3 -m skein.cli swarm /path/to/some/file --leechers 4

# Render an interactive HTML replay of that run from its real event log:
python3 -m skein.cli viz ./skein-swarm-run/events.json
```

Or drive it by hand:

```bash
python3 -m skein.cli create-torrent myfile.bin --tracker http://127.0.0.1:8000 -o myfile.torrent
python3 -m skein.cli tracker --port 8000 &
python3 -m skein.cli seed myfile.torrent myfile.bin &
python3 -m skein.cli leech myfile.torrent downloaded.bin
```

A leecher killed mid-download (Ctrl+C / SIGTERM) and re-run with the
same `dest_file` automatically resumes instead of starting over:

```bash
python3 -m skein.cli leech myfile.torrent downloaded.bin   # ^C partway through
python3 -m skein.cli leech myfile.torrent downloaded.bin   # picks up where it left off
```

## Running the tests

```bash
python3 -m unittest discover -s tests -v
./demo.sh
```

`demo.sh` is the full end-to-end verification: it runs the test suite,
then separately exercises every required/stretch/extra feature against
real processes (standalone tracker+seed+leech, a 5-process swarm demo,
the visualizer under headless Chromium, a real kill-and-restart resume,
and spot-checks of the adversarial-review fixes) and reports a
PASS/FAIL checklist — currently 12/12 green.

97 unit/integration tests: bencode (BEP 3 worked examples + fuzz round-trips + malformed
input rejection), torrent creation/parsing, the real HTTP tracker, the
wire protocol over real sockets, piece manager bookkeeping/rarest-first,
tit-for-tat choking, resume-from-partial-file (including a real
kill-and-restart of a real leecher process), a full in-process
multi-leecher swarm integration test, and regression tests for every
bug in `REVIEW.md`.

## Feature list

**Required — all working end-to-end, verified with real multi-process runs:**
1. Bencode codec (BEP 3 exact, incl. sorted-key dict encoding)
2. Torrent creation & parsing (SHA-1 piece hashing, real info-hash)
3. HTTP tracker (`/announce` compact peer lists, `/scrape`, peer expiry)
4. Real peer wire protocol swarm transfer (handshake + framed messages
   over TCP, seed + N leecher OS processes, per-piece SHA-1 verification)

**Stretch:**
5. Rarest-first piece selection + tit-for-tat choking with optimistic unchoke
6. Interactive HTML swarm visualizer replaying a real captured event log
   (piece-availability heatmap, download-rate chart, live event feed —
   verified with zero console errors in headless Chromium, including on
   degenerate/empty event logs)
7. Resume support — kill a leecher mid-download, restart it against the
   same file, and it hash-verifies what's already there and continues

## Why P2P file distribution, today

Every prior project in this repo that resembles "protocol engineering"
is a compiler/VM, a solver, a renderer, or a single-machine data
structure — never real multi-process networking. Skein is the first
build here where correctness can only be proven by actually running
independent OS processes that only ever talk to each other over TCP
sockets and a real HTTP tracker, then diffing the reassembled bytes.

## Where a human could take this next

- Multi-file torrents (the real BEP 3 `files` list instead of single-file only)
- DHT-based trackerless peer discovery (Kademlia) instead of a central tracker
- Endgame mode (parallel-request the last few blocks from multiple peers)
- Magnet-link style metadata exchange (BEP 9/10) instead of requiring a `.torrent` file up front
- A real terminal UI (curses) instead of the current line-based status output
