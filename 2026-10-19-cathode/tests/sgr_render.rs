use cathode::cell::*;
use cathode::render::*;
use cathode::term::Term;

fn t(cols: usize, rows: usize, s: &str) -> Term {
    let mut t = Term::new(cols, rows);
    t.feed(s.as_bytes());
    t
}

#[test]
fn sgr_basic_attributes_and_resets() {
    let t1 = t(10, 1, "\x1b[1;3;4;5;7;9mA\x1b[22;23;24;25;27;29mB");
    let a = t1.screen.cell(0, 0);
    assert_eq!(a.attrs, BOLD | ITALIC | UNDERLINE | BLINK | INVERSE | STRIKE);
    assert_eq!(t1.screen.cell(1, 0).attrs, 0);
}

#[test]
fn sgr_zero_and_empty_reset_everything() {
    for rst in ["\x1b[0m", "\x1b[m", "\x1b[;m"] {
        let t1 = t(10, 1, &format!("\x1b[1;31;42m{rst}A"));
        assert_eq!(t1.screen.cell(0, 0).pen(), Pen::default(), "{:?}", rst);
    }
}

#[test]
fn sgr_16_colors_and_bright() {
    let t1 = t(10, 1, "\x1b[31;44mA\x1b[91;104mB\x1b[39;49mC");
    assert_eq!((t1.screen.cell(0, 0).fg, t1.screen.cell(0, 0).bg), (Color::Idx(1), Color::Idx(4)));
    assert_eq!((t1.screen.cell(1, 0).fg, t1.screen.cell(1, 0).bg), (Color::Idx(9), Color::Idx(12)));
    assert_eq!((t1.screen.cell(2, 0).fg, t1.screen.cell(2, 0).bg), (Color::Default, Color::Default));
}

#[test]
fn sgr_256_and_truecolor_semicolon_and_colon_forms() {
    let t1 = t(10, 1, "\x1b[38;5;200mA\x1b[48;2;1;2;3mB\x1b[38:5:17mC\x1b[38:2::9:8:7mD\x1b[48:2:6:5:4mE");
    assert_eq!(t1.screen.cell(0, 0).fg, Color::Idx(200));
    assert_eq!(t1.screen.cell(1, 0).bg, Color::Rgb(1, 2, 3));
    assert_eq!(t1.screen.cell(2, 0).fg, Color::Idx(17));
    assert_eq!(t1.screen.cell(3, 0).fg, Color::Rgb(9, 8, 7));
    assert_eq!(t1.screen.cell(4, 0).bg, Color::Rgb(6, 5, 4));
}

#[test]
fn sgr_extended_color_does_not_swallow_following_params() {
    let t1 = t(10, 1, "\x1b[38;5;9;1;4mA");
    let a = t1.screen.cell(0, 0);
    assert_eq!(a.fg, Color::Idx(9));
    assert_eq!(a.attrs, BOLD | UNDERLINE);
    let t2 = t(10, 1, "\x1b[38;2;1;2;3;1mA");
    assert_eq!(t2.screen.cell(0, 0).fg, Color::Rgb(1, 2, 3));
    assert_eq!(t2.screen.cell(0, 0).attrs, BOLD);
}

#[test]
fn sgr_truncated_extended_color_is_harmless() {
    let t1 = t(10, 1, "\x1b[38;5mA\x1b[48;2;1mB\x1b[38mC\x1b[38;9;1mD");
    assert_eq!(t1.screen.row_text(0), "ABCD");
}

#[test]
fn sgr_underline_styles_and_color() {
    let t1 = t(10, 1, "\x1b[4:3mA\x1b[4:2mB\x1b[4:0mC\x1b[4mD\x1b[21mE\x1b[58:2::255:0:0;4mF\x1b[59mG");
    assert_eq!(t1.screen.cell(0, 0).attrs, CURLY_UL);
    assert_eq!(t1.screen.cell(1, 0).attrs, DOUBLE_UL);
    assert_eq!(t1.screen.cell(2, 0).attrs, 0);
    assert_eq!(t1.screen.cell(3, 0).attrs, UNDERLINE);
    assert_eq!(t1.screen.cell(4, 0).attrs, DOUBLE_UL);
    assert_eq!(t1.screen.cell(5, 0).ul, Color::Rgb(255, 0, 0));
    assert_eq!(t1.screen.cell(6, 0).ul, Color::Default);
}

#[test]
fn osc8_hyperlinks_attach_and_detach() {
    let t1 = t(20, 1, "a\x1b]8;;https://x.test/p?a=1\x1b\\link\x1b]8;;\x1b\\b");
    assert_eq!(t1.screen.cell(0, 0).link, 0);
    let l = t1.screen.cell(1, 0).link;
    assert!(l != 0);
    assert_eq!(t1.screen.links[l as usize].uri, "https://x.test/p?a=1");
    assert_eq!(t1.screen.cell(5, 0).link, 0);
    let t2 = t(20, 1, "\x1b]8;id=k1;http://a\x07x\x1b]8;id=k1;http://a\x07y");
    assert_eq!(t2.screen.cell(0, 0).link, t2.screen.cell(1, 0).link);
}

#[test]
fn sgr_reset_does_not_drop_hyperlink() {
    let t1 = t(20, 1, "\x1b]8;;http://a\x1b\\\x1b[1mx\x1b[0my");
    assert!(t1.screen.cell(1, 0).link != 0);
}

// ---- renderers ----------------------------------------------------------------------------

#[test]
fn text_render_trims_and_skips_wide_continuations() {
    let t1 = t(10, 4, "a  \r\n日本\r\n\r\n");
    assert_eq!(to_text(&t1.screen, false), "a\n日本");
}

#[test]
fn ansi_roundtrip_reproduces_cells_exactly() {
    let src = "\x1b[1;31mred\x1b[0m plain \x1b[48;2;10;20;30;38;5;99mbg\x1b[0m\r\n日本語\x1b[4:3m curly\x1b[0m e\u{301}\r\n\x1b[44m\x1b[K\x1b[0m\x1b]8;;http://z\x1b\\lnk\x1b]8;;\x1b\\\x1b[3;1H\x1b[?25l";
    let a = t(30, 5, src);
    let bytes = to_ansi(&a.screen);
    let mut b = Term::new(30, 5);
    b.feed(&bytes);
    for y in 0..5 {
        for x in 0..30 {
            let (ca, cb) = (a.screen.cell(x, y), b.screen.cell(x, y));
            assert_eq!((ca.ch, ca.width, ca.fg, ca.bg, ca.attrs, &ca.comb), (cb.ch, cb.width, cb.fg, cb.bg, cb.attrs, &cb.comb), "cell {},{}", x, y);
            assert_eq!(a.screen.links[ca.link as usize].uri, b.screen.links[cb.link as usize].uri, "link {},{}", x, y);
        }
    }
    assert_eq!((a.screen.cx, a.screen.cy), (b.screen.cx, b.screen.cy));
    assert_eq!(a.screen.modes.cursor_visible, b.screen.modes.cursor_visible);
}

#[test]
fn html_escapes_content_and_never_emits_unsafe_links() {
    let t1 = t(40, 3, "<script>alert(1)</script> & \"q\"\r\n\x1b]8;;javascript:alert(1)\x1b\\evil\x1b]8;;\x1b\\ \x1b]8;;https://ok.test/?a=1&b=2\x1b\\good\x1b]8;;\x1b\\");
    let h = to_html(&t1.screen, &RenderOpts::default());
    assert!(!h.contains("<script>alert"), "raw script tag leaked");
    assert!(h.contains("&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot;"));
    assert!(!h.contains("javascript:"));
    assert!(h.contains("href=\"https://ok.test/?a=1&amp;b=2\""));
}

#[test]
fn html_title_is_escaped() {
    let t1 = t(10, 1, "\x1b]0;</title><script>x</script>\x07");
    let h = to_html(&t1.screen, &RenderOpts::default());
    assert!(!h.contains("<script>x"));
    assert!(h.contains("&lt;/title&gt;"));
}

#[test]
fn html_colors_classes_and_cursor() {
    let t1 = t(10, 1, "\x1b[31mR\x1b[38;2;1;2;3mT\x1b[1mB");
    let h = to_html(&t1.screen, &RenderOpts::default());
    assert!(h.contains("class=\"f1\">R"));
    assert!(h.contains("color:#010203"));
    assert!(h.contains("class=\"bo\"") || h.contains("bo\""));
    assert!(h.contains("cur"));
    let h2 = to_html(&t1.screen, &RenderOpts { cursor: false, ..RenderOpts::default() });
    assert!(!h2.contains("class=\"cur\"") && !h2.contains(" cur\""));
}

#[test]
fn html_inverse_swaps_colors() {
    let t1 = t(10, 1, "\x1b[7mX\x1b[0;31;7mY");
    let h = to_html(&t1.screen, &RenderOpts { cursor: false, ..RenderOpts::default() });
    assert!(h.contains("color:var(--bg);background:var(--fg);") || (h.contains("color:var(--bg)") && h.contains("background:var(--fg)")), "{}", h);
    assert!(h.contains("b1"), "red becomes the background when inverted");
}

#[test]
fn svg_is_well_formed_enough_and_escapes() {
    let t1 = t(20, 2, "<a&b> \x1b[41mred\x1b[0m");
    let s = to_svg(&t1.screen, &RenderOpts::default());
    assert!(s.starts_with("<svg") && s.trim_end().ends_with("</svg>"));
    assert!(s.contains("&lt;a&amp;b&gt;"));
    assert_eq!(s.matches("<text").count(), s.matches("</text>").count());
}

#[test]
fn json_snapshot_has_runs_and_cursor() {
    let t1 = t(10, 2, "\x1b[1;31mhi\x1b[0m yo");
    let v = to_json(&t1.screen);
    let s = v.to_json();
    let back = cathode::json::parse(&s).unwrap();
    assert_eq!(back.get("cols").unwrap().as_f64(), Some(10.0));
    let runs = back.get("lines").unwrap().as_arr().unwrap()[0].get("runs").unwrap().as_arr().unwrap();
    assert_eq!(runs[0].get("text").unwrap().as_str(), Some("hi"));
    assert_eq!(runs[0].get("fg").unwrap().as_f64(), Some(1.0));
    assert_eq!(runs[1].get("text").unwrap().as_str(), Some(" yo"));
}
