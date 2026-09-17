# Adversarial review

Phase 3: attacking the Phase 2 build as a hostile reviewer. Every issue
below was found by actually running the simulator and staring at numbers
that didn't match the textbook result being reproduced — not by
inspection alone — and every one was fixed before Phase 4 began. Each fix
has a regression test.

## Bugs found and fixed

### 1. Vanilla Reno fast recovery had no NewReno partial-ACK handling

**Symptom:** a single flow's throughput collapsed to near zero for
multi-second stretches after its very first loss.

**Root cause:** `Sender` only ever retransmitted the *one* segment that
triggered the 3-dup-ACK fast retransmit. When slow start (which, exactly
like real TCP, has no ceiling until the first loss) overshot a shallow
buffer, an entire burst of segments — not just one — was dropped in the
same window. Recovering the other lost segments then had to wait for a
full RTO each, with exponential backoff compounding: a stall that should
have taken one or two round trips took tens of seconds.

**Fix:** implemented NewReno (RFC 6582) partial-ACK handling in
`flow.py`: a `recovery_point` marks the highest sequence number sent when
recovery began; an ACK that advances `send_base` but doesn't yet pass
`recovery_point` immediately retransmits the *next* lost segment instead
of waiting for another full 3-dup-ACK cycle or an RTO.
Regression test: `tests/test_cubic.py::test_cubic_survives_a_deep_buffer_without_stalling`.

### 2. Unbounded duplicate-ACK window inflation could run away forever

**Symptom:** with a deep buffer (300 packets), a single CUBIC flow's cwnd
grew to over 8,000 packets and its cumulative-ACK progress froze
completely for the rest of a 60-second run, despite the network itself
losing under 2% of packets.

**Root cause:** RFC 5681's "+1 cwnd per duplicate ACK beyond the third"
rule is justified by packet conservation — each duplicate ACK is supposed
to mean one packet has left the network, freeing room for a new one. My
implementation applied that rule with no bound. If the *retransmitted*
segment itself was unlucky enough to be dropped again, every later
out-of-order arrival kept generating another duplicate ACK for the same
still-stuck `send_base`, and cwnd inflated without limit — flooding an
already-overloaded queue with more and more new data, which produced
still more loss, in a self-reinforcing spiral.

**Fix:** capped the number of dup-ACK inflations allowed per recovery
episode to `recovery_point - send_base` at the moment recovery began —
exactly the number of packets that could legitimately have been
in flight, matching RFC 5681's own justification for the rule rather than
extending it indefinitely. Regression test: same as above, plus
`test_packet_conservation_*` in `tests/test_invariants.py` (the runaway
was first caught by cwnd growing far beyond what conservation allows).

### 3. Deterministic drop-tail let one flow permanently lock out another

**Symptom:** in the two-flow fairness and RTT-unfairness experiments, one
flow would occasionally be *completely* starved (zero throughput) for the
rest of a 40-60 second run — and which flow lost was effectively decided
by simulator determinism, not by the algorithm or topology under test.
The short-RTT flow (which real TCP theory says should win) sometimes lost
entirely; a same-RTT pair meant to demonstrate AIMD fairness sometimes
produced a 40:1 split.

**Root cause:** this simulator has no packet jitter, no OS scheduling
noise, and no randomness in drop-tail admission — a real network would
never reproduce the *exact* same queue-full instant on every retry, but a
deterministic discrete-event simulator can, and did: a recovering flow's
RTO-clocked retransmission could land, every single time, at the instant
the competing flow's periodic burst had the queue completely full. This
is a genuine artifact of simulating without noise, not a finding about
Reno or CUBIC.

**Fix:** two changes. (a) Fairness-measuring experiments now default to
RED instead of drop-tail — RED's randomized early drops are the
documented historical fix for exactly this synchronization pathology
(Floyd & Jacobson, 1993); drop-tail is kept (deliberately) only in the
bufferbloat experiment, where reproducing queue-filling behavior *is* the
point. (b) `run_rtt_unfairness` now pools 15 independent trials (distinct
RNG seeds) rather than trusting a single 60-second run, since even with
RED a single trial can still have one rare unlucky stall dominate its
result — pooling total delivered bytes across trials (not averaging
per-trial ratios, which is vulnerable to a near-zero-denominator outlier)
gets a stable, reproducible signal. See the docstrings in
`experiments.py` for the full reasoning and the specific numbers observed
before/after (a single seed swung from a 0.005x to a 75x ratio; pooling
15 trials consistently lands Reno around 1.1–1.5x and CUBIC around
0.9–1.1x across every base seed tried).

### 4. `REDConfig` crashed on a tiny buffer capacity

**Symptom:** `run_bufferbloat(capacity=1, use_red=True)` raised an
unhandled `ValueError` from deep inside `REDConfig.__init__` — a
percentage-based `min_th`/`max_th` derivation can collapse to the same
integer (or invert) when `capacity` is very small.

**Fix:** added `_default_red()`, a shared helper that clamps
`max_th >= min_th + 1` and caps both at `capacity`, used by all three
experiments that construct a RED config. Not reachable through the
shipped CLI (capacity isn't a CLI flag), but it's a real crash for any
direct caller of the library — and a boring one-line class of bug to have
prevented from the visualizer or a future CLI flag ever hitting it.

### 5. CLI accepted nonsensical input silently instead of erroring

**Symptom:** `--duration -5` and `--duration 0` both "succeeded" with
zero delivered packets and no error; `--flows 0` and `--flows -1` for the
fairness scenario both printed a fairness index of `0.0000` with no
explanation; a zero-duration `rtt-unfairness` run printed a throughput
ratio of `inf`.

**Fix:** the CLI now validates `--duration > 0` and, for the `fairness`
scenario, `--flows >= 1`, failing fast with `argparse`'s usual
`error: ...` message instead of producing a technically-non-crashing but
meaningless result.

### 6. Visualizer rendered every stat twice

**Symptom:** every stat card under every chart appeared twice in a row.

**Root cause:** `render()` runs on both the `load` event and the
`resize` event (so charts redraw at their measured canvas size), and
`stat()` appends a new DOM node on every call without first clearing the
container — so a resize firing once during initial layout doubled every
stat panel.

**Fix:** `render()` now clears every `.stats` container before
repopulating it. Caught via a real headless-Chromium screenshot
(`/tmp/undertow_viz.png` during development), not by reading the code —
the duplicated numbers were visually obvious but easy to miss by tracing
the JS alone since both the "first" and "second" copies had identical,
plausible-looking values.

## Known, deliberate simplifications (not bugs)

These are documented in the code where they matter and are called out
here so a reviewer doesn't mistake them for oversights:

- **No SACK.** Every flow uses classic cumulative-ACK recovery. This is a
  real, historically accurate limitation (SACK wasn't universal until the
  late 1990s) and is *why* bug #1 and #2 above were possible in the first
  place — a SACK-based sender would have recovered a multi-segment loss
  burst in one round trip instead of one segment per round trip. Adding
  SACK is the natural "where a human could take this next" item (see
  README.md).
- **Windowed "goodput" can briefly exceed nominal link rate in a short
  sub-interval.** `_interval_throughput` counts *in-order-delivered*
  segments, not raw physical transmissions. Under loss, out-of-order
  segments already physically received get counted as "delivered" all at
  once, at the instant the blocking gap is finally filled — so a short
  measurement window that happens to catch such a catch-up burst can show
  slightly over 100% utilization (observed: up to ~102-119% in early,
  narrower-window versions of the BBR-vs-loss experiment). Verified this
  is a measurement-window artifact, not a physics violation, by checking
  the *whole-run* total against the link's theoretical maximum
  (`bandwidth × duration / (MSS × 8)`), which never exceeds it — see the
  investigation trail in git history. Mitigated by widening the
  measurement window (`bbr-vs-loss` duration raised to 30s, `steady_from`
  left at a fraction generous enough that a single catch-up burst is a
  small fraction of the window) rather than hidden by clamping the
  reported number.
- **BBR is intentionally "-lite".** Documented in
  `src/congestion/bbr.py`: cwnd-based rather than independently
  rate-paced (this simulator's senders are all window-clocked), a
  4-phase PROBE_BW gain cycle instead of the real 8-phase one, and a
  time-proxy for "round trip" counting instead of tracking delivery
  sequence markers. The state machine (STARTUP/DRAIN/PROBE_BW/PROBE_RTT)
  and the windowed bandwidth/RTT filters are real.
- **CUBIC omits HyStart.** Documented in `src/congestion/cubic.py`. Real
  Linux CUBIC uses HyStart specifically to reduce slow-start overshoot;
  without it, this simulator's slow start behaves like pre-HyStart Linux
  TCP, which is part of why buffer sizing mattered so much to bugs #1-#3
  above.

## Fresh run-through after fixes

24/24 tests pass; `demo.sh` (Phase 5) exercises every one of the six
shipped features end-to-end and reports zero of the issues above.
