//! One direction of a network path: a bottleneck link with a drop-tail queue plus a menu of
//! nasty behaviours (loss, corruption, duplication, reordering, jitter). Deterministic given a seed.

use crate::rng::Rng;
use crate::segment::IP_HEADER_LEN;
use std::collections::VecDeque;

#[derive(Clone, Debug)]
pub struct LinkConfig {
    /// Bottleneck rate in bit/s.
    pub rate_bps: u64,
    /// One-way propagation delay (µs).
    pub delay_us: u64,
    /// Uniform extra delay in [0, jitter] per packet (µs). Jitter can reorder packets.
    pub jitter_us: u64,
    /// Drop-tail queue capacity in packets (including the one being transmitted).
    pub queue_pkts: usize,
    /// Random loss probability (on the wire, after queueing).
    pub loss: f64,
    /// Probability a delivered packet has one random bit flipped.
    pub corrupt: f64,
    /// Probability a delivered packet is delivered twice.
    pub dup: f64,
    /// Probability a packet is held back an extra `reorder_extra_us`.
    pub reorder: f64,
    pub reorder_extra_us: u64,
    /// 1-based indices of *data-bearing* packets to drop deterministically (first pass only:
    /// index counts every data packet the link sees, retransmissions included).
    pub drop_data: Vec<usize>,
}

impl Default for LinkConfig {
    fn default() -> Self {
        LinkConfig {
            rate_bps: 10_000_000,
            delay_us: 20_000,
            jitter_us: 0,
            queue_pkts: 100,
            loss: 0.0,
            corrupt: 0.0,
            dup: 0.0,
            reorder: 0.0,
            reorder_extra_us: 0,
            drop_data: Vec::new(),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DropReason {
    QueueFull,
    RandomLoss,
    Scripted,
}

impl DropReason {
    pub fn name(&self) -> &'static str {
        match self {
            DropReason::QueueFull => "queue overflow",
            DropReason::RandomLoss => "random loss",
            DropReason::Scripted => "scripted drop",
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct LinkStats {
    pub sent: u64,
    pub delivered: u64,
    pub dropped_queue: u64,
    pub dropped_loss: u64,
    pub dropped_scripted: u64,
    pub corrupted: u64,
    pub duplicated: u64,
    pub reordered: u64,
    pub bytes_delivered: u64,
    pub max_queue: usize,
}

#[derive(Debug)]
pub enum Verdict {
    Dropped(DropReason),
    /// (arrival time µs, bytes) — 1 entry normally, 2 when duplicated.
    Deliver(Vec<(u64, Vec<u8>)>),
}

pub struct Link {
    pub cfg: LinkConfig,
    rng: Rng,
    busy_until: u64,
    /// Departure (end-of-serialisation) times of packets still queued/being sent.
    queued: VecDeque<u64>,
    data_seen: usize,
    pub stats: LinkStats,
}

impl Link {
    pub fn new(cfg: LinkConfig, seed: u64) -> Self {
        Link { cfg, rng: Rng::new(seed), busy_until: 0, queued: VecDeque::new(), data_seen: 0, stats: LinkStats::default() }
    }

    /// Current queue occupancy (packets) at time `now`.
    pub fn occupancy(&mut self, now: u64) -> usize {
        while matches!(self.queued.front(), Some(&t) if t <= now) {
            self.queued.pop_front();
        }
        self.queued.len()
    }

    /// Offer a packet to the link at time `now`.
    pub fn send(&mut self, now: u64, bytes: Vec<u8>, carries_data: bool) -> Verdict {
        self.stats.sent += 1;
        let occ = self.occupancy(now);
        if carries_data {
            self.data_seen += 1;
        }
        if occ >= self.cfg.queue_pkts {
            self.stats.dropped_queue += 1;
            return Verdict::Dropped(DropReason::QueueFull);
        }
        // Serialise behind whatever is already queued.
        let wire_bits = ((bytes.len() + IP_HEADER_LEN) * 8) as u64;
        let tx_us = (wire_bits * 1_000_000).div_ceil(self.cfg.rate_bps).max(1);
        let start = self.busy_until.max(now);
        let depart = start + tx_us;
        self.busy_until = depart;
        self.queued.push_back(depart);
        self.stats.max_queue = self.stats.max_queue.max(self.queued.len());

        // Loss happens "on the wire": the packet still consumed bottleneck capacity.
        if carries_data && self.cfg.drop_data.contains(&self.data_seen) {
            self.stats.dropped_scripted += 1;
            return Verdict::Dropped(DropReason::Scripted);
        }
        if self.rng.chance(self.cfg.loss) {
            self.stats.dropped_loss += 1;
            return Verdict::Dropped(DropReason::RandomLoss);
        }

        let mut arrive = depart + self.cfg.delay_us;
        if self.cfg.jitter_us > 0 {
            arrive += self.rng.below(self.cfg.jitter_us + 1);
        }
        if self.rng.chance(self.cfg.reorder) {
            arrive += self.cfg.reorder_extra_us;
            self.stats.reordered += 1;
        }
        let mut bytes = bytes;
        if self.rng.chance(self.cfg.corrupt) {
            let bit = self.rng.below(bytes.len() as u64 * 8) as usize;
            bytes[bit / 8] ^= 1 << (bit % 8);
            self.stats.corrupted += 1;
        }
        self.stats.delivered += 1;
        self.stats.bytes_delivered += bytes.len() as u64;
        let mut out = vec![(arrive, bytes.clone())];
        if self.rng.chance(self.cfg.dup) {
            self.stats.duplicated += 1;
            out.push((arrive + 1 + self.rng.below(2_000), bytes));
        }
        Verdict::Deliver(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg() -> LinkConfig {
        LinkConfig { rate_bps: 8_000_000, delay_us: 10_000, queue_pkts: 3, ..Default::default() }
    }

    fn pkt(n: usize) -> Vec<u8> {
        vec![0u8; n]
    }

    #[test]
    fn serialisation_and_propagation_delay() {
        let mut l = Link::new(cfg(), 1);
        // (980 + 20) bytes = 8000 bits @ 8 Mbit/s = 1000 µs.
        match l.send(0, pkt(980), true) {
            Verdict::Deliver(v) => assert_eq!(v, vec![(11_000, pkt(980))]),
            _ => panic!(),
        }
        // Second packet queues behind the first.
        match l.send(0, pkt(980), true) {
            Verdict::Deliver(v) => assert_eq!(v[0].0, 12_000),
            _ => panic!(),
        }
    }

    #[test]
    fn drop_tail_when_queue_full_then_drains() {
        let mut l = Link::new(cfg(), 1);
        for _ in 0..3 {
            assert!(matches!(l.send(0, pkt(980), true), Verdict::Deliver(_)));
        }
        assert!(matches!(l.send(0, pkt(980), true), Verdict::Dropped(DropReason::QueueFull)));
        assert_eq!(l.occupancy(0), 3);
        assert_eq!(l.occupancy(1_000), 2);
        assert_eq!(l.occupancy(3_000), 0);
        assert!(matches!(l.send(3_000, pkt(980), true), Verdict::Deliver(_)));
        assert_eq!(l.stats.dropped_queue, 1);
        assert_eq!(l.stats.max_queue, 3);
    }

    #[test]
    fn scripted_drops_count_only_data_packets() {
        let mut c = cfg();
        c.drop_data = vec![2];
        let mut l = Link::new(c, 1);
        assert!(matches!(l.send(0, pkt(40), false), Verdict::Deliver(_))); // pure ack: not counted
        assert!(matches!(l.send(10_000, pkt(500), true), Verdict::Deliver(_))); // data #1
        assert!(matches!(l.send(20_000, pkt(500), true), Verdict::Dropped(DropReason::Scripted))); // #2
        assert!(matches!(l.send(30_000, pkt(500), true), Verdict::Deliver(_))); // #3
    }

    #[test]
    fn random_loss_rate_is_about_right() {
        let mut c = cfg();
        c.loss = 0.1;
        c.queue_pkts = 10_000;
        let mut l = Link::new(c, 42);
        for i in 0..20_000u64 {
            l.send(i * 10_000, pkt(100), true);
        }
        let d = l.stats.dropped_loss;
        assert!((1_700..2_300).contains(&d), "dropped {d}");
    }

    #[test]
    fn corruption_flips_exactly_one_bit() {
        let mut c = cfg();
        c.corrupt = 1.0;
        let mut l = Link::new(c, 3);
        let orig = pkt(64);
        match l.send(0, orig.clone(), true) {
            Verdict::Deliver(v) => {
                let flipped: u32 = v[0].1.iter().zip(&orig).map(|(a, b)| (a ^ b).count_ones()).sum();
                assert_eq!(flipped, 1);
            }
            _ => panic!(),
        }
    }

    #[test]
    fn duplication_and_reordering() {
        let mut c = cfg();
        c.dup = 1.0;
        let mut l = Link::new(c, 3);
        match l.send(0, pkt(64), true) {
            Verdict::Deliver(v) => {
                assert_eq!(v.len(), 2);
                assert!(v[1].0 > v[0].0);
            }
            _ => panic!(),
        }
        let mut c = cfg();
        c.reorder = 1.0;
        c.reorder_extra_us = 50_000;
        let mut l = Link::new(c, 3);
        match l.send(0, pkt(64), true) {
            Verdict::Deliver(v) => assert!(v[0].0 >= 60_000),
            _ => panic!(),
        }
        assert_eq!(l.stats.reordered, 1);
    }
}
