use cathode::term::Term;

fn t(cols: usize, rows: usize, s: &str) -> Term {
    let mut t = Term::new(cols, rows);
    t.feed(s.as_bytes());
    t
}
fn all_lines(t: &Term) -> Vec<String> {
    let mut v: Vec<String> = t.screen.buf().scrollback.iter().map(|l| l.text()).collect();
    v.extend((0..t.screen.rows).map(|y| t.screen.row_text(y)));
    v
}
fn logical(t: &Term) -> String {
    // join soft-wrapped rows, like copy/paste would
    let mut out = String::new();
    let rows: Vec<&cathode::screen::Line> = t.screen.buf().scrollback.iter().chain(t.screen.buf().lines.iter()).collect();
    for l in rows {
        if l.wrapped {
            // a soft-wrapped row is full: keep its trailing spaces, they are part of the text
            for c in l.cells.iter().filter(|c| c.width != 0) {
                c.push_text(&mut out);
            }
        } else {
            out.push_str(&l.text());
            out.push('\n');
        }
    }
    out.trim_end_matches('\n').to_string()
}

#[test]
fn narrowing_rewraps_a_soft_wrapped_line() {
    let mut x = t(20, 6, "0123456789abcdefghij0123\r\nshort");
    assert_eq!(all_lines(&x)[..3], ["0123456789abcdefghij", "0123", "short"]);
    x.resize(10, 6);
    assert_eq!(all_lines(&x)[..4], ["0123456789", "abcdefghij", "0123", "short"]);
    assert_eq!(logical(&x), "0123456789abcdefghij0123\nshort");
}

#[test]
fn widening_rejoins_wrapped_rows_but_not_hard_newlines() {
    let mut x = t(10, 6, "0123456789abcdefghij0123\r\nshort\r\nx");
    x.resize(30, 6);
    assert_eq!(all_lines(&x)[..3], ["0123456789abcdefghij0123", "short", "x"]);
}

#[test]
fn roundtrip_narrow_then_wide_restores_the_original() {
    let src = "the quick brown fox jumps over the lazy dog 日本語 é\r\n\r\nsecond paragraph here\r\n";
    let mut x = t(60, 8, src);
    let before = x.screen.text();
    x.resize(13, 8);
    assert_eq!(logical(&x), logical(&t(60, 8, src)));
    x.resize(60, 8);
    assert_eq!(x.screen.text(), before);
}

#[test]
fn cursor_follows_its_character() {
    let mut x = t(20, 6, "abcdefghijklmnopqrst0123");
    // cursor is after '3' (row 1, col 4)
    x.resize(8, 6);
    assert_eq!((x.screen.cx, x.screen.cy), (0, 3), "cursor stays right after the last typed char");
    x.feed(b"Z");
    assert!(logical(&x).ends_with("0123Z"));
}

#[test]
fn cursor_in_blank_area_keeps_its_column() {
    let mut x = t(20, 5, "hi\x1b[1;15H");
    x.resize(10, 5);
    // column 14 on a 10-wide screen => wraps to the second row, column 4
    assert_eq!((x.screen.cx, x.screen.cy), (4, 1));
    x.resize(20, 5);
    assert_eq!((x.screen.cx, x.screen.cy), (14, 0));
}

#[test]
fn wide_characters_are_never_split_by_rewrapping() {
    let mut x = t(12, 6, "日本語日本語");
    x.resize(5, 6);
    for l in all_lines(&x) {
        assert!(l.chars().count() <= 2 + 0 || !l.is_empty());
    }
    let rows = all_lines(&x);
    assert_eq!(rows[..3], ["日本", "語日", "本語"]);
    for y in 0..x.screen.rows {
        for c in 0..x.screen.cols {
            let cell = x.screen.cell(c, y);
            if cell.width == 2 {
                assert_eq!(x.screen.cell(c + 1, y).width, 0);
            }
        }
    }
}

#[test]
fn shrinking_pushes_overflow_into_scrollback_and_growing_restores_it() {
    let mut src = String::new();
    for i in 0..10 {
        src.push_str(&format!("line number {} with some padding text\r\n", i));
    }
    let mut x = t(40, 6, &src);
    let total_before = x.screen.scrollback_len() + 6;
    x.resize(20, 6);
    assert!(x.screen.scrollback_len() > total_before - 6, "wrapping creates more rows, which go to history");
    assert_eq!(logical(&x).lines().count(), 10 + 0, "{}", logical(&x));
    assert!(logical(&x).contains("line number 9 with some padding text"));
}

#[test]
fn alt_screen_is_not_reflowed_but_stays_consistent() {
    let mut x = t(20, 5, "main text that is quite long and wraps\x1b[?1049h\x1b[HALT\x1b[3;1Hline3");
    x.resize(10, 4);
    assert!(x.screen.alt_active);
    assert_eq!(x.screen.row_text(0), "ALT");
    x.feed(b"\x1b[?1049l");
    assert!(logical(&x).contains("main text that is quite long and wraps"));
}

#[test]
fn colors_and_attributes_survive_reflow() {
    let mut x = t(10, 4, "\x1b[1;31mabcdefghijklmno\x1b[0m");
    x.resize(5, 6);
    for (i, row) in all_lines(&x).iter().take(3).enumerate() {
        assert_eq!(row.len(), 5, "row {}", i);
    }
    assert_eq!(x.screen.cell(0, 0).fg, cathode::cell::Color::Idx(1));
    assert!(x.screen.cell(0, 2).attrs & cathode::cell::BOLD != 0);
}

#[test]
fn reflow_respects_scrollback_limit_and_never_panics_on_extremes() {
    let mut x = t(80, 24, &"x".repeat(5000));
    x.screen.scrollback_limit = 20;
    for (c, r) in [(1, 1), (2, 3), (200, 5), (3, 50), (80, 24), (1, 100), (7, 2)] {
        x.resize(c, r);
        assert!(x.screen.scrollback_len() <= 20);
        assert!(x.screen.cx < x.screen.cols && x.screen.cy < x.screen.rows);
    }
}
