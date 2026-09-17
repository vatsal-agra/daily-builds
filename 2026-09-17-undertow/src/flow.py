"""TCP-alike loss detection/recovery machinery (shared by every algorithm)
wired to one congestion-control strategy object, plus the minimal receiver
needed to generate real cumulative/duplicate ACKs.

This module owns: cumulative ACK bookkeeping, triple-duplicate-ACK fast
retransmit + fast recovery (RFC 5681 sec. 3.2 — the window-inflation dance
during recovery is generic across Reno/CUBIC/BBR, so it lives here, not in
any one algorithm), RTO computation via the Jacobson/Karels estimator
(RFC 6298), and exponential timeout backoff.
"""

from __future__ import annotations

import itertools

from .packet import Packet

MSS = 1400  # bytes, a realistic Ethernet-safe TCP segment size
INITIAL_RTO_S = 1.0
MIN_RTO_S = 0.2
MAX_RTO_S = 60.0


class Receiver:
    """Cumulative-ACK receiver: no SACK, matching classic Reno/CUBIC/BBR
    deployments this simulator targets. A gap produces a duplicate ACK for
    the last in-order byte, exactly like real TCP."""

    def __init__(self) -> None:
        self.expected_seq = 0
        self._out_of_order: set[int] = set()
        self.delivered_count = 0  # distinct logical segments delivered in order
        self.delivery_log: list[tuple[float, int]] = []  # (time, cumulative delivered_count)

    def on_packet(self, seq: int, now: float) -> int:
        if seq == self.expected_seq:
            self.expected_seq += 1
            self.delivered_count += 1
            self.delivery_log.append((now, self.delivered_count))
            while self.expected_seq in self._out_of_order:
                self._out_of_order.discard(self.expected_seq)
                self.expected_seq += 1
                self.delivered_count += 1
                self.delivery_log.append((now, self.delivered_count))
        elif seq > self.expected_seq:
            self._out_of_order.add(seq)
        # seq < expected_seq: already-delivered duplicate, just re-ACK.
        return self.expected_seq


class Sender:
    def __init__(self, flow_id: int, ev, cc, total_packets: int, send_fn):
        self.flow_id = flow_id
        self.ev = ev
        self.cc = cc
        self.total_packets = total_packets
        self._send_fn = send_fn  # (packet) -> None, injects onto the network

        self.next_seq = 0
        self.send_base = 0
        self.in_flight: dict[int, dict] = {}
        self.dup_ack_count = 0
        self.in_recovery = False
        self.recovery_point = -1  # NewReno "recover": highest seq sent when recovery began
        self._recovery_inflates_left = 0

        self.srtt: float | None = None
        self.rttvar: float | None = None
        self.rto = INITIAL_RTO_S
        self.timer_gen = 0
        self._timer_running = False

        self._phys_id_counter = itertools.count()
        self.finish_time: float | None = None
        self.samples: list[tuple[float, float, float | None]] = []  # (t, cwnd, srtt)
        self.loss_events: list[tuple[float, str]] = []  # (t, "fast_retransmit"|"timeout")

    # -- sending --------------------------------------------------------
    def start(self) -> None:
        self.try_send()

    def try_send(self) -> None:
        sent_any = False
        while self.next_seq < self.total_packets and len(self.in_flight) < self.cc.cwnd:
            self._transmit(self.next_seq, is_retransmit=False)
            self.next_seq += 1
            sent_any = True
        if sent_any:
            self._ensure_timer_running()

    def _transmit(self, seq: int, is_retransmit: bool) -> None:
        now = self.ev.now
        info = self.in_flight.get(seq)
        if info is None:
            info = {"send_time": now, "retransmit": is_retransmit}
            self.in_flight[seq] = info
        else:
            info["send_time"] = now
            info["retransmit"] = True
        pkt = Packet(
            flow_id=self.flow_id,
            seq=seq,
            phys_id=next(self._phys_id_counter),
            size_bytes=MSS,
            send_time=now,
            is_retransmit=is_retransmit,
        )
        self._send_fn(pkt)

    def _ensure_timer_running(self) -> None:
        if not self._timer_running and self.in_flight:
            self._start_timer()

    # -- ACK handling -----------------------------------------------------
    def on_ack(self, ack_num: int, now: float) -> None:
        if ack_num > self.send_base:
            newly_acked = ack_num - self.send_base
            sample_info = self.in_flight.get(ack_num - 1)
            rtt_sample = None
            if sample_info is not None and not sample_info["retransmit"]:
                rtt_sample = now - sample_info["send_time"]
                self._update_rtt(rtt_sample)
            for s in range(self.send_base, ack_num):
                self.in_flight.pop(s, None)
            self.send_base = ack_num
            self.dup_ack_count = 0

            # NewReno (RFC 6582) partial-ACK handling: a burst that
            # overshoots a shallow buffer routinely drops *several*
            # segments in the same window. Without this, the sender only
            # ever repairs the one segment that triggered fast retransmit
            # and then has to wait out a full RTO — often several seconds
            # with exponential backoff — for every other segment lost in
            # the same burst, effectively stalling the flow.
            retransmit_next_lost = False
            if self.in_recovery:
                if ack_num > self.recovery_point:
                    self.in_recovery = False
                    self.cc.exit_fast_recovery()
                else:
                    retransmit_next_lost = True
            else:
                self.cc.on_ack(now, rtt_sample, newly_acked, inflight=len(self.in_flight))

            self._cancel_timer()
            if retransmit_next_lost:
                self._transmit(self.send_base, is_retransmit=True)
            if self.in_flight:
                self._start_timer()
            self.samples.append((now, self.cc.cwnd, self.srtt))
            if self.send_base >= self.total_packets and not self.in_flight:
                self.finish_time = now
            self.try_send()
        elif ack_num == self.send_base and self.send_base < self.next_seq:
            self.dup_ack_count += 1
            if self.dup_ack_count == 3 and not self.in_recovery:
                self.in_recovery = True
                self.recovery_point = self.next_seq - 1
                # RFC 5681's rationale for "+1 cwnd per dup ACK beyond the
                # 3rd" is packet conservation: each one supposedly means a
                # packet has *left* the network, freeing room for a new
                # one. That reasoning only holds for the packets that were
                # actually in flight when the loss was detected — it is
                # not a license to inflate forever. Without this cap, if
                # the retransmitted segment itself is unlucky enough to be
                # dropped again, every later out-of-order arrival keeps
                # generating another duplicate ACK for the same still-stuck
                # send_base, and cwnd (and thus how much new data gets
                # flooded at an already-overloaded queue) grows without
                # bound for as long as that one segment stays lost.
                self._recovery_inflates_left = max(0, self.recovery_point - self.send_base)
                self.cc.on_loss_event(now)
                self.cc.enter_fast_recovery_inflate()
                self.loss_events.append((now, "fast_retransmit"))
                self._cancel_timer()
                self._transmit(self.send_base, is_retransmit=True)
                self._start_timer()
                self.samples.append((now, self.cc.cwnd, self.srtt))
            elif self.dup_ack_count > 3 and self.in_recovery and self._recovery_inflates_left > 0:
                self._recovery_inflates_left -= 1
                self.cc.dup_ack_inflate()
                self.try_send()

    # -- RTT / RTO (RFC 6298) ---------------------------------------------
    def _update_rtt(self, r: float) -> None:
        if self.srtt is None:
            self.srtt = r
            self.rttvar = r / 2
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - r)
            self.srtt = 0.875 * self.srtt + 0.125 * r
        self.rto = min(MAX_RTO_S, max(MIN_RTO_S, self.srtt + max(0.01, 4 * self.rttvar)))

    def _start_timer(self) -> None:
        self.timer_gen += 1
        gen = self.timer_gen
        self._timer_running = True
        self.ev.schedule(self.rto, lambda: self._timer_fire(gen))

    def _cancel_timer(self) -> None:
        self.timer_gen += 1
        self._timer_running = False

    def _timer_fire(self, gen: int) -> None:
        if gen != self.timer_gen or not self.in_flight:
            return
        now = self.ev.now
        self.cc.on_timeout(now)
        self.in_recovery = False
        self.dup_ack_count = 0
        self.rto = min(MAX_RTO_S, self.rto * 2)
        self.loss_events.append((now, "timeout"))
        self._transmit(self.send_base, is_retransmit=True)
        self.samples.append((now, self.cc.cwnd, self.srtt))
        self._start_timer()


class Flow:
    """Wires a Sender + Receiver for one logical connection into a shared
    Network/Bottleneck: forward data packets funnel through the contended
    queue, ACKs travel back over an uncongested reverse path."""

    def __init__(self, flow_id: int, name: str, ev, network, cc, total_packets: int, access_delay_s: float):
        self.flow_id = flow_id
        self.name = name
        self.ev = ev
        self.network = network
        self.access_delay_s = access_delay_s
        self.receiver = Receiver()
        self.sender = Sender(flow_id, ev, cc, total_packets, self._send_data)
        self.cc = cc

    def base_owd(self) -> float:
        return self.access_delay_s + self.network.bottleneck.prop_delay_s

    def _send_data(self, packet: Packet) -> None:
        self.network.register_inflight(packet)
        self.ev.schedule(self.access_delay_s, lambda p=packet: self.network.bottleneck.enqueue(p))

    def on_data_delivered(self, packet: Packet) -> None:
        ack_num = self.receiver.on_packet(packet.seq, self.ev.now)
        # ACK path: assumed uncongested (no queueing), same physical
        # distance as the data path, hence the same one-way delay.
        self.ev.schedule(self.base_owd(), lambda: self.sender.on_ack(ack_num, self.ev.now))

    def start(self) -> None:
        self.sender.start()
