use std::process::exit;
use tcplab::cc::Algo;
use tcplab::report;
use tcplab::sim::*;
use tcplab::units::*;

const USAGE: &str = "\
tcplab — a from-scratch TCP stack over a deterministic simulated network

USAGE
  tcplab run        [options]     one transfer, summary (+ optional packet trace / HTML report)
  tcplab compare    [options]     same scenario under tahoe, reno, newreno and cubic
  tcplab handshake  [options]     annotated packet trace of open → data → close (default 3 KB)
  tcplab scenarios                list presets

OPTIONS (run / compare / handshake)
  --scenario NAME     preset: clean lossy bottleneck satellite slowreader chaos   [clean]
  --algo NAME         tahoe | reno | newreno | cubic                               [newreno]
  --bytes N           bytes client → server (e.g. 2MB)
  --bytes-back N      bytes server → client
  --rate R            link rate both ways (10mbit)        --delay T   one-way delay (20ms)
  --jitter T          uniform extra delay per packet      --queue N   drop-tail queue (packets)
  --loss P            random loss client→server (1%)      --ack-loss P   random loss on ACK path
  --corrupt P  --dup P  --reorder P  --reorder-delay T    packet mangling on the data path
  --drop 20,21        drop these data packets (1-based, retransmissions count)
  --mss N  --rcv-buf N  --reader-rate R   (server app reads R bytes/s)  --no-wscale
  --iss N             initial sequence number of the client (try 4294967000 for wraparound)
  --seed N            RNG seed                            --max-time T   virtual time limit
  --dump [N]          print packet trace (first N lines, default all)
  --html FILE         write a self-contained HTML report
";

struct Args {
    cmd: String,
    kv: Vec<(String, Option<String>)>,
}

fn parse_args() -> Args {
    let mut it = std::env::args().skip(1);
    let cmd = it.next().unwrap_or_else(|| {
        print!("{USAGE}");
        exit(2)
    });
    let mut kv = Vec::new();
    let rest: Vec<String> = it.collect();
    let mut i = 0;
    while i < rest.len() {
        let a = &rest[i];
        if let Some(name) = a.strip_prefix("--") {
            // A following token that is not itself a flag is this flag's value.
            if i + 1 < rest.len() && !rest[i + 1].starts_with("--") {
                kv.push((name.to_string(), Some(rest[i + 1].clone())));
                i += 2;
            } else {
                kv.push((name.to_string(), None));
                i += 1;
            }
        } else {
            fail(&format!("unexpected argument '{a}'"));
        }
    }
    Args { cmd, kv }
}

fn fail(msg: &str) -> ! {
    eprintln!("tcplab: {msg}\n(see `tcplab --help`)");
    exit(2)
}

impl Args {
    fn get(&self, k: &str) -> Option<&Option<String>> {
        self.kv.iter().rev().find(|(n, _)| n == k).map(|(_, v)| v)
    }
    fn has(&self, k: &str) -> bool {
        self.get(k).is_some()
    }
    fn val(&self, k: &str) -> Option<&str> {
        match self.get(k) {
            Some(Some(v)) => Some(v.as_str()),
            Some(None) => fail(&format!("--{k} needs a value")),
            None => None,
        }
    }
    fn parsed<T>(&self, k: &str, f: impl Fn(&str) -> Result<T, String>) -> Option<T> {
        self.val(k).map(|v| f(v).unwrap_or_else(|e| fail(&format!("--{k}: {e}"))))
    }
    fn check_known(&self) {
        const KNOWN: &[&str] = &[
            "scenario", "algo", "bytes", "bytes-back", "rate", "delay", "jitter", "queue", "loss", "ack-loss", "corrupt", "dup",
            "reorder", "reorder-delay", "drop", "mss", "rcv-buf", "reader-rate", "no-wscale", "iss", "seed", "max-time", "dump",
            "html", "help",
        ];
        for (k, _) in &self.kv {
            if !KNOWN.contains(&k.as_str()) {
                fail(&format!("unknown option --{k}"));
            }
        }
    }
}

fn parse_uint(s: &str) -> Result<u64, String> {
    s.parse::<u64>().map_err(|_| format!("'{s}' is not a non-negative integer"))
}

fn build_scenario(args: &Args, default_bytes: Option<usize>) -> Scenario {
    args.check_known();
    let name = args.val("scenario").unwrap_or("clean");
    let mut s = Scenario::preset(name).unwrap_or_else(|| fail(&format!("unknown scenario '{name}' (try `tcplab scenarios`)")));
    if let Some(b) = default_bytes {
        if !args.has("bytes") {
            s.bytes_a_to_b = b;
        }
    }
    if let Some(a) = args.parsed("algo", Algo::parse) {
        s.set_algo(a);
    }
    if let Some(v) = args.parsed("bytes", parse_size) {
        s.bytes_a_to_b = v;
    }
    if let Some(v) = args.parsed("bytes-back", parse_size) {
        s.bytes_b_to_a = v;
    }
    if let Some(v) = args.parsed("rate", parse_rate) {
        s.link_ab.rate_bps = v;
        s.link_ba.rate_bps = v;
    }
    if let Some(v) = args.parsed("delay", parse_duration_us) {
        s.link_ab.delay_us = v;
        s.link_ba.delay_us = v;
    }
    if let Some(v) = args.parsed("jitter", parse_duration_us) {
        s.link_ab.jitter_us = v;
        s.link_ba.jitter_us = v;
    }
    if let Some(v) = args.parsed("queue", |x| parse_uint(x).and_then(|n| if n == 0 { Err("queue must be ≥ 1".into()) } else { Ok(n as usize) })) {
        s.link_ab.queue_pkts = v;
        s.link_ba.queue_pkts = v;
    }
    if let Some(v) = args.parsed("loss", parse_prob) {
        s.link_ab.loss = v;
    }
    if let Some(v) = args.parsed("ack-loss", parse_prob) {
        s.link_ba.loss = v;
    }
    if let Some(v) = args.parsed("corrupt", parse_prob) {
        s.link_ab.corrupt = v;
    }
    if let Some(v) = args.parsed("dup", parse_prob) {
        s.link_ab.dup = v;
    }
    if let Some(v) = args.parsed("reorder", parse_prob) {
        s.link_ab.reorder = v;
        if s.link_ab.reorder_extra_us == 0 {
            s.link_ab.reorder_extra_us = 20_000;
        }
    }
    if let Some(v) = args.parsed("reorder-delay", parse_duration_us) {
        s.link_ab.reorder_extra_us = v;
    }
    if let Some(list) = args.val("drop") {
        s.link_ab.drop_data = list
            .split(',')
            .map(|x| x.trim().parse::<usize>().ok().filter(|n| *n >= 1).unwrap_or_else(|| fail(&format!("--drop: bad packet index '{x}'"))))
            .collect();
    }
    if let Some(v) = args.parsed("mss", |x| parse_uint(x).and_then(|n| if (64..=9000).contains(&n) { Ok(n as usize) } else { Err("mss must be 64..9000".into()) })) {
        s.cfg_a.mss = v;
        s.cfg_b.mss = v;
    }
    if let Some(v) = args.parsed("rcv-buf", parse_size) {
        if v < 512 {
            fail("--rcv-buf must be at least 512 bytes");
        }
        s.cfg_b.rcv_buf = v;
    }
    if let Some(v) = args.parsed("reader-rate", parse_rate) {
        s.reader_b = Some(Reader { bytes_per_sec: v.max(8) / 8, tick_us: 10_000 });
    }
    if args.has("no-wscale") {
        s.cfg_a.window_scaling = false;
        s.cfg_b.window_scaling = false;
    }
    if let Some(v) = args.parsed("iss", |x| parse_uint(x).and_then(|n| u32::try_from(n).map_err(|_| "must fit in 32 bits".to_string()))) {
        s.cfg_a.iss = v;
    }
    if let Some(v) = args.parsed("seed", parse_uint) {
        s.seed = v;
    }
    if let Some(v) = args.parsed("max-time", parse_duration_us) {
        s.max_time_us = v;
    }
    s.dump = args.has("dump") || args.cmd == "handshake";
    s
}

fn print_dump(sim: &Sim, args: &Args) {
    let limit = match args.get("dump") {
        Some(Some(n)) => n.parse::<usize>().unwrap_or_else(|_| fail("--dump takes an optional line count")),
        _ => usize::MAX,
    };
    for l in sim.log.iter().take(limit) {
        println!("{l}");
    }
    if sim.log.len() > limit {
        println!("… {} more lines", sim.log.len() - limit);
    }
    println!();
}

fn main() {
    let args = parse_args();
    if args.cmd == "--help" || args.cmd == "-h" || args.cmd == "help" {
        print!("{USAGE}");
        return;
    }
    match args.cmd.as_str() {
        "scenarios" => {
            for p in Scenario::PRESETS {
                let s = Scenario::preset(p).unwrap();
                println!(
                    "{:<11} {} {}ms one-way, queue {}, loss {:.1}%, {} payload{}",
                    p,
                    fmt_rate(s.link_ab.rate_bps as f64),
                    s.link_ab.delay_us / 1000,
                    s.link_ab.queue_pkts,
                    s.link_ab.loss * 100.0,
                    fmt_bytes(s.bytes_a_to_b as u64),
                    if s.reader_b.is_some() { ", rate-limited reader" } else { "" }
                );
            }
        }
        "run" | "handshake" => {
            let sc = build_scenario(&args, if args.cmd == "handshake" { Some(3000) } else { None });
            let mut sim = Sim::new(sc);
            let o = sim.run();
            if sim.sc.dump {
                print_dump(&sim, &args);
            }
            print!("{}", report::summary(&sim, &o));
            if let Some(path) = args.val("html") {
                write_html(path, &[(&o, &sim)], &sim.sc.name);
            }
            if !o.verified {
                exit(1);
            }
        }
        "compare" => {
            let base = build_scenario(&args, None);
            let mut sims = Vec::new();
            for a in Algo::ALL {
                let mut sc = base.clone();
                sc.set_algo(a);
                sc.dump = false;
                let mut sim = Sim::new(sc);
                let o = sim.run();
                sims.push((o, sim));
            }
            println!(
                "scenario \"{}\": {} bytes, {} one-way, {} ms delay, queue {}, loss {:.2}%, seed {}\n",
                base.name,
                fmt_bytes(base.bytes_a_to_b as u64),
                fmt_rate(base.link_ab.rate_bps as f64),
                base.link_ab.delay_us as f64 / 1e3,
                base.link_ab.queue_pkts,
                base.link_ab.loss * 100.0,
                base.seed
            );
            let rows: Vec<(tcplab::sim::Outcome, &Sim)> = sims.iter().map(|(o, s)| (o.clone(), s)).collect();
            print!("{}", report::compare_table(&rows));
            if let Some(path) = args.val("html") {
                let refs: Vec<(&tcplab::sim::Outcome, &Sim)> = sims.iter().map(|(o, s)| (o, s)).collect();
                write_html(path, &refs, &base.name);
            }
            if sims.iter().any(|(o, _)| !o.verified) {
                exit(1);
            }
        }
        other => fail(&format!("unknown command '{other}'")),
    }
}

fn write_html(path: &str, runs: &[(&tcplab::sim::Outcome, &Sim)], name: &str) {
    let html = tcplab::html::report(runs, name);
    match std::fs::write(path, html) {
        Ok(()) => eprintln!("wrote {path}"),
        Err(e) => {
            eprintln!("tcplab: cannot write {path}: {e}");
            exit(1);
        }
    }
}
