"""MiniTCPSocket: a reliable, ordered, congestion-controlled byte-stream
socket built on raw UDP datagrams — the real thing TCP does, minus IP
fragmentation/routing concerns since we run entirely on top of UDP.

Supports one connection per socket instance (no listen backlog / multiple
simultaneous clients per port) — enough to implement and prove the real
protocol mechanics without the bookkeeping of a multiplexing demux layer.
"""
import random
import socket
import threading
import time

from .congestion import RenoCongestionControl
from .eventlog import NullLog
from .rto import RTOEstimator
from .segment import (
    FLAG_ACK,
    FLAG_FIN,
    FLAG_PSH,
    FLAG_RST,
    FLAG_SYN,
    MSS,
    ChecksumError,
    Segment,
)

CLOSED = "CLOSED"
LISTEN = "LISTEN"
SYN_SENT = "SYN_SENT"
SYN_RCVD = "SYN_RCVD"
ESTABLISHED = "ESTABLISHED"
FIN_WAIT = "FIN_WAIT"
FIN_WAIT2 = "FIN_WAIT2"
CLOSE_WAIT = "CLOSE_WAIT"
LAST_ACK = "LAST_ACK"
TIME_WAIT = "TIME_WAIT"

RECV_WINDOW = 65535  # window field is a 16-bit count of bytes (pre-RFC-1323 style)
TICK_INTERVAL = 0.005
TIME_WAIT_DURATION = 0.05
MAX_RETRANSMITS = 12
MAX_BURST_RETRANSMIT = 16


class ConnectionError_(Exception):
    pass


class _Unacked:
    __slots__ = ("segment", "orig_send_time", "last_send_time", "length", "retransmitted", "retransmit_count")

    def __init__(self, segment, length):
        now = time.monotonic()
        self.segment = segment
        self.orig_send_time = now
        self.last_send_time = now
        self.length = length
        self.retransmitted = False
        self.retransmit_count = 0


class MiniTCPSocket:
    def __init__(self, local_addr, mss=MSS, event_log=None, name=""):
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(local_addr)
        self.local_addr = self.udp.getsockname()
        self.peer_addr = None
        self.mss = mss
        self.name = name or f"{self.local_addr[1]}"
        self.log = event_log or NullLog()

        self.state = CLOSED
        self.lock = threading.RLock()
        self.cv = threading.Condition(self.lock)

        self.rto = RTOEstimator()
        self.cc = RenoCongestionControl(mss)

        self.send_una = 0
        self.next_seq = 0
        self.pending_data = bytearray()
        self.unacked = {}  # seq -> _Unacked
        self.peer_window = 65535

        self.recv_base = 0
        self.recv_buffer = {}  # seq -> payload bytes (out-of-order holding area)
        self.recv_queue = bytearray()
        self.peer_fin_seq = None
        self.error = None
        self.peer_sack_blocks = []  # most recent SACK blocks reported by peer
        self.rtt_probe_seq = None  # the one in-flight segment currently timing an RTT sample
        self.handshake_done = False  # latched True on entering ESTABLISHED, never reset
        self.fin_seq = None  # set once our FIN has been sent, so close() is safe to call concurrently

        self._running = True
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._ticker = threading.Thread(target=self._ticker_loop, daemon=True)
        self._reader.start()
        self._ticker.start()

    # ------------------------------------------------------------------ #
    # low-level send helpers (caller must hold self.lock)
    # ------------------------------------------------------------------ #

    def _send_raw(self, segment):
        try:
            self.udp.sendto(segment.encode(), self.peer_addr)
        except OSError:
            # The socket can legitimately be mid-close (e.g. a background
            # thread's RTO fires the same instant the app tears the
            # connection down) — that's not fatal, just a send that
            # arrived too late to matter. An earlier version let this
            # propagate and silently killed the reader/ticker thread with
            # an unhandled exception the caller had no way to observe.
            pass

    def _in_flight(self):
        return self.next_seq - self.send_una

    def _try_send_more(self):
        if self.state not in (ESTABLISHED, CLOSE_WAIT):
            return
        window = min(self.cc.cwnd, self.peer_window)
        while self.pending_data and self._in_flight() < window:
            room = window - self._in_flight()
            take = min(self.mss, len(self.pending_data), room)
            if take <= 0:
                break
            chunk = bytes(self.pending_data[:take])
            del self.pending_data[:take]
            seg = Segment(
                seq=self.next_seq,
                ack=self.recv_base,
                flags=FLAG_PSH | FLAG_ACK,
                window=RECV_WINDOW,
                payload=chunk,
            )
            self._send_raw(seg)
            self.unacked[self.next_seq] = _Unacked(seg, len(chunk))
            if self.rtt_probe_seq is None:
                # Exactly one in-flight segment at a time is the designated
                # RTT-timing probe (classic single-sample-per-round-trip
                # approach, the same discipline pre-timestamp-option BSD
                # TCP used). Everything else that later gets swept up in
                # the same cumulative ACK is real, correctly-delivered
                # data — just not a valid RTT measurement, since it may
                # have been sitting in the receiver's out-of-order buffer
                # for however long an earlier segment blocked recv_base.
                self.rtt_probe_seq = self.next_seq
            self.log.record(
                "segment_sent", side=self.name, seq=self.next_seq, length=len(chunk),
                cwnd=self.cc.cwnd, ssthresh=self.cc.ssthresh, state=self.cc.state,
            )
            self.next_seq += len(chunk)

    def _retransmit(self, seq):
        entry = self.unacked.get(seq)
        if entry is None:
            return
        entry.retransmitted = True
        entry.retransmit_count += 1
        entry.last_send_time = time.monotonic()
        entry.segment.ack = self.recv_base
        self._send_raw(entry.segment)
        self.log.record(
            "retransmit", side=self.name, seq=seq, count=entry.retransmit_count,
            cwnd=self.cc.cwnd, ssthresh=self.cc.ssthresh,
        )

    def _covered_by_sack(self, seq, length):
        """Has the peer already told us (via a SACK block) that it holds
        this exact byte range? If so, retransmitting it again is pure
        waste — it's sitting in the peer's out-of-order buffer, just
        blocked behind an earlier gap."""
        end = seq + length
        return any(s <= seq and end <= e for s, e in self.peer_sack_blocks)

    def _missing_unacked_seqs(self):
        """Unacked segments the peer has NOT already SACKed, oldest first —
        i.e. the segments actually worth retransmitting right now."""
        return sorted(
            seq for seq, e in self.unacked.items() if not self._covered_by_sack(seq, e.length)
        )

    # ------------------------------------------------------------------ #
    # active / passive open
    # ------------------------------------------------------------------ #

    def listen(self):
        with self.lock:
            self.state = LISTEN

    def accept(self, timeout=15.0):
        deadline = time.monotonic() + timeout
        with self.cv:
            # Wait for the latched handshake_done flag, not `state ==
            # ESTABLISHED` — a real race, caught by testing: for a
            # very short-lived connection (e.g. one that sends no data
            # and closes immediately), a reordered FIN can arrive right
            # behind the final handshake ACK and be processed in the same
            # segment-handling call, carrying the state straight through
            # ESTABLISHED into CLOSE_WAIT before this thread ever wakes up
            # to observe it. Comparing for exact equality then waits
            # forever for a value that will never reappear, even though
            # the handshake genuinely did complete.
            while not self.handshake_done:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("accept() timed out waiting for handshake")
                if self.error:
                    raise ConnectionError_(self.error)
                self.cv.wait(remaining)
        return self

    def connect(self, peer_addr, timeout=15.0):
        with self.lock:
            self.peer_addr = peer_addr
            isn = random.randrange(0, 1_000_000)
            self.send_una = isn
            self.next_seq = isn
            seg = Segment(seq=self.next_seq, flags=FLAG_SYN, window=RECV_WINDOW)
            self._send_raw(seg)
            self.unacked[self.next_seq] = _Unacked(seg, 1)
            self.log.record("syn_sent", side=self.name, seq=self.next_seq)
            self.next_seq += 1
            self.state = SYN_SENT

        deadline = time.monotonic() + timeout
        with self.cv:
            while not self.handshake_done:  # see accept() for why not `state == ESTABLISHED`
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("connect() timed out during handshake")
                if self.error:
                    raise ConnectionError_(self.error)
                self.cv.wait(remaining)

    # ------------------------------------------------------------------ #
    # data path
    # ------------------------------------------------------------------ #

    def send(self, data):
        if not data:
            return
        with self.lock:
            if self.state not in (ESTABLISHED, CLOSE_WAIT):
                raise ConnectionError_(f"cannot send() in state {self.state}")
            self.pending_data.extend(data)
            self._try_send_more()

    def recv(self, maxlen=65536, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        with self.cv:
            while not self.recv_queue and self.peer_fin_seq is None:
                if self.error:
                    raise ConnectionError_(self.error)
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("recv() timed out")
                    self.cv.wait(remaining)
                else:
                    self.cv.wait(1.0)
            if self.recv_queue:
                n = min(maxlen, len(self.recv_queue))
                out = bytes(self.recv_queue[:n])
                del self.recv_queue[:n]
                return out
            return b""  # EOF: queue drained and peer FIN observed

    def recv_all(self, timeout=30.0):
        """Read until the peer closes its writing side (EOF)."""
        chunks = []
        deadline = time.monotonic() + timeout
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            chunk = self.recv(65536, timeout=remaining)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    def close(self, timeout=15.0):
        deadline = time.monotonic() + timeout
        with self.lock:
            if self.state in (CLOSED,):
                return
            while self.pending_data or self._in_flight() > 0:
                if self.error:
                    raise ConnectionError_(self.error)
                if time.monotonic() > deadline:
                    raise TimeoutError("close() timed out flushing send buffer")
                self.cv.wait(0.05)
            if self.fin_seq is None:
                # First caller sends the FIN and records its seq. A second,
                # concurrent close() call (an app is free to call it from
                # two threads, or a retry after a transient error) must
                # not send a *second* FIN at a now-stale next_seq — the
                # peer already ACKed the real one, so that second FIN
                # would sit in `unacked` forever waiting for an ACK that
                # will never come, hanging close() until its timeout.
                # Reusing fin_seq makes concurrent close() calls converge
                # on the same teardown instead.
                fin_seq = self.next_seq
                seg = Segment(seq=fin_seq, ack=self.recv_base, flags=FLAG_FIN | FLAG_ACK, window=RECV_WINDOW)
                self._send_raw(seg)
                self.unacked[fin_seq] = _Unacked(seg, 1)
                self.next_seq += 1
                self.state = LAST_ACK if self.state == CLOSE_WAIT else FIN_WAIT
                self.fin_seq = fin_seq
                self.log.record("fin_sent", side=self.name, seq=fin_seq, state=self.state)
            else:
                fin_seq = self.fin_seq

        with self.cv:
            while fin_seq in self.unacked:
                if self.error:
                    raise ConnectionError_(self.error)
                if time.monotonic() > deadline:
                    raise TimeoutError("close() timed out waiting for FIN ack")
                self.cv.wait(0.05)
            while self.peer_fin_seq is None:
                if self.error:
                    raise ConnectionError_(self.error)
                if time.monotonic() > deadline:
                    raise TimeoutError("close() timed out waiting for peer FIN")
                self.cv.wait(0.05)
            self.state = TIME_WAIT
            self.log.record("time_wait", side=self.name)

        time.sleep(TIME_WAIT_DURATION)
        with self.lock:
            self.state = CLOSED
            self._running = False
            self.log.record("closed", side=self.name)
        # Wait for both background threads to actually exit before closing
        # the OS socket — not a fire-and-forget 1s join(). Closing the fd
        # while the reader thread might still be blocked inside recvfrom()
        # on it is a real hazard under scheduling contention: a *later*,
        # unrelated MiniTCPSocket can have its brand-new fd number reused
        # (POSIX allocates the lowest free fd), and the stale thread can
        # end up silently stealing that new socket's incoming datagrams.
        # Caught exactly this way: a lossy transfer test immediately
        # followed by an unrelated small transfer on fresh ports, where
        # the second transfer's SYN vanished for the *entire* test
        # timeout — not a protocol bug, a socket-lifetime bug.
        join_deadline = time.monotonic() + max(2.0, timeout)
        self._reader.join(timeout=max(0.0, join_deadline - time.monotonic()))
        self._ticker.join(timeout=max(0.0, join_deadline - time.monotonic()))
        if self._reader.is_alive() or self._ticker.is_alive():
            raise TimeoutError(
                "close() could not confirm background threads exited; "
                "refusing to close the socket fd to avoid fd-reuse corruption"
            )
        self.udp.close()

    # ------------------------------------------------------------------ #
    # background threads
    # ------------------------------------------------------------------ #

    def _reader_loop(self):
        self.udp.settimeout(0.2)
        while self._running:
            try:
                data, src = self.udp.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                seg = Segment.decode(data)
            except ChecksumError:
                self.log.record("corrupt_dropped", side=self.name)
                continue
            with self.cv:
                self._handle_segment(seg, src)
                self.cv.notify_all()

    def _ticker_loop(self):
        while self._running:
            time.sleep(TICK_INTERVAL)
            with self.cv:
                if not self.unacked or self.send_una not in self.unacked:
                    self._try_send_more()
                    continue
                now = time.monotonic()
                head = self.unacked[self.send_una]
                # Exactly one retransmission timer, tied to the segment
                # actually blocking cumulative progress (send_una) — this
                # is what a real TCP retransmission timer watches. Backoff
                # only escalates when *that specific* segment repeatedly
                # fails to be acked.
                #
                # An earlier version treated every individually-overdue
                # unacked segment as its own backoff trigger, so under
                # sustained multi-segment loss (many different segments
                # each timing out once, a few ticks apart) the shared RTO
                # estimator got doubled on almost every 5ms tick and
                # rocketed to the 10s ceiling within tens of milliseconds
                # — then stayed pinned there, because Karn's algorithm
                # correctly refuses to resample RTT from a retransmitted
                # segment's ACK. Verified directly: 80KB at 20% loss took
                # 76s and never recovered a usable cwnd. Scoping backoff to
                # send_una's own timer fixes this.
                if now - head.last_send_time >= self.rto.current():
                    if head.retransmit_count >= MAX_RETRANSMITS:
                        self.error = f"gave up after {head.retransmit_count} retransmits of seq {self.send_una}"
                        # Tell the peer, don't just give up locally. Without
                        # this, the peer's recv()/close() would block until
                        # its *own* timeout, with no way to learn the
                        # connection is actually dead — real TCP sends a
                        # RST for exactly this reason.
                        if self.peer_addr is not None:
                            rst = Segment(seq=self.next_seq, ack=self.recv_base, flags=FLAG_RST)
                            self._send_raw(rst)
                        self.cv.notify_all()
                        continue
                    self.cc.on_timeout()
                    self.rto.backoff()
                    # Sweep in every other currently-missing segment too
                    # (SACK-aware), so one timeout recovers a whole lost
                    # flight instead of one segment per RTT.
                    for seq in self._missing_unacked_seqs()[:MAX_BURST_RETRANSMIT]:
                        self._retransmit(seq)
                    self.cv.notify_all()
                self._try_send_more()

    # ------------------------------------------------------------------ #
    # segment dispatch (caller holds self.lock)
    # ------------------------------------------------------------------ #

    def _handle_segment(self, seg, src):
        if self.peer_addr is None:
            self.peer_addr = src
        elif src != self.peer_addr:
            # Once a peer is established, a datagram from any other
            # source is either misdirected or forged — real TCP filters
            # on the (peer IP, peer port) of the connection tuple the same
            # way. Without this check, anything else on the loopback that
            # happens to know the (still-unauthenticated) sequence numbers
            # could inject segments into an active transfer.
            self.log.record("foreign_segment_dropped", side=self.name, src=src)
            return
        self.peer_window = seg.window or self.peer_window
        if seg.is_ack():
            self.peer_sack_blocks = seg.sack_blocks
        self.log.record("segment_received", side=self.name, seq=seg.seq, ack=seg.ack, flags=seg.flags, length=len(seg.payload))

        if seg.is_rst():
            self.error = "connection reset by peer"
            return

        if self.state == LISTEN:
            if seg.is_syn():
                self.recv_base = seg.seq + 1
                isn = random.randrange(0, 1_000_000)
                self.send_una = isn
                self.next_seq = isn
                reply = Segment(seq=self.next_seq, ack=self.recv_base, flags=FLAG_SYN | FLAG_ACK, window=RECV_WINDOW)
                self._send_raw(reply)
                self.unacked[self.next_seq] = _Unacked(reply, 1)
                self.next_seq += 1
                self.state = SYN_RCVD
                self.log.record("synack_sent", side=self.name)
            return

        if self.state == SYN_SENT:
            if seg.is_syn() and seg.is_ack() and seg.ack == self.next_seq:
                self.unacked.pop(self.send_una, None)
                self.send_una = seg.ack
                self.recv_base = seg.seq + 1
                ack = Segment(seq=self.next_seq, ack=self.recv_base, flags=FLAG_ACK, window=RECV_WINDOW)
                self._send_raw(ack)
                self.state = ESTABLISHED
                self.handshake_done = True
                self.log.record("established", side=self.name)
            return

        if self.state == SYN_RCVD:
            if seg.is_ack() and not seg.is_syn() and seg.ack == self.next_seq:
                self.unacked.pop(self.send_una, None)
                self.send_una = seg.ack
                self.state = ESTABLISHED
                self.handshake_done = True
                self.log.record("established", side=self.name)
                # Fall through: this same segment may piggyback the first
                # payload bytes (or even a FIN) on top of completing the
                # handshake — an earlier version `return`ed here and
                # silently dropped that data. A segment that completes the
                # handshake is still a segment that needs its data processed.
            else:
                return

        # ESTABLISHED and both half-closed-but-still-open states share
        # the same data/ack/fin processing.
        if self.state in (ESTABLISHED, CLOSE_WAIT, FIN_WAIT, FIN_WAIT2, LAST_ACK):
            self._handle_ack(seg)
            self._handle_data(seg)
            self._handle_fin(seg)

    def _handle_ack(self, seg):
        if not seg.is_ack():
            return
        if seg.ack > self.send_una and self._seq_covered(seg.ack):
            newly_acked = seg.ack - self.send_una
            covered = [s for s in self.unacked if s + self.unacked[s].length <= seg.ack]
            for seq in covered:
                entry = self.unacked.pop(seq)
                # Sample RTT only from the one designated probe segment
                # (see rtt_probe_seq). A cumulative ACK can cover several
                # segments at once when an earlier one was head-of-line
                # blocking and just got resolved — the other covered
                # segments have been sitting in the receiver's
                # out-of-order buffer for however long the block lasted,
                # so "now - their orig_send_time" is that wait time, not a
                # round trip. Sampling from all of them was a real bug
                # caught by testing: it inflates SRTT/RTTVAR, which pushes
                # RTO up, which makes the next stall last even longer
                # before its own retransmit fires — a self-reinforcing
                # spiral that pinned RTO at the 10s ceiling and starved
                # throughput to ~1KB/s on an 80KB/20%-loss run that should
                # take single-digit seconds.
                if seq == self.rtt_probe_seq:
                    if not entry.retransmitted:
                        self.rto.sample(time.monotonic() - entry.orig_send_time)
                    self.rtt_probe_seq = None
            self.send_una = seg.ack
            self.cc.on_new_ack(newly_acked)
            self.log.record(
                "ack_advance", side=self.name, ack=seg.ack, cwnd=self.cc.cwnd,
                ssthresh=self.cc.ssthresh, cc_state=self.cc.state,
            )
            self._try_send_more()
        elif seg.ack == self.send_una and self._in_flight() > 0:
            result = self.cc.on_duplicate_ack()
            self.log.record("dup_ack", side=self.name, ack=seg.ack, cwnd=self.cc.cwnd, cc_state=self.cc.state)
            if result == "fast_retransmit":
                # SACK-aware loss recovery (RFC 6675-style): rather than
                # retransmitting only send_una and waiting out further RTO
                # cycles for any other holes in the same flight, retransmit
                # every currently-unacked segment the peer hasn't already
                # SACKed. Verified this matters: without it, a single fast
                # retransmit event under multi-segment loss recovers one
                # segment per round trip, and a real demo run at 20% loss
                # took 76s for 80KB with cwnd pinned at 1 MSS throughout.
                for seq in self._missing_unacked_seqs()[:MAX_BURST_RETRANSMIT]:
                    self._retransmit(seq)
            self._try_send_more()

    def _seq_covered(self, ack):
        # A valid cumulative ACK can never exceed our own next_seq.
        return ack - self.next_seq <= 0

    def _handle_data(self, seg):
        if not seg.payload:
            return
        seq = seg.seq
        if seq + len(seg.payload) <= self.recv_base:
            pass  # fully-duplicate retransmission we've already delivered
        elif seq >= self.recv_base:
            self.recv_buffer.setdefault(seq, seg.payload)
            while self.recv_base in self.recv_buffer:
                chunk = self.recv_buffer.pop(self.recv_base)
                self.recv_queue.extend(chunk)
                self.recv_base += len(chunk)
        self._send_data_ack()

    def _handle_fin(self, seg):
        if not seg.is_fin():
            return
        if seg.seq == self.recv_base:
            self.recv_base += 1
            self.peer_fin_seq = seg.seq
            if self.state == ESTABLISHED:
                self.state = CLOSE_WAIT
            elif self.state == FIN_WAIT:
                self.state = FIN_WAIT2  # peer FIN arrived after ours was ACKed
            self.log.record("fin_received", side=self.name, seq=seg.seq, state=self.state)
        self._send_data_ack()

    def _send_data_ack(self):
        sack_blocks = self._sack_blocks()
        ack = Segment(seq=self.next_seq, ack=self.recv_base, flags=FLAG_ACK, window=RECV_WINDOW, sack_blocks=sack_blocks)
        self._send_raw(ack)

    def _sack_blocks(self):
        blocks = []
        for start in sorted(self.recv_buffer):
            end = start + len(self.recv_buffer[start])
            if blocks and start <= blocks[-1][1]:
                blocks[-1] = (blocks[-1][0], max(blocks[-1][1], end))
            else:
                blocks.append((start, end))
        return blocks[-3:]
