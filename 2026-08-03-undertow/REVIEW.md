# Adversarial review — Undertow

Ran as a hostile reviewer against my own Phase 2 build: tried to break the
handshake, the loss-recovery path, the congestion controller, and the
teardown state machine, both by reading the code for races/edge cases and by
actually running adversarial scenarios (concurrent close(), forged packets,
exhausted retransmits, back-to-back tests sharing a process) rather than
just eyeballing it. Every issue below was independently reproduced with a
failing test before being fixed, and each fix has a regression test.

## Issues found and fixed

### 1. Data silently dropped when it piggybacks on the final handshake ACK
**Found in Phase 2, before the first commit.** In `SYN_RCVD`, a segment that
both completes the handshake (`ACK`, no `SYN`) *and* carries the first
payload bytes was handled by transitioning to `ESTABLISHED` and then
`return`ing immediately — never falling through to process that segment's
payload. This is a completely normal, common case (the client sends its
final handshake ACK and its first data segment back-to-back; nothing
prevents them from arriving in a way where a piggybacked segment does both
jobs at once), and it silently ate the first chunk of every transfer that
hit it. Every subsequent segment would then fail to fill the resulting hole
and the connection would stall until an RTO recovered it — a real
correctness bug, not just a slowdown.
**Fix:** the `SYN_RCVD`/`SYN_SENT` handlers now fall through to the normal
ack/data/fin processing for the same segment instead of returning early.

### 2. `NetSim`'s per-packet `threading.Timer` caused spurious retransmits at 0% configured loss
**Found in Phase 2.** The first `NetSim` implementation spawned one OS
thread (`threading.Timer`) per datagram for delayed delivery. Under any
real send rate this means dozens of concurrent short-lived threads, and the
resulting GIL contention was enough to delay ACK delivery past the RTO —
observed directly: a transfer with `loss=0` still produced real
retransmits. This broke the "zero loss ⇒ zero retransmits" invariant that's
supposed to prove the protocol isn't retransmitting spuriously.
**Fix:** replaced per-packet `Timer` threads with a single scheduler thread
driven by a `heapq`-ordered priority queue. Verified the invariant now holds
under a fixed (jitter-free), zero-loss network — see the note on jitter
below for why *some* jitter can still legitimately cause a rare fast
retransmit.

### 3. Naive "retransmit only the oldest segment" made multi-loss recovery catastrophically slow
**Found while stress-testing at 10–20% loss.** A first version's RTO ticker
retransmitted only the single oldest unacked segment per timer firing. Under
sustained loss, where a flight can lose more than one segment at once, this
degrades to recovering one segment per round trip — measured directly: an
80KB transfer at 20% loss took 76 seconds with cwnd pinned at 1 MSS the
entire time.
**Fix:** a timeout now sweeps in every currently-missing unacked segment
(SACK-aware — see below), not just the oldest, as one recovery burst.

### 4. RTT sampling from head-of-line-blocked segments poisoned the RTO estimator
**Found while chasing issue #3's fix — the sweep alone wasn't enough.** When
a cumulative ACK jumps forward and covers several segments at once (because
an earlier one was blocking and just got resolved), the *other* covered
segments have been sitting in the receiver's out-of-order buffer for
however long the block lasted. Sampling RTT from `now - orig_send_time` for
all of them fed wildly inflated "RTT" values into the Jacobson/Karels
estimator, which pushed RTO up, which made the *next* stall last even
longer before its own retransmit fired — a self-reinforcing spiral that
pinned RTO at the 10-second ceiling and starved throughput to ~1KB/s.
**Fix:** exactly one in-flight segment at a time is now the designated RTT
probe (`rtt_probe_seq`), matching the discipline pre-timestamp-option BSD
TCP used — a single, unambiguous timing sample per round trip instead of
one derived from every segment a cumulative ACK happens to cover.

### 5. Backoff scoped to "any overdue segment" instead of the actual blocking one
**Found alongside #3/#4.** The ticker doubled the shared RTO estimator once
per tick whenever *any* unacked segment was overdue — under sustained loss,
different segments time out a few milliseconds apart, so the estimator got
doubled almost every 5ms tick and rocketed to the ceiling in tens of
milliseconds, for reasons unrelated to any single segment repeatedly
failing.
**Fix:** backoff now fires only when the segment actually blocking
cumulative progress (`send_una`) times out — one retransmission timer, tied
to the segment that matters, matching how a real TCP retransmission timer
works.

### 6. `accept()`/`connect()` waited for `state == ESTABLISHED` exactly — a real race, not just flakiness
**Found via a test that passed in isolation but failed reliably when run
right after a lossy transfer test in the same process (~2 out of 3 runs).**
For a very short-lived connection (e.g. one that sends no data and closes
immediately), a reordered FIN can arrive right behind the final handshake
ACK and get processed in the *same* segment-handling call — carrying the
state straight through `ESTABLISHED` into `CLOSE_WAIT` before the waiting
thread ever wakes up to observe the intermediate value. Comparing for exact
equality then waits forever for a state that will never reappear, even
though the handshake genuinely completed. This is not a hypothetical: it
reproduced deterministically once traced (raw-packet logging showed the
handshake and the FIN both landing within about 6ms of each other) and
would have shipped as an intermittent hang.
**Fix:** a latched `handshake_done` flag, set once on entering
`ESTABLISHED` and never cleared, is what `accept()`/`connect()` actually
wait on.

### 7. `close()` didn't wait long enough for background threads to actually exit before closing the fd
**Found investigating #6, before finding the real cause.** `close()` gave
the reader/ticker threads a fixed 1-second `join()` and then closed the
socket regardless of whether they'd actually exited. Under scheduling
contention, closing the fd while a thread might still be inside a blocking
`recvfrom()` on it is a real hazard: a *later*, unrelated `MiniTCPSocket`
can have a fresh fd number reused (POSIX allocates the lowest free one),
and the stale thread can end up stealing that new socket's incoming
datagrams. This turned out not to be issue #6's actual root cause, but it's
a real latent hazard on its own, so the fix stayed: `close()` now waits
(bounded by its own `timeout`) for both threads to confirm they've exited,
and raises rather than silently closing the fd if they haven't.

### 8. Concurrent `close()` calls could send a second, doomed FIN
**Found by deliberately calling `close()` from two threads at once.** The
first call sends a FIN and records its sequence number implicitly via
`next_seq`; a second, overlapping call would compute a *new* `fin_seq` at
the now-stale `next_seq` and send another FIN the peer would never
acknowledge (it already acked the real one) — hanging the second caller
until its own timeout instead of just converging on the same teardown.
**Fix:** the FIN sequence number is now recorded once (`self.fin_seq`) and
reused by any later concurrent `close()` call.

### 9. No source-address validation once a peer was known
**Found by reasoning about what a hostile third party on the same host
could do, then verifying it.** After the peer address was learned from the
first segment, nothing checked that later segments actually came from that
same address — anything else on the loopback that guessed the
(unauthenticated) sequence numbers could inject data into an active
connection. Real TCP filters incoming segments on the (peer IP, peer port)
of the connection tuple for exactly this reason.
**Fix:** segments from any source other than the established peer are now
dropped and logged (`foreign_segment_dropped`).

### 10. A peer that gave up after exhausting retransmits never told the other side
**Found by reasoning about the give-up path, then verifying it.** When a
segment exceeded `MAX_RETRANSMITS`, the sending side recorded a local error
and simply stopped — the peer would sit blocked in `recv()`/`close()` until
*its own* timeout with no way to learn the connection had actually died.
**Fix:** giving up now sends a RST, and the peer's `self.error` (and any
blocked call) reacts to it immediately.

### 11. An unhandled `OSError` in `_send_raw` could silently kill a background thread
**Found as a side effect of testing #10** (a send racing the socket's own
close crashed the ticker thread with a visible but uncaught traceback). Any
transient `sendto()` failure — most commonly a send landing just as the
socket is being closed — propagated out of the background thread and killed
it outright, with no way for the application to notice: the connection
would just silently stop making progress.
**Fix:** `_send_raw` now catches `OSError` the same way `NetSim`'s delivery
path already did.

## Investigated, not a bug — noted so it isn't re-litigated

**Jitter can legitimately cause a rare fast retransmit even at 0% configured
loss.** Two packets sent microseconds apart can still be delivered
out of order if their independently-drawn random delays differ, which can
trigger a false 3-duplicate-ACK fast retransmit — this is real, documented
TCP behavior (the reason DSACK/Eifel-style improvements exist), not a bug in
this implementation. The zero-retransmit invariant is tested against a
zero-loss **and** zero-jitter (fixed-delay) network specifically to isolate
protocol correctness from this separate, expected phenomenon.

**Throughput at high sustained loss (~20%+) is genuinely slow (single-digit
KB/s on small transfers), even after fixes #3–#5.** This matches real,
well-documented behavior of loss-based congestion control without full
RFC 6675-style SACK loss recovery — classic Reno degrades severely under
loss this heavy. Verified this is "slow but correct," not "broken": transfers
complete and are byte-exact given enough time; they're just not fast. Given
the size of this build, going further (full SACK-based scoreboard recovery,
NewReno-style partial-ACK handling) was scoped out rather than chased
indefinitely — documented here instead of silently shipped as-is.

**`recv()` still returns already-buffered data after the connection has
errored (e.g. after a RST).** Initially flagged this as a bug while writing
a test, then realized it's correct, real-socket-like behavior: data that
was genuinely received before the error is still deliverable; only once the
buffer is drained does the next `recv()` call surface the error.

**Test timing is sensitive to real CPU contention on the host.** One run of
the full suite, executed as a background task while other work was also
running in the same session, took 125s (vs. a normal ~47-52s) and one lossy
transfer test missed its 60s budget. Every timeout in this codebase is
measuring real wall-clock RTO/backoff/retransmit behavior over real
threads — there's no simulated clock to insulate it from the host actually
being busy. Re-running the identical suite with nothing else competing for
CPU passed cleanly, twice. Not a logic bug; noted so a future flake under
heavy host load isn't mistaken for a regression.

## Fresh run-through after fixes

Re-ran the full scenario that surfaced the worst of these (a lossy transfer
immediately followed by an unrelated short transfer on fresh ports, in the
same process) five times back to back with no failures, and the full 45-test
suite three times back to back with nothing else competing for CPU — clean
every time. See `tests/` for the regression test covering each numbered
issue above.
