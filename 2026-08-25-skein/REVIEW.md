# Adversarial Review

Attacking Skein's own code as a hostile reviewer: malformed input, edge
cases in file sizes, misuse of the CLI, and a peer sending deliberately
bogus wire-protocol messages. Every finding below was reproduced first,
then fixed, then reproduced again to confirm the fix actually holds.

## Findings

### 1. A malicious/buggy peer can crash a connection thread with an unhandled traceback (CRITICAL)

**Repro:** connect directly to a running leecher's listen port, complete
a normal handshake, then send a `HAVE` message with piece index `9999`
against a torrent that only has a handful of pieces. Also reproduced
with a `HAVE` message whose payload is truncated to 2 bytes instead of 4.

```
IndexError: list index out of range   (piecemanager.py: note_peer_have)
struct.error: unpack requires a buffer of 4 bytes   (wire.py: unpack_have)
```

Both crash the per-connection thread with a raw, unhandled traceback
printed to stderr. The connection *does* get torn down (the `finally`
in `_run_connection` still runs), so the node itself survives and other
peers are unaffected — but this is exactly the kind of input a hostile
or simply buggy peer sends, and a real BitTorrent client is expected to
treat a malformed message as "drop this peer," not "let an exception
propagate out of a message handler." The same class of bug also exists
for `REQUEST` (`_handle_request` calls `pm.has_piece(index)`, which
indexes `self._have[index]` with no bounds check) and for any message
whose payload is the wrong length for its `struct.unpack` call.

**Root cause:** wire-level parsing (`unpack_have`/`unpack_request`/
`unpack_piece`) and piece-index bounds checking were never treated as
"untrusted input from the network" — they assumed a well-behaved peer.

**Fix:** `Node._handle_message` now wraps its whole dispatch in a single
`try/except (struct.error, IndexError, ValueError)` and treats any of
those as a protocol violation: log a `protocol_violation` event and
raise `wire.WireError`, which the existing per-connection loop already
catches and turns into a clean, silent teardown — no unhandled
traceback, no thread death by exception. `PieceManager.has_piece`,
`note_peer_have`, and `note_peer_bitfield` also gained explicit
bounds-checks (raising `PieceError`, folded into the same catch) so the
hardening lives at the layer that actually knows what a valid index is,
not just at the call site that happened to trigger the first crash.

### 2. Every CLI subcommand crashes with a raw Python traceback on ordinary, expected user error

**Repro:**
- `skein create-torrent missing-file.bin --tracker ...` → `TorrentError`
  traceback (should be: "not a regular file", exit 1, no traceback)
- `skein create-torrent empty-file.bin --tracker ...` → `TorrentError` traceback
- `skein create-torrent file.bin --tracker ... --piece-length 0` → `TorrentError` traceback
- `skein seed nonexistent.torrent data.bin` → `FileNotFoundError` traceback
- `skein seed corrupt.torrent data.bin` (not valid bencode) → `TorrentError` traceback
- `skein viz malformed.json` → `json.JSONDecodeError` traceback
- `skein tracker --port 18080` when something is already listening
  there → raw `OSError: [Errno 98] Address already in use` traceback

None of these are bugs in the underlying logic — every one of them is
already raising the *right* exception with a *clear* message. The bug
is that `cli.py` never catches anything, so every expected, anticipated
error condition (bad path, bad torrent, bad JSON, busy port) surfaces
as 15 lines of stack trace instead of a one-line, script-friendly error
message on stderr with exit code 1 — exactly the "raw
AssertionError/KeyError instead of a clean error" pattern flagged
repeatedly in this repo's own history (Kiln, Silicon).

**Fix:** `main()` now wraps `args.func(args)` in a `try/except` over the
specific exception types every subcommand can legitimately raise
(`TorrentError`, `bencode.BencodeError`, `OSError`, `json.JSONDecodeError`)
and prints `error: <message>` to stderr with exit code 1. Verified all
seven repro cases above now fail cleanly with no traceback.

### 3. `skein swarm --leechers 0` (or a negative count) silently "succeeds"

**Repro:** `skein swarm file.bin --leechers 0` starts a tracker and a
seeder, does *nothing else* (the leecher loop never executes), and then
prints `RESULT: OK — every leecher reconstructed the file byte-for-byte`
— a textbook vacuous truth (`all_ok` stays `True` over an empty loop). A
negative count (`--leechers -1`) does the same, since `range(-1)` is
also empty. This is exactly the kind of thing a script driving this CLI
in a loop would silently trust.

**Fix:** `cmd_swarm` now validates `args.leechers >= 1` up front and
fails with a clear stderr message and exit code 1 instead of reaching
the success-reporting code path at all.

## Non-findings (checked, not bugs)

- **6 leechers against a 4-slot + 1-optimistic choke manager**: verified
  all 6 still complete (no starvation) — optimistic unchoke rotation is
  doing its job.
- **Odd file sizes** (1 byte, exactly one piece, a prime byte count):
  all transfer correctly and verify byte-for-byte.
- **Unreachable tracker**: `leech` times out cleanly with exit code 1
  and no traceback — the announce loop's existing broad
  `except Exception` around the HTTP call already handled this.
- **Concurrent block delivery to the same piece from different peers**:
  `PieceManager.receive_block` holds `self._lock` for the entire
  verify-and-write, so this is already fully serialized — no race.

## Not a Skein bug

While probing with `pkill -f "skein.cli"` to clean up stray test
processes between manual repros, the pattern matched the *shell
command's own argv* (it literally contains the substring `skein.cli`)
and killed the shell running the review itself. Worth noting only
because it looked, for a moment, like a Skein-induced crash — it
wasn't; it's a classic `pkill -f` self-match footgun, unrelated to any
code in this project.
