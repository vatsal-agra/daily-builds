//! Congestion control: Tahoe, Reno (RFC 5681), NewReno (RFC 6582) and CUBIC (RFC 8312).
//!
//! The TCB owns the wire; this module owns `cwnd`/`ssthresh` and decides *when a loss happened*.
//! All windows are in bytes.

use crate::segment::{seq_geq, seq_gt};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Algo {
    Tahoe,
    Reno,
    NewReno,
    Cubic,
}

impl Algo {
    pub const ALL: [Algo; 4] = [Algo::Tahoe, Algo::Reno, Algo::NewReno, Algo::Cubic];

    pub fn name(&self) -> &'static str {
        match self {
            Algo::Tahoe => "tahoe",
            Algo::Reno => "reno",
            Algo::NewReno => "newreno",
            Algo::Cubic => "cubic",
        }
    }

    pub fn parse(s: &str) -> Result<Algo, String> {
        match s.to_ascii_lowercase().as_str() {
            "tahoe" => Ok(Algo::Tahoe),
            "reno" => Ok(Algo::Reno),
            "newreno" | "new-reno" => Ok(Algo::NewReno),
            "cubic" => Ok(Algo::Cubic),
            _ => Err(format!("unknown congestion control '{s}' (tahoe|reno|newreno|cubic)")),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DupAction {
    /// Nothing to do.
    None,
    /// Third duplicate ACK: retransmit the head of the window now.
    FastRetransmit,
    /// Already in fast recovery: cwnd was inflated, try to send new data.
    Inflate,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AckAction {
    None,
    /// NewReno partial ACK: retransmit the next hole immediately.
    RetransmitHead,
    /// Recovery finished with this ACK.
    RecoveryExit,
}

const CUBIC_C: f64 = 0.4;
const CUBIC_BETA: f64 = 0.7;

#[derive(Clone, Debug, Default)]
struct CubicState {
    /// Window (segments) just before the last reduction.
    w_max: f64,
    w_last_max: f64,
    epoch_start: Option<u64>,
    k: f64,
    origin: f64,
    w_est: f64,
    /// Sub-byte remainder of cwnd growth.
    frac: f64,
}

#[derive(Clone, Debug)]
pub struct Cc {
    pub algo: Algo,
    mss: u64,
    pub cwnd: u64,
    pub ssthresh: u64,
    pub dupacks: u32,
    pub in_recovery: bool,
    /// Highest sequence number sent when the current loss episode began (RFC 6582 "recover").
    pub recover: u32,
    ca_acc: u64,
    cubic: CubicState,
}

impl Cc {
    pub fn new(algo: Algo, mss: usize, init_segs: usize, iss: u32) -> Cc {
        Cc {
            algo,
            mss: mss as u64,
            cwnd: (init_segs * mss) as u64,
            ssthresh: u64::MAX / 4,
            dupacks: 0,
            in_recovery: false,
            recover: iss,
            ca_acc: 0,
            cubic: CubicState::default(),
        }
    }

    pub fn in_slow_start(&self) -> bool {
        self.cwnd < self.ssthresh
    }

    fn reduced_ssthresh(&self, flight: u64) -> u64 {
        let base = match self.algo {
            Algo::Cubic => (self.cwnd as f64 * CUBIC_BETA) as u64,
            _ => flight / 2,
        };
        base.max(2 * self.mss)
    }

    fn cubic_on_loss(&mut self) {
        let segs = self.cwnd as f64 / self.mss as f64;
        let c = &mut self.cubic;
        // Fast convergence: if we lost below the previous peak, release bandwidth faster.
        if segs < c.w_last_max {
            c.w_last_max = segs;
            c.w_max = segs * (1.0 + CUBIC_BETA) / 2.0;
        } else {
            c.w_last_max = segs;
            c.w_max = segs;
        }
        c.epoch_start = None;
        c.frac = 0.0;
    }

    /// A duplicate ACK arrived (same ack, no data, window unchanged, data outstanding).
    pub fn on_dupack(&mut self, flight: u64, snd_una: u32, snd_nxt: u32) -> DupAction {
        self.dupacks += 1;
        if self.in_recovery {
            self.cwnd += self.mss;
            return DupAction::Inflate;
        }
        if self.dupacks == 3 && seq_gt(snd_una, self.recover) {
            if self.algo == Algo::Cubic {
                self.cubic_on_loss();
            }
            self.ssthresh = self.reduced_ssthresh(flight);
            self.recover = snd_nxt;
            if self.algo == Algo::Tahoe {
                self.cwnd = self.mss;
                self.dupacks = 0;
            } else {
                self.in_recovery = true;
                self.cwnd = self.ssthresh + 3 * self.mss;
            }
            return DupAction::FastRetransmit;
        }
        DupAction::None
    }

    /// A new cumulative ACK advanced snd_una to `snd_una`, acknowledging `acked` bytes.
    pub fn on_new_ack(&mut self, acked: u64, snd_una: u32, now_us: u64, min_rtt_us: u64) -> AckAction {
        self.dupacks = 0;
        if self.in_recovery {
            let full = seq_geq(snd_una, self.recover);
            if self.algo == Algo::Reno || full {
                self.cwnd = self.ssthresh;
                self.in_recovery = false;
                self.ca_acc = 0;
                return AckAction::RecoveryExit;
            }
            // NewReno / CUBIC partial ACK: deflate by what was acked, add back one MSS.
            self.cwnd = self.cwnd.saturating_sub(acked);
            if acked >= self.mss {
                self.cwnd += self.mss;
            }
            self.cwnd = self.cwnd.max(self.mss);
            return AckAction::RetransmitHead;
        }
        if self.in_slow_start() {
            self.cwnd += acked.min(self.mss);
            return AckAction::None;
        }
        match self.algo {
            Algo::Cubic => self.cubic_grow(acked, now_us, min_rtt_us),
            _ => {
                // Congestion avoidance: +1 MSS per cwnd bytes acked (≈ +1 MSS per RTT).
                self.ca_acc += acked;
                if self.ca_acc >= self.cwnd {
                    self.ca_acc -= self.cwnd;
                    self.cwnd += self.mss;
                }
            }
        }
        AckAction::None
    }

    fn cubic_grow(&mut self, acked: u64, now_us: u64, min_rtt_us: u64) {
        let mss = self.mss as f64;
        let cwnd_segs = self.cwnd as f64 / mss;
        let acked_segs = acked as f64 / mss;
        let c = &mut self.cubic;
        if c.epoch_start.is_none() {
            c.epoch_start = Some(now_us);
            c.w_est = cwnd_segs;
            if cwnd_segs < c.w_max {
                c.k = ((c.w_max - cwnd_segs) / CUBIC_C).cbrt();
                c.origin = c.w_max;
            } else {
                c.k = 0.0;
                c.origin = cwnd_segs;
            }
        }
        let t = (now_us - c.epoch_start.unwrap()) as f64 / 1e6 + min_rtt_us as f64 / 1e6;
        let w_cubic = CUBIC_C * (t - c.k).powi(3) + c.origin;
        // TCP-friendly region (RFC 8312 §4.2): what Reno-AIMD with the same β would have.
        c.w_est += 3.0 * (1.0 - CUBIC_BETA) / (1.0 + CUBIC_BETA) * acked_segs / cwnd_segs;
        let target = w_cubic.max(c.w_est);
        let inc_segs = if target > cwnd_segs {
            // Cap growth at +0.5 segment per acked segment (≤ 1.5× per RTT).
            ((target - cwnd_segs) / cwnd_segs).min(0.5) * acked_segs
        } else {
            acked_segs / (100.0 * cwnd_segs)
        };
        let total = self.cwnd as f64 + c.frac + inc_segs * mss;
        self.cwnd = total.floor() as u64;
        c.frac = total - total.floor();
    }

    /// Retransmission timeout fired.
    pub fn on_timeout(&mut self, flight: u64, snd_nxt: u32) {
        if self.algo == Algo::Cubic {
            self.cubic_on_loss();
        }
        self.ssthresh = self.reduced_ssthresh(flight);
        self.cwnd = self.mss;
        self.dupacks = 0;
        self.in_recovery = false;
        self.recover = snd_nxt;
        self.ca_acc = 0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const MSS: u64 = 1000;

    fn cc(a: Algo) -> Cc {
        Cc::new(a, MSS as usize, 2, 1000)
    }

    #[test]
    fn slow_start_doubles_per_rtt() {
        let mut c = cc(Algo::Reno);
        assert_eq!(c.cwnd, 2000);
        // One RTT = ack every outstanding segment.
        for _ in 0..2 {
            c.on_new_ack(MSS, 2001, 0, 0);
        }
        assert_eq!(c.cwnd, 4000);
        for _ in 0..4 {
            c.on_new_ack(MSS, 2001, 0, 0);
        }
        assert_eq!(c.cwnd, 8000);
    }

    #[test]
    fn congestion_avoidance_adds_one_mss_per_rtt() {
        let mut c = cc(Algo::Reno);
        c.cwnd = 10_000;
        c.ssthresh = 5_000;
        for _ in 0..10 {
            c.on_new_ack(MSS, 5001, 0, 0);
        }
        assert_eq!(c.cwnd, 11_000);
    }

    #[test]
    fn reno_triple_dupack_halves_and_inflates() {
        let mut c = cc(Algo::Reno);
        c.cwnd = 20_000;
        c.ssthresh = 5_000;
        assert_eq!(c.on_dupack(20_000, 2001, 22001), DupAction::None);
        assert_eq!(c.on_dupack(20_000, 2001, 22001), DupAction::None);
        assert_eq!(c.on_dupack(20_000, 2001, 22001), DupAction::FastRetransmit);
        assert_eq!(c.ssthresh, 10_000);
        assert_eq!(c.cwnd, 13_000);
        assert!(c.in_recovery);
        assert_eq!(c.on_dupack(20_000, 2001, 22001), DupAction::Inflate);
        assert_eq!(c.cwnd, 14_000);
        // Any new ACK deflates to ssthresh and exits (Reno).
        assert_eq!(c.on_new_ack(MSS, 3001, 0, 0), AckAction::RecoveryExit);
        assert_eq!(c.cwnd, 10_000);
        assert!(!c.in_recovery);
    }

    #[test]
    fn newreno_partial_ack_stays_in_recovery() {
        let mut c = cc(Algo::NewReno);
        c.cwnd = 20_000;
        c.ssthresh = 5_000;
        for _ in 0..3 {
            c.on_dupack(20_000, 2001, 22001);
        }
        assert!(c.in_recovery);
        assert_eq!(c.recover, 22001);
        // Partial ack (2 segments) < recover
        assert_eq!(c.on_new_ack(2 * MSS, 4001, 0, 0), AckAction::RetransmitHead);
        assert!(c.in_recovery);
        assert_eq!(c.cwnd, 13_000 - 2000 + 1000);
        // Full ack exits.
        assert_eq!(c.on_new_ack(18 * MSS, 22001, 0, 0), AckAction::RecoveryExit);
        assert_eq!(c.cwnd, 10_000);
    }

    #[test]
    fn tahoe_collapses_to_one_mss() {
        let mut c = cc(Algo::Tahoe);
        c.cwnd = 16_000;
        for _ in 0..2 {
            c.on_dupack(16_000, 2001, 18001);
        }
        assert_eq!(c.on_dupack(16_000, 2001, 18001), DupAction::FastRetransmit);
        assert_eq!(c.cwnd, MSS);
        assert_eq!(c.ssthresh, 8_000);
        assert!(!c.in_recovery);
        assert!(c.in_slow_start());
    }

    #[test]
    fn timeout_resets_window() {
        for a in Algo::ALL {
            let mut c = cc(a);
            c.cwnd = 30_000;
            c.on_timeout(30_000, 40_000);
            assert_eq!(c.cwnd, MSS, "{a:?}");
            assert!(c.ssthresh >= 2 * MSS && c.ssthresh <= 21_000, "{a:?} {}", c.ssthresh);
            assert!(!c.in_recovery);
        }
        // ssthresh floor.
        let mut c = cc(Algo::Reno);
        c.on_timeout(1_000, 2);
        assert_eq!(c.ssthresh, 2 * MSS);
    }

    #[test]
    fn stale_dupacks_after_recovery_do_not_retrigger() {
        // RFC 6582: dupacks for data sent before `recover` must not start a new episode.
        let mut c = cc(Algo::NewReno);
        c.cwnd = 20_000;
        c.recover = 50_000;
        for _ in 0..5 {
            assert_eq!(c.on_dupack(20_000, 40_000, 60_000), DupAction::None);
        }
        assert!(!c.in_recovery);
    }

    #[test]
    fn cubic_reduces_by_beta_and_regrows_concavely_toward_wmax() {
        let mut c = cc(Algo::Cubic);
        c.cwnd = 100 * MSS;
        c.ssthresh = 50 * MSS;
        for _ in 0..2 {
            c.on_dupack(100_000, 2001, 102_001);
        }
        assert_eq!(c.on_dupack(100_000, 2001, 102_001), DupAction::FastRetransmit);
        assert_eq!(c.ssthresh, 70_000);
        assert_eq!(c.cwnd, 73_000);
        c.on_new_ack(MSS, 102_001, 1_000_000, 50_000); // exit recovery
        assert_eq!(c.cwnd, 70_000);
        // Ack-clock 100 ms RTTs for 15 s; cwnd should approach and pass the old peak (100 segs)
        // around K = cbrt((100-70)/0.4) ≈ 4.2 s, growing fast first, then flattening near w_max.
        let mut now = 1_000_000u64;
        let mut at_k = 0;
        let mut samples = Vec::new();
        for rtt in 0..150 {
            let segs = c.cwnd / MSS;
            for _ in 0..segs {
                c.on_new_ack(MSS, 102_001, now, 50_000);
            }
            now += 100_000;
            if rtt == 41 {
                at_k = c.cwnd / MSS;
            }
            samples.push(c.cwnd / MSS);
        }
        assert!((90..=112).contains(&at_k), "cwnd at K ≈ {at_k} segs");
        // concave then convex: growth in the first second > growth around the plateau.
        let early = samples[9] - samples[0];
        let plateau = samples[45] - samples[36];
        assert!(early > plateau, "early {early} plateau {plateau}");
        assert!(samples[149] > 100, "should exceed old w_max eventually: {}", samples[149]);
    }

    #[test]
    fn cubic_fast_convergence_lowers_wmax_when_losing_below_last_peak() {
        let mut c = cc(Algo::Cubic);
        c.cwnd = 100 * MSS;
        c.on_timeout(100_000, 5);
        let wmax_first = c.cubic.w_max;
        assert!((wmax_first - 100.0).abs() < 1e-9);
        c.cwnd = 60 * MSS; // regrew only to 60 < 100, then lost again
        c.on_timeout(60_000, 9);
        assert!((c.cubic.w_max - 60.0 * 0.85).abs() < 1e-9, "{}", c.cubic.w_max);
    }

    #[test]
    fn parse_names() {
        assert_eq!(Algo::parse("NewReno").unwrap(), Algo::NewReno);
        assert!(Algo::parse("bbr").is_err());
    }
}
