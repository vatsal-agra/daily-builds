"""The Undertow protocol state machine.

A ``Connection`` drives one point-to-point reliable byte stream over
anything that looks like a connected UDP socket (``.sendto(bytes)`` /
``.recvfrom(bufsize, timeout) -> bytes``): a 3-way handshake, a sliding
send/receive window, retransmission on RTO, fast retransmit on duplicate
ACKs, and graceful FIN/ACK teardown — all driven by one background thread
per connection so the public API (``send``/``recv``/``close``) can be used
from an application thread while packets are handled as they arrive.

SYN and FIN each consume exactly one byte of sequence space, exactly like
real TCP, which is what lets the same retransmission/ack machinery that
handles data segments also handle the handshake and teardown without any
special-cased retry logic.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field

from .congestion import CongestionController, RenoCongestionController
from .packet import FLAG_ACK, FLAG_FIN, FLAG_RST, FLAG_SYN, MAX_SACK_BLOCKS, MSS, Packet, PacketError
from .rto import RTOEstimator
from .seqmath import seq_add, seq_diff, seq_ge, seq_gt, seq_le

STATE_CLOSED = "CLOSED"
STATE_LISTEN = "LISTEN"
STATE_SYN_SENT = "SYN_SENT"
STATE_SYN_RCVD = "SYN_RCVD"
STATE_ESTABLISHED = "ESTABLISHED"
STATE_FIN_WAIT = "FIN_WAIT"
STATE_CLOSE_WAIT = "CLOSE_WAIT"
STATE_LAST_ACK = "LAST_ACK"

RECV_WINDOW_CAP = 65535
POLL_INTERVAL = 0.01
LINGER = 0.3
PERSIST_MIN_INTERVAL = 0.5


@dataclass
class _Segment:
    seq: int
    data: bytes
    flags: int
    send_time: float
    retransmit_count: int = 0

    def seqlen(self) -> int:
        return len(self.data) + (1 if self.flags & (FLAG_SYN | FLAG_FIN) else 0)


class ConnectionError_(ConnectionError):
    pass


class Connection:
    def __init__(
        self,
        transport,
        congestion_controller: CongestionController | None = None,
        mss: int = MSS,
        initial_seq: int | None = None,
        trace: bool = True,
    ) -> None:
        self.transport = transport
        self.cc = congestion_controller or RenoCongestionController(mss=mss)
        self.mss = mss
        self.rto = RTOEstimator()
        self._forced_isn = initial_seq

        self.state = STATE_CLOSED
        self.iss: int | None = None
        self.irs: int | None = None
        self.send_una: int | None = None
        self.send_next: int | None = None
        self.recv_next: int | None = None

        self.pending = bytearray()  # app bytes not yet carved into segments
        self.unacked: dict[int, _Segment] = {}
        self.recv_buffer: dict[int, bytes] = {}  # out-of-order received chunks
        self.unread = bytearray()  # in-order, delivered, not yet read by app
        self.peer_window = RECV_WINDOW_CAP
        self.peer_sack_blocks: list[tuple[int, int]] = []
        self.dup_ack_run = 0
        self._fin_seq: int | None = None
        self._peer_fin_seq: int | None = None
        self._peer_closed = False
        self._aborted = False
        self._close_requested = False
        self._linger_until: float | None = None
        self._last_advertised_window = RECV_WINDOW_CAP
        self._last_persist_probe = 0.0

        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._established_event = threading.Event()
        self._closed_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stop = False

        self._t0 = time.monotonic()
        self._trace_enabled = trace
        self.trace_log: list[dict] = []

    # ------------------------------------------------------------------ #
    # tracing
    def _trace(self, event: str, **kw) -> None:
        if not self._trace_enabled:
            return
        self.trace_log.append({"t": time.monotonic() - self._t0, "event": event, **kw})

    def _record_cwnd(self) -> None:
        self._trace(
            "cwnd",
            cwnd=self.cc.cwnd,
            ssthresh=getattr(self.cc, "ssthresh", None),
            cc_state=getattr(self.cc, "state", None),
            rto=self.rto.current(),
        )

    # ------------------------------------------------------------------ #
    # public API
    def connect(self, timeout: float = 10.0) -> None:
        with self._lock:
            self.iss = self._initial_seq()
            self.send_una = self.iss
            self.send_next = self.iss
            self.state = STATE_SYN_SENT
        self._start_thread()
        with self._lock:
            self._enqueue_control(self.iss, FLAG_SYN, time.monotonic())
        if not self._established_event.wait(timeout):
            self._abort()
            raise TimeoutError("connect() timed out waiting for the handshake")

    def accept(self, timeout: float = 30.0) -> None:
        with self._lock:
            self.state = STATE_LISTEN
        self._start_thread()
        if not self._established_event.wait(timeout):
            self._abort()
            raise TimeoutError("accept() timed out waiting for a connection")

    def send(self, data: bytes) -> None:
        with self._lock:
            if self.state != STATE_ESTABLISHED:
                raise ConnectionError_(f"cannot send() in state {self.state}")
            self.pending.extend(data)

    def recv(self, maxlen: int, timeout: float | None = None) -> bytes:
        """Read up to `maxlen` bytes. Returns b'' once the peer has closed
        and everything it sent has been delivered (EOF). Raises
        ConnectionError_ if the connection was reset (RST) with nothing
        left to deliver.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while not self.unread and not self._peer_closed:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("recv() timed out")
                self._cv.wait(timeout=remaining)
            if not self.unread and self._aborted:
                raise ConnectionError_("connection reset")
            chunk = bytes(self.unread[:maxlen])
            del self.unread[:maxlen]
            self._maybe_send_window_update()
            return chunk

    def recv_all(self, timeout: float = 120.0) -> bytes:
        """Read until the peer closes (EOF). Only meaningful once the peer
        has called (or will soon call) close() -- if both ends call
        recv_all() while waiting on each other's full stream and neither
        has closed its own send side, this blocks forever on both sides,
        the same way a blocking read on a socket that's open on both ends
        would. For simultaneous bidirectional traffic of a known size, use
        repeated recv(n) calls instead.
        """
        out = bytearray()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("recv_all() timed out")
            chunk = self.recv(65536, timeout=remaining)
            if chunk:
                out.extend(chunk)
                continue
            with self._lock:
                if self._peer_closed and not self.unread:
                    break
        return bytes(out)

    def close(self, timeout: float = 15.0) -> None:
        with self._lock:
            if self.state not in (STATE_ESTABLISHED, STATE_CLOSE_WAIT):
                if self.state in (STATE_CLOSED,) or self._closed_event.is_set():
                    return
                raise ConnectionError_(f"cannot close() in state {self.state}")
            self._close_requested = True
        if not self._closed_event.wait(timeout):
            raise TimeoutError("close() timed out waiting for teardown")

    def abort(self, reason: str = "") -> None:
        """Abruptly reset the connection: sends one RST, then tears down
        locally without waiting for any acknowledgment (RST isn't acked)."""
        with self._lock:
            if self.state not in (STATE_CLOSED,):
                pkt = Packet(seq=self.send_next or 0, ack=self.recv_next or 0, flags=FLAG_RST)
                try:
                    self.transport.sendto(pkt.encode())
                except OSError:
                    pass
            self._trace("abort_sent", reason=reason)
        self._abort()

    @property
    def is_established(self) -> bool:
        return self.state == STATE_ESTABLISHED

    def stats(self) -> dict:
        with self._lock:
            return {
                "state": self.state,
                "cwnd": self.cc.cwnd,
                "ssthresh": getattr(self.cc, "ssthresh", None),
                "cc_state": getattr(self.cc, "state", None),
                "srtt": self.rto.srtt,
                "rto": self.rto.current(),
                "samples_taken": self.rto.samples_taken,
            }

    # ------------------------------------------------------------------ #
    # internals
    def _initial_seq(self) -> int:
        return self._forced_isn if self._forced_isn is not None else random.getrandbits(32)

    def _start_thread(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _abort(self) -> None:
        with self._lock:
            self._stop = True
            self._aborted = True
            self._peer_closed = True  # unblocks any blocked recv()/recv_all()
            self.state = STATE_CLOSED
        self._established_event.set()
        self._closed_event.set()
        with self._cv:
            self._cv.notify_all()

    def _send_packet(self, pkt: Packet) -> None:
        """The single choke point every outgoing packet goes through, so
        window bookkeeping (for the zero-window recovery logic below) never
        drifts out of sync with what was actually put on the wire."""
        self.transport.sendto(pkt.encode())
        self._last_advertised_window = pkt.window

    def _advertised_window(self) -> int:
        used = len(self.unread) + sum(len(v) for v in self.recv_buffer.values())
        return max(0, min(RECV_WINDOW_CAP, RECV_WINDOW_CAP - used))

    def _maybe_send_window_update(self) -> None:
        """Real TCP deadlocks if a sender that's been told "window: 0"
        never learns the receiver's app drained its buffer, because an
        ACK carrying that news is never re-sent on its own. Real stacks
        fix this two ways: the receiver proactively announces a reopened
        window (this method, called whenever the app calls recv()), and
        the sender periodically probes with 1 byte in case that
        announcement itself is lost (see the persist-probe logic in
        _send_pending). Undertow does both, for the same reason.
        """
        if self.send_next is None or self.recv_next is None:
            return
        new_window = self._advertised_window()
        if self._last_advertised_window < self.mss and new_window >= self.mss:
            pkt = Packet(
                seq=self.send_next,
                ack=self.recv_next,
                flags=FLAG_ACK,
                window=new_window,
                sack_blocks=self._compute_sack_blocks(),
            )
            self._send_packet(pkt)
            self._trace("window_update", window=new_window)

    def _seg_len(self, seg: _Segment) -> int:
        return seg.seqlen()

    def _enqueue_control(self, seq: int, flags: int, now: float) -> None:
        seg = _Segment(seq=seq, data=b"", flags=flags, send_time=now)
        self.unacked[seq] = seg
        self.send_next = seq_add(seq, seg.seqlen())
        pkt = Packet(seq=seq, ack=self.recv_next or 0, flags=flags, window=self._advertised_window())
        self._send_packet(pkt)
        self._trace("send_ctrl", seq=seq, flags=flags)

    def _compute_sack_blocks(self) -> list[tuple[int, int]]:
        if not self.recv_buffer:
            return []
        items = sorted(self.recv_buffer.items(), key=lambda kv: seq_diff(self.recv_next, kv[0]))
        blocks: list[tuple[int, int]] = []
        cur_start = cur_end = None
        for seq, data in items:
            end = seq_add(seq, len(data))
            if cur_start is None:
                cur_start, cur_end = seq, end
            elif seq == cur_end:
                cur_end = end
            else:
                blocks.append((cur_start, cur_end))
                cur_start, cur_end = seq, end
        blocks.append((cur_start, cur_end))
        return blocks[:MAX_SACK_BLOCKS]

    # -- the main loop, run in a background thread --------------------- #
    def _loop(self) -> None:
        while True:
            raw = None
            try:
                raw = self.transport.recvfrom(4096, timeout=POLL_INTERVAL)
            except OSError:
                raw = None
            now = time.monotonic()
            with self._lock:
                if raw:
                    try:
                        pkt = Packet.decode(raw)
                    except PacketError:
                        pkt = None
                    if pkt is not None:
                        self._handle_packet(pkt, now)
                self._handle_timers(now)
                self._maybe_finish_close(now)
                if self._stop and (self._linger_until is None or now >= self._linger_until):
                    return

    # -- packet handling ------------------------------------------------ #
    def _handle_packet(self, pkt: Packet, now: float) -> None:
        if pkt.is_rst:
            self._abort()
            return

        if pkt.is_syn and self.irs is None:
            self.irs = pkt.seq
            self.recv_next = seq_add(self.irs, 1)
            if self.state == STATE_LISTEN:
                self.iss = self._initial_seq()
                self.send_una = self.iss
                self.send_next = self.iss
                self.state = STATE_SYN_RCVD
                self._enqueue_control(self.iss, FLAG_SYN | FLAG_ACK, now)

        if pkt.is_ack and self.iss is not None:
            self._process_ack(pkt, now)

        if (
            self.state in (STATE_SYN_SENT, STATE_SYN_RCVD)
            and self.irs is not None
            and self.send_una == self.send_next
        ):
            if self.state == STATE_SYN_SENT:
                ack_pkt = Packet(seq=self.send_next, ack=self.recv_next, flags=FLAG_ACK, window=self._advertised_window())
                self._send_packet(ack_pkt)
                self._trace("send_final_handshake_ack")
            self.state = STATE_ESTABLISHED
            self._established_event.set()

        if self.irs is not None:
            self._process_data(pkt, now)

        self._maybe_finish_close(now)

    def _process_ack(self, pkt: Packet, now: float) -> None:
        if self.send_una is None:
            return
        if seq_gt(pkt.ack, self.send_una):
            acked_amt = seq_diff(self.send_una, pkt.ack)
            for seq in list(self.unacked):
                seg = self.unacked[seq]
                seg_end = seq_add(seq, self._seg_len(seg))
                if seq_le(seg_end, pkt.ack):
                    if seg.retransmit_count == 0:
                        self.rto.sample(max(1e-6, now - seg.send_time))
                    del self.unacked[seq]
                    self._trace("acked", seq=seg.seq, len=self._seg_len(seg))
            self.send_una = pkt.ack
            self.peer_window = pkt.window
            self.cc.on_new_ack(acked_amt)
            self.dup_ack_run = 0
            self._record_cwnd()
        else:
            self.peer_window = pkt.window
            if pkt.ack == self.send_una and not pkt.payload and self.unacked:
                self.dup_ack_run += 1
                if self.cc.on_dup_ack():
                    self._trace("fast_retransmit", seq=self.send_una, dup_acks=self.dup_ack_run)
                    seg = self.unacked.get(self.send_una)
                    if seg is not None:
                        self._retransmit(seg, now)
                    self._record_cwnd()
        self.peer_sack_blocks = pkt.sack_blocks

    def _process_data(self, pkt: Packet, now: float) -> None:
        got_something = False

        if pkt.payload:
            if seq_ge(pkt.seq, self.recv_next) and pkt.seq not in self.recv_buffer:
                # Enforce our own advertised window defensively: a
                # well-behaved sender already respects it, but nothing
                # here should let out-of-order chunks accumulate past what
                # we told the peer we could hold. Rejected data is simply
                # never ACKed, so it's recovered exactly like ordinary
                # packet loss -- the sender retransmits it later.
                if len(pkt.payload) <= self._advertised_window():
                    self.recv_buffer[pkt.seq] = pkt.payload
                else:
                    self._trace("recv_window_full_drop", seq=pkt.seq, len=len(pkt.payload))
            got_something = True

        if pkt.is_fin:
            if self._peer_fin_seq is None:
                self._peer_fin_seq = pkt.seq
            got_something = True

        while True:
            if self.recv_next in self.recv_buffer:
                chunk = self.recv_buffer.pop(self.recv_next)
                self.unread.extend(chunk)
                self.recv_next = seq_add(self.recv_next, len(chunk))
                self._cv.notify_all()
                continue
            if self._peer_fin_seq is not None and self.recv_next == self._peer_fin_seq:
                self.recv_next = seq_add(self.recv_next, 1)
                self._peer_closed = True
                self._cv.notify_all()
                continue
            break

        if self._peer_closed and self.state == STATE_ESTABLISHED:
            self.state = STATE_CLOSE_WAIT

        if got_something:
            ack_pkt = Packet(
                seq=self.send_next if self.send_next is not None else 0,
                ack=self.recv_next,
                flags=FLAG_ACK,
                window=self._advertised_window(),
                sack_blocks=self._compute_sack_blocks(),
            )
            self._send_packet(ack_pkt)
            self._trace("recv_ack", ack=self.recv_next, sack=list(ack_pkt.sack_blocks))

    def _handle_timers(self, now: float) -> None:
        # Undertow keeps exactly one retransmission timer per connection,
        # like classic (non-SACK-retransmitting) TCP: it always tracks the
        # segment at send_una, never "whichever segment's timer is most
        # overdue". Checking any other outstanding segment independently
        # would let one segment's exponential backoff apply to segments
        # that were sent earlier under a smaller RTO, timing them out too
        # early and cascading retransmits across the whole window instead
        # of just the head of it.
        if self.unacked and self.send_una is not None:
            oldest = self.unacked.get(self.send_una)
            if oldest is not None and now - oldest.send_time >= self.rto.current():
                self._trace("rto_timeout", seq=oldest.seq, rto=self.rto.current())
                self.cc.on_timeout()
                self.rto.backoff()
                self.dup_ack_run = 0
                self._retransmit(oldest, now)
                self._record_cwnd()
        self._send_pending(now)

    def _retransmit(self, seg: _Segment, now: float) -> None:
        seg.send_time = now
        seg.retransmit_count += 1
        pkt = Packet(
            seq=seg.seq,
            ack=self.recv_next or 0,
            flags=seg.flags,
            window=self._advertised_window(),
            payload=seg.data,
        )
        self._send_packet(pkt)
        self._trace("retransmit", seq=seg.seq, count=seg.retransmit_count)

    def _send_pending(self, now: float) -> None:
        if self.state not in (STATE_ESTABLISHED, STATE_CLOSE_WAIT):
            return
        while self.pending:
            in_flight = seq_diff(self.send_una, self.send_next)
            room = min(self.cc.cwnd, self.peer_window) - in_flight
            if room <= 0:
                # Zero-window persist probe: if we're stalled specifically
                # because the peer advertised window 0 (not because cwnd is
                # small) and nothing else is outstanding, force exactly one
                # byte through periodically. This is the sender-side half
                # of the deadlock fix described in _maybe_send_window_update
                # -- it covers the case where the receiver's own window-
                # reopened announcement gets lost, which would otherwise
                # stall the connection forever since plain ACKs are never
                # independently retransmitted.
                if (
                    self.peer_window == 0
                    and in_flight == 0
                    and now - self._last_persist_probe >= max(PERSIST_MIN_INTERVAL, self.rto.current())
                ):
                    room = 1
                    self._last_persist_probe = now
                    self._trace("persist_probe")
                else:
                    break
            chunk_len = min(self.mss, room, len(self.pending))
            if chunk_len <= 0:
                break
            chunk = bytes(self.pending[:chunk_len])
            del self.pending[:chunk_len]
            seq = self.send_next
            self.unacked[seq] = _Segment(seq=seq, data=chunk, flags=FLAG_ACK, send_time=now)
            self.send_next = seq_add(seq, chunk_len)
            pkt = Packet(seq=seq, ack=self.recv_next, flags=FLAG_ACK, window=self._advertised_window(), payload=chunk)
            self._send_packet(pkt)
            self._trace("send", seq=seq, len=chunk_len, cwnd=self.cc.cwnd)

        if self._close_requested and not self.pending and self._fin_seq is None and self.send_una == self.send_next:
            self._fin_seq = self.send_next
            self.unacked[self._fin_seq] = _Segment(seq=self._fin_seq, data=b"", flags=FLAG_FIN | FLAG_ACK, send_time=now)
            pkt = Packet(seq=self._fin_seq, ack=self.recv_next, flags=FLAG_FIN | FLAG_ACK, window=self._advertised_window())
            self._send_packet(pkt)
            self._trace("send_fin", seq=self._fin_seq)
            self.send_next = seq_add(self._fin_seq, 1)
            self.state = STATE_LAST_ACK if self.state == STATE_CLOSE_WAIT else STATE_FIN_WAIT

    def _maybe_finish_close(self, now: float) -> None:
        if self._stop:
            return
        if self.state in (STATE_FIN_WAIT, STATE_LAST_ACK):
            fin_acked = self._fin_seq is not None and seq_ge(self.send_una, seq_add(self._fin_seq, 1))
            if fin_acked and self._peer_closed:
                self.state = STATE_CLOSED
                self._closed_event.set()
                self._cv.notify_all()
                self._linger_until = now + max(LINGER, 3 * self.rto.current())
                self._stop = True
