"""ConduitSocket: a TCP-like reliable byte-stream transport over raw UDP.

This is the heart of Conduit. It implements, from scratch:

  * a three-way handshake (SYN / SYN+ACK / ACK) and a real TCP-shaped
    close state machine (FIN_WAIT_1 / FIN_WAIT_2 / CLOSING / CLOSE_WAIT /
    LAST_ACK / TIME_WAIT), with SYN and FIN each consuming one sequence
    number exactly like real TCP;
  * byte-stream sequence numbers with 32-bit serial (wraparound-safe)
    arithmetic;
  * a sliding send window bounded by min(cwnd, peer-advertised window),
    an out-of-order reassembly buffer on the receive side, and cumulative
    ACKs;
  * a single oldest-unacked-segment retransmission timer driven by a
    Jacobson/Karels RTO estimate, plus fast retransmit on 3 duplicate
    ACKs (Reno);
  * an optional `trace` callback that receives every protocol event
    (send/recv/ack/dup-ack/retransmit/timeout/cwnd-change/rtt-sample) —
    this is what feeds the trace visualizer.

A `ConduitSocket` never touches `socket.SOCK_STREAM`. Its only contact
with the outside world is `send_raw(bytes) -> None` (supplied by the
caller) and a `queue.Queue` of raw incoming datagrams (also fed by the
caller) — see `channel.py` for the two concrete wirings (a dedicated UDP
socket for clients, a demultiplexed shared socket for a listener's
accepted connections).
"""

import queue
import random
import threading
import time

from conduit.congestion import RenoCongestionControl
from conduit.rto import RTOEstimator
from conduit.segment import FLAG_ACK, FLAG_FIN, FLAG_RST, FLAG_SYN, Segment, SegmentError
from conduit.seqmath import seq_diff

DEFAULT_MSS = 1024
ENGINE_TICK = 0.01          # engine loop granularity, seconds
# The wire `window` field is 16 bits (max 65535) — cap the default at that,
# not 64*1024, which wraps to 0 and silently zeros the peer's send window.
DEFAULT_RECV_WINDOW = 65535
TIME_WAIT_LINGER = 0.3      # seconds spent in TIME_WAIT to catch a retransmitted FIN
HANDSHAKE_GIVE_UP_AFTER = 10.0  # seconds of unanswered handshake retries before giving up


class ConduitError(Exception):
    pass


class ConduitTimeout(ConduitError):
    pass


class ConduitReset(ConduitError):
    pass


def _noop_trace(event, **fields):
    pass


class _OutSeg:
    """One segment sitting in the retransmission queue (data, or a
    control segment — SYN/SYN+ACK/FIN — whose logical length is 1).
    `flags` are the flags the segment was originally sent with, minus
    ACK/ack-value/window which are refreshed to current values on
    every retransmit (exactly like real TCP)."""

    __slots__ = ("seq", "data", "seg_len", "flags", "send_time", "retransmitted")

    def __init__(self, seq, data, flags):
        self.seq = seq
        self.data = data
        self.seg_len = max(1, len(data))
        self.flags = flags
        self.send_time = None
        self.retransmitted = False

    def is_control(self) -> bool:
        return self.data == b"" and self.seg_len == 1


# Connection states, named after their real-TCP counterparts.
CLOSED = "CLOSED"
SYN_SENT = "SYN_SENT"
SYN_RCVD = "SYN_RCVD"
ESTABLISHED = "ESTABLISHED"
FIN_WAIT_1 = "FIN_WAIT_1"
FIN_WAIT_2 = "FIN_WAIT_2"
CLOSING = "CLOSING"
CLOSE_WAIT = "CLOSE_WAIT"
LAST_ACK = "LAST_ACK"
TIME_WAIT = "TIME_WAIT"
CLOSED_FINAL = "CLOSED_FINAL"
RESET = "RESET"

_CAN_SEND_DATA = frozenset({ESTABLISHED, CLOSE_WAIT})
_CAN_RECV_DATA = frozenset({ESTABLISHED, FIN_WAIT_1, FIN_WAIT_2, CLOSING})


class ConduitSocket:
    def __init__(self, send_raw, incoming, mss=DEFAULT_MSS,
                 recv_window_cap=DEFAULT_RECV_WINDOW, trace=None, peer_addr=None,
                 name="socket", on_teardown=None):
        self._send_raw = send_raw
        self._incoming: "queue.Queue" = incoming
        self.mss = mss
        self.recv_window_cap = recv_window_cap
        self.peer_addr = peer_addr
        self._trace = trace or _noop_trace
        self.name = name
        self._on_teardown = on_teardown

        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)

        self.state = CLOSED
        self._error = None

        # --- sender state ---
        self.send_una = 0
        self.send_next = 0
        self._pending = bytearray()
        self._outstanding = []  # list[_OutSeg], ascending seq
        self.cc = RenoCongestionControl(mss)
        self.rto_est = RTOEstimator()
        self.peer_window = DEFAULT_RECV_WINDOW

        # --- receiver state ---
        self.recv_next = 0
        self._reorder = {}          # seq -> payload, out-of-order data
        self._recv_queue = bytearray()
        self._peer_fin_seq = None
        self._eof_delivered = False

        self._engine_thread = None
        self._stop = threading.Event()
        self._time_wait_deadline = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def connect(self, timeout=5.0):
        iss = random.getrandbits(32)
        with self._lock:
            self.send_una = iss
            self.send_next = iss
            self.state = SYN_SENT
            self._send_control(FLAG_SYN)
        self._ensure_engine()
        with self._cv:
            deadline = time.monotonic() + timeout
            while self.state == SYN_SENT:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ConduitTimeout("handshake timed out (no SYN+ACK)")
                self._cv.wait(timeout=remaining)
            if self.state == RESET:
                raise ConduitReset("connection reset during handshake")

    def send(self, data: bytes) -> int:
        if not data:
            return 0
        with self._cv:
            if self.state not in _CAN_SEND_DATA:
                raise ConduitError(f"cannot send() in state {self.state}")
            self._pending.extend(data)
            self._cv.notify_all()
        return len(data)

    def sendall(self, data: bytes) -> None:
        self.send(data)
        with self._cv:
            while self._pending or self._outstanding_data_len() > 0:
                if self.state in (RESET,):
                    raise ConduitReset("connection reset while sending")
                self._cv.wait(timeout=0.5)

    def recv(self, bufsize: int, timeout=None) -> bytes:
        with self._cv:
            deadline = None if timeout is None else time.monotonic() + timeout
            while not self._recv_queue and not self._eof_delivered:
                if self.state == RESET:
                    raise ConduitReset("connection reset")
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ConduitTimeout("recv() timed out")
                    self._cv.wait(timeout=remaining)
                else:
                    self._cv.wait(timeout=0.5)
            if not self._recv_queue and self._eof_delivered:
                return b""
            chunk = bytes(self._recv_queue[:bufsize])
            del self._recv_queue[:len(chunk)]
            return chunk

    def recv_exact(self, n: int, timeout=10.0) -> bytes:
        out = bytearray()
        deadline = time.monotonic() + timeout
        while len(out) < n:
            remaining = max(0.0, deadline - time.monotonic())
            chunk = self.recv(n - len(out), timeout=remaining)
            if not chunk:
                raise ConduitTimeout(f"recv_exact: EOF/timeout after {len(out)}/{n} bytes")
            out.extend(chunk)
        return bytes(out)

    def close(self, linger=2.0):
        with self._cv:
            if self.state in (CLOSED, CLOSED_FINAL, RESET):
                return

            # Flush any queued application data before initiating the FIN
            # handshake — otherwise bytes still sitting in `_pending` would
            # be silently dropped the moment the state leaves _CAN_SEND_DATA.
            flush_deadline = time.monotonic() + linger
            while self.state in (ESTABLISHED, CLOSE_WAIT) and \
                    (self._pending or self._outstanding_data_len() > 0):
                if time.monotonic() >= flush_deadline:
                    break
                self._cv.wait(timeout=0.1)

            if self.state == CLOSE_WAIT:
                self._send_control(FLAG_FIN | FLAG_ACK)
                self.state = LAST_ACK
            elif self.state in (ESTABLISHED,):
                self._send_control(FLAG_FIN | FLAG_ACK)
                self.state = FIN_WAIT_1
            elif self.state in (SYN_SENT, SYN_RCVD, CLOSED):
                self.state = CLOSED_FINAL
            # else: already closing — let the state machine finish.
            self._cv.notify_all()
            deadline = time.monotonic() + linger
            while self.state not in (CLOSED_FINAL, RESET) and time.monotonic() < deadline:
                self._cv.wait(timeout=0.1)
        self._stop_engine()
        if self._on_teardown is not None:
            self._on_teardown()

    def is_established(self) -> bool:
        return self.state == ESTABLISHED

    # ------------------------------------------------------------------
    # server-side handshake entry point (used by Listener)
    # ------------------------------------------------------------------

    def _begin_as_server(self, peer_iss):
        iss = random.getrandbits(32)
        self.send_una = iss
        self.send_next = iss
        self.recv_next = (peer_iss + 1) & 0xFFFFFFFF
        self.state = SYN_RCVD
        self._send_control(FLAG_SYN | FLAG_ACK)
        self._ensure_engine()

    def wait_established(self, timeout=5.0):
        with self._cv:
            deadline = time.monotonic() + timeout
            while self.state == SYN_RCVD:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ConduitTimeout("handshake timed out (no final ACK)")
                self._cv.wait(timeout=remaining)
            if self.state == RESET:
                raise ConduitReset("connection reset during handshake")

    # ------------------------------------------------------------------
    # engine
    # ------------------------------------------------------------------

    def _ensure_engine(self):
        if self._engine_thread is None:
            self._engine_thread = threading.Thread(
                target=self._engine_loop, name=f"conduit-engine-{self.name}", daemon=True
            )
            self._engine_thread.start()

    def _stop_engine(self):
        self._stop.set()

    def _engine_loop(self):
        handshake_deadline = time.monotonic() + HANDSHAKE_GIVE_UP_AFTER
        while not self._stop.is_set():
            try:
                raw = self._incoming.get(timeout=ENGINE_TICK)
            except queue.Empty:
                raw = None
            if raw is not None:
                try:
                    seg = Segment.decode(raw)
                except SegmentError:
                    self._trace("corrupt_segment", size=len(raw))
                else:
                    with self._cv:
                        self._handle_segment(seg)
                        self._cv.notify_all()

            with self._cv:
                self._tick_locked()
                if self.state in (SYN_SENT, SYN_RCVD) and time.monotonic() > handshake_deadline:
                    self.state = RESET
                    self._cv.notify_all()
                if self.state == TIME_WAIT and self._time_wait_deadline is not None \
                        and time.monotonic() >= self._time_wait_deadline:
                    self.state = CLOSED_FINAL
                    self._cv.notify_all()
                done = self.state in (CLOSED_FINAL, RESET)
            if done:
                break

    def _tick_locked(self):
        now = time.monotonic()
        if self._outstanding:
            oldest = self._outstanding[0]
            if oldest.send_time is not None and (now - oldest.send_time) >= self.rto_est.rto:
                self._trace("timeout", seq=oldest.seq, rto=self.rto_est.rto)
                self.cc.on_timeout()
                self.rto_est.backoff()
                self._retransmit(oldest)
        self._try_send_pending()

    # ------------------------------------------------------------------
    # sending
    # ------------------------------------------------------------------

    def _outstanding_data_len(self):
        return sum(len(s.data) for s in self._outstanding)

    def _advertised_window(self):
        used = len(self._recv_queue) + sum(len(v) for v in self._reorder.values())
        return max(0, min(0xFFFF, self.recv_window_cap - used))

    def _transmit(self, seg: Segment):
        try:
            self._send_raw(seg.encode())
        except OSError:
            # The underlying socket was torn down out from under us — e.g. a
            # Listener closing while a lingering TIME_WAIT connection's engine
            # thread is still ticking. Nothing useful to do but drop the send;
            # the engine loop's own state checks will wind the connection down.
            self._trace("send_failed", seq=seg.seq)
            return
        self._trace("send", seq=seg.seq, ack=seg.ack, flags=seg.flag_str(), length=len(seg.payload))

    def _send_control(self, flags, payload=b""):
        """Send a control segment (SYN, SYN+ACK, or FIN+ACK). `flags`
        must already include ACK if an ack value is meaningful."""
        seg = Segment(seq=self.send_next, ack=self.recv_next, flags=flags,
                      window=self._advertised_window(), payload=payload)
        self._transmit(seg)
        if flags & (FLAG_SYN | FLAG_FIN):
            outseg = _OutSeg(self.send_next, payload, flags)
            outseg.send_time = time.monotonic()
            self._outstanding.append(outseg)
            self.send_next = (self.send_next + outseg.seg_len) & 0xFFFFFFFF

    def _send_ack(self):
        seg = Segment(seq=self.send_next, ack=self.recv_next, flags=FLAG_ACK,
                      window=self._advertised_window())
        self._transmit(seg)

    def _send_data(self, chunk: bytes):
        seg = Segment(seq=self.send_next, ack=self.recv_next, flags=FLAG_ACK,
                      window=self._advertised_window(), payload=chunk)
        self._transmit(seg)
        outseg = _OutSeg(self.send_next, chunk, FLAG_ACK)
        outseg.send_time = time.monotonic()
        self._outstanding.append(outseg)
        self.send_next = (self.send_next + len(chunk)) & 0xFFFFFFFF

    def _try_send_pending(self):
        if self.state not in _CAN_SEND_DATA:
            return
        while self._pending:
            in_flight = seq_diff(self.send_next, self.send_una)
            window = min(self.cc.cwnd, self.peer_window)
            room = window - in_flight
            if room <= 0:
                break
            chunk_len = min(self.mss, room, len(self._pending))
            if chunk_len <= 0:
                break
            chunk = bytes(self._pending[:chunk_len])
            del self._pending[:chunk_len]
            self._send_data(chunk)

    def _retransmit(self, outseg: _OutSeg):
        # Refresh ack/window to current values, exactly like a real TCP
        # retransmission — only seq/flags/payload are replayed verbatim.
        seg = Segment(seq=outseg.seq, ack=self.recv_next, flags=outseg.flags,
                      window=self._advertised_window(), payload=outseg.data)
        self._transmit(seg)
        outseg.send_time = time.monotonic()
        outseg.retransmitted = True
        self._trace("retransmit", seq=outseg.seq, length=len(outseg.data))

    # ------------------------------------------------------------------
    # receiving / segment dispatch
    # ------------------------------------------------------------------

    def _handle_segment(self, seg: Segment):
        if seg.has(FLAG_RST):
            self.state = RESET
            return

        if self.state == SYN_SENT:
            self._handle_syn_sent(seg)
            return
        if self.state == SYN_RCVD:
            self._handle_syn_rcvd(seg)
            return

        if seg.has(FLAG_ACK):
            self._process_ack(seg.ack)
        self.peer_window = seg.window

        if seg.payload:
            self._handle_data(seg)
        if seg.has(FLAG_FIN):
            self._handle_fin(seg.seq)
        elif not seg.payload and seg.has(FLAG_ACK) and not seg.has(FLAG_SYN):
            self._maybe_dup_ack(seg)

        self._advance_close_state()

    def _handle_syn_sent(self, seg: Segment):
        if seg.has(FLAG_SYN) and seg.has(FLAG_ACK):
            self._process_ack(seg.ack)
            self.recv_next = (seg.seq + 1) & 0xFFFFFFFF
            self.peer_window = seg.window
            self.state = ESTABLISHED
            self._send_control(FLAG_ACK)

    def _handle_syn_rcvd(self, seg: Segment):
        if seg.has(FLAG_ACK):
            self._process_ack(seg.ack)
            self.peer_window = seg.window
            if not self._outstanding:  # our SYN+ACK got fully acked
                self.state = ESTABLISHED

    def _maybe_dup_ack(self, seg: Segment):
        if not self._outstanding:
            return
        if seg.ack == self.send_una and seq_diff(self.send_next, self.send_una) > 0:
            fast = self.cc.on_duplicate_ack(self.send_next)
            self._trace("dup_ack", ack=seg.ack, count=self.cc.dup_ack_count)
            if fast:
                self._trace("fast_retransmit", seq=self._outstanding[0].seq)
                self._retransmit(self._outstanding[0])

    def _process_ack(self, ack_value):
        if seq_diff(ack_value, self.send_una) < 0:
            return  # stale ack, ignore
        now = time.monotonic()
        acked_total = 0

        # Take at most ONE RTT sample per ACK, from the *first* (oldest)
        # segment this ACK covers — not one per segment popped. A single
        # cumulative ACK can retire a whole burst at once (e.g. right after
        # head-of-line blocking on an earlier lost segment finally clears),
        # and every segment after the first was sent around the same time
        # but sat waiting for that unrelated retransmission — timing them
        # individually would report the *blocking delay* as if it were
        # network RTT, inflating SRTT/RTO on every such burst. Classic TCP
        # (without the timestamps option) has the same one-sample-in-flight
        # limitation for the same reason.
        if self._outstanding and not self._outstanding[0].retransmitted:
            seg0 = self._outstanding[0]
            rtt = now - seg0.send_time
            self.rto_est.sample(rtt)
            self._trace("rtt_sample", rtt=rtt, srtt=self.rto_est.srtt, rto=self.rto_est.rto)

        while self._outstanding and seq_diff(ack_value, self._outstanding[0].seq) >= self._outstanding[0].seg_len:
            seg0 = self._outstanding.pop(0)
            acked_total += seg0.seg_len
        if self._outstanding:
            seg0 = self._outstanding[0]
            covered = seq_diff(ack_value, seg0.seq)
            if covered > 0:
                seg0.data = seg0.data[covered:]
                seg0.seq = (seg0.seq + covered) & 0xFFFFFFFF
                seg0.seg_len -= covered
                acked_total += covered
        if acked_total > 0 and seq_diff(ack_value, self.send_una) > 0:
            self.send_una = ack_value
            self.cc.on_new_ack(acked_total, self.send_una)
            self._trace("cwnd", **self.cc.snapshot())

    def _handle_data(self, seg: Segment):
        d = seq_diff(seg.seq, self.recv_next)
        if d == 0:
            self._recv_queue.extend(seg.payload)
            self.recv_next = (self.recv_next + len(seg.payload)) & 0xFFFFFFFF
            while True:
                nxt = self._reorder.pop(self.recv_next, None)
                if nxt is None:
                    break
                self._recv_queue.extend(nxt)
                self.recv_next = (self.recv_next + len(nxt)) & 0xFFFFFFFF
        elif d > 0:
            self._reorder.setdefault(seg.seq, seg.payload)
        # d < 0: stale duplicate, already delivered — fall through to re-ACK
        self._send_ack()
        self._trace("recv", seq=seg.seq, length=len(seg.payload), recv_next=self.recv_next)

    def _handle_fin(self, fin_seq):
        d = seq_diff(fin_seq, self.recv_next)
        if d == 0:
            self.recv_next = (self.recv_next + 1) & 0xFFFFFFFF
            self._eof_delivered = True
            self._send_ack()
        else:
            self._peer_fin_seq = fin_seq  # out of order; wait for data to catch up

    def _advance_close_state(self):
        # If a previously-buffered FIN is now at the front of the stream, apply it.
        if self._peer_fin_seq is not None and seq_diff(self._peer_fin_seq, self.recv_next) == 0:
            fin_seq = self._peer_fin_seq
            self._peer_fin_seq = None
            self._handle_fin(fin_seq)

        if not self._eof_delivered:
            return

        our_fin_acked = not any(s.is_control() for s in self._outstanding) \
            if self.state in (FIN_WAIT_1, CLOSING, LAST_ACK) else False

        if self.state == ESTABLISHED:
            self.state = CLOSE_WAIT
        elif self.state == FIN_WAIT_1:
            self.state = CLOSING if not our_fin_acked else TIME_WAIT
            if self.state == TIME_WAIT:
                self._time_wait_deadline = time.monotonic() + TIME_WAIT_LINGER
        elif self.state == FIN_WAIT_2:
            self.state = TIME_WAIT
            self._time_wait_deadline = time.monotonic() + TIME_WAIT_LINGER
        elif self.state == CLOSING and our_fin_acked:
            self.state = TIME_WAIT
            self._time_wait_deadline = time.monotonic() + TIME_WAIT_LINGER

        if self.state in (FIN_WAIT_1, FIN_WAIT_2, CLOSING) and our_fin_acked and self._eof_delivered:
            self.state = TIME_WAIT
            self._time_wait_deadline = time.monotonic() + TIME_WAIT_LINGER

        if self.state == LAST_ACK and not any(s.is_control() for s in self._outstanding):
            self.state = CLOSED_FINAL
