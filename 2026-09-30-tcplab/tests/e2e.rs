//! End-to-end tests: every feature exercised through the deterministic simulator.

use tcplab::cc::Algo;
use tcplab::link::LinkConfig;
use tcplab::segment::*;
use tcplab::sim::*;
use tcplab::tcp::*;

fn states(t: &Tcb) -> Vec<State> {
    let mut v = vec![State::Closed];
    for (_, e) in &t.events {
        if let Event::State(_, to) = e {
            v.push(*to);
        }
    }
    v
}

fn run(sc: Scenario) -> (Sim, Outcome) {
    let mut sim = Sim::new(sc);
    let o = sim.run();
    (sim, o)
}

fn base(bytes: usize) -> Scenario {
    let mut s = Scenario::new("t");
    s.bytes_a_to_b = bytes;
    s
}

// ---------------------------------------------------------------- feature 2: state machine

#[test]
fn full_lifecycle_state_sequences() {
    let (sim, o) = run(base(5_000));
    assert!(o.verified);
    use State::*;
    assert_eq!(states(&sim.a), vec![Closed, SynSent, Established, FinWait1, FinWait2, TimeWait, Closed]);
    assert_eq!(states(&sim.b), vec![Closed, Listen, SynRcvd, Established, CloseWait, LastAck, Closed]);
    assert!(sim.a.error.is_none() && sim.b.error.is_none());
}

#[test]
fn handshake_negotiates_mss_and_window_scale() {
    let mut s = base(0);
    s.cfg_a.mss = 1460;
    s.cfg_b.mss = 536;
    s.cfg_b.rcv_buf = 1 << 20; // needs wscale 5 to advertise
    let (sim, o) = run(s);
    assert!(o.verified);
    assert_eq!(sim.a.mss, 536);
    assert_eq!(sim.b.mss, 536);
}

#[test]
fn syn_ack_carries_options_on_the_wire() {
    let mut s = base(0);
    s.dump = true;
    s.cfg_b.rcv_buf = 1 << 20;
    let (sim, _) = run(s);
    let syn = sim.log.iter().find(|l| l.contains("Flags [S]")).unwrap();
    let synack = sim.log.iter().find(|l| l.contains("Flags [S.]")).unwrap();
    assert!(syn.contains("mss 1000") && syn.contains("wscale 1"), "{syn}");
    assert!(synack.contains("wscale 5"), "{synack}");
}

#[test]
fn connection_refused_when_nobody_listens() {
    let mut s = base(1000);
    s.b_listens = false;
    let (sim, o) = run(s);
    assert_eq!(o.a_error, Some(ConnError::Refused));
    assert_eq!(o.a_state, State::Closed);
    assert!(!o.verified);
    assert_eq!(sim.b.stats.rst_tx, 1);
    assert!(o.end_us < 200_000, "refusal must be immediate, took {} us", o.end_us);
}

#[test]
fn syn_retries_back_off_then_time_out() {
    let mut s = base(1000);
    s.link_ab.loss = 1.0; // black hole
    s.cfg_a.syn_retries = 3;
    s.cfg_a.init_rto_us = 1_000_000;
    let (sim, o) = run(s);
    assert_eq!(o.a_error, Some(ConnError::TimedOut));
    assert_eq!(sim.a.stats.retransmits, 3);
    // 1s + 2s + 4s + 8s of backoff before giving up.
    assert_eq!(o.end_us, 15_000_000);
}

#[test]
fn simultaneous_open_completes_and_transfers() {
    let mut s = base(20_000);
    s.simultaneous_open = true;
    let (sim, o) = run(s);
    assert!(o.verified, "{o:?}");
    use State::*;
    assert_eq!(states(&sim.a)[..4], [Closed, SynSent, SynRcvd, Established]);
    assert_eq!(states(&sim.b)[..4], [Closed, SynSent, SynRcvd, Established]);
}

#[test]
fn simultaneous_close_goes_through_closing() {
    let mut s = base(0);
    s.b_close_at_start = true;
    let (sim, o) = run(s);
    assert_eq!(o.a_error, None);
    assert_eq!(o.b_error, None);
    assert!(states(&sim.a).contains(&State::Closing) || states(&sim.b).contains(&State::Closing));
    assert!(states(&sim.a).contains(&State::TimeWait) && states(&sim.b).contains(&State::TimeWait));
    assert_eq!((o.a_state, o.b_state), (State::Closed, State::Closed));
}

#[test]
fn time_wait_lasts_two_msl() {
    let mut s = base(0);
    s.cfg_a.msl_us = 3_000_000;
    let (sim, _) = run(s);
    let tw = sim.a.events.iter().find_map(|(t, e)| matches!(e, Event::State(_, State::TimeWait)).then_some(*t)).unwrap();
    let closed = sim.a.events.iter().rev().find_map(|(t, e)| matches!(e, Event::State(_, State::Closed)).then_some(*t)).unwrap();
    assert_eq!(closed - tw, 6_000_000);
}

#[test]
fn lost_final_ack_is_recovered_by_fin_retransmit() {
    // Drop A→B pure ACKs? Use heavy loss on the A→B path in the closing phase via seeds sweep.
    for seed in 0..20 {
        let mut s = base(3_000);
        s.seed = seed;
        s.link_ab.loss = 0.3;
        s.link_ba.loss = 0.3;
        let (_, o) = run(s);
        assert!(o.verified, "seed {seed}: {o:?}");
        assert_eq!((o.a_state, o.b_state), (State::Closed, State::Closed), "seed {seed}");
    }
}

// ---------------------------------------------------------------- feature 3: reliability

#[test]
fn clean_transfer_needs_no_retransmissions() {
    let (sim, o) = run(base(500_000));
    assert!(o.verified);
    assert_eq!(sim.a.stats.retransmits, 0);
    assert_eq!(sim.a.stats.timeouts, 0);
    assert_eq!(sim.b.stats.ooo_segs, 0);
    assert_eq!(sim.a.stats.bytes_acked, 500_000);
}

#[test]
fn single_loss_is_repaired_by_fast_retransmit_not_timeout() {
    for algo in [Algo::Reno, Algo::NewReno, Algo::Cubic, Algo::Tahoe] {
        let mut s = base(300_000);
        s.set_algo(algo);
        s.link_ab.drop_data = vec![60];
        let (sim, o) = run(s);
        assert!(o.verified, "{algo:?}");
        assert_eq!(sim.a.stats.timeouts, 0, "{algo:?}");
        assert_eq!(sim.a.stats.fast_retransmits, 1, "{algo:?}");
        assert!(sim.a.stats.dupacks_rx >= 3);
        assert!(sim.b.stats.ooo_segs >= 3);
    }
}

#[test]
fn tail_loss_needs_an_rto() {
    let mut s = base(50_000); // exactly 50 data segments
    s.link_ab.drop_data = vec![50];
    let (sim, o) = run(s);
    assert!(o.verified);
    assert_eq!(sim.a.stats.fast_retransmits, 0);
    assert!(sim.a.stats.timeouts >= 1);
}

#[test]
fn rto_backs_off_exponentially_on_repeated_loss() {
    let mut s = base(20_000);
    // Lose the last segment and its next three retransmissions.
    s.link_ab.drop_data = vec![20, 21, 22, 23];
    let (sim, o) = run(s);
    assert!(o.verified);
    let rtos: Vec<u64> = sim.a.events.iter().filter_map(|(_, e)| if let Event::Timeout { rto_us } = e { Some(*rto_us) } else { None }).collect();
    assert_eq!(rtos.len(), 4, "{rtos:?}");
    for w in rtos.windows(2) {
        assert_eq!(w[1], w[0] * 2, "{rtos:?}");
    }
    assert_eq!(sim.a.stats.timeouts, 4);
}

#[test]
fn rto_never_below_floor_and_srtt_tracks_path_rtt() {
    let (sim, _) = run(base(200_000));
    let srtt = sim.a.srtt_us().unwrap();
    // 2×20 ms propagation + serialisation of 1000 B @10 Mbit (~0.8 ms) + queueing.
    assert!((40_000..90_000).contains(&srtt), "srtt {srtt}");
    assert!(sim.a.rto_us >= sim.a.cfg.min_rto_us);
    assert!(sim.a.rto_us < 1_000_000);
}

#[test]
fn newreno_recovers_multiple_losses_in_one_window_without_timeout() {
    let mut s = base(400_000);
    s.set_algo(Algo::NewReno);
    s.link_ab.drop_data = vec![100, 102, 104];
    let (sim, o) = run(s);
    assert!(o.verified);
    assert_eq!(sim.a.stats.timeouts, 0, "NewReno partial-ACK handling should avoid an RTO");
    assert_eq!(sim.a.stats.fast_retransmits, 1);
    assert!(sim.a.events.iter().any(|(_, e)| matches!(e, Event::PartialAckRetransmit)));
}

#[test]
fn reno_suffers_more_than_newreno_on_multiple_losses() {
    let mk = |a: Algo| {
        let mut s = base(400_000);
        s.set_algo(a);
        s.link_ab.drop_data = vec![100, 102, 104];
        run(s)
    };
    let (reno, ro) = mk(Algo::Reno);
    let (newreno, no) = mk(Algo::NewReno);
    assert!(ro.verified && no.verified);
    assert!(reno.a.stats.timeouts + reno.a.stats.fast_retransmits > newreno.a.stats.timeouts + newreno.a.stats.fast_retransmits);
    assert!(no.end_us < ro.end_us, "newreno {} reno {}", no.end_us, ro.end_us);
}

#[test]
fn survives_reorder_duplication_and_corruption() {
    let mut s = base(300_000);
    s.link_ab.reorder = 0.1;
    s.link_ab.reorder_extra_us = 25_000;
    s.link_ab.dup = 0.1;
    s.link_ab.corrupt = 0.05;
    s.link_ba = s.link_ab.clone();
    let (sim, o) = run(s);
    assert!(o.verified);
    assert!(sim.b.stats.bad_checksum > 0, "corruption must have been detected by checksum");
    assert!(sim.b.stats.dup_segs > 0);
    assert!(sim.b.stats.ooo_segs > 0);
}

#[test]
fn sequence_number_wraparound() {
    for iss in [0xFFFF_F000u32, 0xFFFF_FFFF, 0xFFFF_FC18] {
        let mut s = base(200_000);
        s.cfg_a.iss = iss;
        s.cfg_b.iss = iss.wrapping_sub(500);
        s.link_ab.loss = 0.02;
        s.bytes_b_to_a = 50_000;
        let (_, o) = run(s);
        assert!(o.verified, "iss {iss:#x}: {o:?}");
    }
}

#[test]
fn bidirectional_transfer() {
    let mut s = base(150_000);
    s.bytes_b_to_a = 220_000;
    s.link_ab.loss = 0.02;
    s.link_ba.loss = 0.02;
    let (_, o) = run(s);
    assert!(o.verified);
}

#[test]
fn many_seeds_many_algorithms_heavy_loss() {
    for algo in Algo::ALL {
        for seed in 0..12 {
            let mut s = base(120_000);
            s.set_algo(algo);
            s.seed = seed;
            s.link_ab.loss = 0.08;
            s.link_ab.reorder = 0.05;
            s.link_ab.reorder_extra_us = 20_000;
            s.link_ab.dup = 0.03;
            s.link_ab.corrupt = 0.03;
            s.link_ba.loss = 0.05;
            let (_, o) = run(s);
            assert!(o.verified, "{algo:?} seed {seed}: {o:?}");
            assert!(!o.timed_out);
        }
    }
}

#[test]
fn data_segments_are_full_mss_except_the_last() {
    let (sim, o) = run(base(10 * 1000 + 123));
    assert!(o.verified);
    let lens: Vec<u32> = sim.a.tx_log.iter().map(|r| r.len).collect();
    assert_eq!(lens.len(), 11);
    assert!(lens[..10].iter().all(|&l| l == 1000), "{lens:?}");
    assert_eq!(lens[10], 123);
}

#[test]
fn empty_and_tiny_transfers() {
    for n in [0usize, 1, 2, 999, 1000, 1001] {
        let (_, o) = run(base(n));
        assert!(o.verified, "n={n}");
        assert_eq!(o.a_state, State::Closed, "n={n}");
    }
}

#[test]
fn simulation_is_deterministic() {
    let mk = || {
        let mut s = Scenario::preset("chaos").unwrap();
        s.dump = true;
        run(s)
    };
    let (a, oa) = mk();
    let (b, ob) = mk();
    assert_eq!(a.log, b.log);
    assert_eq!(oa.end_us, ob.end_us);
    let mut s = Scenario::preset("chaos").unwrap();
    s.seed = 99;
    s.dump = true;
    let (c, _) = run(s);
    assert_ne!(a.log, c.log);
}

// ---------------------------------------------------------------- feature 4: cc + flow control

#[test]
fn slow_start_grows_exponentially_at_first() {
    let (sim, _) = run(base(1_000_000));
    let mss = 1000u64;
    let rtt = 42_000u64;
    let cw_at = |t: u64| sim.a.samples.iter().take_while(|s| s.t <= t).last().map(|s| s.cwnd).unwrap();
    let t0 = 40_000; // established
    let c0 = cw_at(t0 + 1);
    let c3 = cw_at(t0 + 3 * rtt + rtt / 2);
    assert!(c0 <= 3 * mss, "c0={c0}");
    assert!(c3 >= 8 * c0, "cwnd after ~3 RTTs should be ≥ 8× initial: {c0} → {c3}");
}

#[test]
fn reno_sawtooth_on_a_droptail_bottleneck() {
    let mut s = Scenario::preset("bottleneck").unwrap();
    s.set_algo(Algo::Reno);
    let (sim, o) = run(s);
    assert!(o.verified);
    let a = &sim.a;
    assert!(a.stats.fast_retransmits >= 3, "expected repeated congestion episodes: {}", a.stats.fast_retransmits);
    assert!(sim.link_ab.stats.dropped_queue >= 3, "losses must come from queue overflow");
    // after each fast retransmit ssthresh is finite and cwnd never exceeds the pipe by absurd amounts
    let bdp_plus_queue = (5_000_000f64 * 0.052 / 8.0) as u64 + 20 * 1040;
    let max_flight = a.samples.iter().map(|s| s.flight).max().unwrap();
    assert!(max_flight < 3 * bdp_plus_queue, "flight {max_flight} vs pipe {bdp_plus_queue}");
    // cwnd goes down at least twice (multiplicative decrease) …
    let drops = a.samples.windows(2).filter(|w| w[1].ssthresh < w[0].ssthresh).count();
    assert!(drops >= 3, "ssthresh reductions: {drops}");
    // … and goodput is a healthy fraction of the 5 Mbit/s bottleneck.
    assert!(o.goodput_bps > 2.5e6, "goodput {}", o.goodput_bps);
}

#[test]
fn tahoe_collapses_to_one_mss_on_fast_retransmit() {
    let mut s = base(300_000);
    s.set_algo(Algo::Tahoe);
    s.link_ab.drop_data = vec![60];
    let (sim, _) = run(s);
    let ev_t = sim.a.events.iter().find_map(|(t, e)| matches!(e, Event::FastRetransmit).then_some(*t)).unwrap();
    let s_after = sim.a.samples.iter().rev().find(|s| s.t == ev_t).unwrap();
    assert_eq!(s_after.cwnd, 1000);
    assert!(s_after.ssthresh > 2000);
}

#[test]
fn cubic_outperforms_reno_on_long_fat_lossy_path() {
    let mk = |a: Algo| {
        let mut s = Scenario::preset("satellite").unwrap();
        s.set_algo(a);
        s.bytes_a_to_b = 2_000_000;
        run(s).1
    };
    let reno = mk(Algo::Reno);
    let cubic = mk(Algo::Cubic);
    assert!(reno.verified && cubic.verified);
    assert!(cubic.end_us < reno.end_us, "cubic {} vs reno {}", cubic.end_us, reno.end_us);
}

#[test]
fn flow_control_never_overruns_the_receive_buffer() {
    let sc = Scenario::preset("slowreader").unwrap();
    let cap = sc.cfg_b.rcv_buf;
    let mut sim = Sim::new(sc);
    let mut max_readable = 0;
    while sim.step() {
        max_readable = max_readable.max(sim.b.readable());
        assert!(sim.b.readable() <= cap);
    }
    let o = sim.outcome();
    assert!(o.verified);
    assert!(max_readable > cap / 2, "the buffer should actually fill: {max_readable}");
    // Sender was throttled to the reader's speed (200 kB/s) → 600 kB takes ≥ ~3 s.
    assert!(o.delivered_us.unwrap() > 2_800_000, "{:?}", o.delivered_us);
    let peak_flight = sim.a.samples.iter().map(|s| s.flight).max().unwrap();
    assert!(peak_flight <= cap as u64, "flight {peak_flight} > rcv buf {cap}");
    assert!(sim.a.samples.iter().any(|s| s.peer_wnd < 2000), "window should have closed");
}

#[test]
fn zero_window_persist_probes_survive_lost_window_updates() {
    let mut s = base(30_000);
    s.cfg_b.rcv_buf = 4096;
    s.reader_b = Some(Reader { bytes_per_sec: 4_000, tick_us: 50_000 });
    s.link_ba.loss = 0.6; // lots of lost window updates
    s.seed = 7;
    let (sim, o) = run(s);
    assert!(o.verified, "{o:?}");
    assert!(sim.a.stats.zero_window_probes > 0);
    assert_eq!(o.a_error, None, "probing must not exhaust the retry budget");
}

#[test]
fn window_scaling_negotiated_and_disabled() {
    // Large buffer + scaling: flight can exceed 65535.
    let mut s = Scenario::preset("satellite").unwrap();
    s.bytes_a_to_b = 1_500_000;
    let (sim, o) = run(s);
    assert!(o.verified);
    assert!(sim.a.samples.iter().map(|x| x.flight).max().unwrap() > 65_535);
    // Without scaling on B the window is capped at 64 KiB even with a 2 MiB buffer.
    let mut s = Scenario::preset("satellite").unwrap();
    s.bytes_a_to_b = 300_000;
    s.cfg_b.window_scaling = false;
    let (sim, o) = run(s);
    assert!(o.verified);
    assert!(sim.a.samples.iter().map(|x| x.flight).max().unwrap() <= 65_535);
}

#[test]
fn receiver_never_shrinks_advertised_edge_and_avoids_silly_windows() {
    let mut s = base(100_000);
    s.cfg_b.rcv_buf = 8000;
    s.reader_b = Some(Reader { bytes_per_sec: 50_000, tick_us: 10_000 });
    s.dump = true;
    let (sim, o) = run(s);
    assert!(o.verified);
    // No advertised window on the B→A path is in (0, mss): SWS avoidance.
    for l in sim.log.iter().filter(|l| l.contains("B > A") && !l.contains("Flags [S")) {
        let w: u64 = l.split("win ").nth(1).unwrap().split(',').next().unwrap().parse().unwrap();
        let w = w << sim.b_wscale_for_test();
        assert!(w == 0 || w >= 1000 || l.contains("Flags [F"), "silly window {w} in {l}");
    }
}

// ---------------------------------------------------------------- RST handling / robustness

/// Two hand-driven TCBs, no simulator: deliver segments explicitly.
struct Pair {
    a: Tcb,
    b: Tcb,
    now: u64,
}

impl Pair {
    fn new() -> Pair {
        let mut a = Tcb::new(Config { iss: 100, ..Config::default() }, ADDR_A, PORT_A);
        let mut b = Tcb::new(Config { iss: 900, ..Config::default() }, ADDR_B, PORT_B);
        b.listen();
        a.connect(0, ADDR_B, PORT_B);
        let mut p = Pair { a, b, now: 0 };
        p.settle();
        p
    }
    fn settle(&mut self) {
        for _ in 0..50 {
            self.now += 1000;
            let sa = self.a.take_outbox();
            let sb = self.b.take_outbox();
            if sa.is_empty() && sb.is_empty() {
                return;
            }
            for s in sa {
                let d = Segment::decode(s.src_addr, s.dst_addr, &s.encode()).unwrap();
                self.b.on_segment(self.now, d);
            }
            for s in sb {
                let d = Segment::decode(s.src_addr, s.dst_addr, &s.encode()).unwrap();
                self.a.on_segment(self.now, d);
            }
        }
    }
}

#[test]
fn abort_sends_rst_and_peer_reports_reset() {
    let mut p = Pair::new();
    assert_eq!((p.a.state, p.b.state), (State::Established, State::Established));
    p.a.abort(p.now);
    p.settle();
    assert_eq!(p.a.state, State::Closed);
    assert_eq!(p.b.state, State::Closed);
    assert_eq!(p.b.error, Some(ConnError::Reset));
}

#[test]
fn blind_rst_outside_window_is_ignored_but_in_window_rst_kills() {
    let mut p = Pair::new();
    let mut rst = Segment { src_addr: ADDR_A, dst_addr: ADDR_B, src_port: PORT_A, dst_port: PORT_B, flags: RST, seq: p.b.rcv_nxt.wrapping_add(1_000_000), ..Default::default() };
    p.b.on_segment(p.now, rst.clone());
    assert_eq!(p.b.state, State::Established, "out-of-window RST must be ignored");
    rst.seq = p.b.rcv_nxt;
    p.b.on_segment(p.now, rst);
    assert_eq!(p.b.state, State::Closed);
    assert_eq!(p.b.error, Some(ConnError::Reset));
}

#[test]
fn closed_endpoint_answers_data_with_rst_but_never_answers_rst() {
    let mut b = Tcb::new(Config::default(), ADDR_B, PORT_B);
    let data = Segment { src_addr: ADDR_A, dst_addr: ADDR_B, src_port: PORT_A, dst_port: PORT_B, flags: ACK, seq: 5, ack: 77, payload: vec![1, 2, 3], ..Default::default() };
    b.on_segment(0, data);
    let out = b.take_outbox();
    assert_eq!(out.len(), 1);
    assert!(out[0].has(RST) && out[0].seq == 77);
    let rst = Segment { src_addr: ADDR_A, dst_addr: ADDR_B, src_port: PORT_A, dst_port: PORT_B, flags: RST, ..Default::default() };
    b.on_segment(0, rst);
    assert!(b.take_outbox().is_empty());
    // A bare SYN to a closed port: RST|ACK acknowledging the SYN.
    let syn = Segment { src_addr: ADDR_A, dst_addr: ADDR_B, src_port: PORT_A, dst_port: PORT_B, flags: SYN, seq: 10, ..Default::default() };
    b.on_segment(0, syn);
    let out = b.take_outbox();
    assert!(out[0].has(RST) && out[0].has(ACK) && out[0].ack == 11);
}

#[test]
fn acks_for_unsent_data_are_answered_not_believed() {
    let mut p = Pair::new();
    let bogus = Segment { src_addr: ADDR_B, dst_addr: ADDR_A, src_port: PORT_B, dst_port: PORT_A, flags: ACK, seq: p.a.rcv_nxt, ack: p.a.snd_nxt.wrapping_add(50_000), window: 1000, ..Default::default() };
    let una_before = p.a.snd_una;
    p.a.on_segment(p.now, bogus);
    assert_eq!(p.a.snd_una, una_before);
    assert_eq!(p.a.state, State::Established);
    assert_eq!(p.a.take_outbox().len(), 1, "should answer with a corrective ACK");
}

#[test]
fn write_after_close_is_rejected_and_close_is_idempotent() {
    let mut p = Pair::new();
    p.a.write(p.now, b"hello").unwrap();
    p.a.close(p.now);
    assert!(p.a.write(p.now, b"more").is_err());
    p.a.close(p.now);
    p.settle();
    assert_eq!(p.b.read(p.now, 100), b"hello");
    assert!(p.b.eof());
}

#[test]
fn a_bad_link_config_default_is_sane() {
    let l = LinkConfig::default();
    assert!(l.rate_bps > 0 && l.queue_pkts > 0);
}

// ---------------------------------------------------------------- regressions from REVIEW.md

#[test]
fn review_fin_is_accepted_at_zero_window() {
    let mut p = Pair::new();
    p.b.cfg.rcv_buf = 2000; // tiny receive buffer on B; fill it so the window is zero
    // (cfg is read live for window computation.)
    p.a.write(p.now, &vec![1u8; 2000]).unwrap();
    p.settle();
    assert_eq!(p.b.readable(), 2000);
    p.a.close(p.now);
    p.settle();
    assert!(p.b.peer_fin, "FIN at rcv_nxt must be accepted although the window is zero");
    assert_eq!(p.b.state, State::CloseWait);
    assert_eq!(p.b.read(p.now, 10_000).len(), 2000);
}

fn deliver(from: &mut Tcb, to: &mut Tcb, now: u64) -> Vec<Segment> {
    let segs = from.take_outbox();
    for s in &segs {
        to.on_segment(now, Segment::decode(s.src_addr, s.dst_addr, &s.encode()).unwrap());
    }
    segs
}

#[test]
fn review_pure_ack_uses_snd_max_after_rto_rewind() {
    let mut p = Pair::new();
    p.a.write(p.now, &vec![1u8; 3000]).unwrap();
    p.b.write(p.now, &vec![2u8; 500]).unwrap(); // B's data segment is held back (ack = old rcv_nxt)
    let held = p.b.take_outbox();
    assert_eq!(held.len(), 1);
    // A's two in-window segments reach B, but B's ACKs are lost.
    deliver(&mut p.a, &mut p.b, p.now);
    p.b.take_outbox();
    // A's RTO fires: snd_nxt is rewound to snd_una.
    let t = p.a.next_timer().unwrap();
    p.now = t;
    p.a.on_timer(t);
    p.a.take_outbox();
    assert!(seq_lt(p.a.snd_nxt, p.a.snd_max), "test setup: snd_nxt must be rewound");
    // B's held data arrives; A answers with a pure ACK. Its seq must be snd_max, not the stale snd_nxt.
    p.a.on_segment(p.now, Segment::decode(held[0].src_addr, held[0].dst_addr, &held[0].encode()).unwrap());
    let acks = p.a.take_outbox();
    let pure = acks.iter().find(|s| s.payload.is_empty() && s.has(ACK)).expect("A must ACK B's data");
    assert_eq!(pure.seq, p.a.snd_max);
    // and B accepts it as an ordinary ACK (no "unacceptable segment" reply)
    let before = p.b.stats.segs_tx;
    p.b.on_segment(p.now, Segment::decode(pure.src_addr, pure.dst_addr, &pure.encode()).unwrap());
    assert_eq!(p.b.stats.segs_tx, before, "B rejected A's pure ACK as out-of-window");
}

#[test]
fn review_backoff_ends_on_forward_progress() {
    let mut p = Pair::new();
    p.a.write(p.now, &vec![1u8; 3000]).unwrap();
    p.a.take_outbox(); // both initial segments lost
    let t = p.a.next_timer().unwrap();
    p.now = t;
    p.a.on_timer(t);
    let backed_off = p.a.rto_us;
    assert_eq!(backed_off, 2 * p.a.cfg.min_rto_us);
    let rtx = p.a.take_outbox();
    p.b.on_segment(p.now, Segment::decode(rtx[0].src_addr, rtx[0].dst_addr, &rtx[0].encode()).unwrap());
    let ack = p.b.take_outbox();
    p.now += 10_000;
    p.a.on_segment(p.now, Segment::decode(ack[0].src_addr, ack[0].dst_addr, &ack[0].encode()).unwrap());
    // An ACK for new data ends the backoff even though it acknowledged retransmitted data.
    assert_eq!(p.a.rto_us, p.a.cfg.min_rto_us);
}

#[test]
fn review_extreme_loss_does_not_ratchet_rto_to_the_cap() {
    // 50 % loss: a "keep backoff until a clean RTT sample" rule never sees a sample and livelocks
    // (rto → 60 s, transfer stalls past the time limit). Forward-progress reset keeps it moving.
    let mut s = base(100_000);
    s.link_ab.loss = 0.5;
    s.max_time_us = 400_000_000;
    let (sim, o) = run(s);
    assert!(o.verified, "{o:?}");
    assert!(!o.timed_out);
    let worst = sim.a.events.iter().filter_map(|(_, e)| if let Event::Timeout { rto_us } = e { Some(*rto_us) } else { None }).max().unwrap();
    assert!(worst < 60_000_000, "RTO reached the cap: {worst}");
}

#[test]
fn review_ooo_buffer_prefers_longer_duplicate() {
    // Two segments at the same out-of-order offset (long one first): the short duplicate must not evict it.
    let mut p = Pair::new();
    let mk = |seq: u32, n: usize, ack: u32| Segment { src_addr: ADDR_A, dst_addr: ADDR_B, src_port: PORT_A, dst_port: PORT_B, flags: ACK, seq, ack, window: 1000, payload: vec![5u8; n], ..Default::default() };
    let base_seq = p.b.rcv_nxt;
    let ack = p.a.rcv_nxt;
    p.b.on_segment(p.now, mk(base_seq.wrapping_add(1000), 1000, ack));
    p.b.on_segment(p.now, mk(base_seq.wrapping_add(1000), 300, ack));
    p.b.on_segment(p.now, mk(base_seq, 1000, ack));
    assert_eq!(p.b.readable(), 2000);
}
