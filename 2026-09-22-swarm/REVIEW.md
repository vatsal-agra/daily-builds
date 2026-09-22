# Adversarial review

Attacking Swarm's own work as a hostile reviewer: a malicious/buggy peer, a
hand-crafted `.torrent`, and plain bad CLI input, hunting for crashes,
silent data corruption, resource abuse, and lazy shortcuts.

## Found before this phase, while getting the core demo reliable

**CRITICAL — a just-completed leecher could strand a peer still downloading
from it, via an unsafe cross-thread socket close.** `cmd_leech` called
`node.stop()` the instant `wait_until_complete()` returned, which closes
every peer socket from the CLI's own thread while that connection's
*own* read-loop thread might still be blocked inside a blocking `recv()`
on the very same file descriptor. Closing a socket from one thread while
another thread has an in-flight blocking read on it is a classic race: the
freed file descriptor number can be reused by something unrelated
elsewhere in the process before the blocked `recv()` call returns,
surfacing as a spurious `[Errno 9] Bad file descriptor` on one side and
`[Errno 104] Connection reset by peer` on the other. Caught by running
Scenario B (two peers, each holding a disjoint half of a file, no seed)
repeatedly: roughly 1 run in 3 had one peer stall at exactly its preseeded
piece count, never receiving anything from the other side, because that
side had already torn itself down mid-transfer the moment *it* finished.
Fixed two ways, together: `PeerConnection.close()` now calls
`sock.shutdown(SHUT_RDWR)` — which *is* safe to call from another thread and
reliably unblocks a concurrent `recv()` with a clean EOF — before
`sock.close()`; and `swarm leech` now stays up for a short grace period
(`--seed-time`, default 3s) after completing and keeps serving existing
connections instead of disconnecting everyone the instant its own download
is done, matching how a real BitTorrent client transitions to seeding
rather than vanishing. Verified with a dedicated two-process repro script
run 8 times consecutively post-fix (0 failures, was ~33% failure pre-fix)
and confirmed further by 5 consecutive full `swarm demo` runs.

## Found in this phase

1. **CRITICAL (would have shipped) — `peer.py` had a `NameError` at import
   time.** `PeerConnection.MAX_SERVED_BLOCK = 4 * BLOCK_SIZE` was added
   referencing a name never imported into `peer.py` (`BLOCK_SIZE` lives in
   `piecemanager.py`). `python3 -m py_compile` passed cleanly — compiling
   to bytecode doesn't execute a class body, so it can't catch a NameError
   that only fires when the module is actually imported and the class
   statement runs. Caught immediately by the next `swarm demo` run (import
   failure, not a subtle bug), which is exactly why "it compiles" was never
   treated as a substitute for "it runs" anywhere in this build. Fixed by
   importing `BLOCK_SIZE` from `piecemanager`.

2. **No upper bound on a peer's requested block length.**
   `read_block_for_upload` computed `begin + length > size` to bounds-check
   a request, but a negative `length` passes that check (a smaller number
   is never `>` a positive size) and Python's `file.read(n)` treats a
   negative `n` as "read to EOF" — a single malformed `request` message
   with `length=-1` would have made this node hand back the *entire rest
   of the file* instead of one block, a real amplification/DoS footgun.
   Fixed with an explicit `length < 0` rejection plus a separate sane
   upper cap (`MAX_SERVED_BLOCK`, 4× our own block size) enforced before
   even touching the piece manager, matching how real clients refuse to
   honor absurdly large `request` messages regardless of whether they're
   technically in-bounds.

3. **Out-of-range piece indices from the wire could crash a connection's
   read thread with an unhandled exception instead of a clean disconnect.**
   `receive_block`/`read_block_for_upload` indexed `self._state[piece_index]`
   directly; Python lists don't raise on a *negative* out-of-range index
   (`[-1]` silently wraps to the last element) and raise a raw `IndexError`
   — not anything `_run()`'s except clause was catching — for an
   overflowing positive one. A peer sending a `piece`/`request` message
   with `index=-1` or `index=999999999` would have either silently touched
   the wrong piece's bookkeeping or killed the connection thread with an
   unhandled-exception traceback on stderr rather than a logged, graceful
   drop. Fixed with explicit `0 <= piece_index < num_pieces` checks at the
   top of both methods (raising `ValueError`, not relying on whatever
   Python's default indexing behavior happens to do) and a `ValueError`
   handler in `PeerConnection._run()` alongside the existing
   connection/protocol-error handling.

4. **A single corrupt peer could make a piece un-gettable forever, not just
   slow.** After a piece failed its SHA-1 check, its state reset to
   `MISSING` and the *same* connection immediately tried again via
   `_fill_pipeline()` — with only one peer offering that piece (exactly
   Scenario B's topology, and generally true near the end of any download
   once a piece gets rare), this is an infinite retry loop against a peer
   that will never produce a valid copy, not a transient failure. Fixed by
   tracking consecutive hash failures per connection and disconnecting the
   peer after 3, so a bad actor gets dropped (freeing that piece to be
   requested from whoever connects next) instead of thrashed against
   forever. Verified with a test that runs a real fake "peer" over a real
   socket that always answers requests with all-zero (hash-mismatching)
   blocks, asserting the node drops the connection rather than retrying
   indefinitely.

5. **A hand-crafted `.torrent` with an internally inconsistent `length` vs.
   `piece_length`/piece count would crash deep inside the piece manager
   with a confusing error** (a negative last-piece size flowing into
   `bytearray(negative)` inside `choose_piece_for_peer`, several call
   frames away from the actual bad input) **instead of being rejected at
   parse time with a clear message.** Fixed by adding validation directly
   to `TorrentInfo.__post_init__` (piece_length > 0, length > 0, pieces a
   multiple of 20 bytes, and the derived last-piece size consistent with
   `length`), so both `create_torrent`'s own output and any externally
   loaded `.torrent` go through the same check at construction time,
   before anything downstream ever sees it.

6. **CLI commands raised raw Python tracebacks on ordinary bad input**
   (missing file, empty file, malformed `.torrent`) instead of a clean,
   scriptable error. Fixed by wrapping `main()`'s dispatch in a single
   `except (OSError, ValueError, RuntimeError)` that prints `error: ...` to
   stderr and returns exit code 1, verified with CLI-level tests that
   assert `"Traceback"` never appears in stderr for missing files, empty
   files, and corrupt `.torrent` files.

7. **Tracker accepted an out-of-range `port` in `/announce`,** which would
   only fail much later — and for a completely different peer — inside
   `_pack_compact_peers`' `struct.pack(">H", port)` when *someone else's*
   announce tried to include the bad entry in a compact peer list. Fixed by
   validating `0 < port <= 65535` (and `left >= 0`) at the point of
   announce, returning a clean bencoded 400 instead of corrupting a later,
   unrelated request.

8. **`PieceManager(seed=True, preseed_pieces=...)` was accepted silently**
   even though a full seed already has every piece by definition — a
   caller passing both by mistake would have the `preseed_*` arguments
   quietly ignored with no signal anything was wrong. Fixed by rejecting
   the combination outright.

## Found in Phase 4, wiring in the stretch features

9. **CRITICAL — a completed piece could get silently un-counted when its
   supplying peer later disconnected.** `receive_block()` set a piece's
   state to `HAVE` on success but never cleared `_assigned_peer[piece_index]`
   (whose only real meaning is "who this piece is currently *downloading*
   from"). `remove_peer()` — called whenever any connection closes —
   reset *every* piece still pointing at the departing peer_id back to
   `MISSING`, with no check that the piece hadn't since completed. Caught
   by re-running the Scenario B peer-to-peer demo (now reporting through
   the new dashboard) repeatedly: L1 would finish (`is_complete()` true,
   `verify_full_file()` true, every `piece_source()` correctly populated)
   but then, during the post-completion grace period, its own
   `have_count()` would drop from 13 back down to 6 the moment its one and
   only source peer (L2) disconnected — even though the on-disk bytes were
   always correct the whole time, since `verify_full_file()` re-reads and
   re-hashes from disk independently of this in-memory bookkeeping and
   never flagged a problem. This was purely a bookkeeping bug, not data
   corruption, but a serious one: a node could end up honestly convinced
   it was incomplete (and might re-request or misreport status) despite
   already having everything, and in a case with no other peer left to
   re-supply from, it would have no way to recover the "truth" it had
   already earned. Fixed two ways: `receive_block()` now clears
   `_assigned_peer[piece_index]` the moment a piece leaves `DOWNLOADING`
   (success or hash-failure alike, matching what the hash-failure path
   already did), and `remove_peer()` now only resets a piece that's still
   actually `DOWNLOADING` — the same guard `release_piece()` already had,
   applied consistently. Verified with a regression test that completes
   every piece from one peer, disconnects that peer, and asserts
   `is_complete()`/`have_count()`/`verify_full_file()` all still agree the
   node is done (confirmed to fail without the fix); the demo now reports
   `have=13/13` on every one of 6 consecutive runs, not just most of them.

10. **`peer.py` had a `NameError` at import time** after adding
    `MAX_SERVED_BLOCK = 4 * BLOCK_SIZE` to `PeerConnection` without
    importing `BLOCK_SIZE` from `piecemanager`. `python3 -m py_compile`
    passed (compiling to bytecode never executes a class body, so it can't
    catch a name that's only missing once the class statement actually
    runs at import time); caught immediately by the very next `swarm demo`
    run failing to even start. A reminder that "it compiles" was never
    treated as equivalent to "it runs" anywhere in this build — every fix
    in this document was confirmed against the real demo and/or a targeted
    test, not just a syntax check.

## What held up

- The bencode decoder's strict-sorted-keys rule already rejected duplicate
  dict keys (`d3:aaai1e3:aaai2ee` — a classic ambiguous-parse attack in
  other bencode implementations) as a side effect of enforcing canonical
  key order; confirmed with a dedicated test rather than assumed.
- `_handle_request` already refused to serve while choking the requester
  and already caught `(ValueError, IndexError, OSError)` around the actual
  disk read, so most malformed-request handling only needed the length cap
  above, not a new code path.
- The rarest-first piece manager's block/piece bookkeeping (dedup by
  peer-and-piece assignment, releasing a piece back to `MISSING` on
  disconnect) held up correctly under the hash-failure and out-of-range
  fuzzing above with no additional bugs found.
