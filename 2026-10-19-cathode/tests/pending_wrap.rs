//! The deferred-wrap ("last column") state, which the tmux oracle showed matters for real programs.
use cathode::cell::*;
use cathode::term::Term;

fn t(cols: usize, rows: usize, s: &str) -> Term {
    let mut t = Term::new(cols, rows);
    t.feed(s.as_bytes());
    t
}

#[test]
fn full_width_reverse_bar_survives_trailing_el() {
    // ncurses `top`: a reverse-video header exactly as wide as the screen, then reset + EL.
    let t1 = t(10, 2, "\x1b[7mPID  USER  \x1b[m\x1b[K");
    assert!(t1.screen.cell(9, 0).attrs & INVERSE != 0, "last cell must keep its reverse video");
    assert_eq!(t1.screen.cell(9, 0).ch, ' ');
}

#[test]
fn erase_ops_do_not_end_the_deferred_wrap() {
    for op in ["\x1b[K", "\x1b[2K", "\x1b[J", "\x1b[X", "\x1b[P", "\x1b[@"] {
        let t1 = t(5, 2, &format!("abcde{op}z"));
        if op != "\x1b[2K" {
            assert_eq!(t1.screen.row_text(0), "abcde", "{:?} must not touch the last cell", op);
        }
        assert_eq!(t1.screen.cell(0, 1).ch, 'z', "z wraps to the next line after {:?}", op);
    }
}

#[test]
fn erase_left_at_pending_wrap_erases_through_the_last_cell() {
    let t1 = t(5, 1, "abcde\x1b[1K");
    assert_eq!(t1.screen.row_text(0), "");
}

#[test]
fn explicit_cursor_movement_ends_the_deferred_wrap() {
    for mv in ["\x1b[G", "\x1b[1;5H", "\x1b[D", "\r", "\x1b[d"] {
        let t1 = t(5, 2, &format!("abcde{mv}z"));
        assert_eq!(t1.screen.cell(0, 1).ch, ' ', "no wrap after {:?}", mv);
    }
}

#[test]
fn decrc_ends_the_deferred_wrap() {
    let t1 = t(5, 2, "abcde\x1b7\x1b8z");
    assert_eq!(t1.screen.row_text(0), "abcdz");
}

#[test]
fn tab_in_deferred_wrap_does_nothing() {
    let t1 = t(5, 2, "abcde\tz");
    assert_eq!(t1.screen.cell(0, 1).ch, 'z');
}

#[test]
fn backspace_from_deferred_wrap_moves_left_of_the_last_column() {
    // xterm behaviour (tmux differs): the cursor is *on* the last column.
    let t1 = t(5, 1, "abcde\x08z");
    assert_eq!(t1.screen.row_text(0), "abcze");
}
