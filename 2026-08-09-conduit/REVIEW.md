# Adversarial Review

Hostile-reviewer pass over the Phase 2 build, looking for real bugs,
broken edge cases, and lazy shortcuts. Findings are grouped into **fixed**
(genuine bugs, corrected and covered by a regression test) and **known
limitations** (real, understood trade-offs that are either fundamental to
the class of protocol being built or reasonably out of scope — documented
rather than silently left for someone else to discover).

## Fixed

### 1. RTO estimator poisoned by head-of-line-blocking bursts (found during Phase 2, already fixed before that commit — recorded here for completeness)
A single cumulative ACK that retires a whole burst of segments at once
(e.g. right after an earlier lost segment's retransmission finally lands
and unblocks everything queued behind it) was feeding *every* retired
segment into the RTT estimator as an independent sample. All of those
segments were sent around the same original time but sat waiting through
an unrelated retransmission — timing them individually reports the
*blocking delay*, not the network RTT, and the EWMA compounds it on every
such burst. Observed effect: RTO exploding from ~1s to 26s within a few
seconds on a 15%-loss link, and a 50KB transfer taking 18 seconds because
one unlucky segment's inflated timer dominated the whole connection.
**Fix:** sample RTT at most once per ACK, from the oldest covered
segment only — matching how classic (non-timestamp) TCP times one
in-flight segment at a time. Covered by `tests/test_transport_integration.py`'s
lossy-network suite, which would time out under the old behavior.

### 2. `connect()` leaked a thread + socket on handshake failure
If the handshake timed out or was reset, `api.connect()` raised without
ever stopping the client's UDP reader thread or closing its socket —
`ConduitSocket.close()` (which normally does this via the `on_teardown`
hook) is never reached because there's no established connection to call
it on. Confirmed with a thread-count probe: a single failed `connect()`
leaked 2 threads that lived until process exit. **Fix:** `connect()` now
tears itself down on any exception from the handshake.
Regression: `test_failed_connect_does_not_leak_threads`.

### 3. Dead `FIN_WAIT_2` state / unused `_CAN_RECV_DATA` guard
`FIN_WAIT_2` was defined and included in state-set constants but no code
path ever set a connection to it — the close FSM collapsed "our FIN
acked, waiting on peer's FIN" into a same-looking `FIN_WAIT_1`, which
happened to still produce the right final state but made the FSM harder
to reason about and, separately, meant data segments arriving in a
half-closed state (`TIME_WAIT`, `LAST_ACK`, etc.) were processed instead
of ignored. **Fix:** `_advance_close_state` now explicitly transitions
`FIN_WAIT_1 -> FIN_WAIT_2` when our FIN is acked before the peer's FIN
arrives (distinct from the simultaneous-close path, which goes straight
to `CLOSING`), and `_handle_segment` gates data processing on
`_CAN_RECV_DATA`. Regression: `test_passive_close_reaches_closed_final`
plus the existing full-suite close paths exercised by every integration
test's teardown.

### 4. `NetworkSimulator`/`Listener` teardown races printed unhandled tracebacks
Closing a `Listener` (or the process exiting) while a `TIME_WAIT`
connection's engine thread was still ticking hit `sendto()` on an
already-closed socket, crashing that thread with an unhandled `OSError`
traceback (harmless — the connection was already done — but noisy and a
bad look for anything watching stderr). **Fix:** `_transmit()` now
catches `OSError` from a torn-down channel and logs a trace event instead
of crashing the engine thread; `Listener.close()` also proactively stops
every connection's engine loop.

## Known limitations (considered, not bugs)

### Duplicate ACKs from network-level duplication can trigger a spurious fast retransmit
`NetworkSimulator`'s `dup_prob` occasionally delivers a *literal* second
copy of an already-processed ACK. Conduit's fast-retransmit logic (like
real TCP's) cannot distinguish "the receiver is telling me the same
segment is still missing" from "the network handed me a second copy of
an ACK I already acted on" — both look like an identical repeated ACK.
The result is an occasional unnecessary cwnd cut / redundant
retransmission under `dup_prob` settings well above what real networks
exhibit (real IP networks essentially never duplicate packets this
often; 2–5% here is already an aggressive stress setting). This is the
same class of ambiguity D-SACK and the Eifel algorithm exist to resolve
in real TCP, and is out of scope here — the effect is a performance hit,
never a correctness one (the receiver's own duplicate/out-of-order
handling in `_handle_data` still delivers exactly the right bytes).

### No chunked Transfer-Encoding on *request* bodies
`httpd.server` frames request bodies by `Content-Length` only. A client
sending `Transfer-Encoding: chunked` without `Content-Length` will have
its body misparsed as the start of the next request (which fails loudly
with a 400, not silently). Every path this project actually exercises
(curl GETs, the static file server, the `/echo` POST test) sends
`Content-Length`, so this was deprioritized in favor of protocol-layer
correctness. Response bodies are always sent with `Content-Length` and
are unaffected.

### No per-connection give-up policy for data (only for the handshake)
An established connection whose peer stops responding entirely will
retry at the RTO ceiling (30s) indefinitely — there's no "give up after N
retries" for data, only for the initial handshake. This matches
default real TCP behavior (no automatic dead-peer detection without
keepalive), so it's an intentional parity choice, not an oversight.

### Single reader / single writer per socket
`ConduitSocket.send()`/`recv()` assume one application thread calling
each at a time (the same assumption BSD sockets make in practice, even
though nothing stops two threads from racing `recv()` calls). Not
enforced with a lock beyond what's needed for internal consistency.

## Fresh run-through after fixes

Full suite re-run clean: **62/62 tests passing**, including the three
new regression tests added for findings #1–#3 above, the full lossy
integration suite, and the curl oracle suite (real `curl`, through the
bridge, through the simulator, at up to 15% configured loss).
