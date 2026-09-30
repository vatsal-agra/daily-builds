//! Hostile-input tests: random and adversarial segments must never panic (debug builds trap
//! integer overflow) or break the control block's invariants.

use tcplab::rng::Rng;
use tcplab::segment::*;
use tcplab::sim::*;
use tcplab::tcp::*;

#[test]
fn decode_never_panics_on_garbage() {
    let mut r = Rng::new(0xF00D);
    for _ in 0..50_000 {
        let n = r.below(80) as usize;
        let mut b: Vec<u8> = (0..n).map(|_| r.below(256) as u8).collect();
        // Often make the header shape plausible so we get past the early rejects.
        if n >= 20 && r.chance(0.7) {
            b[12] = ((5 + r.below(4)) as u8) << 4;
        }
        let _ = Segment::decode(1, 2, &b);
    }
}

#[test]
fn decode_of_mutated_valid_segments_is_rejected_or_identical() {
    let mut r = Rng::new(5);
    for _ in 0..5_000 {
        let s = Segment {
            src_addr: 1,
            dst_addr: 2,
            src_port: r.below(65536) as u16,
            dst_port: r.below(65536) as u16,
            seq: r.next_u64() as u32,
            ack: r.next_u64() as u32,
            flags: (r.below(32)) as u8,
            window: r.below(65536) as u16,
            opts: Options { mss: r.chance(0.5).then(|| r.below(65536) as u16), wscale: r.chance(0.5).then(|| r.below(15) as u8) },
            payload: (0..r.below(200)).map(|_| r.below(256) as u8).collect(),
        };
        let b = s.encode();
        assert_eq!(Segment::decode(1, 2, &b).unwrap(), s);
        let mut m = b.clone();
        let i = r.below(m.len() as u64) as usize;
        m[i] ^= 1 << r.below(8);
        assert!(Segment::decode(1, 2, &m).is_err(), "single-bit corruption slipped through");
        let cut = r.below(b.len() as u64) as usize;
        if cut < b.len() {
            let _ = Segment::decode(1, 2, &b[..cut]); // must not panic
        }
    }
}

fn check_invariants(t: &Tcb, tag: &str) {
    assert!(seq_leq(t.snd_una, t.snd_nxt), "{tag}: una>nxt");
    assert!(seq_leq(t.snd_una, t.snd_max), "{tag}: una > max ({} {})", t.snd_una, t.snd_max);
    assert!(seq_leq(t.snd_nxt, t.snd_max), "{tag}: nxt > max");
    assert!(t.readable() <= t.cfg.rcv_buf, "{tag}: receive buffer overrun {}", t.readable());
    assert!(t.cc.cwnd >= 1, "{tag}: cwnd zero");
}

fn shuttle(a: &mut Tcb, b: &mut Tcb, now: &mut u64) {
    for _ in 0..40 {
        *now += 500;
        let sa = a.take_outbox();
        let sb = b.take_outbox();
        if sa.is_empty() && sb.is_empty() {
            return;
        }
        for s in sa {
            b.on_segment(*now, Segment::decode(s.src_addr, s.dst_addr, &s.encode()).unwrap());
        }
        for s in sb {
            a.on_segment(*now, Segment::decode(s.src_addr, s.dst_addr, &s.encode()).unwrap());
        }
    }
}

fn random_segment(r: &mut Rng, victim: &Tcb, from_a: bool) -> Segment {
    let near = |r: &mut Rng, base: u32| -> u32 {
        match r.below(6) {
            0 => base,
            1 => base.wrapping_add(r.below(5000) as u32),
            2 => base.wrapping_sub(r.below(5000) as u32),
            3 => base.wrapping_add(r.below(1 << 31) as u32),
            4 => r.next_u64() as u32,
            _ => base.wrapping_add(1),
        }
    };
    let mut flags = r.below(32) as u8;
    if r.chance(0.5) {
        flags |= ACK;
    }
    let (sa, da, sp, dp) = if from_a { (ADDR_A, ADDR_B, PORT_A, PORT_B) } else { (ADDR_B, ADDR_A, PORT_B, PORT_A) };
    let (sa, sp) = if r.chance(0.05) { (sa ^ 1, sp) } else { (sa, sp) };
    Segment {
        src_addr: sa,
        dst_addr: da,
        src_port: sp,
        dst_port: dp,
        seq: near(r, victim.rcv_nxt),
        ack: near(r, victim.snd_una),
        flags,
        window: if r.chance(0.3) { 0 } else { r.below(65536) as u16 },
        opts: Options { mss: r.chance(0.2).then(|| r.below(3000) as u16), wscale: r.chance(0.2).then(|| r.below(20) as u8) },
        payload: (0..if r.chance(0.5) { 0 } else { r.below(2500) }).map(|_| r.below(256) as u8).collect(),
    }
}

#[test]
fn random_segments_never_break_a_connection_or_panic() {
    let mut seen = std::collections::HashSet::new();
    for seed in 0..300u64 {
        let mut r = Rng::new(seed);
        let mut a = Tcb::new(Config { iss: r.next_u64() as u32, rcv_buf: 4096 + r.below(60_000) as usize, ..Config::default() }, ADDR_A, PORT_A);
        let mut b = Tcb::new(Config { iss: r.next_u64() as u32, rcv_buf: 4096 + r.below(60_000) as usize, ..Config::default() }, ADDR_B, PORT_B);
        let mut now = 1u64;
        b.listen();
        // Sometimes attack mid-handshake, sometimes on an established connection with data in flight.
        let hs_steps = r.below(3);
        a.connect(now, ADDR_B, PORT_B);
        for _ in 0..hs_steps {
            shuttle(&mut a, &mut b, &mut now);
            break;
        }
        if r.chance(0.8) {
            shuttle(&mut a, &mut b, &mut now);
        }
        if a.state == State::Established || a.state == State::SynSent {
            let d: Vec<u8> = (0..r.below(50_000)).map(|i| i as u8).collect();
            let _ = a.write(now, &d);
        }
        for step in 0..120 {
            now += 1 + r.below(300_000);
            match r.below(6) {
                0 => {
                    let s = random_segment(&mut r, &b, true);
                    b.on_segment(now, s);
                }
                1 => {
                    let s = random_segment(&mut r, &a, false);
                    a.on_segment(now, s);
                }
                2 => shuttle(&mut a, &mut b, &mut now),
                3 => {
                    if let Some(t) = a.next_timer() {
                        now = now.max(t);
                        a.on_timer(now);
                    }
                    if let Some(t) = b.next_timer() {
                        now = now.max(t);
                        b.on_timer(now);
                    }
                }
                4 => {
                    let n = r.below(3000) as usize;
                    let _ = b.read(now, n);
                    let _ = a.read(now, n);
                }
                _ => match r.below(5) {
                    0 => a.close(now),
                    1 => b.close(now),
                    2 => {
                        let _ = b.write(now, &vec![7u8; r.below(4000) as usize]);
                    }
                    3 => {
                        if r.chance(0.2) {
                            a.abort(now)
                        }
                    }
                    _ => {
                        let _ = a.write(now, &vec![9u8; r.below(4000) as usize]);
                    }
                },
            }
            // Deliver whatever the victim emitted so state keeps evolving; ignore its content.
            for s in a.take_outbox() {
                if r.chance(0.7) {
                    b.on_segment(now, Segment::decode(s.src_addr, s.dst_addr, &s.encode()).unwrap());
                }
            }
            for s in b.take_outbox() {
                if r.chance(0.7) {
                    a.on_segment(now, Segment::decode(s.src_addr, s.dst_addr, &s.encode()).unwrap());
                }
            }
            seen.insert(a.state.name());
            seen.insert(b.state.name());
            check_invariants(&a, &format!("seed {seed} step {step} A {:?}", a.state));
            check_invariants(&b, &format!("seed {seed} step {step} B {:?}", b.state));
        }
    }
    // The fuzzer must actually have wandered through the state machine, not sat in one state.
    for st in ["SYN_SENT", "SYN_RCVD", "ESTABLISHED", "FIN_WAIT_1", "FIN_WAIT_2", "CLOSE_WAIT", "LAST_ACK", "TIME_WAIT", "CLOSED", "LISTEN"] {
        assert!(seen.contains(st), "fuzzer never reached {st}; saw {seen:?}");
    }
}
