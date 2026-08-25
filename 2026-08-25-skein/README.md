# Skein

*Status: Phase 3 (adversarial review) complete — 3 real bugs found and
fixed (see [`REVIEW.md`](REVIEW.md)), including a security-relevant one:
a malicious/buggy peer could crash a connection thread with an
unhandled traceback via an out-of-range or malformed wire message.
Stretch features + final polish still to come.*

A from-scratch peer-to-peer file distribution system — real bencode, a
real HTTP tracker, and the real BitTorrent peer wire protocol over TCP
sockets — implemented in pure Python 3 stdlib, no third-party
networking or torrent libraries. See [`PLAN.md`](PLAN.md) for the full
concept, architecture, and feature list.

## Quick start

```bash
cd 2026-08-25-skein

# The all-in-one demo: spins up a real tracker, a seeder, and 3
# leechers as SEPARATE OS PROCESSES, transfers a file purely over
# TCP peer connections, and verifies every leecher's output is
# byte-identical to the source.
python3 -m skein.cli swarm /path/to/some/file --leechers 3

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

## Running the tests

```bash
python3 -m unittest discover -s tests -v
```

93 tests: bencode (BEP 3 worked examples + fuzz round-trips + malformed
input rejection), torrent creation/parsing, the real HTTP tracker, the
wire protocol over real sockets, piece manager bookkeeping/rarest-first,
tit-for-tat choking, a full in-process multi-leecher swarm integration
test, and regression tests for every bug in `REVIEW.md`.

## Feature list (see PLAN.md for full detail)

**Required — all working end-to-end:**
1. Bencode codec (BEP 3 exact, incl. sorted-key dict encoding)
2. Torrent creation & parsing (SHA-1 piece hashing, real info-hash)
3. HTTP tracker (`/announce` compact peer lists, `/scrape`, peer expiry)
4. Real peer wire protocol swarm transfer (handshake + framed messages
   over TCP, seed + 3 leecher OS processes, per-piece SHA-1 verification)

**Stretch:**
5. Rarest-first piece selection + tit-for-tat choking with optimistic unchoke
6. Interactive HTML swarm visualizer replaying a real captured event log

Phase 3 (adversarial review) and Phase 4 (stretch + polish) are next.
