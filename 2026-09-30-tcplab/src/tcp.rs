//! The TCP control block: connection state machine, reliable delivery, flow control and
//! congestion control glue. Pure logic — no I/O, no clock: the caller passes `now` (µs) in and
//! collects outgoing segments from the outbox, which is what makes it deterministic and testable.

use crate::cc::{AckAction, Algo, Cc, DupAction};
use crate::segment::*;
use std::collections::{BTreeMap, VecDeque};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum State {
    Closed,
    Listen,
    SynSent,
    SynRcvd,
    Established,
    FinWait1,
    FinWait2,
    CloseWait,
    Closing,
    LastAck,
    TimeWait,
}

impl State {
    pub fn name(&self) -> &'static str {
        match self {
            State::Closed => "CLOSED",
            State::Listen => "LISTEN",
            State::SynSent => "SYN_SENT",
            State::SynRcvd => "SYN_RCVD",
            State::Established => "ESTABLISHED",
            State::FinWait1 => "FIN_WAIT_1",
            State::FinWait2 => "FIN_WAIT_2",
            State::CloseWait => "CLOSE_WAIT",
            State::Closing => "CLOSING",
            State::LastAck => "LAST_ACK",
            State::TimeWait => "TIME_WAIT",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ConnError {
    Refused,
    Reset,
    TimedOut,
}

impl ConnError {
    pub fn name(&self) -> &'static str {
        match self {
            ConnError::Refused => "connection refused",
            ConnError::Reset => "connection reset by peer",
            ConnError::TimedOut => "connection timed out",
        }
    }
}

#[derive(Clone, Debug)]
pub struct Config {
    pub mss: usize,
    pub init_cwnd_segs: usize,
    pub rcv_buf: usize,
    pub min_rto_us: u64,
    pub init_rto_us: u64,
    pub max_rto_us: u64,
    /// Consecutive data RTOs tolerated before giving up.
    pub max_retries: u32,
    pub syn_retries: u32,
    pub msl_us: u64,
    pub algo: Algo,
    pub iss: u32,
    /// Offer RFC 7323 window scaling on SYN.
    pub window_scaling: bool,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            mss: 1000,
            init_cwnd_segs: 2,
            rcv_buf: 64 * 1024,
            min_rto_us: 200_000,
            init_rto_us: 1_000_000,
            max_rto_us: 60_000_000,
            max_retries: 12,
            syn_retries: 5,
            msl_us: 500_000,
            algo: Algo::NewReno,
            iss: 1000,
            window_scaling: true,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Stats {
    pub segs_tx: u64,
    pub segs_rx: u64,
    pub data_segs_tx: u64,
    pub retransmits: u64,
    pub timeouts: u64,
    pub fast_retransmits: u64,
    pub dupacks_rx: u64,
    pub ooo_segs: u64,
    pub dup_segs: u64,
    pub bad_checksum: u64,
    pub zero_window_probes: u64,
    pub bytes_acked: u64,
    pub rst_tx: u64,
    pub window_updates: u64,
}

#[derive(Clone, Debug)]
pub enum Event {
    State(State, State),
    Timeout { rto_us: u64 },
    FastRetransmit,
    PartialAckRetransmit,
    RecoveryExit,
    ZeroWindowProbe,
    Error(ConnError),
}

#[derive(Clone, Copy, Debug)]
pub struct Sample {
    pub t: u64,
    pub cwnd: u64,
    pub ssthresh: u64,
    pub flight: u64,
    pub srtt_us: u64,
    pub rto_us: u64,
    pub peer_wnd: u64,
}

/// A data segment transmission, offsets relative to the first data byte.
#[derive(Clone, Copy, Debug)]
pub struct TxRec {
    pub t: u64,
    pub off: u32,
    pub len: u32,
    pub retx: bool,
}

pub struct Tcb {
    pub cfg: Config,
    pub state: State,
    pub error: Option<ConnError>,
    pub stats: Stats,
    pub events: Vec<(u64, Event)>,
    pub samples: Vec<Sample>,
    pub tx_log: Vec<TxRec>,
    /// (time, cumulative-ack offset) for every ACK that advanced snd_una.
    pub ack_log: Vec<(u64, u32)>,
    outbox: Vec<Segment>,

    // identity
    pub local_addr: u32,
    pub local_port: u16,
    pub remote_addr: u32,
    pub remote_port: u16,

    // send side
    pub iss: u32,
    pub snd_una: u32,
    pub snd_nxt: u32,
    /// Highest sequence number ever sent (snd_nxt is rewound after an RTO).
    pub snd_max: u32,
    pub snd_wnd: u64,
    snd_wl1: u32,
    snd_wl2: u32,
    snd_wscale: u8,
    sendbuf: VecDeque<u8>,
    total_written: u64,
    fin_seq: Option<u32>,
    close_pending: bool,
    pub mss: usize,
    pub cc: Cc,
    probe_out: bool,
    probe_len: usize,

    // timers / RTT
    srtt_us: Option<f64>,
    rttvar_us: f64,
    pub rto_us: u64,
    rto_deadline: Option<u64>,
    tw_deadline: Option<u64>,
    retries: u32,
    rtt_probe: Option<(u32, u64)>,
    pub min_rtt_us: u64,

    // receive side
    pub irs: u32,
    pub rcv_nxt: u32,
    rcv_adv: u32,
    rcv_wscale: u8,
    wscale_ok: bool,
    readbuf: VecDeque<u8>,
    /// Out-of-order segments keyed by stream offset (bytes since irs+1).
    ooo: BTreeMap<u64, Vec<u8>>,
    rcv_off: u64,
    fin_rcvd_seq: Option<u32>,
    pub peer_fin: bool,
    ack_pending: bool,
    ack_pure: bool,
}

fn scale_for(buf: usize) -> u8 {
    let mut s = 0u8;
    while (buf >> s) > 65535 && s < 14 {
        s += 1;
    }
    s
}

impl Tcb {
    pub fn new(cfg: Config, addr: u32, port: u16) -> Tcb {
        let iss = cfg.iss;
        let cc = Cc::new(cfg.algo, cfg.mss, cfg.init_cwnd_segs, iss);
        Tcb {
            state: State::Closed,
            error: None,
            stats: Stats::default(),
            events: Vec::new(),
            samples: Vec::new(),
            tx_log: Vec::new(),
            ack_log: Vec::new(),
            outbox: Vec::new(),
            local_addr: addr,
            local_port: port,
            remote_addr: 0,
            remote_port: 0,
            iss,
            snd_una: iss,
            snd_nxt: iss,
            snd_max: iss,
            snd_wnd: 0,
            snd_wl1: 0,
            snd_wl2: 0,
            snd_wscale: 0,
            sendbuf: VecDeque::new(),
            total_written: 0,
            fin_seq: None,
            close_pending: false,
            mss: cfg.mss,
            cc,
            probe_out: false,
            probe_len: 0,
            srtt_us: None,
            rttvar_us: 0.0,
            rto_us: cfg.init_rto_us,
            rto_deadline: None,
            tw_deadline: None,
            retries: 0,
            rtt_probe: None,
            min_rtt_us: 0,
            irs: 0,
            rcv_nxt: 0,
            rcv_adv: 0,
            rcv_wscale: if cfg.window_scaling { scale_for(cfg.rcv_buf) } else { 0 },
            wscale_ok: false,
            readbuf: VecDeque::new(),
            ooo: BTreeMap::new(),
            rcv_off: 0,
            fin_rcvd_seq: None,
            peer_fin: false,
            ack_pending: false,
            ack_pure: false,
            cfg,
        }
    }

    // ---- public API ------------------------------------------------------------------------

    pub fn take_outbox(&mut self) -> Vec<Segment> {
        std::mem::take(&mut self.outbox)
    }

    pub fn rcv_wscale(&self) -> u8 {
        self.rcv_wscale
    }

    pub fn srtt_us(&self) -> Option<u64> {
        self.srtt_us.map(|s| s as u64)
    }

    /// Bytes buffered for the application.
    pub fn readable(&self) -> usize {
        self.readbuf.len()
    }

    /// Bytes written by the app that are not yet acknowledged.
    pub fn unacked_buffered(&self) -> usize {
        self.sendbuf.len()
    }

    /// Bytes in flight (sent, unacknowledged; excludes SYN/FIN).
    pub fn flight(&self) -> u64 {
        self.data_in_flight()
    }

    pub fn listen(&mut self) {
        assert_eq!(self.state, State::Closed, "listen() on a non-closed TCB");
        self.set_state(0, State::Listen);
    }

    pub fn connect(&mut self, now: u64, raddr: u32, rport: u16) {
        assert_eq!(self.state, State::Closed, "connect() on a non-closed TCB");
        self.remote_addr = raddr;
        self.remote_port = rport;
        self.snd_una = self.iss;
        self.snd_nxt = self.iss.wrapping_add(1);
        self.snd_max = self.snd_nxt;
        self.set_state(now, State::SynSent);
        self.send_syn(now, false);
        self.rtt_probe = Some((self.snd_nxt, now));
        self.rto_deadline = Some(now + self.rto_us);
        self.record(now);
    }

    /// Queue application data. Errors once the send side has been closed.
    pub fn write(&mut self, now: u64, data: &[u8]) -> Result<(), &'static str> {
        match self.state {
            State::SynSent | State::SynRcvd | State::Established | State::CloseWait => {}
            _ => return Err("connection not writable"),
        }
        if self.fin_seq.is_some() || self.close_pending {
            return Err("write after close");
        }
        self.sendbuf.extend(data);
        self.total_written += data.len() as u64;
        self.output(now);
        self.record(now);
        Ok(())
    }

    /// Half-close: queue a FIN after all written data.
    pub fn close(&mut self, now: u64) {
        match self.state {
            State::Closed | State::Listen => self.set_state(now, State::Closed),
            State::SynSent | State::SynRcvd => self.close_pending = true,
            State::Established => self.begin_close(now, State::FinWait1),
            State::CloseWait => self.begin_close(now, State::LastAck),
            _ => {}
        }
    }

    /// Abortive close: send RST and drop everything.
    pub fn abort(&mut self, now: u64) {
        if !matches!(self.state, State::Closed | State::Listen | State::SynSent) {
            let seg = self.base_segment(self.snd_nxt, RST | ACK);
            self.emit(now, seg);
            self.stats.rst_tx += 1;
        }
        self.shutdown(now, None);
    }

    /// Application read. Returns up to `max` bytes; may trigger a window-update ACK.
    pub fn read(&mut self, now: u64, max: usize) -> Vec<u8> {
        let n = max.min(self.readbuf.len());
        let out: Vec<u8> = self.readbuf.drain(..n).collect();
        if n > 0 && self.is_synchronized() {
            let (_, edge) = self.compute_window();
            // Only worth a window-update ACK if the sender might be (nearly) blocked: the
            // promised window is under half the buffer. Otherwise the next ACK carries it.
            let cur = self.rcv_adv.wrapping_sub(self.rcv_nxt) as i32 as i64;
            if seq_gt(edge, self.rcv_adv) && cur < (self.cfg.rcv_buf / 2) as i64 {
                self.stats.window_updates += 1;
                self.send_ack(now);
            }
        }
        out
    }

    /// True once the peer's FIN has been received *and* the app has drained everything.
    pub fn eof(&self) -> bool {
        self.peer_fin && self.readbuf.is_empty()
    }

    pub fn note_corrupt(&mut self) {
        self.stats.bad_checksum += 1;
    }

    pub fn next_timer(&self) -> Option<u64> {
        match (self.rto_deadline, self.tw_deadline) {
            (Some(a), Some(b)) => Some(a.min(b)),
            (a, b) => a.or(b),
        }
    }

    pub fn on_timer(&mut self, now: u64) {
        if matches!(self.tw_deadline, Some(t) if t <= now) {
            self.tw_deadline = None;
            self.shutdown(now, None);
            return;
        }
        if matches!(self.rto_deadline, Some(t) if t <= now) {
            self.rto_deadline = None;
            self.rto_fire(now);
        }
        self.record(now);
    }

    // ---- state helpers ---------------------------------------------------------------------

    fn is_synchronized(&self) -> bool {
        !matches!(self.state, State::Closed | State::Listen | State::SynSent | State::SynRcvd)
    }

    fn set_state(&mut self, now: u64, s: State) {
        if self.state != s {
            let old = self.state;
            self.state = s;
            self.events.push((now, Event::State(old, s)));
        }
    }

    fn shutdown(&mut self, now: u64, err: Option<ConnError>) {
        if let Some(e) = err {
            self.error = Some(e);
            self.events.push((now, Event::Error(e)));
        }
        self.rto_deadline = None;
        self.tw_deadline = None;
        self.set_state(now, State::Closed);
    }

    fn begin_close(&mut self, now: u64, next: State) {
        self.fin_seq = Some(self.iss.wrapping_add(1).wrapping_add(self.total_written as u32));
        self.set_state(now, next);
        self.output(now);
        self.record(now);
    }

    fn fin_acked(&self) -> bool {
        matches!(self.fin_seq, Some(f) if seq_gt(self.snd_una, f))
    }

    fn fin_in_flight_or_sent(&self) -> bool {
        matches!(self.fin_seq, Some(f) if seq_gt(self.snd_nxt, f))
    }

    fn data_in_flight(&self) -> u64 {
        let raw = self.snd_nxt.wrapping_sub(self.snd_una) as i32;
        if raw <= 0 {
            return 0;
        }
        let mut n = raw as u64;
        if self.fin_in_flight_or_sent() {
            n -= 1;
        }
        // Before the handshake completes the SYN occupies one sequence number.
        if matches!(self.state, State::SynSent | State::SynRcvd) {
            n = n.saturating_sub(1);
        }
        n
    }

    /// Data is waiting, nothing is in flight, and the peer's window is too small to send it.
    fn window_blocked(&self) -> bool {
        let unsent = self.unsent();
        unsent > 0 && self.snd_una == self.snd_max && (self.snd_wnd as usize) < self.mss.min(unsent)
    }

    fn unsent(&self) -> usize {
        self.sendbuf.len().saturating_sub(self.data_in_flight() as usize)
    }

    // ---- window computation ----------------------------------------------------------------

    fn free_space(&self) -> u64 {
        (self.cfg.rcv_buf - self.readbuf.len().min(self.cfg.rcv_buf)) as u64
    }

    /// (16-bit window field, resulting right edge). Never shrinks the promised edge and applies
    /// receiver-side silly-window avoidance (RFC 1122 §4.2.3.3).
    fn compute_window(&self) -> (u16, u32) {
        let free = self.free_space();
        let cur = (self.rcv_adv.wrapping_sub(self.rcv_nxt) as i32).max(0) as u64;
        let thresh = (self.cfg.rcv_buf / 2).min(self.mss) as u64;
        let w = if free >= cur + thresh { free } else { cur };
        let w16 = ((w >> self.rcv_wscale).min(65535)) as u16;
        let edge = self.rcv_nxt.wrapping_add(((w16 as u64) << self.rcv_wscale) as u32);
        // Never move the edge backwards because of scale rounding.
        if seq_lt(edge, self.rcv_adv) {
            let w = self.rcv_adv.wrapping_sub(self.rcv_nxt) as u64;
            (((w >> self.rcv_wscale).min(65535)) as u16, self.rcv_adv)
        } else {
            (w16, edge)
        }
    }

    // ---- segment construction --------------------------------------------------------------

    fn base_segment(&self, seq: u32, flags: u8) -> Segment {
        Segment {
            src_addr: self.local_addr,
            dst_addr: self.remote_addr,
            src_port: self.local_port,
            dst_port: self.remote_port,
            seq,
            ack: if flags & ACK != 0 { self.rcv_nxt } else { 0 },
            flags,
            window: 0,
            opts: Options::default(),
            payload: Vec::new(),
        }
    }

    /// Finalise (window field) and queue a segment.
    fn emit(&mut self, _now: u64, mut seg: Segment) {
        if seg.has(SYN) {
            seg.window = self.cfg.rcv_buf.min(65535) as u16;
            if seg.has(ACK) {
                self.rcv_adv = self.rcv_nxt.wrapping_add(seg.window as u32);
            }
        } else if seg.has(ACK) && !seg.has(RST) {
            let (w, edge) = self.compute_window();
            seg.window = w;
            self.rcv_adv = edge;
        }
        if seg.has(ACK) {
            self.ack_pending = false;
            self.ack_pure = false;
        }
        self.stats.segs_tx += 1;
        self.outbox.push(seg);
    }

    fn send_syn(&mut self, now: u64, with_ack: bool) {
        let mut seg = self.base_segment(self.iss, if with_ack { SYN | ACK } else { SYN });
        seg.opts.mss = Some(self.cfg.mss as u16);
        // Offer window scaling on active open; on passive open only if the peer offered it.
        if self.cfg.window_scaling && (!with_ack || self.wscale_ok) {
            seg.opts.wscale = Some(self.rcv_wscale);
        }
        self.emit(now, seg);
    }

    fn send_ack(&mut self, now: u64) {
        // snd_max, not snd_nxt: after an RTO snd_nxt is rewound below what the peer already holds,
        // and a pure ACK with a stale seq would be rejected as out-of-window.
        let seg = self.base_segment(self.snd_max, ACK);
        self.emit(now, seg);
    }

    fn send_rst_for(&mut self, seg: &Segment) {
        if seg.has(RST) {
            return;
        }
        let mut r = Segment {
            src_addr: seg.dst_addr,
            dst_addr: seg.src_addr,
            src_port: seg.dst_port,
            dst_port: seg.src_port,
            ..Default::default()
        };
        if seg.has(ACK) {
            r.seq = seg.ack;
            r.flags = RST;
        } else {
            r.seq = 0;
            r.ack = seg.seq.wrapping_add(seg.seq_len());
            r.flags = RST | ACK;
        }
        self.stats.rst_tx += 1;
        self.stats.segs_tx += 1;
        self.outbox.push(r);
    }

    // ---- sending ---------------------------------------------------------------------------

    fn can_send_data(&self) -> bool {
        matches!(self.state, State::Established | State::CloseWait | State::FinWait1 | State::LastAck)
    }

    /// Push out as much new (or rewound) data as cwnd, the peer window and SWS rules allow.
    fn output(&mut self, now: u64) {
        if self.can_send_data() {
            loop {
                let flight = self.snd_nxt.wrapping_sub(self.snd_una) as i32 as i64;
                let flight = flight.max(0) as u64;
                let wnd = self.cc.cwnd.min(self.snd_wnd);
                let unsent = self.unsent();
                if unsent > 0 {
                    if flight >= wnd {
                        break;
                    }
                    let usable = (wnd - flight) as usize;
                    let len = self.mss.min(unsent).min(usable);
                    // Sender-side SWS avoidance: only send a runt if it drains the buffer.
                    if len < self.mss && len < unsent {
                        break;
                    }
                    let seq = self.snd_nxt;
                    self.send_data(now, seq, len);
                    self.snd_nxt = self.snd_nxt.wrapping_add(len as u32);
                    if seq_gt(self.snd_nxt, self.snd_max) {
                        self.snd_max = self.snd_nxt;
                    }
                } else if matches!(self.fin_seq, Some(f) if f == self.snd_nxt) {
                    let seg = self.base_segment(self.snd_nxt, FIN | ACK);
                    self.emit(now, seg);
                    if self.snd_nxt != self.snd_max {
                        self.stats.retransmits += 1;
                    }
                    self.snd_nxt = self.snd_nxt.wrapping_add(1);
                    if seq_gt(self.snd_nxt, self.snd_max) {
                        self.snd_max = self.snd_nxt;
                    }
                    break;
                } else {
                    break;
                }
            }
            // Peer window too small to send with data waiting and nothing in flight: persist probing.
            if self.window_blocked() && self.rto_deadline.is_none() {
                self.rto_deadline = Some(now + self.rto_us);
            }
        }
        if self.snd_una != self.snd_max && self.rto_deadline.is_none() && self.state != State::TimeWait {
            self.rto_deadline = Some(now + self.rto_us);
        }
    }

    /// Emit a data segment for stream position `seq` (which must lie within the send buffer).
    fn send_data(&mut self, now: u64, seq: u32, len: usize) {
        let off = seq.wrapping_sub(self.snd_una) as usize;
        let payload: Vec<u8> = self.sendbuf.range(off..off + len).copied().collect();
        let retx = seq_lt(seq, self.snd_max);
        let mut seg = self.base_segment(seq, ACK);
        if off + len == self.sendbuf.len() {
            seg.flags |= PSH;
        }
        seg.payload = payload;
        self.emit(now, seg);
        self.stats.data_segs_tx += 1;
        self.tx_log.push(TxRec { t: now, off: seq.wrapping_sub(self.iss.wrapping_add(1)), len: len as u32, retx });
        if retx {
            self.stats.retransmits += 1;
            // Karn: never time a segment that may be a retransmission.
            self.rtt_probe = None;
        } else if self.rtt_probe.is_none() {
            self.rtt_probe = Some((seq.wrapping_add(len as u32), now));
        }
    }

    /// Retransmit exactly one segment from snd_una without moving snd_nxt (fast retransmit).
    fn retransmit_head(&mut self, now: u64) {
        let in_flight = self.data_in_flight() as usize;
        let len = self.mss.min(in_flight).min(self.sendbuf.len());
        if len > 0 {
            let seq = self.snd_una;
            self.send_data(now, seq, len);
        } else if matches!(self.fin_seq, Some(f) if f == self.snd_una) {
            let seg = self.base_segment(self.snd_una, FIN | ACK);
            self.emit(now, seg);
            self.stats.retransmits += 1;
            self.rtt_probe = None;
        }
    }

    fn rto_fire(&mut self, now: u64) {
        match self.state {
            State::SynSent | State::SynRcvd => {
                self.retries += 1;
                if self.retries > self.cfg.syn_retries {
                    self.shutdown(now, Some(ConnError::TimedOut));
                    return;
                }
                self.rto_us = (self.rto_us * 2).min(self.cfg.max_rto_us);
                self.stats.retransmits += 1;
                self.rtt_probe = None;
                self.send_syn(now, self.state == State::SynRcvd);
                self.rto_deadline = Some(now + self.rto_us);
            }
            State::Established | State::CloseWait | State::FinWait1 | State::Closing | State::LastAck => {
                // Persist timer: peer advertises zero window and we have data to send.
                if self.probe_out || self.window_blocked() {
                    self.zero_window_probe(now);
                    return;
                }
                if self.snd_una == self.snd_max {
                    return; // spurious: everything already acknowledged
                }
                self.retries += 1;
                if self.retries > self.cfg.max_retries {
                    self.shutdown(now, Some(ConnError::TimedOut));
                    return;
                }
                let flight = self.snd_nxt.wrapping_sub(self.snd_una) as i32 as i64;
                self.cc.on_timeout(flight.max(0) as u64, self.snd_max);
                self.stats.timeouts += 1;
                self.rto_us = (self.rto_us * 2).min(self.cfg.max_rto_us);
                self.events.push((now, Event::Timeout { rto_us: self.rto_us }));
                self.rtt_probe = None;
                self.snd_nxt = self.snd_una; // go back and resend from the hole
                self.output(now);
                if self.rto_deadline.is_none() {
                    self.rto_deadline = Some(now + self.rto_us);
                }
            }
            _ => {}
        }
    }

    /// Persist timer: push a small probe into a closed/tiny window so a lost window-update ACK
    /// can never deadlock the connection. Not a congestion event, not counted toward retries.
    fn zero_window_probe(&mut self, now: u64) {
        self.stats.zero_window_probes += 1;
        self.events.push((now, Event::ZeroWindowProbe));
        let (seq, len, retx) = if !self.probe_out {
            let len = if self.snd_wnd > 0 { (self.snd_wnd as usize).min(self.unsent()).min(self.mss) } else { 1 };
            (self.snd_nxt, len, false)
        } else {
            (self.snd_una, self.probe_len.min(self.sendbuf.len()), true)
        };
        let off = seq.wrapping_sub(self.snd_una) as usize;
        let payload: Vec<u8> = self.sendbuf.range(off..off + len).copied().collect();
        let mut seg = self.base_segment(seq, ACK);
        seg.payload = payload;
        self.emit(now, seg);
        self.stats.data_segs_tx += 1;
        self.tx_log.push(TxRec { t: now, off: seq.wrapping_sub(self.iss.wrapping_add(1)), len: len as u32, retx });
        if !retx {
            self.snd_nxt = self.snd_nxt.wrapping_add(len as u32);
            if seq_gt(self.snd_nxt, self.snd_max) {
                self.snd_max = self.snd_nxt;
            }
            self.probe_out = true;
            self.probe_len = len;
        }
        self.rto_us = (self.rto_us * 2).min(self.cfg.max_rto_us.min(5_000_000));
        self.rto_deadline = Some(now + self.rto_us);
        self.record(now);
    }

    // ---- RTT / RTO (RFC 6298) ------------------------------------------------------------------

    fn rtt_sample(&mut self, r_us: u64) {
        let r = r_us.max(1) as f64;
        match self.srtt_us {
            None => {
                self.srtt_us = Some(r);
                self.rttvar_us = r / 2.0;
            }
            Some(s) => {
                self.rttvar_us = 0.75 * self.rttvar_us + 0.25 * (s - r).abs();
                self.srtt_us = Some(0.875 * s + 0.125 * r);
            }
        }
        self.min_rtt_us = if self.min_rtt_us == 0 { r_us } else { self.min_rtt_us.min(r_us) };
        self.rto_us = self.computed_rto();
    }

    fn computed_rto(&self) -> u64 {
        match self.srtt_us {
            Some(s) => {
                let rto = s + (4.0 * self.rttvar_us).max(1_000.0);
                (rto as u64).clamp(self.cfg.min_rto_us, self.cfg.max_rto_us)
            }
            None => self.cfg.init_rto_us,
        }
    }

    fn record(&mut self, now: u64) {
        if matches!(self.state, State::Closed | State::Listen) && self.samples.is_empty() {
            return;
        }
        let flight = (self.snd_nxt.wrapping_sub(self.snd_una) as i32).max(0) as u64;
        let s = Sample {
            t: now,
            cwnd: self.cc.cwnd,
            ssthresh: self.cc.ssthresh,
            flight,
            srtt_us: self.srtt_us().unwrap_or(0),
            rto_us: self.rto_us,
            peer_wnd: self.snd_wnd,
        };
        if let Some(last) = self.samples.last() {
            if last.t == s.t && last.cwnd == s.cwnd && last.ssthresh == s.ssthresh && last.flight == s.flight {
                return;
            }
        }
        self.samples.push(s);
    }

    // ---- receiving -------------------------------------------------------------------------

    pub fn on_segment(&mut self, now: u64, seg: Segment) {
        self.stats.segs_rx += 1;
        match self.state {
            State::Closed => self.closed_rx(&seg),
            State::Listen => self.listen_rx(now, &seg),
            State::SynSent => self.synsent_rx(now, &seg),
            _ => self.synchronized_rx(now, &seg),
        }
        self.record(now);
    }

    fn matches_conn(&self, seg: &Segment) -> bool {
        seg.dst_port == self.local_port
            && seg.src_port == self.remote_port
            && seg.src_addr == self.remote_addr
            && seg.dst_addr == self.local_addr
    }

    fn closed_rx(&mut self, seg: &Segment) {
        self.send_rst_for(seg);
    }

    fn adopt_peer_options(&mut self, seg: &Segment) {
        let peer_mss = seg.opts.mss.map(|m| m as usize).unwrap_or(536).max(64);
        self.mss = self.cfg.mss.min(peer_mss);
        self.cc = Cc::new(self.cfg.algo, self.mss, self.cfg.init_cwnd_segs, self.iss);
        if let (true, Some(ws)) = (self.cfg.window_scaling, seg.opts.wscale) {
            self.wscale_ok = true;
            self.snd_wscale = ws;
        } else {
            self.wscale_ok = false;
            self.snd_wscale = 0;
            self.rcv_wscale = 0;
        }
    }

    fn listen_rx(&mut self, now: u64, seg: &Segment) {
        if seg.dst_port != self.local_port || seg.dst_addr != self.local_addr {
            self.send_rst_for(seg);
            return;
        }
        if seg.has(RST) {
            return;
        }
        if seg.has(ACK) {
            self.send_rst_for(seg);
            return;
        }
        if seg.has(SYN) {
            self.remote_addr = seg.src_addr;
            self.remote_port = seg.src_port;
            self.irs = seg.seq;
            self.rcv_nxt = seg.seq.wrapping_add(1);
            self.adopt_peer_options(seg);
            self.snd_wnd = seg.window as u64; // SYN windows are never scaled
            self.snd_una = self.iss;
            self.snd_nxt = self.iss.wrapping_add(1);
            self.snd_max = self.snd_nxt;
            self.set_state(now, State::SynRcvd);
            self.send_syn(now, true);
            self.rtt_probe = Some((self.snd_nxt, now));
            self.rto_deadline = Some(now + self.rto_us);
        }
    }

    fn synsent_rx(&mut self, now: u64, seg: &Segment) {
        if seg.dst_port != self.local_port || seg.src_port != self.remote_port {
            self.send_rst_for(seg);
            return;
        }
        let mut ack_ok = false;
        if seg.has(ACK) {
            if seg.ack != self.iss.wrapping_add(1) {
                // Unacceptable ACK (stale duplicate); reset the sender unless it's an RST.
                self.send_rst_for(seg);
                return;
            }
            ack_ok = true;
        }
        if seg.has(RST) {
            if ack_ok {
                self.shutdown(now, Some(ConnError::Refused));
            }
            return;
        }
        if seg.has(SYN) {
            self.irs = seg.seq;
            self.rcv_nxt = seg.seq.wrapping_add(1);
            self.adopt_peer_options(seg);
            if ack_ok {
                if let Some((_, t0)) = self.rtt_probe.take() {
                    self.rtt_sample(now - t0); // handshake RTT (cleared on any SYN retransmit: Karn)
                }
                self.snd_una = seg.ack;
                self.snd_wnd = seg.window as u64;
                self.snd_wl1 = seg.seq;
                self.snd_wl2 = seg.ack;
                self.rto_deadline = None;
                self.retries = 0;
                self.set_state(now, State::Established);
                self.rcv_adv = self.rcv_nxt;
                self.send_ack(now);
                self.after_established(now);
            } else {
                // Simultaneous open.
                self.snd_wnd = seg.window as u64;
                self.set_state(now, State::SynRcvd);
                self.send_syn(now, true);
                self.rto_deadline = Some(now + self.rto_us);
            }
        }
    }

    fn after_established(&mut self, now: u64) {
        if self.close_pending {
            self.close_pending = false;
            let next = if self.state == State::CloseWait { State::LastAck } else { State::FinWait1 };
            self.begin_close(now, next);
        } else {
            self.output(now);
        }
    }

    /// Is any part of [seq, seq+len) inside our receive window?
    fn acceptable(&self, seg: &Segment) -> bool {
        let wnd = self.free_space() as u32;
        let len = seg.seq_len();
        let start = seg.seq;
        let rn = self.rcv_nxt;
        let in_win = |s: u32| seq_geq(s, rn) && seq_lt(s, rn.wrapping_add(wnd));
        match (len, wnd) {
            (0, 0) => start == rn,
            (0, _) => in_win(start),
            // Zero window: only a payload-free segment (a bare FIN) exactly at rcv_nxt may land.
            (_, 0) => seg.payload.is_empty() && !seg.has(SYN) && start == rn,
            (_, _) => in_win(start) || in_win(start.wrapping_add(len - 1)) || (seq_lt(start, rn) && seq_geq(start.wrapping_add(len - 1), rn)),
        }
    }

    fn synchronized_rx(&mut self, now: u64, seg: &Segment) {
        if !self.matches_conn(seg) {
            self.send_rst_for(seg);
            return;
        }
        // Retransmitted SYN while we're in SYN_RCVD: answer with SYN+ACK again.
        if self.state == State::SynRcvd && seg.has(SYN) && !seg.has(ACK) && seg.seq == self.irs {
            self.send_syn(now, true);
            return;
        }
        if !self.acceptable(seg) {
            if !seg.payload.is_empty() && seq_lt(seg.seq, self.rcv_nxt) {
                self.stats.dup_segs += 1;
            }
            if !seg.has(RST) {
                // Stale/duplicate/out-of-window: re-assert our position (and in TIME_WAIT,
                // a retransmitted FIN restarts the 2·MSL wait).
                self.emit_pure_ack(now);
                if self.state == State::TimeWait && seg.has(FIN) {
                    self.tw_deadline = Some(now + 2 * self.cfg.msl_us);
                }
            }
            return;
        }
        if seg.has(RST) {
            if self.state == State::TimeWait {
                return; // RFC 1337: don't let a stray RST assassinate TIME_WAIT
            }
            let err = if self.state == State::SynRcvd { ConnError::Refused } else { ConnError::Reset };
            self.shutdown(now, Some(err));
            return;
        }
        if seg.has(SYN) && seq_geq(seg.seq, self.rcv_nxt) {
            // SYN inside the window on a synchronised connection: fatal (RFC 5961 would challenge).
            let seq = self.snd_nxt;
            let rst = self.base_segment(seq, RST | ACK);
            self.stats.rst_tx += 1;
            self.stats.segs_tx += 1;
            self.outbox.push(rst);
            self.shutdown(now, Some(ConnError::Reset));
            return;
        }
        if !seg.has(ACK) {
            return;
        }

        if self.state == State::SynRcvd {
            if seg.ack == self.iss.wrapping_add(1) {
                if let Some((_, t0)) = self.rtt_probe.take() {
                    self.rtt_sample(now - t0);
                }
                self.snd_una = seg.ack;
                self.snd_wnd = (seg.window as u64) << self.snd_wscale;
                self.snd_wl1 = seg.seq;
                self.snd_wl2 = seg.ack;
                self.rto_deadline = None;
                self.retries = 0;
                self.rcv_adv = self.rcv_nxt.wrapping_add(self.cfg.rcv_buf.min(65535) as u32);
                self.set_state(now, State::Established);
                self.after_established(now);
            } else {
                self.send_rst_for(seg);
                return;
            }
        } else {
            self.process_ack(now, seg);
            if self.state == State::Closed {
                return;
            }
        }

        // FIN-acknowledgement transitions.
        if self.fin_acked() {
            match self.state {
                State::FinWait1 => self.set_state(now, State::FinWait2),
                State::Closing => self.enter_time_wait(now),
                State::LastAck => {
                    self.shutdown(now, None);
                    return;
                }
                _ => {}
            }
        }

        if matches!(self.state, State::Established | State::FinWait1 | State::FinWait2) {
            self.process_payload(now, seg);
        }
        if self.state == State::TimeWait && seg.has(FIN) {
            self.tw_deadline = Some(now + 2 * self.cfg.msl_us);
        }

        // New data may now be sendable (ack opened the window / cwnd); it carries the ACK.
        self.output(now);
        if self.ack_pure || self.ack_pending {
            self.emit_pure_ack(now);
        }
    }

    fn emit_pure_ack(&mut self, now: u64) {
        let seg = self.base_segment(self.snd_max, ACK);
        self.emit(now, seg);
    }

    fn enter_time_wait(&mut self, now: u64) {
        self.set_state(now, State::TimeWait);
        self.rto_deadline = None;
        self.tw_deadline = Some(now + 2 * self.cfg.msl_us);
    }

    fn process_ack(&mut self, now: u64, seg: &Segment) {
        let ack = seg.ack;
        if seq_gt(ack, self.snd_max) {
            // ACK for something we never sent.
            self.ack_pure = true;
            return;
        }
        if seq_lt(ack, self.snd_una) {
            return; // old duplicate
        }
        let old_wnd = self.snd_wnd;
        if seq_lt(self.snd_wl1, seg.seq) || (self.snd_wl1 == seg.seq && seq_leq(self.snd_wl2, ack)) {
            self.snd_wnd = (seg.window as u64) << self.snd_wscale;
            self.snd_wl1 = seg.seq;
            self.snd_wl2 = ack;
        }

        if ack == self.snd_una {
            let is_dup = seg.payload.is_empty()
                && !seg.has(SYN)
                && !seg.has(FIN)
                && self.snd_wnd == old_wnd
                && self.snd_wnd > 0
                && self.snd_una != self.snd_max;
            if is_dup {
                self.stats.dupacks_rx += 1;
                let flight = (self.snd_nxt.wrapping_sub(self.snd_una) as i32).max(0) as u64;
                match self.cc.on_dupack(flight, self.snd_una, self.snd_nxt) {
                    DupAction::FastRetransmit => {
                        self.stats.fast_retransmits += 1;
                        self.events.push((now, Event::FastRetransmit));
                        if self.cfg.algo == Algo::Tahoe {
                            self.snd_nxt = self.snd_una; // Tahoe: go-back-N in slow start
                            self.rtt_probe = None;
                        } else {
                            self.retransmit_head(now);
                        }
                    }
                    DupAction::Inflate | DupAction::None => {}
                }
            }
        } else {
            let total = ack.wrapping_sub(self.snd_una) as u64;
            let fin_covered = matches!(self.fin_seq, Some(f) if seq_gt(ack, f));
            let data_acked = total - fin_covered as u64;
            let n = (data_acked as usize).min(self.sendbuf.len());
            self.sendbuf.drain(..n);
            self.snd_una = ack;
            if seq_lt(self.snd_nxt, ack) {
                self.snd_nxt = ack;
            }
            self.stats.bytes_acked += data_acked;
            self.ack_log.push((now, ack.wrapping_sub(self.iss.wrapping_add(1))));
            if let Some((end, t0)) = self.rtt_probe {
                if seq_geq(ack, end) {
                    self.rtt_sample(now - t0);
                    self.rtt_probe = None;
                }
            }
            self.probe_out = false;
            self.retries = 0;
            // Forward progress ends the backoff (BSD/Linux practice). Holding the backed-off value until a
            // clean RTT sample (RFC 6298 §5.7) livelocks under heavy loss without timestamps: every ACK
            // covers retransmitted data, so no sample ever arrives and the RTO ratchets to its cap.
            self.rto_us = self.computed_rto();
            if data_acked > 0 {
                match self.cc.on_new_ack(data_acked, self.snd_una, now, self.min_rtt_us) {
                    AckAction::RetransmitHead => {
                        self.events.push((now, Event::PartialAckRetransmit));
                        self.retransmit_head(now);
                    }
                    AckAction::RecoveryExit => self.events.push((now, Event::RecoveryExit)),
                    AckAction::None => {}
                }
            }
            self.rto_deadline = if self.snd_una == self.snd_max { None } else { Some(now + self.rto_us) };
        }

        // Window grew while a probe was outstanding and unacknowledged: resend it as ordinary data.
        if self.snd_wnd > old_wnd && self.probe_out {
            self.snd_nxt = self.snd_una;
            self.probe_out = false;
            self.rto_deadline = None;
        }
    }

    fn process_payload(&mut self, now: u64, seg: &Segment) {
        let _ = now;
        let len = seg.payload.len();
        let fin = seg.has(FIN);
        if len == 0 && !fin {
            return;
        }
        let free = self.free_space() as i64;
        let mut start = seg.seq.wrapping_sub(self.rcv_nxt) as i32 as i64; // offset vs rcv_nxt
        let mut data: &[u8] = &seg.payload;
        let mut whole = true;
        if start < 0 {
            let skip = (-start) as usize;
            if skip >= data.len() {
                data = &[];
            } else {
                data = &data[skip..];
            }
            start = 0;
            self.stats.dup_segs += 1;
            self.ack_pure = true;
        }
        if start + data.len() as i64 > free {
            let keep = (free - start).max(0) as usize;
            if keep < data.len() {
                data = &data[..keep];
                whole = false;
            }
        }
        if !data.is_empty() {
            if start == 0 {
                self.readbuf.extend(data);
                self.rcv_nxt = self.rcv_nxt.wrapping_add(data.len() as u32);
                self.rcv_off += data.len() as u64;
                self.drain_ooo();
                self.ack_pending = true;
                // A gap still open behind us? then the peer needs a pure (duplicate-able) ACK.
                if !self.ooo.is_empty() {
                    self.ack_pure = true;
                }
            } else {
                self.stats.ooo_segs += 1;
                let key = self.rcv_off + start as u64;
                let longer = self.ooo.get(&key).map_or(true, |old| old.len() < data.len());
                if longer {
                    self.ooo.insert(key, data.to_vec());
                }
                self.ack_pure = true; // dup ACK for fast retransmit
            }
        }
        if fin && whole {
            let fin_at = seg.seq.wrapping_add(len as u32);
            self.fin_rcvd_seq = Some(fin_at);
        }
        self.try_deliver_fin(now);
    }

    fn drain_ooo(&mut self) {
        loop {
            let (k, len) = match self.ooo.iter().next() {
                Some((&k, v)) => (k, v.len() as u64),
                None => return,
            };
            if k > self.rcv_off {
                return;
            }
            let v = self.ooo.remove(&k).unwrap();
            let end = k + len;
            if end > self.rcv_off {
                let skip = (self.rcv_off - k) as usize;
                let room = self.cfg.rcv_buf.saturating_sub(self.readbuf.len());
                let take = (v.len() - skip).min(room);
                self.readbuf.extend(&v[skip..skip + take]);
                self.rcv_nxt = self.rcv_nxt.wrapping_add(take as u32);
                self.rcv_off += take as u64;
            }
        }
    }

    fn try_deliver_fin(&mut self, now: u64) {
        if let Some(f) = self.fin_rcvd_seq {
            if f == self.rcv_nxt && !self.peer_fin {
                self.peer_fin = true;
                self.rcv_nxt = self.rcv_nxt.wrapping_add(1);
                self.ack_pure = true;
                match self.state {
                    State::Established => self.set_state(now, State::CloseWait),
                    State::FinWait1 => {
                        if self.fin_acked() {
                            self.enter_time_wait(now);
                        } else {
                            self.set_state(now, State::Closing);
                        }
                    }
                    State::FinWait2 => self.enter_time_wait(now),
                    _ => {}
                }
            }
        }
    }
}
