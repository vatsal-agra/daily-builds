"""A real (simplified) TCP implementation: handshake, byte-stream sliding
window, out-of-order reassembly, cumulative/duplicate ACKs, and the
RTO-timer/dup-ACK glue that drives `congestion.py`'s pluggable algorithms.

Deliberate, documented simplifications (also called out in README.md):

* Sequence numbers are unbounded Python ints — no 32-bit wraparound.
* One direction only: the "sender" transfers a byte stream to the
  "receiver"; the receiver never sends data back, only ACKs (like the
  response side of an HTTP GET). The sender still advertises a real
  (always-open) receive window on the segments it sends, as a real
  bidirectional stack would, even though nothing is ever sent into it.
* No delayed-ACK coalescing (RFC 1122 §4.2.3.2) — every received segment
  is ACKed immediately. This is itself a legitimate, once-common TCP
  configuration (delayed ACKs are an optimization, not a protocol
  requirement) and keeps RTT sampling and dup-ACK counting exact rather
  than approximated.
* Fast recovery is Reno-style, not NewReno: a recovery episode covering
  more than one lost segment resolves with a second round of dup ACKs
  rather than NewReno's partial-ACK handling. This is a real, named Reno
  limitation, not a shortcut invented for this build.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import congestion
from .network import AccessLink, Link, Simulator
from .packet import Segment
from .rtt import RttEstimator

DEFAULT_RECV_WINDOW = 65536


@dataclass
class Outstanding:
    seg: Segment
    send_time: float
    seq_len: int


class TcpSender:
    def __init__(
        self,
        sim: Simulator,
        mss: int,
        cc: congestion.CongestionControl,
        data: bytes,
        link_send: Callable[[Segment], None],
        recv_window: int = DEFAULT_RECV_WINDOW,
        rng: Optional[random.Random] = None,
        min_rto_s: float = 1.0,
    ) -> None:
        if mss <= 0:
            raise ValueError(f"mss must be positive, got {mss}")

        self.sim = sim
        self.mss = mss
        self.cc = cc
        # Per RFC 6298, the *pre-measurement* default RTO is 1s regardless
        # of any floor a caller applies to later, sample-derived RTOs --
        # except when a caller explicitly lowers min_rto_s below that
        # default (as tests do, to keep simulated timeouts fast), in which
        # case the initial guess should honor the same floor rather than
        # start needlessly conservative.
        self.rtt = RttEstimator(min_rto_s=min_rto_s, initial_rto_s=min(1.0, min_rto_s))
        self.data = data
        self.total_len = len(data)
        self.link_send = link_send
        self.recv_window = recv_window

        rng = rng or random.Random()
        self.iss = rng.randrange(0, 2 ** 30)
        self.next_seq = self.iss
        self.una = self.iss
        self.rwnd = DEFAULT_RECV_WINDOW
        self.irs: Optional[int] = None

        self.in_flight: Dict[int, Outstanding] = {}
        self.dup_ack_count = 0
        self.state = "CLOSED"
        self.timer_epoch = 0
        self.fin_seq: Optional[int] = None

        self.start_time: Optional[float] = None
        self.done = False
        self.done_time: Optional[float] = None

        self.timeouts = 0
        self.fast_retransmits = 0
        self.segments_sent = 0

        self.cwnd_series: List[Tuple[float, float]] = []
        self.rtt_series: List[Tuple[float, float]] = []
        self.inflight_series: List[Tuple[float, int]] = []

    # -- helpers ---------------------------------------------------------

    def _flight_bytes(self) -> int:
        return sum(o.seq_len for o in self.in_flight.values())

    def _record_sample(self, now: float) -> None:
        self.cwnd_series.append((now, self.cc.cwnd))
        self.rtt_series.append((now, self.rtt.srtt if self.rtt.srtt is not None else float("nan")))
        self.inflight_series.append((now, self._flight_bytes()))

    def _reset_timer(self) -> None:
        self.timer_epoch += 1
        if self.in_flight:
            epoch = self.timer_epoch
            self.sim.schedule_after(self.rtt.rto, lambda: self._on_timer(epoch))

    def _cancel_timer(self) -> None:
        self.timer_epoch += 1

    def _send_segment(self, seg: Segment) -> None:
        now = self.sim.now
        seg.send_time = now
        self.in_flight[seg.seq] = Outstanding(seg=seg, send_time=now, seq_len=seg.seq_len)
        self.segments_sent += 1
        self.link_send(seg)
        self._reset_timer()

    # -- handshake ---------------------------------------------------------

    def connect(self) -> None:
        self.state = "SYN_SENT"
        self.start_time = self.sim.now
        syn = Segment(seq=self.iss, ack=0, syn=True, window=self.recv_window)
        self.next_seq = self.iss + 1  # SYN consumes one sequence number, immediately
        self._send_segment(syn)

    # -- inbound (ACKs / SYN-ACK) from the receiver -----------------------

    def on_segment(self, seg: Segment, now: float) -> None:
        if self.state == "SYN_SENT":
            if seg.syn and seg.ack_flag and seg.ack == self.iss + 1:
                self.in_flight.pop(self.iss, None)
                self.una = self.iss + 1
                self.irs = seg.seq
                self.rwnd = seg.window
                self.state = "ESTABLISHED"
                self._cancel_timer()
                ack = Segment(seq=self.next_seq, ack=self.irs + 1, ack_flag=True, window=self.recv_window)
                self.link_send(ack)
                self._maybe_send_more(now)
            return

        if self.state in ("ESTABLISHED", "FIN_WAIT"):
            self._process_ack(seg, now)

    def _process_ack(self, seg: Segment, now: float) -> None:
        if not seg.ack_flag:
            return
        self.rwnd = seg.window

        if seg.ack > self.una:
            flight_before = self._flight_bytes()
            newly_acked = 0
            for k in sorted(k for k in self.in_flight if k < seg.ack):
                out = self.in_flight.pop(k)
                newly_acked += out.seq_len
                if not out.seg.is_retransmit:
                    self.rtt.sample(now - out.send_time)

            was_recovery = self.cc.in_recovery
            self.una = seg.ack
            self.dup_ack_count = 0

            if was_recovery:
                self.cc.on_recovery_ack()
            else:
                self.cc.on_ack(newly_acked, flight_before, now)

            self._record_sample(now)
            if self.in_flight:
                self._reset_timer()
            else:
                self._cancel_timer()

            if self.state == "FIN_WAIT" and not self.in_flight and self.fin_seq is not None and self.una >= self.fin_seq + 1:
                self.state = "CLOSED"
                self.done = True
                self.done_time = now
                return

            self._maybe_send_more(now)

        elif seg.ack == self.una and self.in_flight:
            self.dup_ack_count += 1
            flight_before = self._flight_bytes()
            fire = self.cc.on_dup_ack(self.dup_ack_count, flight_before)
            self._record_sample(now)
            if fire:
                self.fast_retransmits += 1
                oldest = min(self.in_flight)
                out = self.in_flight.pop(oldest)
                retseg = out.seg.clone_for_retransmit()
                self._send_segment(retseg)
            self._maybe_send_more(now)

    def _on_timer(self, epoch: int) -> None:
        if epoch != self.timer_epoch or not self.in_flight:
            return
        oldest = min(self.in_flight)
        out = self.in_flight.pop(oldest)
        flight_before = out.seq_len + self._flight_bytes()
        self.cc.on_timeout(flight_before)
        self.timeouts += 1
        self.rtt.backoff()
        retseg = out.seg.clone_for_retransmit()
        self._send_segment(retseg)
        # A timeout during the handshake retransmits the SYN itself (the
        # only thing that can be in `in_flight` in SYN_SENT); there is no
        # data to send yet (self.irs isn't even known), so trying to fill
        # the window here would crash on `self.irs + 1` — this was a real
        # bug caught by fuzzing (see REVIEW.md).
        if self.state != "SYN_SENT":
            self._maybe_send_more(self.sim.now)

    # -- outbound data -----------------------------------------------------

    def _maybe_send_more(self, now: float) -> None:
        sent_data_bytes = (self.next_seq - (self.iss + 1))
        while True:
            flight = self._flight_bytes()
            window = min(self.cc.cwnd, self.rwnd)
            if flight >= window:
                break
            if sent_data_bytes >= self.total_len:
                if not self.fin_seq and self.una == self.iss + 1 + self.total_len:
                    self._send_fin()
                break
            room = int(window - flight)
            if room <= 0:
                break
            chunk_len = min(self.mss, room, self.total_len - sent_data_bytes)
            if chunk_len <= 0:
                break
            offset = sent_data_bytes
            payload = self.data[offset: offset + chunk_len]
            seg = Segment(seq=self.next_seq, ack=self.irs + 1, ack_flag=True,
                          window=self.recv_window, payload=payload)
            self.next_seq += chunk_len
            sent_data_bytes += chunk_len
            self._send_segment(seg)

    def _send_fin(self) -> None:
        seg = Segment(seq=self.next_seq, ack=self.irs + 1, ack_flag=True, fin=True,
                      window=self.recv_window)
        self.fin_seq = self.next_seq
        self.next_seq += 1
        self.state = "FIN_WAIT"
        self._send_segment(seg)


class TcpReceiver:
    def __init__(
        self,
        sim: Simulator,
        link_send: Callable[[Segment], None],
        recv_window_capacity: int = DEFAULT_RECV_WINDOW,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.sim = sim
        self.link_send = link_send
        self.recv_window_capacity = recv_window_capacity

        rng = rng or random.Random()
        self.iss = rng.randrange(0, 2 ** 30)
        self.irs: Optional[int] = None
        self.rcv_nxt: Optional[int] = None
        self.state = "LISTEN"

        self.out_of_order: Dict[int, bytes] = {}
        self.assembled = bytearray()
        self.duplicate_segments = 0
        self.fin_received = False
        self.done = False
        self.done_time: Optional[float] = None

    def _out_of_order_bytes(self) -> int:
        return sum(len(v) for v in self.out_of_order.values())

    def _advertised_window(self) -> int:
        return max(0, self.recv_window_capacity - self._out_of_order_bytes())

    def on_segment(self, seg: Segment, now: float) -> None:
        if self.state == "LISTEN":
            if seg.syn:
                self.irs = seg.seq
                self.rcv_nxt = self.irs + 1
                self.state = "SYN_RCVD"
                synack = Segment(seq=self.iss, ack=self.rcv_nxt, syn=True, ack_flag=True,
                                  window=self._advertised_window())
                self.link_send(synack)
            return

        if self.state == "SYN_RCVD":
            # Real TCP sets ACK on every segment following the initial SYN,
            # so *any* such segment — the handshake's bare completion ACK,
            # or (if that ACK itself was lost) the first real data segment,
            # which also carries ack_flag=True — is enough to confirm the
            # handshake and move to ESTABLISHED. This closes a real
            # deadlock: without it, a dropped final-ACK would leave the
            # receiver stuck in SYN_RCVD forever, since data segments are
            # otherwise only handled in the ESTABLISHED state.
            if seg.ack_flag and not seg.syn and seg.ack == self.iss + 1:
                self.state = "ESTABLISHED"
                self._handle_data(seg, now)
            return

        if self.state == "ESTABLISHED":
            self._handle_data(seg, now)

    def _drain_out_of_order(self) -> None:
        assert self.rcv_nxt is not None
        while self.rcv_nxt in self.out_of_order:
            chunk = self.out_of_order.pop(self.rcv_nxt)
            self.assembled.extend(chunk)
            self.rcv_nxt += len(chunk)
        stale = [k for k in self.out_of_order if k < self.rcv_nxt]
        for k in stale:
            del self.out_of_order[k]

    def _handle_data(self, seg: Segment, now: float) -> None:
        assert self.rcv_nxt is not None
        payload = seg.payload
        if payload:
            seq = seg.seq
            end = seq + len(payload)
            if end <= self.rcv_nxt:
                self.duplicate_segments += 1
            elif seq <= self.rcv_nxt:
                new_part = payload[self.rcv_nxt - seq:]
                self.assembled.extend(new_part)
                self.rcv_nxt += len(new_part)
                self._drain_out_of_order()
            else:
                if seq not in self.out_of_order and len(payload) <= self._advertised_window():
                    self.out_of_order[seq] = payload

        if seg.fin and seg.seq == self.rcv_nxt:
            self.rcv_nxt += 1
            self.fin_received = True

        ack = Segment(seq=self.iss + 1, ack=self.rcv_nxt, ack_flag=True, window=self._advertised_window())
        self.link_send(ack)

        if self.fin_received and not self.done:
            self.done = True
            self.done_time = now


class Topology:
    """A simplified dumbbell: one shared bandwidth-limited bottleneck link
    in each direction (`fwd_link` carries data, `rev_link` carries ACKs),
    with each registered flow given its own "last-mile" `AccessLink` delay
    applied once on the sender's outbound leg and once on the sender's
    inbound (ACK-return) leg. That's enough to give competing flows
    different RTTs for the fairness/RTT-bias experiments while keeping the
    congestion interaction concentrated in one real, shared, finite buffer
    — the actual thing being studied."""

    def __init__(
        self,
        sim: Simulator,
        fwd_bandwidth_Bps: float,
        fwd_buffer_bytes: int,
        core_prop_delay_s: float,
        fwd_loss_prob: float = 0.0,
        fwd_reorder_prob: float = 0.0,
        rev_bandwidth_Bps: Optional[float] = None,
        rev_buffer_bytes: Optional[int] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.sim = sim
        rng = rng or random.Random()
        self.fwd_link = Link(sim, fwd_bandwidth_Bps, fwd_buffer_bytes, core_prop_delay_s,
                              fwd_loss_prob, fwd_reorder_prob, rng, name="fwd")
        self.rev_link = Link(sim, rev_bandwidth_Bps or fwd_bandwidth_Bps * 4,
                              rev_buffer_bytes or fwd_buffer_bytes, core_prop_delay_s,
                              0.0, 0.0, rng, name="rev")
        self.access: Dict[int, AccessLink] = {}
        self.receiver_cb: Dict[int, Callable[[Segment, float], None]] = {}
        self.sender_cb: Dict[int, Callable[[Segment, float], None]] = {}

    def add_flow(self, flow_id: int, access_delay_s: float,
                 on_deliver_to_receiver: Callable[[Segment, float], None],
                 on_deliver_to_sender: Callable[[Segment, float], None]) -> None:
        self.access[flow_id] = AccessLink(self.sim, access_delay_s)
        self.receiver_cb[flow_id] = on_deliver_to_receiver
        self.sender_cb[flow_id] = on_deliver_to_sender

    def send_from_sender(self, flow_id: int, seg: Segment) -> None:
        seg.flow_id = flow_id
        access = self.access[flow_id]

        def to_bottleneck(pkt: Segment, t: float) -> None:
            self.fwd_link.send(pkt, lambda pkt2, t2: self.receiver_cb[flow_id](pkt2, t2))

        access.send(seg, to_bottleneck)

    def send_from_receiver(self, flow_id: int, seg: Segment) -> None:
        seg.flow_id = flow_id

        def to_access(pkt: Segment, t: float) -> None:
            self.access[flow_id].send(pkt, lambda pkt2, t2: self.sender_cb[flow_id](pkt2, t2))

        self.rev_link.send(seg, to_access)


class TcpConnection:
    def __init__(
        self,
        sim: Simulator,
        flow_id: int,
        topology: Topology,
        data: bytes,
        access_delay_s: float,
        mss: int = 1460,
        cc_name: str = "reno",
        recv_window: int = DEFAULT_RECV_WINDOW,
        rng: Optional[random.Random] = None,
        min_rto_s: float = 1.0,
    ) -> None:
        rng = rng or random.Random()
        cc = congestion.make(cc_name, mss)
        self.flow_id = flow_id
        self.cc_name = cc_name
        self.sender = TcpSender(
            sim, mss, cc, data,
            link_send=lambda seg: topology.send_from_sender(flow_id, seg),
            recv_window=recv_window, rng=rng, min_rto_s=min_rto_s,
        )
        self.receiver = TcpReceiver(
            sim,
            link_send=lambda seg: topology.send_from_receiver(flow_id, seg),
            recv_window_capacity=recv_window, rng=rng,
        )
        topology.add_flow(flow_id, access_delay_s,
                           on_deliver_to_receiver=self.receiver.on_segment,
                           on_deliver_to_sender=self.sender.on_segment)

    def start(self) -> None:
        self.sender.connect()

    @property
    def finished(self) -> bool:
        return self.receiver.done and self.sender.done
