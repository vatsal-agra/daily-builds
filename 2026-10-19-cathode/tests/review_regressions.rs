//! One regression test per finding in REVIEW.md.
use cathode::cast::Cast;
use cathode::input::{parse_script, Item};
use cathode::render::*;
use cathode::term::{Term, MAX_PENDING_REPLY, MAX_TITLE};

fn t(cols: usize, rows: usize, s: &str) -> Term {
    let mut t = Term::new(cols, rows);
    t.feed(s.as_bytes());
    t
}

// R-03: OSC 8 link table must be bounded
#[test]
fn r03_hyperlink_table_is_bounded() {
    let mut term = Term::new(20, 2);
    for i in 0..70_000 {
        term.feed(format!("\x1b]8;;http://h/{}\x07x\x1b]8;;\x07", i).as_bytes());
    }
    assert!(term.screen.links.len() <= cathode::screen::MAX_LINKS);
    let long = format!("\x1b]8;;http://{}\x07y", "a".repeat(10_000));
    term.feed(long.as_bytes());
    assert_eq!(term.screen.pen.link, 0, "over-long URIs are dropped");
}

// R-04: pending replies are bounded when nobody drains them
#[test]
fn r04_reply_queue_is_bounded() {
    let mut term = Term::new(20, 2);
    for _ in 0..50_000 {
        term.feed(b"\x1b[6n\x1b[c");
    }
    assert!(term.out.len() <= MAX_PENDING_REPLY);
}

// R-05: C1 controls decoded from UTF-8 are not combining marks
#[test]
fn r05_c1_controls_are_ignored() {
    let term = t(10, 1, "a\u{85}\u{9b}b\u{80}");
    assert_eq!(term.screen.row_text(0), "ab");
    assert!(term.screen.cell(0, 0).comb.is_none());
}

// R-06: SVG must stay well-formed XML
#[test]
fn r06_svg_has_no_xml_invalid_characters() {
    let term = t(10, 1, "a\u{FFFE}b\u{FFFF}");
    let svg = to_svg(&term.screen, &RenderOpts::default());
    assert!(!svg.contains('\u{FFFE}') && !svg.contains('\u{FFFF}'));
}

// R-07: typed '<' is literal unless it looks like a key spec
#[test]
fn r07_script_literal_angle_brackets() {
    assert_eq!(parse_script("a <b> c").unwrap(), vec![Item::Text("a <b> c".into())]);
    assert_eq!(parse_script("if x < 3 && y > 2").unwrap(), vec![Item::Text("if x < 3 && y > 2".into())]);
    assert!(parse_script("<Escc>").is_err(), "typos in key names are errors, not silent text");
}

// R-02: HTML rows must not be separated by text nodes (rendered as blank lines in <pre>)
#[test]
fn r02_html_rows_are_adjacent() {
    let term = t(10, 3, "a\r\nb\r\nc");
    let h = to_html(&term.screen, &RenderOpts::default());
    assert!(!h.contains("</div>\n<div"), "newline between row divs double-spaces the output");
}

// R-08: title length is capped
#[test]
fn r08_title_is_capped() {
    let term = t(10, 1, &format!("\x1b]0;{}\x07", "t".repeat(100_000)));
    assert_eq!(term.screen.title.chars().count(), MAX_TITLE);
}

// R-09: hostile cast header
#[test]
fn r09_cast_dimensions_are_capped() {
    assert!(Cast::parse("{\"version\":2,\"width\":10000,\"height\":10000}\n").is_err());
    assert!(Cast::parse("{\"version\":2,\"width\":80,\"height\":24}\n[0,\"r\",\"99999x99999\"]\n").is_ok());
    let c = Cast::parse("{\"version\":2,\"width\":80,\"height\":24}\n[0,\"r\",\"99999x99999\"]\n").unwrap();
    let term = c.replay(None);
    assert_eq!((term.screen.cols, term.screen.rows), (80, 24), "absurd resize events are ignored");
}

// R-10: shrinking must respect the scrollback limit
#[test]
fn r10_resize_respects_scrollback_limit() {
    let mut term = Term::new(10, 50);
    term.screen.scrollback_limit = 5;
    for i in 0..50 {
        term.feed(format!("line{}\r\n", i).as_bytes());
    }
    term.resize(10, 2);
    assert!(term.screen.scrollback_len() <= 5);
}
