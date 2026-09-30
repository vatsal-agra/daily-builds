# REVIEW — adversarial pass on tcplab

Method: (1) ran the whole suite in **debug** mode, because release builds silently wrap integer overflow
and TCP is 32-bit-modular arithmetic all the way down; (2) ran a battery of hostile CLI scenarios
(100 % loss, 50 % loss, queue of 1, 60 ms jitter, 100 % duplication + 30 % corruption, 1 kbit/s link,
64-byte MSS, 1 Gbit/s × 50 MB, zero bytes, wraparound ISS); (3) wrote a fuzzer (random garbage and
mutated segments into `decode`; 300 seeds of random segments with near-window seq/ack values injected
into connections in every state, interleaved with timers, reads, closes, aborts and writes, asserting
invariants); (4) read my own code as a hostile reviewer would.

## Findings (all fixed; each has a regression test that I verified *fails* with the fix reverted)

| # | Severity | Finding | How it was found | Fix / test |
|---|----------|---------|------------------|------------|
| 1 | high | **TIME_WAIT assassination.** A duplicated ACK reaching an already-CLOSED peer made it emit RST; the client, sitting in TIME_WAIT, obeyed it and reported "connection reset" after a perfectly good transfer (chaos preset, reno/cubic). | preset × algo sweep | RFC 1337: RST is ignored in TIME_WAIT. Covered by `many_seeds_many_algorithms_heavy_loss` / chaos sweep. |
| 2 | high | **Persist-timer deadlock.** If the peer's window shrank to *non-zero but < MSS* and the window-update ACK was lost, the sender's SWS rule refused to send, and no timer was armed (persist logic only handled window == 0) → connection hung forever. | `zero_window_persist_probes_survive_lost_window_updates` timed out at 900 s of virtual time | Persist now triggers on "data waiting, nothing in flight, window < min(MSS, unsent)"; probe size = min(window, unsent, MSS) or 1 byte if zero; probes neither count toward the retry limit nor touch cwnd. |
| 3 | medium | **Pure ACKs carried a stale sequence number.** After an RTO rewinds `snd_nxt`, ACK-only segments used `snd_nxt`, which can be *below* what the peer already holds → peer discards them as out-of-window (losing window updates). | code read-through | ACK-only segments use `snd_max`. `review_pure_ack_uses_snd_max_after_rto_rewind` |
| 4 | *withdrawn* | I first "fixed" a perceived Karn violation (RTO recomputed on the ACK of retransmitted data, contra RFC 6298 §5.7). **That fix was wrong** — see #11. | code read-through | reverted; see #11 |
| 5 | medium | **FIN dropped at zero window.** A bare FIN exactly at `rcv_nxt` was rejected as unacceptable when the receive buffer was full, forcing extra RTO round-trips at connection end. | code read-through | Payload-free segment at `rcv_nxt` is acceptable at zero window. `review_fin_is_accepted_at_zero_window` |
| 6 | low | **Out-of-order map kept the *shorter* of two segments at the same offset**, discarding buffered bytes that then had to be retransmitted. | code read-through | keep the longer. `review_ooo_buffer_prefers_longer_duplicate` |
| 7 | low | **Double ACKs.** Every in-order segment was ACKed, then the instant app read triggered a second "window update" ACK. Wasteful and it muddied traces. | packet trace of the first clean run | Window-update ACKs only when the promised window is under half the buffer (sender might actually be blocked). |
| 8 | low | Duplicate segments were never counted (`dup_segs` stayed 0) because they were discarded by the acceptability check before the payload path. | `survives_reorder_duplication_and_corruption` | count in the unacceptable branch |
| 9 | low (UX) | `--bytes 0` printed "0 B in 0.000 s → goodput 0 bit/s (0 % of link)". | CLI probe | dedicated "no payload" line |
| 11 | high (regression I introduced) | **Strict RFC 6298 §5.7 backoff livelocks at heavy loss.** Holding the backed-off RTO until a clean RTT sample means that at 50 % loss no sample ever arrives (every ACK covers retransmitted data), the RTO ratchets to the 60 s cap and the transfer stalls (100 KB unfinished after 900 s of virtual time; it had completed in 56 s before fix #4). | **the fresh run-through** of the CLI battery (`--loss 50%`) — exactly what the gate is for | Reverted to BSD/Linux practice: an ACK of new data ends the backoff. `review_backoff_ends_on_forward_progress`, `review_extreme_loss_does_not_ratchet_rto_to_the_cap` (fails with the strict rule). |
| 10 | test hygiene | Three of my first four regression tests passed even with the fix reverted (they didn't reach the buggy path). | mutation check: revert each fix, re-run | rewrote them as hand-driven two-TCB tests that reach the exact state; all now fail when their fix is reverted. |

## Checked and found OK
* Debug-mode overflow traps: none across unit, e2e and fuzz tests (300 fuzz seeds × 120 steps).
* Every single-bit flip of a segment is detected by the checksum (exhaustive test over all bit positions).
* Byte-exact delivery under 8 % loss + reorder + duplication + corruption for all 4 algorithms × 12 seeds.
* Sequence wraparound at ISS = 0xFFFFFFFF / 0xFFFFF000 with loss and bidirectional data.
* Blind RST (out of window) ignored; in-window RST honoured; RST never answered with RST.
* Determinism: same seed → byte-identical trace; different seed → different trace.
* CLI rejects: unknown flags/scenarios, probabilities >100 %, `--drop 0`, tiny `--rcv-buf`, non-numeric values.

## Known limitations (documented, deliberate)
* No SACK, no timestamps, no Limited Transmit, no delayed ACKs, no Nagle: tail losses with < 4 segments in
  flight need an RTO, and heavy *jitter* reordering causes spurious fast retransmits (no DSACK/RACK to undo them).
* One connection per simulation; the passive side does not re-listen after closing.
* Congestion window is not restarted after idle periods (RFC 5681 §4.1).

## Fresh run-through after the fixes
The first fresh run-through **found #11** (my own regression); after reverting it, the suite is green in debug
and release and the hostile CLI battery re-run gives: every transfer verified byte-exact except the 100 %-loss
case, which correctly reports `connection timed out` and exits non-zero.
