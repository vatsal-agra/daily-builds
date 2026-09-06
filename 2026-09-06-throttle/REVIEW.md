# Adversarial review

Method: manual code reading looking for logic errors, plus randomized
fuzzing (300+ single-flow runs and 150+ multi-flow runs across randomized
bandwidth/buffer/delay/loss/reorder/algorithm/size combinations, including
degenerate sizes 0 and 1 byte) asserting on every run that (a) nothing
raises, and (b) any transfer that reports itself "done" reassembled
**byte-for-byte identical** to what was sent. Every issue below was found
by one of those two methods, not invented for show.

## Issues found and fixed

### 1. CRITICAL — crash on a lost/timed-out SYN (`tcp.py`, `TcpSender._on_timer`)

**Found by:** fuzzing (2 of the first 60 randomized runs crashed).

`_on_timer` unconditionally called `self._maybe_send_more(self.sim.now)`
after retransmitting whatever timed out. If the timed-out segment was the
handshake's own SYN (i.e. the SYN itself was lost), the connection is
still in `SYN_SENT` — `self.irs` (the receiver's initial sequence number,
learned only from the SYN-ACK) is still `None`. `_maybe_send_more` builds
every outgoing data segment with `ack=self.irs + 1`, so this raised
`TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'`,
killing the whole simulation the moment any run happened to lose a SYN on
a lossy link — a scenario the "single-flow-lossy" experiment exercises by
design.

**Fix:** guard the call with `if self.state != "SYN_SENT"`. A SYN timeout
now only retransmits the SYN, exactly as it should — there is nothing else
to send until the handshake completes. Regression test:
`test_syn_timeout_retransmits_without_crashing` (verified to fail against
the pre-fix code, and to pass after).

### 2. CRITICAL — the sequence-number bug that made the very first build broken

**Found by:** manual smoke test, before any automated tests existed.

`next_seq` was never advanced past the SYN's own sequence number after
`connect()` sent it. The first data segment therefore reused the SYN's
sequence number and, because `_maybe_send_more`'s byte-offset arithmetic
(`sent_data_bytes = next_seq - (iss + 1)`) went negative as a result, a
negative Python slice silently produced an **empty payload** for that
first "data" segment instead of raising. The connection would then sit
with zero cumulative ACK progress forever (every real data segment kept
arriving at the receiver, but always past a gap the empty phantom segment
never filled), each RTO backing off exponentially until the run stalled
completely. Fixed by setting `next_seq = iss + 1` at the moment the SYN is
sent (a SYN consumes one sequence number *immediately*, not just once
acked — matching real TCP). See the `test_clean_link_transfer_completes_*`
tests for the regression coverage (byte-exact reassembly on a clean link).

### 3. CRITICAL — a lost final handshake ACK could deadlock a connection forever

**Found by:** manual review while fixing #2 (asking "what if this segment
is dropped?" of every message in the handshake).

The sender's bare completion ACK (the third message of the 3-way
handshake) was sent directly via `link_send`, bypassing the
retransmission-tracking `_send_segment` path — intentionally, since a pure
ACK carries nothing worth retransmitting on its own. But the receiver's
`SYN_RCVD` state only advanced to `ESTABLISHED` on exactly that segment; if
it was lost, the receiver would stay in `SYN_RCVD` forever and silently
ignore every subsequent real data segment (which are only handled in
`ESTABLISHED`), since nothing ever prompts the sender to retransmit a
segment it never tracked as outstanding.

**Fix:** real TCP sets the ACK flag on every segment after the initial
SYN, not just the bare completion ACK — so the sender now does too (all
data and FIN segments carry `ack_flag=True`), and the receiver treats
*any* ack-flagged, non-SYN segment arriving in `SYN_RCVD` as handshake
confirmation, processing it as data too if it carries any. Regression
test: `test_lost_final_handshake_ack_does_not_deadlock_connection`.

### 4. Real bug in the review tooling itself — `Simulator.run()` corrupting duration/throughput/utilization figures

**Found by:** using the newly-added `Link.utilization()` output (see #6
below) and noticing a single-flow experiment that finished in ~10.5
simulated seconds was reporting "120.00s duration" and "1.3% utilized."

While fixing a test (`test_simulator_run_until_stops_early_and_can_resume`)
I made `Simulator.run(until=X)` always advance `self.now` to `X` before
returning, including when the event heap ran out *entirely* before `X` —
i.e. "nothing left to simulate" got silently reinterpreted as "simulated
the full duration." Every `ExperimentResult.duration_s` (and everything
computed from it: link utilization, incomplete-flow throughput estimates)
was then wrong for any experiment that finished before its time cap —
which is all of them. Fixed by only advancing `now` to the horizon when
the heap still has a *future* event beyond it (time provably passed with
nothing happening); when the heap empties naturally, `now` correctly stays
at the last real event's time. This is exactly the kind of self-inflicted
bug a "no shortcuts" adversarial pass exists to catch: the fix for one
test's assumption silently broke a real invariant everything else in the
codebase depended on.

### 5. UX — invalid parameters raised raw tracebacks instead of clean errors

**Found by:** deliberately trying `--bandwidth -5`, `--loss 1.5`, `--cap 0`.

`Link`/`AccessLink` had no input validation, so a negative bandwidth
produced a negative "packet finish time," which then hit
`Simulator.schedule_at`'s past-scheduling guard several stack frames away
from the actual mistake, as a confusing `ValueError` buried in a
`network.py` traceback. Fixed by validating every network/TCP parameter
(`bandwidth_Bps > 0`, `buffer_bytes >= 0`, `0 <= loss_prob/reorder_prob <=
1`, `mss > 0`, etc.) at the point of construction with a specific message,
and by having `throttle`'s CLI catch `ValueError` at the top level and
print `throttle: error: <message>` with exit code 2 instead of a
traceback. `--bytes` and `--cap` get the same treatment at the CLI layer
since they aren't otherwise validated deeper in the stack.

### 6. Hygiene — dead code / unused feature (`Link.utilization()`)

`Link.utilization()` existed but nothing called it. An unused method in a
"no stubs" build is worth questioning: either it's not needed (delete it)
or it should actually be surfacing something real. It was the latter —
bottleneck utilization is exactly the number that makes the fairness and
high-BDP experiments' claims checkable at a glance. Wired into both the
CLI's per-flow summary and the HTML report's per-experiment header. Also
led directly to finding issue #4 above.

### 7. Minor — `RttEstimator`'s pre-sample RTO ignored a caller's `min_rto_s` override

Per RFC 6298 the pre-measurement default RTO is a hardcoded 1 second,
independent of the floor later, sample-derived RTOs get clamped to. That's
correct behavior for the default (`min_rto_s=1.0`, matching the RFC), but
when a caller explicitly *lowers* `min_rto_s` (as the test suite does, to
keep simulated-time timeouts from eating unnecessary wall-clock/event
volume), the very first timeout — before any RTT sample exists — would
still wait the full un-lowered 1s, silently ignoring the override's
intent. Fixed by seeding `initial_rto_s = min(1.0, min_rto_s)`.

## Considered and deliberately *not* "fixed"

**TCP Reno's go-back-1 collapse under severe/bursty loss.** Early
experiment tuning (documented in git history, not shipped) used a
bottleneck buffer sized well under one bandwidth-delay-product with two
flows blasting from a cold start. The result: a burst overflowed the
buffer badly enough that *every* segment behind the first loss in a
window was also dropped, so no duplicate ACKs ever arrived to trigger fast
retransmit — recovery fell back entirely to RTO, which (correctly, per
Karn's algorithm) retransmits only the single oldest unacked segment per
timeout and doubles the timeout after each one. With many segments lost
in the same window, that serializes into a multi-minute simulated stall.
This is not a bug: it is a **real, well-documented limitation of Reno
without SACK** (bad enough in practice that it helped motivate both
NewReno and RFC 2018 SACK). The fix was choosing experiment parameters
that don't induce a self-made buffer catastrophe (buffers sized nearer a
real bandwidth-delay product), not changing the protocol logic — changing
the logic to "recover faster" here would mean *not implementing Reno*.
`PLAN.md`'s SACK stretch goal exists specifically because this is the
real, named reason SACK was invented.

**Reno's window inflation/deflation only implements classic Reno, not
NewReno.** A fast-recovery episode that needs to repair more than one lost
segment in the same window will, correctly for *Reno* (not NewReno),
require a second round of duplicate ACKs rather than resolving in one.
Documented as a deliberate scope boundary in `tcp.py`'s module docstring,
not silently passed off as more capable than it is.

## What a fresh run-through now hits

Zero of the above. `pytest` (63 tests) is green, the 300+/150+ single- and
multi-flow fuzz sweeps (independent of the pytest suite, run again after
every fix in this document) report zero crashes and zero reassembly
mismatches, and `throttle demo` completes all 6 canned experiments with
verified, byte-exact reassembly on every flow.
