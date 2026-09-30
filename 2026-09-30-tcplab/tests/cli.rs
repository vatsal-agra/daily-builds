//! Drives the real binary: exit codes, error messages, packet trace, HTML report.
use std::process::Command;

fn run(args: &[&str]) -> (i32, String, String) {
    let o = Command::new(env!("CARGO_BIN_EXE_tcplab")).args(args).output().unwrap();
    (o.status.code().unwrap_or(-1), String::from_utf8_lossy(&o.stdout).into(), String::from_utf8_lossy(&o.stderr).into())
}

fn tmp(name: &str) -> String {
    let d = std::env::temp_dir().join(format!("tcplab-test-{}", std::process::id()));
    std::fs::create_dir_all(&d).unwrap();
    d.join(name).to_string_lossy().into()
}

#[test]
fn handshake_prints_full_lifecycle() {
    let (code, out, _) = run(&["handshake"]);
    assert_eq!(code, 0);
    for needle in ["Flags [S]", "Flags [S.]", "Flags [F.]", "SYN_SENT -> ESTABLISHED", "LISTEN -> SYN_RCVD", "FIN_WAIT_2 -> TIME_WAIT", "LAST_ACK -> CLOSED", "VERIFIED byte-exact"] {
        assert!(out.contains(needle), "missing {needle:?}\n{out}");
    }
}

#[test]
fn scripted_drop_shows_up_in_trace_and_is_repaired() {
    let (code, out, _) = run(&["run", "--bytes", "200KB", "--drop", "30", "--dump"]);
    assert_eq!(code, 0);
    assert!(out.contains("dropped: scripted drop"));
    assert!(out.contains("fast retransmit (3 dupacks)"));
    assert!(out.contains("1 fast, 0 RTO"), "{out}");
}

#[test]
fn every_preset_and_algorithm_verifies() {
    for p in ["clean", "lossy", "bottleneck", "satellite", "slowreader", "chaos"] {
        let (code, out, err) = run(&["compare", "--scenario", p, "--bytes", "300KB"]);
        assert_eq!(code, 0, "{p}\n{out}\n{err}");
        assert_eq!(out.matches(" yes").count(), 4, "{p}\n{out}");
    }
}

#[test]
fn failure_exit_codes_and_messages() {
    let (code, out, _) = run(&["run", "--loss", "100%", "--bytes", "5KB"]);
    assert_eq!(code, 1);
    assert!(out.contains("connection timed out"));
    for (args, msg) in [
        (vec!["run", "--bogus"], "unknown option"),
        (vec!["run", "--loss", "2"], "out of range"),
        (vec!["run", "--scenario", "nope"], "unknown scenario"),
        (vec!["run", "--algo", "bbr"], "unknown congestion control"),
        (vec!["run", "--rate", "fast"], "--rate"),
        (vec!["run", "--drop", "1,x"], "bad packet index"),
        (vec!["run", "--rcv-buf", "10"], "at least 512"),
        (vec!["run", "--iss", "99999999999"], "32 bits"),
        (vec!["run", "--bytes"], "needs a value"),
        (vec!["frobnicate"], "unknown command"),
    ] {
        let (code, _, err) = run(&args);
        assert_eq!(code, 2, "{args:?}");
        assert!(err.contains(msg), "{args:?}: {err}");
    }
}

#[test]
fn scenarios_and_help() {
    let (code, out, _) = run(&["scenarios"]);
    assert_eq!(code, 0);
    assert!(out.contains("bottleneck") && out.contains("chaos"));
    let (code, out, _) = run(&["--help"]);
    assert_eq!(code, 0);
    assert!(out.contains("USAGE"));
}

#[test]
fn html_report_single_and_compare() {
    let f = tmp("one.html");
    let (code, _, err) = run(&["run", "--scenario", "lossy", "--bytes", "400KB", "--html", &f]);
    assert_eq!(code, 0, "{err}");
    let h = std::fs::read_to_string(&f).unwrap();
    assert!(h.starts_with("<!doctype html>") && h.contains("Congestion window") && h.contains("Time–sequence"));
    assert_eq!(h.matches("<svg").count(), 4);
    assert!(!h.contains("NaN") && !h.contains("inf"), "non-finite number leaked into SVG");

    let f = tmp("cmp.html");
    let (code, _, _) = run(&["compare", "--scenario", "chaos", "--bytes", "200KB", "--html", &f]);
    assert_eq!(code, 0);
    let h = std::fs::read_to_string(&f).unwrap();
    assert!(h.contains("Algorithm comparison"));
    assert_eq!(h.matches("<svg").count(), 1 + 4 * 4);
    assert!(!h.contains("NaN"));
    // empty payload must not produce a broken chart either
    let f = tmp("empty.html");
    let (code, _, _) = run(&["run", "--bytes", "0", "--html", &f]);
    assert_eq!(code, 0);
    assert!(!std::fs::read_to_string(&f).unwrap().contains("NaN"));
    let (code, _, err) = run(&["run", "--html", "/nonexistent-dir/x.html", "--bytes", "1KB"]);
    assert_eq!(code, 1);
    assert!(err.contains("cannot write"));
}
