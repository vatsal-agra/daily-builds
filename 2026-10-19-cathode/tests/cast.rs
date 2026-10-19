use cathode::cast::{player_html, Cast, Event, Utf8Chunker};
use cathode::json::{self, Value};
use cathode::pty::SpawnOpts;
use cathode::render::{to_text, Theme};
use cathode::session::Session;

fn ev(t: f64, k: char, d: &str) -> Event {
    Event { t, kind: k, data: d.to_string() }
}

#[test]
fn cast_roundtrips_through_text() {
    let mut c = Cast::new(80, 24);
    c.title = Some("demo \"quoted\"".into());
    c.command = Some("sh -c 'echo hi'".into());
    c.events = vec![ev(0.1, 'o', "hello\r\n"), ev(0.25, 'o', "\x1b[1;31mred\x1b[0m 日本語 😀 \u{7f}\u{1}"), ev(1.5, 'r', "100x30"), ev(2.0, 'o', "tab\there\\ \"q\"")];
    let text = c.to_string();
    let back = Cast::parse(&text).unwrap();
    assert_eq!(back, c);
    assert!(text.lines().next().unwrap().contains("\"version\":2"));
}

#[test]
fn replay_at_time_and_resize_events() {
    let mut c = Cast::new(20, 5);
    c.events = vec![ev(0.0, 'o', "one"), ev(1.0, 'o', "\r\ntwo"), ev(2.0, 'r', "30x6"), ev(3.0, 'o', "\r\nthree")];
    assert_eq!(to_text(&c.replay(Some(0.5)).screen, false), "one");
    assert_eq!(to_text(&c.replay(Some(1.5)).screen, false), "one\ntwo");
    let t = c.replay(None);
    assert_eq!((t.screen.cols, t.screen.rows), (30, 6));
    assert_eq!(to_text(&t.screen, false), "one\ntwo\nthree");
}

#[test]
fn idle_gaps_are_compressed() {
    let mut c = Cast::new(10, 2);
    c.events = vec![ev(0.5, 'o', "a"), ev(10.5, 'o', "b"), ev(10.6, 'o', "c"), ev(40.6, 'o', "d")];
    c.cap_idle(2.0);
    let ts: Vec<f64> = c.events.iter().map(|e| (e.t * 100.0).round() / 100.0).collect();
    assert_eq!(ts, vec![0.5, 2.5, 2.6, 4.6]);
}

#[test]
fn malformed_casts_are_rejected_with_a_reason() {
    let bad: &[(&str, &str)] = &[
        ("", "empty"),
        ("not json\n", "bad header"),
        ("{\"version\":1,\"width\":1,\"height\":1}\n", "unsupported"),
        ("{\"width\":1,\"height\":1}\n", "no version"),
        ("{\"version\":2,\"width\":0,\"height\":5}\n", "out of range"),
        ("{\"version\":2,\"width\":5,\"height\":5}\n[1.0,\"o\"]\n", "3 elements"),
        ("{\"version\":2,\"width\":5,\"height\":5}\n[-1,\"o\",\"x\"]\n", "negative"),
        ("{\"version\":2,\"width\":5,\"height\":5}\n[1,\"o\",5]\n", "not a string"),
        ("{\"version\":2,\"width\":5,\"height\":5}\n[2,\"o\",\"a\"]\n[1,\"o\",\"b\"]\n", "backwards"),
        ("{\"version\":2,\"width\":5,\"height\":5}\n{\"a\":1}\n", "not an array"),
    ];
    for (src, what) in bad {
        let e = Cast::parse(src).expect_err(what);
        assert!(!e.is_empty(), "{}", what);
    }
}

#[test]
fn json_parser_edge_cases() {
    assert_eq!(json::parse("\"\\ud83d\\ude00 \\u00e9\\n\"").unwrap(), Value::Str("😀 é\n".into()));
    assert_eq!(json::parse("\"\\ud83d x\"").unwrap(), Value::Str("\u{fffd} x".into()));
    assert!(json::parse("[1,2,]").is_err());
    assert!(json::parse("{\"a\":1} x").is_err());
    assert!(json::parse("\"abc").is_err());
    assert!(json::parse("[").is_err());
    let deep = "[".repeat(200) + &"]".repeat(200);
    assert!(json::parse(&deep).is_err(), "nesting depth is bounded");
    assert_eq!(json::parse(" [ 1 , 2.5e1 , -3 ] ").unwrap(), Value::Arr(vec![Value::Num(1.0), Value::Num(25.0), Value::Num(-3.0)]));
    let v = Value::Str("a\"b\\c\u{1}\u{7f}é".into());
    assert_eq!(json::parse(&v.to_json()).unwrap(), v);
}

#[test]
fn utf8_chunker_never_splits_a_character() {
    let s = "héllo 日本語 😀!";
    let bytes = s.as_bytes();
    for step in 1..=5 {
        let mut ch = Utf8Chunker::default();
        let mut out = String::new();
        for c in bytes.chunks(step) {
            let piece = ch.push(c);
            assert!(!piece.contains('\u{fffd}'), "step {} produced a replacement char", step);
            out.push_str(&piece);
        }
        out.push_str(&ch.finish());
        assert_eq!(out, s);
    }
}

#[test]
fn recording_a_real_session_and_replaying_it_gives_the_same_screen() {
    let argv: Vec<String> = ["sh", "-c", "printf 'start\\n'; sleep 0.3; printf '\\033[1;32mgreen\\033[0m 日本\\n'; sleep 0.2; printf 'end'"].iter().map(|s| s.to_string()).collect();
    let mut s = Session::spawn(&argv, &SpawnOpts { cols: 40, rows: 6, ..Default::default() }, true).unwrap();
    s.pump_until_idle(500, 5000).unwrap();
    s.finish(500);
    let cast = s.cast.take().unwrap();
    assert!(cast.duration() >= 0.4, "timestamps should reflect real time, got {}", cast.duration());
    assert!(cast.events.windows(2).all(|w| w[0].t <= w[1].t));
    let replayed = Cast::parse(&cast.to_string()).unwrap().replay(None);
    assert_eq!(replayed.screen.text(), s.term.screen.text());
    // a mid-recording snapshot shows only the first line
    let mid = cast.replay(Some(0.15));
    assert_eq!(to_text(&mid.screen, false), "start");
}

#[test]
fn recording_resize_is_replayed() {
    let argv: Vec<String> = ["sh", "-c", "trap 'echo resized' WINCH; echo ready; while :; do sleep 0.05; done"].iter().map(|s| s.to_string()).collect();
    let mut s = Session::spawn(&argv, &SpawnOpts { cols: 30, rows: 5, ..Default::default() }, true).unwrap();
    assert!(s.wait_for_text("ready", 3000).unwrap());
    s.resize(50, 8).unwrap();
    assert!(s.wait_for_text("resized", 3000).unwrap());
    s.finish(100);
    let cast = s.cast.take().unwrap();
    assert!(cast.events.iter().any(|e| e.kind == 'r' && e.data == "50x8"));
    let t = cast.replay(None);
    assert_eq!((t.screen.cols, t.screen.rows), (50, 8));
}

#[test]
fn input_recording_is_opt_in() {
    let argv: Vec<String> = vec!["cat".into()];
    let mut s = Session::spawn(&argv, &SpawnOpts::default(), true).unwrap();
    s.pump_until_idle(200, 2000).unwrap();
    s.send(b"secret\r").unwrap();
    s.pump_until_idle(200, 2000).unwrap();
    assert!(s.cast.as_ref().unwrap().events.iter().all(|e| e.kind != 'i'), "keystrokes must not be recorded by default");
    s.record_input = true;
    s.send(b"typed\r").unwrap();
    s.pump_until_idle(200, 2000).unwrap();
    assert!(s.cast.as_ref().unwrap().events.iter().any(|e| e.kind == 'i' && e.data == "typed\r"));
    s.finish(100);
}

#[test]
fn player_html_is_self_contained_and_deduplicates_rows() {
    let mut c = Cast::new(30, 5);
    c.title = Some("</title><script>alert(1)</script>".into());
    let mut t = 0.0;
    for i in 0..60 {
        t += 0.1;
        c.events.push(ev(t, 'o', &format!("\x1b[{};1Hline {}", (i % 4) + 1, i)));
    }
    let h = player_html(&c, Theme::Dark, 400);
    assert!(h.starts_with("<!doctype html>"));
    assert!(!h.contains("<script>alert(1)"), "title must be escaped");
    assert!(!h.contains("http://") && !h.contains("https://") && !h.contains("src="), "no external resources");
    assert!(h.contains("const ROWS=[") && h.contains("FRAMES=["));
    // fewer frames than max_frames is honoured when asked
    let small = player_html(&c, Theme::Dark, 10);
    assert!(small.len() < h.len());
}
