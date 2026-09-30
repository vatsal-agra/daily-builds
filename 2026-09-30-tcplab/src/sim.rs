//! Discrete-event network simulator: two TCBs (A = client, B = server) joined by two independent
//! links, plus a scripted "application" that writes/reads/closes. Virtual time only.

use crate::cc::Algo;
use crate::link::{DropReason, Link, LinkConfig, LinkStats, Verdict};
use crate::rng::Rng;
use crate::segment::Segment;
use crate::tcp::{Config, Event, State, Tcb};
use std::cmp::Reverse;
use std::collections::BinaryHeap;

pub const ADDR_A: u32 = 0x0A00_0001;
pub const ADDR_B: u32 = 0x0A00_0002;
pub const PORT_A: u16 = 40_000;
pub const PORT_B: u16 = 80;

/// Rate-limited application reader (to exercise flow control).
#[derive(Clone, Copy, Debug)]
pub struct Reader {
    pub bytes_per_sec: u64,
    pub tick_us: u64,
}

#[derive(Clone)]
pub struct Scenario {
    pub name: String,
    pub cfg_a: Config,
    pub cfg_b: Config,
    pub link_ab: LinkConfig,
    pub link_ba: LinkConfig,
    pub bytes_a_to_b: usize,
    pub bytes_b_to_a: usize,
    pub seed: u64,
    pub reader_a: Option<Reader>,
    pub reader_b: Option<Reader>,
    /// If false, B never listens (connection-refused scenario).
    pub b_listens: bool,
    /// If true B also actively connects at t=0 (simultaneous open); B does not listen.
    pub simultaneous_open: bool,
    /// B closes as soon as the connection exists instead of waiting for A's FIN (simultaneous close).
    pub b_close_at_start: bool,
    pub max_time_us: u64,
    pub dump: bool,
}

impl Scenario {
    pub fn new(name: &str) -> Scenario {
        let link = LinkConfig::default();
        Scenario {
            name: name.to_string(),
            cfg_a: Config { iss: 1000, ..Config::default() },
            cfg_b: Config { iss: 500_000, ..Config::default() },
            link_ab: link.clone(),
            link_ba: link,
            bytes_a_to_b: 1_000_000,
            bytes_b_to_a: 0,
            seed: 1,
            reader_a: None,
            reader_b: None,
            b_listens: true,
            simultaneous_open: false,
            b_close_at_start: false,
            max_time_us: 900_000_000,
            dump: false,
        }
    }

    pub fn set_algo(&mut self, a: Algo) {
        self.cfg_a.algo = a;
        self.cfg_b.algo = a;
    }

    /// Named presets for the CLI.
    pub fn preset(name: &str) -> Option<Scenario> {
        let mut s = Scenario::new(name);
        match name {
            "clean" => {
                s.bytes_a_to_b = 2_000_000;
            }
            "lossy" => {
                s.bytes_a_to_b = 2_000_000;
                s.link_ab.loss = 0.01;
            }
            "bottleneck" => {
                s.bytes_a_to_b = 4_000_000;
                s.link_ab.rate_bps = 5_000_000;
                s.link_ab.delay_us = 25_000;
                s.link_ab.queue_pkts = 20;
                s.link_ba = LinkConfig { rate_bps: 100_000_000, delay_us: 25_000, ..LinkConfig::default() };
            }
            "satellite" => {
                s.bytes_a_to_b = 3_000_000;
                s.link_ab.rate_bps = 8_000_000;
                s.link_ab.delay_us = 300_000;
                s.link_ab.loss = 0.002;
                s.link_ab.queue_pkts = 400;
                s.link_ba = LinkConfig { rate_bps: 8_000_000, delay_us: 300_000, ..LinkConfig::default() };
                s.cfg_b.rcv_buf = 2 * 1024 * 1024;
            }
            "slowreader" => {
                s.bytes_a_to_b = 600_000;
                s.cfg_b.rcv_buf = 32 * 1024;
                s.reader_b = Some(Reader { bytes_per_sec: 200_000, tick_us: 10_000 });
            }
            "chaos" => {
                s.bytes_a_to_b = 500_000;
                s.link_ab.loss = 0.05;
                s.link_ab.reorder = 0.05;
                s.link_ab.reorder_extra_us = 30_000;
                s.link_ab.dup = 0.02;
                s.link_ab.corrupt = 0.02;
                s.link_ab.jitter_us = 5_000;
                s.link_ba = s.link_ab.clone();
            }
            _ => return None,
        }
        s.link_ba.drop_data.clear();
        Some(s)
    }

    pub const PRESETS: [&'static str; 6] = ["clean", "lossy", "bottleneck", "satellite", "slowreader", "chaos"];
}

/// Deterministic pseudo-random payload so any misordering/corruption is byte-exact detectable.
pub fn pattern(len: usize, seed: u64) -> Vec<u8> {
    let mut r = Rng::new(seed);
    let mut out = Vec::with_capacity(len);
    while out.len() < len {
        out.extend_from_slice(&r.next_u64().to_le_bytes());
    }
    out.truncate(len);
    out
}

#[derive(Clone, Debug)]
pub struct Outcome {
    pub name: String,
    pub algo: Algo,
    pub verified: bool,
    pub bytes: usize,
    /// Virtual time at which B had the last byte of A's stream (µs), if it did.
    pub delivered_us: Option<u64>,
    pub end_us: u64,
    pub goodput_bps: f64,
    pub timed_out: bool,
    pub a_state: State,
    pub b_state: State,
    pub a_error: Option<crate::tcp::ConnError>,
    pub b_error: Option<crate::tcp::ConnError>,
}

pub struct Sim {
    pub sc: Scenario,
    pub now: u64,
    pub a: Tcb,
    pub b: Tcb,
    pub link_ab: Link,
    pub link_ba: Link,
    heap: BinaryHeap<Reverse<(u64, u64, u8, Vec<u8>)>>,
    seq: u64,
    pub recv_a: Vec<u8>,
    pub recv_b: Vec<u8>,
    data_a: Vec<u8>,
    data_b: Vec<u8>,
    b_written: bool,
    next_read: [Option<u64>; 2],
    pub delivered_us: Option<u64>,
    pub timed_out: bool,
    pub log: Vec<String>,
    /// (time, offset) of A→B data segments dropped in the network.
    pub drops: Vec<(u64, u32, DropReason)>,
    ev_seen: [usize; 2],
    started: bool,
}

impl Sim {
    pub fn new(sc: Scenario) -> Sim {
        let a = Tcb::new(sc.cfg_a.clone(), ADDR_A, PORT_A);
        let b = Tcb::new(sc.cfg_b.clone(), ADDR_B, PORT_B);
        let link_ab = Link::new(sc.link_ab.clone(), sc.seed.wrapping_mul(2).wrapping_add(1));
        let link_ba = Link::new(sc.link_ba.clone(), sc.seed.wrapping_mul(2).wrapping_add(2));
        let data_a = pattern(sc.bytes_a_to_b, sc.seed ^ 0xA);
        let data_b = pattern(sc.bytes_b_to_a, sc.seed ^ 0xB);
        Sim {
            now: 0,
            a,
            b,
            link_ab,
            link_ba,
            heap: BinaryHeap::new(),
            seq: 0,
            recv_a: Vec::new(),
            recv_b: Vec::new(),
            data_a,
            data_b,
            b_written: false,
            next_read: [None, None],
            delivered_us: None,
            timed_out: false,
            log: Vec::new(),
            drops: Vec::new(),
            ev_seen: [0, 0],
            started: false,
            sc,
        }
    }

    fn logf(&mut self, t: u64, who: &str, msg: String) {
        if self.sc.dump {
            self.log.push(format!("{:>10.6}  {}  {}", t as f64 / 1e6, who, msg));
        }
    }

    /// Move everything the TCBs queued onto the links.
    fn pump(&mut self) {
        let now = self.now;
        for who in 0..2 {
            let segs = if who == 0 { self.a.take_outbox() } else { self.b.take_outbox() };
            for seg in segs {
                let bytes = seg.encode();
                let carries = !seg.payload.is_empty();
                let (link, dest, arrow) = if who == 0 { (&mut self.link_ab, 1u8, "A > B") } else { (&mut self.link_ba, 0u8, "B > A") };
                let verdict = link.send(now, bytes, carries);
                match verdict {
                    Verdict::Dropped(reason) => {
                        if who == 0 && carries {
                            let off = seg.seq.wrapping_sub(self.a.iss.wrapping_add(1));
                            self.drops.push((now, off, reason));
                        }
                        self.logf(now, arrow, format!("{}   ** dropped: {} **", seg.summary(), reason.name()));
                    }
                    Verdict::Deliver(list) => {
                        self.logf(now, arrow, seg.summary());
                        for (t, bytes) in list {
                            self.seq += 1;
                            self.heap.push(Reverse((t, self.seq, dest, bytes)));
                        }
                    }
                }
            }
        }
    }

    fn drain_events(&mut self) {
        for who in 0..2 {
            let (name, tcb) = if who == 0 { ("A", &self.a) } else { ("B", &self.b) };
            let evs: Vec<(u64, String)> = tcb.events[self.ev_seen[who]..]
                .iter()
                .filter_map(|(t, e)| {
                    let s = match e {
                        Event::State(from, to) => format!("state {} -> {}", from.name(), to.name()),
                        Event::Timeout { rto_us } => format!("RTO fired (next rto {:.0} ms)", *rto_us as f64 / 1e3),
                        Event::FastRetransmit => "fast retransmit (3 dupacks)".to_string(),
                        Event::PartialAckRetransmit => "partial ACK: retransmit next hole".to_string(),
                        Event::RecoveryExit => "leave fast recovery".to_string(),
                        Event::ZeroWindowProbe => "zero-window probe".to_string(),
                        Event::Error(e) => format!("error: {}", e.name()),
                    };
                    Some((*t, s))
                })
                .collect();
            self.ev_seen[who] = tcb.events.len();
            for (t, s) in evs {
                self.logf(t, name, format!("-- {s}"));
            }
        }
    }

    fn reader_of(&self, who: usize) -> Option<Reader> {
        if who == 0 { self.sc.reader_a } else { self.sc.reader_b }
    }

    fn app_step(&mut self) {
        let now = self.now;
        // B writes its response payload as soon as the connection exists.
        if !self.b_written && matches!(self.b.state, State::SynRcvd | State::Established) {
            self.b_written = true;
            if !self.data_b.is_empty() {
                let d = std::mem::take(&mut self.data_b);
                self.b.write(now, &d).expect("server write");
            }
            if self.sc.b_close_at_start {
                self.b.close(now);
            }
        }
        for who in 0..2 {
            if self.reader_of(who).is_none() {
                let tcb = if who == 0 { &mut self.a } else { &mut self.b };
                let d = tcb.read(now, usize::MAX);
                if who == 0 { self.recv_a.extend(d) } else { self.recv_b.extend(d) }
            }
        }
        // Server closes when it hits EOF; client closes right after queueing its data.
        if self.b.eof() && self.b.state == State::CloseWait {
            self.b.close(now);
        }
        if self.a.eof() && self.a.state == State::CloseWait {
            self.a.close(now);
        }
        if self.delivered_us.is_none() && self.recv_b.len() >= self.sc.bytes_a_to_b && self.b.state != State::Closed {
            self.delivered_us = Some(now);
        }
        self.pump();
        self.drain_events();
    }

    fn arm_reader(&mut self, who: usize) {
        if let Some(r) = self.reader_of(who) {
            let tcb = if who == 0 { &self.a } else { &self.b };
            let active = !matches!(tcb.state, State::Closed) && !tcb.eof();
            if active && self.next_read[who].is_none() {
                self.next_read[who] = Some(self.now + r.tick_us);
            }
        }
    }

    pub fn start(&mut self) {
        if self.started {
            return;
        }
        self.started = true;
        if self.sc.simultaneous_open {
            self.b.connect(0, ADDR_A, PORT_A);
        } else if self.sc.b_listens {
            self.b.listen();
        }
        self.a.connect(0, ADDR_B, PORT_B);
        if !self.data_a.is_empty() {
            let d = self.data_a.clone();
            self.a.write(0, &d).expect("client write");
        }
        self.a.close(0);
        self.app_step();
        self.arm_reader(0);
        self.arm_reader(1);
    }

    /// Earliest pending thing: (time, kind). kind: 0 delivery, 1 timer A, 2 timer B, 3 read A, 4 read B.
    fn next(&self) -> Option<(u64, u8)> {
        let mut best: Option<(u64, u8)> = None;
        let mut consider = |t: u64, k: u8| {
            if best.map_or(true, |(bt, bk)| (t, k) < (bt, bk)) {
                best = Some((t, k));
            }
        };
        if let Some(Reverse((t, ..))) = self.heap.peek() {
            consider(*t, 0);
        }
        if let Some(t) = self.a.next_timer() {
            consider(t, 1);
        }
        if let Some(t) = self.b.next_timer() {
            consider(t, 2);
        }
        if let Some(t) = self.next_read[0] {
            consider(t, 3);
        }
        if let Some(t) = self.next_read[1] {
            consider(t, 4);
        }
        best
    }

    /// Advance one event. Returns false when nothing is left to do.
    pub fn step(&mut self) -> bool {
        self.start();
        let Some((t, kind)) = self.next() else { return false };
        if t > self.sc.max_time_us {
            self.timed_out = true;
            return false;
        }
        self.now = t.max(self.now);
        match kind {
            0 => {
                let Reverse((_, _, dest, bytes)) = self.heap.pop().unwrap();
                let (src, dst) = if dest == 0 { (ADDR_B, ADDR_A) } else { (ADDR_A, ADDR_B) };
                let tcb = if dest == 0 { &mut self.a } else { &mut self.b };
                match Segment::decode(src, dst, &bytes) {
                    Ok(seg) => tcb.on_segment(self.now, seg),
                    Err(e) => {
                        tcb.note_corrupt();
                        let who = if dest == 0 { "A" } else { "B" };
                        self.logf(self.now, who, format!("-- discarded corrupt segment ({e})"));
                    }
                }
            }
            1 => self.a.on_timer(self.now),
            2 => self.b.on_timer(self.now),
            k => {
                let who = (k - 3) as usize;
                self.next_read[who] = None;
                let r = self.reader_of(who).unwrap();
                let n = ((r.bytes_per_sec as u128 * r.tick_us as u128) / 1_000_000).max(1) as usize;
                let tcb = if who == 0 { &mut self.a } else { &mut self.b };
                let d = tcb.read(self.now, n);
                if who == 0 { self.recv_a.extend(d) } else { self.recv_b.extend(d) }
            }
        }
        self.app_step();
        self.arm_reader(0);
        self.arm_reader(1);
        true
    }

    pub fn run(&mut self) -> Outcome {
        let mut n = 0u64;
        while self.step() {
            n += 1;
            if n > 50_000_000 {
                self.timed_out = true;
                break;
            }
        }
        self.outcome()
    }

    pub fn outcome(&self) -> Outcome {
        let verified = self.recv_b == pattern(self.sc.bytes_a_to_b, self.sc.seed ^ 0xA)
            && self.recv_a == pattern(self.sc.bytes_b_to_a, self.sc.seed ^ 0xB);
        let goodput = match self.delivered_us {
            Some(t) if t > 0 => self.sc.bytes_a_to_b as f64 * 8.0 / (t as f64 / 1e6),
            _ => 0.0,
        };
        Outcome {
            name: self.sc.name.clone(),
            algo: self.sc.cfg_a.algo,
            verified,
            bytes: self.sc.bytes_a_to_b,
            delivered_us: self.delivered_us,
            end_us: self.now,
            goodput_bps: goodput,
            timed_out: self.timed_out,
            a_state: self.a.state,
            b_state: self.b.state,
            a_error: self.a.error,
            b_error: self.b.error,
        }
    }

    /// Window-scale shift B advertises with (test helper).
    pub fn b_wscale_for_test(&self) -> u8 {
        self.b.rcv_wscale()
    }

    pub fn link_stats(&self) -> (&LinkStats, &LinkStats) {
        (&self.link_ab.stats, &self.link_ba.stats)
    }
}
