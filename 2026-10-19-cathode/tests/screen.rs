use cathode::cell::*;
use cathode::term::Term;

fn t(cols: usize, rows: usize, s: &str) -> Term {
    let mut t = Term::new(cols, rows);
    t.feed(s.as_bytes());
    t
}
fn rows(t: &Term) -> Vec<String> {
    (0..t.screen.rows).map(|y| t.screen.row_text(y)).collect()
}
fn cur(t: &Term) -> (usize, usize) {
    (t.screen.cx, t.screen.cy)
}
fn reply(t: &mut Term) -> String {
    String::from_utf8(t.take_output()).unwrap()
}

#[test]
fn autowrap_is_deferred_until_next_char() {
    let t1 = t(5, 3, "abcde");
    assert_eq!(cur(&t1), (4, 0));
    assert!(t1.screen.pending_wrap);
    assert_eq!(rows(&t1), ["abcde", "", ""]);
    let t2 = t(5, 3, "abcdef");
    assert_eq!(rows(&t2), ["abcde", "f", ""]);
    assert!(t2.screen.line(0).wrapped);
}

#[test]
fn cr_after_full_line_does_not_wrap() {
    let t = t(5, 3, "abcde\rX");
    assert_eq!(rows(&t), ["Xbcde", "", ""]);
}

#[test]
fn autowrap_off_overwrites_last_column() {
    let t = t(5, 2, "\x1b[?7labcdefg");
    assert_eq!(rows(&t), ["abcdg", ""]);
    assert_eq!(cur(&t), (4, 0));
}

#[test]
fn scrolling_pushes_into_scrollback() {
    let t = t(4, 2, "a\r\nb\r\nc\r\nd");
    assert_eq!(rows(&t), ["c", "d"]);
    assert_eq!(t.screen.scrollback_len(), 2);
    assert_eq!(t.screen.buf().scrollback[0].text(), "a");
}

#[test]
fn cursor_movement_clamps() {
    let mut x = t(10, 5, "\x1b[3;4H");
    assert_eq!(cur(&x), (3, 2));
    x.feed(b"\x1b[99A\x1b[99D");
    assert_eq!(cur(&x), (0, 0));
    x.feed(b"\x1b[99B\x1b[99C");
    assert_eq!(cur(&x), (9, 4));
    x.feed(b"\x1b[2;3H\x1b[2E");
    assert_eq!(cur(&x), (0, 3));
    x.feed(b"\x1b[1F");
    assert_eq!(cur(&x), (0, 2));
    x.feed(b"\x1b[5G\x1b[2d");
    assert_eq!(cur(&x), (4, 1));
    x.feed(b"\x1b[0A"); // 0 means 1
    assert_eq!(cur(&x), (4, 0));
}
#[test]
fn erase_display_modes() {
    let base = "aaaa\r\nbbbb\r\ncccc\x1b[2;2H";
    assert_eq!(rows(&t(4, 3, &format!("{base}\x1b[J"))), ["aaaa", "b", ""]);
    assert_eq!(rows(&t(4, 3, &format!("{base}\x1b[1J"))), ["", "  bb", "cccc"]);
    assert_eq!(rows(&t(4, 3, &format!("{base}\x1b[2J"))), ["", "", ""]);
}

#[test]
fn erase_line_modes() {
    let base = "abcdef\x1b[1;3H";
    assert_eq!(rows(&t(6, 1, &format!("{base}\x1b[K")))[0], "ab");
    assert_eq!(rows(&t(6, 1, &format!("{base}\x1b[1K")))[0], "   def");
    assert_eq!(rows(&t(6, 1, &format!("{base}\x1b[2K")))[0], "");
}

#[test]
fn insert_delete_erase_chars() {
    let base = "abcdef\x1b[1;3H";
    assert_eq!(rows(&t(6, 1, &format!("{base}\x1b[2@")))[0], "ab  cd");
    assert_eq!(rows(&t(6, 1, &format!("{base}\x1b[2P")))[0], "abef");
    assert_eq!(rows(&t(6, 1, &format!("{base}\x1b[2X")))[0], "ab  ef");
    assert_eq!(rows(&t(6, 1, &format!("{base}\x1b[99P")))[0], "ab");
}

#[test]
fn insert_delete_lines_respect_region() {
    let s = "1\r\n2\r\n3\r\n4\r\n5";
    // region rows 2..4, cursor inside
    let t1 = t(3, 5, &format!("{s}\x1b[2;4r\x1b[3;1H\x1b[L"));
    assert_eq!(rows(&t1), ["1", "2", "", "3", "5"]);
    let t2 = t(3, 5, &format!("{s}\x1b[2;4r\x1b[3;1H\x1b[M"));
    assert_eq!(rows(&t2), ["1", "2", "4", "", "5"]);
    // cursor outside region: no-op
    let t3 = t(3, 5, &format!("{s}\x1b[2;4r\x1b[1;1H\x1b[L"));
    assert_eq!(rows(&t3), ["1", "2", "3", "4", "5"]);
}

#[test]
fn scroll_region_linefeed_and_su_sd() {
    let t1 = t(3, 5, "1\r\n2\r\n3\r\n4\r\n5\x1b[2;4r\x1b[4;1H\n");
    assert_eq!(rows(&t1), ["1", "3", "4", "", "5"]);
    assert_eq!(t1.screen.scrollback_len(), 0, "partial regions never feed scrollback");
    let t2 = t(3, 5, "1\r\n2\r\n3\r\n4\r\n5\x1b[2;4r\x1b[S");
    assert_eq!(rows(&t2), ["1", "3", "4", "", "5"]);
    let t3 = t(3, 5, "1\r\n2\r\n3\r\n4\r\n5\x1b[2;4r\x1b[T");
    assert_eq!(rows(&t3), ["1", "", "2", "3", "5"]);
}

#[test]
fn reverse_index_scrolls_down_at_top_margin() {
    let t1 = t(3, 3, "1\r\n2\r\n3\x1b[1;1H\x1bM");
    assert_eq!(rows(&t1), ["", "1", "2"]);
}

#[test]
fn origin_mode_is_relative_to_margins() {
    let t1 = t(10, 6, "\x1b[2;5r\x1b[?6h\x1b[1;1HX\x1b[99;1HY");
    assert_eq!(rows(&t1)[1], "X");
    assert_eq!(rows(&t1)[4], "Y");
    let mut t2 = t(10, 6, "\x1b[2;5r\x1b[?6h\x1b[2;3H\x1b[6n");
    assert_eq!(reply(&mut t2), "\x1b[2;3R");
}

#[test]
fn invalid_margins_are_ignored() {
    let t1 = t(5, 5, "\x1b[4;2r");
    assert_eq!((t1.screen.top, t1.screen.bottom), (0, 4));
    let t2 = t(5, 5, "\x1b[2;99r");
    assert_eq!((t2.screen.top, t2.screen.bottom), (1, 4));
    let t3 = t(5, 5, "\x1b[3;3r");
    assert_eq!((t3.screen.top, t3.screen.bottom), (0, 4));
}

#[test]
fn tab_stops() {
    let t1 = t(30, 1, "\tX\tY");
    assert_eq!(t1.screen.row_text(0), "        X       Y");
    let t2 = t(30, 1, "\x1b[3g\x1b[5G\x1bH\x1b[1G\tX"); // clear all, set at col 5 (index 4)
    assert_eq!(t2.screen.row_text(0), "    X");
    let t3 = t(30, 1, "\x1b[20G\x1b[Z\x1b[Z|");
    assert_eq!(t3.screen.cx, 9);
    let t4 = t(20, 1, "\x1b[2I|");
    assert_eq!(t4.screen.cx, 17);
}

#[test]
fn save_restore_cursor_includes_pen_and_wrap_state() {
    let t1 = t(10, 3, "\x1b[2;3H\x1b[1;31m\x1b7\x1b[H\x1b[0m\x1b8X");
    assert_eq!(t1.screen.cell(2, 1).ch, 'X');
    assert_eq!(t1.screen.cell(2, 1).fg, Color::Idx(1));
    assert!(t1.screen.cell(2, 1).attrs & BOLD != 0);
}

#[test]
fn dec_special_graphics() {
    let t1 = t(8, 1, "\x1b(0lqqk\x1b(B lqk");
    assert_eq!(t1.screen.row_text(0), "┌──┐ lqk");
    let t2 = t(8, 1, "\x0e" /*SO*/);
    let _ = t2;
    let t3 = t(8, 1, "\x1b)0\x0elqk\x0flqk");
    assert_eq!(t3.screen.row_text(0), "┌─┐lqk");
}

#[test]
fn wide_characters_occupy_two_cells() {
    let t1 = t(6, 2, "日本a");
    assert_eq!(t1.screen.cell(0, 0).width, 2);
    assert_eq!(t1.screen.cell(1, 0).width, 0);
    assert_eq!(t1.screen.row_text(0), "日本a");
    assert_eq!(cur(&t1), (5, 0));
}

#[test]
fn wide_char_wraps_instead_of_splitting() {
    let t1 = t(5, 2, "abcd日");
    assert_eq!(rows(&t1), ["abcd", "日"]);
    assert!(t1.screen.line(0).wrapped);
}

#[test]
fn overwriting_half_of_wide_char_blanks_the_other_half() {
    let t1 = t(6, 1, "日本\x1b[1;2Hx");
    assert_eq!(t1.screen.row_text(0), " x本");
    let t2 = t(6, 1, "日本\x1b[1;1Hx");
    assert_eq!(t2.screen.row_text(0), "x 本");
    let t3 = t(6, 1, "日本\x1b[1;2H\x1b[K");
    assert_eq!(t3.screen.row_text(0), "");
}

#[test]
fn delete_char_through_wide_char_leaves_no_orphans() {
    let t1 = t(6, 1, "a日b\x1b[1;1H\x1b[P");
    assert_eq!(t1.screen.row_text(0), "日b");
    let t2 = t(6, 1, "a日b\x1b[1;2H\x1b[P");
    assert_eq!(t2.screen.row_text(0), "a b", "the orphaned right half is blanked, never left dangling");
}

#[test]
fn combining_marks_attach_to_previous_cell() {
    let t1 = t(6, 1, "e\u{301}x");
    assert_eq!(t1.screen.row_text(0), "e\u{301}x");
    assert_eq!(cur(&t1), (2, 0));
    // at line start with nothing before: dropped
    let t2 = t(6, 1, "\u{301}x");
    assert_eq!(t2.screen.row_text(0), "x");
}

#[test]
fn insert_mode_shifts_right() {
    let t1 = t(6, 1, "abcd\x1b[1;2H\x1b[4hXY");
    assert_eq!(t1.screen.row_text(0), "aXYbcd");
}

#[test]
fn newline_mode() {
    let t1 = t(6, 2, "ab\x1b[20h\ncd");
    assert_eq!(rows(&t1), ["ab", "cd"]);
}

#[test]
fn rep_repeats_last_char() {
    let t1 = t(10, 1, "ab\x1b[3b");
    assert_eq!(t1.screen.row_text(0), "abbbb");
}

#[test]
fn alt_screen_1049_saves_cursor_and_restores_content() {
    let mut t1 = t(10, 3, "main\x1b[?1049h\x1b[H");
    assert!(t1.screen.alt_active);
    assert_eq!(rows(&t1), ["", "", ""]);
    t1.feed(b"ALT");
    assert_eq!(t1.screen.row_text(0), "ALT");
    t1.feed(b"\x1b[?1049l");
    assert!(!t1.screen.alt_active);
    assert_eq!(t1.screen.row_text(0), "main");
    assert_eq!(cur(&t1), (4, 0));
}

#[test]
fn alt_screen_has_no_scrollback() {
    let t1 = t(4, 2, "\x1b[?1049h1\r\n2\r\n3\r\n4");
    assert_eq!(t1.screen.scrollback_len(), 0);
    assert_eq!(t1.screen.main.scrollback.len(), 0);
}

#[test]
fn full_reset_and_alignment_test() {
    let t1 = t(4, 2, "abc\x1b[1m\x1bc");
    assert_eq!(rows(&t1), ["", ""]);
    assert_eq!(t1.screen.pen, Pen::default());
    let t2 = t(3, 2, "\x1b#8");
    assert_eq!(rows(&t2), ["EEE", "EEE"]);
}

#[test]
fn soft_reset_keeps_screen_content() {
    let t1 = t(6, 2, "ab\x1b[?7l\x1b[1m\x1b[!p");
    assert_eq!(t1.screen.row_text(0), "ab");
    assert!(t1.screen.modes.autowrap);
    assert_eq!(t1.screen.pen, Pen::default());
}

#[test]
fn bel_and_title_osc() {
    let t1 = t(10, 1, "\x07\x07\x1b]0;my title\x07");
    assert_eq!(t1.screen.bell_count, 2);
    assert_eq!(t1.screen.title, "my title");
    let t2 = t(10, 1, "\x1b]2;a;b;c\x1b\\");
    assert_eq!(t2.screen.title, "a;b;c");
}

#[test]
fn background_color_erase() {
    let t1 = t(6, 2, "\x1b[44m\x1b[2J");
    assert_eq!(t1.screen.cell(3, 1).bg, Color::Idx(4));
    let t2 = t(6, 1, "\x1b[41mabc\x1b[0m\x1b[1;2H\x1b[K");
    assert_eq!(t2.screen.cell(5, 0).bg, Color::Default);
    let t3 = t(6, 1, "\x1b[41m\x1b[1;2H\x1b[K");
    assert_eq!(t3.screen.cell(5, 0).bg, Color::Idx(1));
    assert_eq!(t3.screen.cell(0, 0).bg, Color::Default);
}

#[test]
fn scrolling_uses_current_background() {
    let t1 = t(4, 2, "\x1b[42m\n\n");
    assert_eq!(t1.screen.cell(0, 1).bg, Color::Idx(2));
}

#[test]
fn resize_shrink_pushes_top_lines_to_scrollback_and_grow_restores() {
    let mut t1 = t(6, 4, "1\r\n2\r\n3\r\n4");
    t1.resize(6, 2);
    assert_eq!(rows(&t1), ["3", "4"]);
    assert_eq!(t1.screen.scrollback_len(), 2);
    assert_eq!(cur(&t1), (1, 1));
    t1.resize(6, 4);
    assert_eq!(rows(&t1), ["1", "2", "3", "4"]);
    assert_eq!(t1.screen.scrollback_len(), 0);
    assert_eq!(cur(&t1), (1, 3));
}

#[test]
fn resize_narrower_rewraps_and_keeps_cursor_on_its_character() {
    let mut t1 = t(10, 2, "abcdefghij");
    t1.resize(4, 2);
    assert_eq!(rows(&t1), ["efgh", "ij"]);
    assert_eq!(t1.screen.scrollback_len(), 1);
    assert_eq!(t1.screen.buf().scrollback[0].text(), "abcd");
    assert_eq!(cur(&t1), (2, 1), "the cursor stays just after 'j'");
    t1.feed(b"Z");
    assert_eq!(t1.screen.row_text(1), "ijZ");
}

#[test]
fn resize_to_1x1_does_not_panic_and_keeps_working() {
    let mut t1 = t(10, 5, "hello\r\nworld");
    t1.resize(1, 1);
    t1.feed("日x\x1b[3Pabc\x1b[L\x1b[M\x1b[2J\n\n".as_bytes());
    t1.resize(80, 24);
    t1.feed(b"ok");
    assert!(t1.screen.text().contains("ok"));
}

// ---- replies ---------------------------------------------------------------------------------

#[test]
fn device_status_and_cursor_position_report() {
    let mut t1 = t(20, 10, "\x1b[5;7H\x1b[6n\x1b[5n\x1b[?6n");
    assert_eq!(reply(&mut t1), "\x1b[5;7R\x1b[0n\x1b[?5;7R");
}

#[test]
fn device_attributes() {
    let mut t1 = t(20, 10, "\x1b[c\x1b[0c\x1b[>c");
    assert_eq!(reply(&mut t1), "\x1b[?62;22c\x1b[?62;22c\x1b[>1;10;0c");
    let mut t2 = t(20, 10, "\x1b[>0q");
    assert!(reply(&mut t2).starts_with("\x1bP>|cathode("));
}

#[test]
fn decrqm_reports_mode_state() {
    let mut t1 = t(20, 10, "\x1b[?25$p\x1b[?2004$p\x1b[?2004h\x1b[?2004$p\x1b[?9999$p\x1b[4$p");
    assert_eq!(reply(&mut t1), "\x1b[?25;1$y\x1b[?2004;2$y\x1b[?2004;1$y\x1b[?9999;0$y\x1b[4;2$y");
}

#[test]
fn xtwinops_size_reports() {
    let mut t1 = t(100, 30, "\x1b[18t\x1b[14t\x1b[16t");
    assert_eq!(reply(&mut t1), "\x1b[8;30;100t\x1b[4;480;800t\x1b[6;16;8t");
}

#[test]
fn decrqss_replies() {
    let mut t1 = t(20, 10, "\x1b[1;31m\x1bP$qm\x1b\\\x1b[2;5r\x1bP$qr\x1b\\\x1b[4 q\x1bP$q q\x1b\\\x1bP$qzzz\x1b\\");
    assert_eq!(reply(&mut t1), "\x1bP1$r0;1;31m\x1b\\\x1bP1$r2;5r\x1b\\\x1bP1$r4 q\x1b\\\x1bP0$r\x1b\\");
}

#[test]
fn osc_palette_and_default_color_queries_and_sets() {
    let mut t1 = t(20, 10, "\x1b]4;1;?\x07\x1b]4;1;rgb:12/34/56\x07\x1b]4;1;?\x07\x1b]11;?\x07\x1b]11;#102030\x07\x1b]11;?\x07");
    let r = reply(&mut t1);
    assert_eq!(
        r,
        "\x1b]4;1;rgb:cdcd/0000/0000\x1b\\\x1b]4;1;rgb:1212/3434/5656\x1b\\\x1b]11;rgb:0000/0000/0000\x1b\\\x1b]11;rgb:1010/2020/3030\x1b\\"
    );
    t1.feed(b"\x1b]104\x07\x1b]4;1;?\x07");
    assert_eq!(reply(&mut t1), "\x1b]4;1;rgb:cdcd/0000/0000\x1b\\");
}

#[test]
fn osc52_clipboard_is_not_honoured_and_unknown_osc_ignored() {
    let mut t1 = t(20, 2, "\x1b]52;c;aGVsbG8=\x07\x1b]777;notify;x\x07\x1b]abc;x\x07ok");
    assert_eq!(reply(&mut t1), "");
    assert_eq!(t1.screen.row_text(0), "ok");
}
