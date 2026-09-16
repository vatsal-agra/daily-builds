# Phase 3 — Adversarial Review

Attacked Undertow's own implementation as a hostile reviewer: manual
scenario reproduction first (to find real bugs fast), then a permanent
regression test for each one in `tests/test_review_regressions.py`. Every
issue below was reproduced, root-caused, fixed, and re-verified.

## Bugs found and fixed

### 1. CRITICAL — handshake never completed (`_enqueue_control` forgot to advance `send_next`)

`connect()`/`accept()` inject the SYN/SYN-ACK as a 1-byte pseudo-segment via
`_enqueue_control()`, which added it to `unacked` but never advanced
`self.send_next` past that byte. The peer's ACK correctly set
`send_una = iss + 1`, but `send_next` stayed at `iss` forever — so the
handshake-complete check (`send_una == send_next`) could never fire, and
every single `connect()`/`accept()` call hung until its own timeout, on a
perfectly clean link with zero loss. This was caught immediately by the
first real two-socket test (Phase 2's own smoke test), before it ever
reached a lossy scenario. One-line fix: `_enqueue_control` now sets
`self.send_next = seq_add(seq, seg.seqlen())`, exactly mirroring what
`_send_pending` already did for data segments.

### 2. CRITICAL — cascading retransmission-timeout backoff stalled bulk transfers under loss

`_handle_timers` picked "whichever unacked segment has the oldest
`send_time`" to check against the RTO. That's *not* the same thing as
"the segment at `send_una`" once a retransmission has happened: retransmitting
`send_una` resets its `send_time` to now, which flips "oldest by send_time"
to a *different*, earlier-sent sibling segment — and that segment then gets
judged against the connection's shared, already-doubled-by-the-first-timeout
RTO value, instead of the smaller RTO that was actually in effect when it
was sent. It times out far too early, its own backoff doubles the RTO
again, and the next sibling suffers the same fate on an even larger RTO.
Reproduced concretely: a 400KB transfer at 8% loss produced a 6s → 10s →
15s cascade of retransmit gaps and never finished. Real (non-SACK) TCP
avoids this by keeping exactly one retransmission timer per connection,
always tied to `send_una`, never to "whichever segment looks oldest right
now" — `_handle_timers` now does the same:
`self.unacked.get(self.send_una)` instead of `min(..., key=lambda s: s.send_time)`.

### 3. CRITICAL — zero-window deadlock (a slow receiver could stall the connection forever)

Once a sender fills the receiver's 64KB window, `_send_pending` correctly
stops sending. But nothing ever told the sender the window reopened once
the receiving application actually called `recv()` and drained its buffer:
an ACK carrying the new window is only ever generated in reaction to an
*incoming* packet, and the sender has stopped sending (that's the whole
point of respecting the window), so nothing arrives to react to. A
perfectly well-behaved receiver whose application was merely a little slow
to start reading — not misbehaving, not attacking — would deadlock the
whole connection permanently. Reproduced directly: an app that `sleep(3)`s
before calling `recv_all()` while the peer pushes >64KB never recovers.
Real TCP fixes this with two complementary mechanisms, and it needs both
(one alone isn't enough, because the fix for "the sender doesn't know"
can itself be lost on the wire): the receiver proactively announces a
reopened window on `recv()` (`_maybe_send_window_update`), *and* the
sender periodically probes with a single byte whenever it's stalled purely
on `peer_window == 0` (the persist-probe branch in `_send_pending`), in
case that announcement was itself dropped.

### 4. MEDIUM — receiver never actually enforced its own advertised window

`_process_data` stored every in-window-or-not out-of-order chunk into
`recv_buffer` unconditionally — the window value sent to the peer was
honest telemetry, but nothing locally acted on it, so a sender that
ignored the advertised window (or a bug that miscounted `peer_window`)
could grow `recv_buffer`/`unread` without bound. Fixed by checking
`len(pkt.payload) <= self._advertised_window()` before buffering; data
that doesn't fit is simply never ACKed and recovered exactly like ordinary
packet loss, via the sender's normal retransmission path — no special
rejection protocol needed.

### 5. MINOR — `FLAG_RST` was decodable but nothing in the codebase ever sent one

`_handle_packet` handled an incoming RST correctly (aborts the connection),
but no code path produced one, so the whole feature was untested,
unreachable dead weight. Added a real public `Connection.abort(reason)` /
`recv()` now raises a clear `ConnectionError_("connection reset")` once an
abort is observed with nothing left to deliver, instead of an inscrutable
timeout. Verified end-to-end: one peer aborts mid-transfer, the other sees
a real reset, not a hang.

### 6. Resource leak — `UndertowSocket` was never closed in tests/CLI/demo code

Every test and the `demo`/`send`/`serve` CLI commands created real UDP
sockets via `UndertowSocket` but only ever called `Connection.close()`
(the protocol-level FIN handshake), never `UndertowSocket.close()` (the
underlying OS socket). Harmless for a single short-lived script, but it
produced `ResourceWarning: unclosed socket` on every test run and would
leak file descriptors in anything longer-lived. Fixed by closing the
socket in `run_transfer()`, `cmd_send()`, `cmd_serve()`, and every test's
teardown.

## Investigated, not a library bug

**"Simultaneous bidirectional `recv_all()` on both ends deadlocks."**
Reproduced, then root-caused to the *test*, not the library:
`recv_all()`/EOF-based reads only return once the peer sends FIN, so if
neither side ever calls `close()` before waiting for the other's full
stream, both wait forever — this is exactly how blocking TCP reads over a
socket that's still open on both ends behave too. Real fix is at the
application level (read a known length with `recv(n)` in a loop, or
half-close one direction first), not in the transport. Documented as a
`recv_all()` docstring/README caveat rather than "fixed", and added a
proper full-duplex regression test using the correct read-exact-N-bytes
pattern (`TestFullDuplex`), which passes cleanly.

## What held up

- Wraparound-safe sequence arithmetic: transferring data across the exact
  `2**32 - 1 → 0` boundary (forced `initial_seq`) round-trips correctly.
- Genuine out-of-order reassembly and SACK-block generation were verified
  directly against the receiver's internal state (not just inferred from a
  successful end-to-end transfer, which loss-triggered retransmission alone
  could have produced without ever exercising the out-of-order code path at
  all): fed segments B, C out of order, confirmed the exact SACK block
  `(5010, 5030)` reported for the gap, then filled the gap with A and
  confirmed clean, correctly-ordered reassembly and an empty `recv_buffer`.
  A duplicate re-delivery of the same segment afterward was confirmed to
  leave the stream untouched.
- Survives a live flood of random, checksum-garbage UDP datagrams sent at
  both endpoints throughout a transfer (an unauthenticated third party
  spamming the wire) with the real data still landing byte-exact.
- Corruption detection (bit flips in header and payload), truncated
  packets, and a bogus SACK count are all rejected by `Packet.decode`
  before any protocol logic sees them.
