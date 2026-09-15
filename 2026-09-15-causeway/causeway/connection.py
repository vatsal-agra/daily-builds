"""The Causeway protocol engine: a single bidirectional-handshake,
unidirectional-data connection, driven entirely by repeated ``step(now)``
calls from either a real-time pump loop (over a real UDP socket) or a
discrete-event simulation driver (over ``SimulatedLink``).

Scope notes (deliberate, documented simplifications rather than hidden
gaps):

* Initial sequence numbers are not randomized. Real TCP randomizes the ISN
  specifically to make off-path segment injection/spoofing harder; that's
  an internet-facing security property, out of scope for a transport meant
  to run over localhost/loopback between two processes that trust each
  other in this project's demos.
* Sequence numbers are tracked as unbounded Python ints and only masked to
  32 bits when a segment is put on the wire. 32-bit wraparound mid-connection
  is not handled -- it would require transferring more than 4 GiB on a
  single connection, far past anything this project's demos or tests do.
* True RFC 793 simultaneous close (both sides FIN at once, the CLOSING
  state) isn't implemented -- only the standard case this project's own
  demos exercise: one side finishes writing and closes, the other detects
  the peer's FIN (end of stream) and then closes in turn. The TIME_WAIT
  robustness this *does* implement -- surviving a lost final ACK by having
  the peer's un-acked FIN simply retransmit like any other segment -- is
  exercised directly by the adversarial tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from . import segment as seg_mod
from .segment import ACK, FIN, SYN, Segment

DEFAULT_MSS = 536
DEFAULT_RECV_CAPACITY = 64 * 1024


class RttEstimator:
    """Jacobson/Karels RTT estimation, exactly as RFC 6298 specifies it."""

    ALPHA = 1 / 8
    BETA = 1 / 4

    def __init__(self, min_rto: float = 0.2, max_rto: float = 5.0, initial_rto: float = 1.0,
                 clock_granularity: float = 0.01):
        self.srtt: Optional[float] = None
        self.rttvar: Optional[float] = None
        self.rto = initial_rto
        self.min_rto = min_rto
        self.max_rto = max_rto
        self.g = clock_granularity
        self.samples = 0

    def sample(self, r: float) -> None:
        r = max(r, 1e-6)
        self.samples += 1
        if self.srtt is None:
            self.srtt = r
            self.rttvar = r / 2
        else:
            self.rttvar = (1 - self.BETA) * self.rttvar + self.BETA * abs(self.srtt - r)
            self.srtt = (1 - self.ALPHA) * self.srtt + self.ALPHA * r
        self.rto = self.srtt + max(self.g, 4 * self.rttvar)
        self.rto = min(max(self.rto, self.min_rto), self.max_rto)


@dataclass
class _OutSeg:
    seq: int
    flags: int
    payload: bytes
    sent_time: float
    retransmit_count: int = 0

    def seq_end(self) -> int:
        n = len(self.payload)
        if self.flags & SYN:
            n += 1
        if self.flags & FIN:
            n += 1
        return self.seq + n


class Connection:
    def __init__(
        self,
        role: str,
        wire,
        clock,
        *,
        mss: int = DEFAULT_MSS,
        recv_capacity: int = DEFAULT_RECV_CAPACITY,
        iss: int = 0,
        initial_rto: float = 1.0,
        min_rto: float = 0.2,
        max_rto: float = 5.0,
        time_wait_duration: float = 1.0,
        persist_base: float = 0.5,
        persist_max: float = 4.0,
        on_event: Optional[Callable[[dict], None]] = None,
    ):
        assert role in ("client", "server")
        if mss < 1:
            # mss <= 0 makes every send-side chunk size <= 0, which silently
            # stops the sender from ever transmitting again -- caught by
            # adversarial review as a permanent, hard-to-diagnose deadlock
            # rather than an immediate, obvious error.
            raise ValueError(f"mss must be >= 1, got {mss}")
        if recv_capacity < 1:
            raise ValueError(f"recv_capacity must be >= 1, got {recv_capacity}")
        self.role = role
        self.wire = wire
        self.clock = clock
        self.mss = mss
        self.recv_capacity = recv_capacity
        self.on_event = on_event

        self.rtt = RttEstimator(min_rto=min_rto, max_rto=max_rto, initial_rto=initial_rto)

        # Congestion control.
        self.cwnd = float(mss)
        self.ssthresh = float(64 * mss)
        self.dup_ack_count = 0
        self.in_fast_recovery = False
        self.recover_seq = 0

        # Send side.
        self.iss = iss
        self.snd_una = iss
        self.snd_nxt = iss
        self.send_queue = bytearray()
        self.unacked_segments: List[_OutSeg] = []
        self.peer_rwnd = 65535  # optimistic default until we hear otherwise
        self.close_requested = False
        self.fin_sent = False
        self._fin_seq: Optional[int] = None
        self.last_probe_time = float("-inf")
        self.persist_attempts = 0
        # See _record_retransmission()/_sample_rtt_for_popped(): guards against
        # sampling RTT from a segment that was never itself retransmitted but
        # sat queued behind one that was, which would time it against a stale
        # send time and badly inflate the RTO.
        self._rtt_sample_hold: Optional[int] = None
        self.persist_base = persist_base
        self.persist_max = persist_max

        # Recv side.
        self.irs: Optional[int] = None
        self.rcv_nxt = 0
        self.ready = bytearray()
        self.ooo = {}  # seq -> payload, for out-of-order buffering
        self.peer_fin_received = False

        # Lifecycle.
        self.time_wait_duration = time_wait_duration
        self.in_time_wait = False
        self.time_wait_deadline = 0.0
        self.closed = False
        self.error: Optional[str] = None

        # Stats, purely informational.
        self.stats = {
            "segments_sent": 0, "segments_received": 0, "bad_checksum": 0,
            "retransmits": 0, "timeouts": 0, "fast_retransmits": 0,
            "dup_acks_received": 0, "persist_probes": 0,
        }

        if role == "client":
            self.phase = "SYN_SENT"
            syn = Segment(seq=self.iss, ack=0, window=self._my_advertised_window(), flags=SYN)
            self.wire.send(syn.encode())
            self.unacked_segments.append(_OutSeg(seq=self.iss, flags=SYN, payload=b"",
                                                  sent_time=self.clock.now()))
            self.snd_nxt = self.iss + 1
            self._emit("syn_sent")
        else:
            self.phase = "LISTEN"

    # ------------------------------------------------------------------ #
    # Public application-facing API
    # ------------------------------------------------------------------ #

    @property
    def is_established(self) -> bool:
        return self.phase == "ESTABLISHED"

    @property
    def is_closed(self) -> bool:
        return self.closed

    @property
    def eof(self) -> bool:
        """True once the peer's FIN has arrived and every byte before it
        has been delivered to us -- i.e. there is nothing left to `recv()`
        and nothing more will ever arrive."""
        return self.peer_fin_received and len(self.ready) == 0

    @property
    def bytes_in_flight(self) -> int:
        return self.snd_nxt - self.snd_una

    @property
    def fin_acked(self) -> bool:
        return self.fin_sent and self._fin_seq is not None and self.snd_una > self._fin_seq

    def send(self, data: bytes) -> None:
        if self.close_requested:
            raise RuntimeError("cannot send() after close()")
        self.send_queue.extend(data)

    def recv(self, max_bytes: Optional[int] = None) -> bytes:
        if max_bytes is None or max_bytes >= len(self.ready):
            data = bytes(self.ready)
            self.ready.clear()
        else:
            data = bytes(self.ready[:max_bytes])
            del self.ready[:max_bytes]
        return data

    def close(self) -> None:
        self.close_requested = True

    # ------------------------------------------------------------------ #
    # The engine
    # ------------------------------------------------------------------ #

    def step(self, now: float) -> None:
        if self.closed:
            return
        for raw in self.wire.poll():
            self._handle_raw(raw, now)
        self._check_retransmit_timeout(now)
        self._send_pending(now)
        self._advance_lifecycle(now)
        self._emit("sample")

    # -- receiving -------------------------------------------------------

    def _handle_raw(self, raw: bytes, now: float) -> None:
        try:
            s = Segment.decode(raw)
        except ValueError:
            return
        self.stats["segments_received"] += 1
        if not s._decoded_checksum_ok:
            self.stats["bad_checksum"] += 1
            return  # corrupted on the wire -- silently dropped, exactly like real UDP/TCP

        if self.phase == "SYN_SENT":
            self._handle_syn_sent(s, now)
            return
        if self.phase == "LISTEN":
            self._handle_listen(s, now)
            return
        if self.phase == "SYN_RCVD":
            self._handle_syn_rcvd(s, now)
            # fall through: a piggybacked payload on the handshake-completing
            # ACK is legal and should still be reassembled below
            if self.phase != "ESTABLISHED":
                return

        # ESTABLISHED (or past it, into the close sequence) -- data phase.
        self._ack_update(s, now)
        self._data_receive(s, now)

    def _handle_syn_sent(self, s: Segment, now: float) -> None:
        if not (s.is_syn and s.is_ack and s.ack == self.snd_nxt):
            return
        syn_out = self.unacked_segments[0] if self.unacked_segments else None
        self.unacked_segments.clear()  # the SYN is acked
        if syn_out is not None and syn_out.retransmit_count == 0:
            self.rtt.sample(now - syn_out.sent_time)  # Karn's algorithm: never sample a retransmit
        self.snd_una = s.ack
        self.irs = s.seq
        self.rcv_nxt = s.seq + 1
        self.phase = "ESTABLISHED"
        ack = Segment(seq=self.snd_nxt, ack=self.rcv_nxt, window=self._my_advertised_window(), flags=ACK)
        self.wire.send(ack.encode())
        self._emit("established")

    def _handle_listen(self, s: Segment, now: float) -> None:
        if not s.is_syn:
            return
        self.irs = s.seq
        self.rcv_nxt = s.seq + 1
        synack = Segment(seq=self.snd_nxt, ack=self.rcv_nxt, window=self._my_advertised_window(),
                          flags=SYN | ACK)
        self.wire.send(synack.encode())
        self.unacked_segments.append(_OutSeg(seq=self.snd_nxt, flags=SYN | ACK, payload=b"", sent_time=now))
        self.snd_nxt += 1
        self.phase = "SYN_RCVD"

    def _handle_syn_rcvd(self, s: Segment, now: float) -> None:
        if not (s.is_ack and s.ack == self.snd_nxt):
            return
        acked = self.unacked_segments
        self.unacked_segments = []
        self._sample_rtt_for_popped(acked, s.ack, now)
        self.snd_una = s.ack
        self.peer_rwnd = s.window
        self.phase = "ESTABLISHED"
        self._emit("established")

    def _ack_update(self, s: Segment, now: float) -> None:
        if not s.is_ack:
            return
        if s.ack > self.snd_una:
            newly_acked = s.ack - self.snd_una
            popped = []
            while self.unacked_segments and self.unacked_segments[0].seq_end() <= s.ack:
                popped.append(self.unacked_segments.pop(0))
            self._sample_rtt_for_popped(popped, s.ack, now)
            self.snd_una = s.ack
            self.dup_ack_count = 0
            if self.in_fast_recovery:
                if s.ack >= self.recover_seq:
                    self.cwnd = float(self.ssthresh)
                    self.in_fast_recovery = False
                else:
                    # NewReno-style partial ack: another segment was lost in
                    # the same window: deflate proportionally and re-send the
                    # next unacked segment immediately instead of waiting for
                    # a fresh round of duplicate ACKs.
                    self.cwnd = max(self.cwnd - newly_acked, float(self.mss))
                    if self.unacked_segments:
                        self._retransmit(self.unacked_segments[0], now)
            else:
                if self.cwnd < self.ssthresh:
                    self.cwnd += self.mss  # slow start
                else:
                    self.cwnd += max(1.0, (self.mss * self.mss) / self.cwnd)  # congestion avoidance
            self._emit("ack")
        elif s.ack == self.snd_una and self.unacked_segments:
            self.dup_ack_count += 1
            self.stats["dup_acks_received"] += 1
            if self.dup_ack_count == 3 and not self.in_fast_recovery:
                self.ssthresh = max(self.cwnd / 2, 2.0 * self.mss)
                self.recover_seq = self.snd_nxt
                self.cwnd = self.ssthresh + 3 * self.mss
                self.in_fast_recovery = True
                self.stats["fast_retransmits"] += 1
                self._retransmit(self.unacked_segments[0], now)
                self._emit("fast_retransmit")
            elif self.dup_ack_count > 3 and self.in_fast_recovery:
                self.cwnd += self.mss
        self.peer_rwnd = s.window

    def _data_receive(self, s: Segment, now: float) -> None:
        if not s.payload and not s.is_fin:
            return
        if s.seq < self.rcv_nxt:
            if s.is_fin and self.in_time_wait:
                self.time_wait_deadline = now + self.time_wait_duration
            self._send_ack(now)
            return
        if s.seq > self.rcv_nxt:
            occupied = len(self.ready) + sum(len(p) for p in self.ooo.values())
            if s.seq not in self.ooo and occupied + len(s.payload) <= self.recv_capacity:
                self.ooo[s.seq] = s.payload
            self._send_ack(now)
            return
        # In-order arrival. Deliberately not capacity-checked (unlike the
        # out-of-order path above): a compliant sender never exceeds our
        # last-advertised window, and the zero-window persist probe (see
        # _send_pending) specifically depends on a receiver accepting one
        # more byte even when its buffer is nominally full -- that's what
        # actually reveals a reopened window. A non-compliant/hostile
        # sender could exceed our stated capacity this way; Causeway's
        # threat model (its own demos, both ends cooperating) doesn't
        # include that case, exactly like a real TCP receiver.
        self.ready.extend(s.payload)
        self.rcv_nxt += len(s.payload)
        if s.is_fin:
            self.rcv_nxt += 1
            self.peer_fin_received = True
            self._emit("fin_received")
        while self.rcv_nxt in self.ooo:
            p = self.ooo.pop(self.rcv_nxt)
            self.ready.extend(p)
            self.rcv_nxt += len(p)
        self._send_ack(now)

    def _send_ack(self, now: float) -> None:
        ack = Segment(seq=self.snd_nxt, ack=self.rcv_nxt, window=self._my_advertised_window(), flags=ACK)
        self.wire.send(ack.encode())
        self.stats["segments_sent"] += 1

    def _my_advertised_window(self) -> int:
        occupied = len(self.ready) + sum(len(p) for p in self.ooo.values())
        return max(0, min(65535, self.recv_capacity - occupied))

    # -- sending -----------------------------------------------------------

    def _send_pending(self, now: float) -> None:
        if self.phase not in ("ESTABLISHED",):
            return
        sent_any = False
        while self.send_queue:
            budget = min(self.cwnd, self.peer_rwnd) - self.bytes_in_flight
            if budget < 1:
                break
            n = int(min(self.mss, budget, len(self.send_queue)))
            if n < 1:
                break
            self._take_and_send(n, now)
            sent_any = True
        if sent_any:
            self.persist_attempts = 0
        elif self.send_queue and self.peer_rwnd == 0:
            if now - self.last_probe_time >= self._persist_rto():
                self._take_and_send(1, now)
                self.last_probe_time = now
                self.persist_attempts += 1
                self.stats["persist_probes"] += 1
                self._emit("persist_probe")

        if (
            self.close_requested
            and not self.fin_sent
            and not self.send_queue
        ):
            fin = Segment(seq=self.snd_nxt, ack=self.rcv_nxt, window=self._my_advertised_window(),
                           flags=ACK | FIN)
            self.wire.send(fin.encode())
            self.unacked_segments.append(_OutSeg(seq=self.snd_nxt, flags=ACK | FIN, payload=b"", sent_time=now))
            self._fin_seq = self.snd_nxt
            self.snd_nxt += 1
            self.fin_sent = True
            self.stats["segments_sent"] += 1
            self._emit("fin_sent")

    def _take_and_send(self, n: int, now: float) -> None:
        chunk = bytes(self.send_queue[:n])
        del self.send_queue[:n]
        s = Segment(seq=self.snd_nxt, ack=self.rcv_nxt, window=self._my_advertised_window(),
                    flags=ACK, payload=chunk)
        self.wire.send(s.encode())
        self.unacked_segments.append(_OutSeg(seq=self.snd_nxt, flags=ACK, payload=chunk, sent_time=now))
        self.snd_nxt += len(chunk)
        self.stats["segments_sent"] += 1
        self._emit("sent_data")

    def _persist_rto(self) -> float:
        return min(self.persist_base * (2 ** self.persist_attempts), self.persist_max)

    def _retransmit(self, out: _OutSeg, now: float) -> None:
        s = Segment(seq=out.seq, ack=self.rcv_nxt, window=self._my_advertised_window(),
                     flags=out.flags, payload=out.payload)
        self.wire.send(s.encode())
        out.sent_time = now
        out.retransmit_count += 1
        self.stats["segments_sent"] += 1
        self.stats["retransmits"] += 1
        self._record_retransmission()

    def _record_retransmission(self) -> None:
        """Taint every byte currently in flight for RTT-sampling purposes.

        Without SACK, a cumulative-ACK receiver can't tell the sender which
        of several outstanding segments a given ACK is actually confirming
        the *timing* of: if segment A is lost and retransmitted while
        segment B (sent right after it, never itself retransmitted) is
        sitting behind it waiting on the cumulative ACK, the single ACK that
        finally covers both arrives only once A's retry succeeds -- so
        naively sampling B's "RTT" as (now - B.sent_time) measures A's whole
        loss-and-retry delay, not a real round trip. This is a real,
        well-known ambiguity in classic non-SACK TCP (one of the reasons
        RFC 7323 timestamps exist); Causeway's fix is the conservative one:
        hold off sampling entirely until an ACK arrives for data sent after
        the retransmission, at which point the ambiguity is gone.
        """
        self._rtt_sample_hold = max(self._rtt_sample_hold or 0, self.snd_nxt)

    def _sample_rtt_for_popped(self, popped: list, ack_value: int, now: float) -> None:
        if self._rtt_sample_hold is not None:
            if ack_value > self._rtt_sample_hold:
                self._rtt_sample_hold = None
            return
        for done in popped:
            if done.retransmit_count == 0:
                self.rtt.sample(now - done.sent_time)

    def _check_retransmit_timeout(self, now: float) -> None:
        if not self.unacked_segments:
            return
        oldest = self.unacked_segments[0]
        backoff = 2 ** min(oldest.retransmit_count, 6)
        deadline = oldest.sent_time + self.rtt.rto * backoff
        if now < deadline:
            return
        self.stats["timeouts"] += 1
        self.ssthresh = max(self.cwnd / 2, 2.0 * self.mss)
        self.cwnd = float(self.mss)
        self.in_fast_recovery = False
        self.dup_ack_count = 0
        self._retransmit(oldest, now)
        self._emit("timeout")

    # -- lifecycle -----------------------------------------------------------

    def next_timer_deadline(self) -> Optional[float]:
        """Earliest time at which this connection has internal work to do
        even with no incoming packet -- used by the discrete-event driver to
        know how far it may safely advance the virtual clock."""
        deadlines = []
        if self.unacked_segments:
            oldest = self.unacked_segments[0]
            backoff = 2 ** min(oldest.retransmit_count, 6)
            deadlines.append(oldest.sent_time + self.rtt.rto * backoff)
        if self.send_queue and self.peer_rwnd == 0:
            deadlines.append(self.last_probe_time + self._persist_rto())
        if self.in_time_wait and not self.closed:
            deadlines.append(self.time_wait_deadline)
        return min(deadlines) if deadlines else None

    def _advance_lifecycle(self, now: float) -> None:
        if self.closed:
            return
        if self.fin_sent and self.fin_acked and self.peer_fin_received and not self.in_time_wait:
            self.in_time_wait = True
            self.time_wait_deadline = now + self.time_wait_duration
            self._emit("time_wait")
        if self.in_time_wait and now >= self.time_wait_deadline:
            self.closed = True
            self._emit("closed")

    def _emit(self, kind: str) -> None:
        if self.on_event is None:
            return
        self.on_event({
            "t": self.clock.now(),
            "type": kind,
            "phase": self.phase,
            "cwnd": self.cwnd,
            "ssthresh": self.ssthresh,
            "srtt": self.rtt.srtt,
            "rto": self.rtt.rto,
            "in_flight": self.bytes_in_flight,
            "peer_rwnd": self.peer_rwnd,
            "snd_una": self.snd_una,
            "rcv_nxt": self.rcv_nxt,
            "in_fast_recovery": self.in_fast_recovery,
        })
