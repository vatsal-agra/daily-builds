# Causeway — Adversarial Review (Phase 3)

Attacking Causeway as a hostile reviewer: hunting for real bugs, broken
edge cases, ugly UX, and lazy shortcuts, not just re-reading the happy
path.

## Bugs found while building Phase 2 (already fixed, noted for the record)

These two were caught by directly stress-testing the core engine before
even reaching a formal review pass — worth recording here since they're
exactly the kind of thing an adversarial pass exists to catch, and because
the *symptom* each produced is itself instructive.

1. **CRITICAL — retransmitted SYN-ACK and FIN segments silently dropped
   their ACK flag, causing a permanent connection-establishment deadlock
   under loss.** `_handle_listen()` sent the real `SYN|ACK` segment
   correctly on the wire the *first* time, but recorded the tracking
   `_OutSeg` for retransmission with `flags=SYN` only (the ACK bit
   missing); `_send_pending()`'s FIN path had the identical bug
   (`flags=FIN` instead of `ACK | FIN`). Every *retransmission* of that
   segment therefore went out missing its ACK bit, and the peer's
   handshake/close logic requires `is_ack` to accept it — so if the
   *original* SYN-ACK happened to be lost (a routine event on any lossy
   link), the connection could never complete the handshake at all: found
   by running a single 30%-loss transfer, which stalled for the entire
   300-second simulation budget instead of completing in the low hundreds
   of seconds a link that lossy should actually need. Fixed by recording
   the actual transmitted flags in the retransmission queue.
2. **HIGH — RTT sampling could be contaminated by a segment that sat
   queued behind an unrelated retransmission, wildly inflating the
   estimated RTO.** Without SACK, a single cumulative ACK can acknowledge
   several segments at once; if the *first* of them needed a retransmit
   while a *later* one (never itself retransmitted) was simply waiting its
   turn, naively timing that later segment as `now - sent_time` measures
   the first segment's entire loss-and-retry delay, not a real round trip.
   Observed directly: `srtt` jumped from `None` to over 15 seconds on a
   link whose real one-way delay was 20-30ms, capping RTO at its 5s
   ceiling and turning what should have been a ~180s transfer under 30%
   loss into one that blew through a 100,000-second budget without
   finishing. This is a real, well-known non-SACK TCP ambiguity (one of
   the motivations for RFC 7323 timestamps); fixed with the standard
   conservative mitigation — hold off RTT sampling entirely from the
   moment any retransmission happens until an ACK arrives for data sent
   *after* that point, via `_record_retransmission()` /
   `_sample_rtt_for_popped()`.

## New findings from the Phase 3 pass

3. **HIGH — `mss <= 0` deadlocks the connection permanently, with no error
   at construction time.** `_send_pending()`'s per-segment size is
   `min(self.mss, budget, len(queue))`; with `mss <= 0` this is always
   `<= 0`, so `n < 1` breaks the send loop on every single call — no data
   is ever sent, no timer is ever armed for it, and the simulation's own
   deadlock detector (`SimulationStalled`) is the only thing that
   eventually reports it, correctly but unhelpfully late. Reproduced with
   `run_transfer(b"hello world", mss=0)`. **Fix:** `Connection.__init__`
   now rejects `mss < 1` immediately with a clear `ValueError`.
4. **MEDIUM — `causeway demo --bytes -5` raises a raw
   `ValueError: negative argument not allowed` from deep inside
   `os.urandom`, and any other invalid CLI input (a loss probability
   outside `[0, 1]`, a missing file to `send`, a port already in use, an
   unwritable output path to `recv`) surfaces as an unhandled Python
   traceback instead of a clean, actionable message.** This is real
   "lazy shortcut" territory — the protocol code validates nothing about
   its own inputs and neither does the CLI wrapping it. **Fix:** added
   `_validate_common(args)` checks (bytes >= 0, mss >= 1, loss/dup/reorder
   each in `[0, 1]`) plus a top-level `try/except` in `main()` that turns
   `ValueError`, `OSError` (covers "file not found," "address already in
   use," permission errors, etc.), and the protocol's own
   `SimulationStalled`/`TimeoutError` into a one-line `error: ...` message
   on stderr and exit code 1 — while still letting a genuine internal bug
   (an `AssertionError`, anything unexpected) surface with its full
   traceback rather than being silently swallowed.
5. **MEDIUM — the `demo` subcommand's `--random` flag was dead code: it
   defaulted to `action="store_true", default=True"` with no
   `--no-random` counterpart, so `args.random` was unconditionally `True`
   and the entire "else" branch generating repeating placeholder bytes was
   unreachable.** An unreachable branch of *fake, non-random placeholder
   data* pretending to be a real option is precisely the kind of shortcut
   this phase exists to catch. **Fix:** removed the flag and the dead
   branch entirely; `demo` always transfers genuine random bytes (the
   `--seed` flag already gives full reproducibility of the *network*
   conditions, which is what actually matters for a repeatable demo).
6. **LOW — `causeway proxy`'s single-writer assumption for
   `_pending_swap` was correct in practice (only the one main `recv`
   loop thread ever calls `_schedule`) but read it partly outside the
   lock that protects everything else in that method, which is a latent
   race waiting to happen the moment anyone parallelizes that loop.**
   **Fix:** the whole per-packet decision (loss roll, delay, dup roll,
   swap decision *and* the swap itself) now happens under one lock
   acquisition in `_schedule`; only the actual `sendto()` (in `_send`,
   invoked later from a `Timer` thread) happens outside it.
7. **DOCUMENTED, not fixed — `recv_capacity` bounds the *advertised*
   window but is not independently enforced against a sender that ignores
   it.** In-order arrivals are appended to the ready buffer unconditionally
   (only *out-of-order* buffering checks capacity), which is exactly what
   makes the zero-window persist-probe mechanism work at all (a 1-byte
   probe must be accepted even when the window is nominally full). A
   deliberately non-compliant sender could exceed a receiver's stated
   buffer size by continuing to send after being told the window is
   closed; Causeway's threat model (two mutually-cooperating processes in
   its own demos) doesn't include a hostile peer, so this is called out
   in code comments rather than "fixed" with an enforcement mechanism real
   TCP stacks don't strictly have either.
8. **DOCUMENTED, not fixed — single-peer-per-`Connection` design.** A
   `RealUdpWire`/server `Connection` locks onto whichever address it hears
   from first; a second, different peer attempting to reach the same
   listening socket is silently ignored rather than getting its own
   connection. Fine for this project's one-sender/one-receiver file
   transfer demo; a real multi-client listener would need an accept-loop
   demultiplexing by source address into per-peer `Connection` objects,
   which is out of scope here.

## Verification

After the fixes above, the full test suite (29 tests) plus a fresh
targeted re-run of exactly the four broken scenarios (mss=0, negative
`--bytes`, an out-of-range `--loss`, a nonexistent file to `send`) all
pass/fail cleanly as expected — see `demo.sh`'s dedicated
"adversarial regression" section, which pins each of these four as an
explicit check so they can never silently regress.
