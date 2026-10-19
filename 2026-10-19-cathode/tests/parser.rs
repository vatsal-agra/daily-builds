use cathode::parser::{Params, Parser, Perform};

#[derive(Debug, PartialEq, Clone)]
enum Ev {
    Print(char),
    Exec(u8),
    Csi { groups: Vec<Vec<Option<u16>>>, marker: u8, inter: Vec<u8>, fin: u8 },
    Esc { inter: Vec<u8>, fin: u8 },
    Osc(Vec<u8>),
    Dcs { fin: u8, inter: Vec<u8>, data: Vec<u8> },
}

#[derive(Default)]
struct Rec(Vec<Ev>);

impl Perform for Rec {
    fn print(&mut self, c: char) {
        self.0.push(Ev::Print(c));
    }
    fn execute(&mut self, b: u8) {
        self.0.push(Ev::Exec(b));
    }
    fn csi(&mut self, p: &Params, marker: u8, inter: &[u8], fin: u8) {
        self.0.push(Ev::Csi { groups: p.groups(), marker, inter: inter.to_vec(), fin });
    }
    fn esc(&mut self, inter: &[u8], fin: u8) {
        self.0.push(Ev::Esc { inter: inter.to_vec(), fin });
    }
    fn osc(&mut self, d: &[u8]) {
        self.0.push(Ev::Osc(d.to_vec()));
    }
    fn dcs(&mut self, _p: &Params, _m: u8, inter: &[u8], fin: u8, data: &[u8]) {
        self.0.push(Ev::Dcs { fin, inter: inter.to_vec(), data: data.to_vec() });
    }
}

fn parse(chunks: &[&[u8]]) -> Vec<Ev> {
    let mut p = Parser::new();
    let mut r = Rec::default();
    for c in chunks {
        p.advance(&mut r, c);
    }
    r.0
}

fn csi(groups: &[&[Option<u16>]], marker: u8, inter: &[u8], fin: u8) -> Ev {
    Ev::Csi { groups: groups.iter().map(|g| g.to_vec()).collect(), marker, inter: inter.to_vec(), fin }
}

#[test]
fn plain_text_and_c0() {
    assert_eq!(parse(&[b"a\x07b\r\n"]), vec![Ev::Print('a'), Ev::Exec(7), Ev::Print('b'), Ev::Exec(13), Ev::Exec(10)]);
}

#[test]
fn csi_params_defaults_and_omitted() {
    assert_eq!(parse(&[b"\x1b[1;2H"]), vec![csi(&[&[Some(1)], &[Some(2)]], 0, b"", b'H')]);
    assert_eq!(parse(&[b"\x1b[H"]), vec![csi(&[], 0, b"", b'H')]);
    assert_eq!(parse(&[b"\x1b[;5H"]), vec![csi(&[&[None], &[Some(5)]], 0, b"", b'H')]);
    assert_eq!(parse(&[b"\x1b[5;H"]), vec![csi(&[&[Some(5)], &[None]], 0, b"", b'H')]);
}

#[test]
fn csi_private_marker_and_intermediates() {
    assert_eq!(parse(&[b"\x1b[?1049h"]), vec![csi(&[&[Some(1049)]], b'?', b"", b'h')]);
    assert_eq!(parse(&[b"\x1b[>0c"]), vec![csi(&[&[Some(0)]], b'>', b"", b'c')]);
    assert_eq!(parse(&[b"\x1b[2 q"]), vec![csi(&[&[Some(2)]], 0, b" ", b'q')]);
    assert_eq!(parse(&[b"\x1b[?25$p"]), vec![csi(&[&[Some(25)]], b'?', b"$", b'p')]);
}

#[test]
fn subparameters() {
    assert_eq!(parse(&[b"\x1b[38:2::10:20:30m"]), vec![csi(&[&[Some(38), Some(2), None, Some(10), Some(20), Some(30)]], 0, b"", b'm')]);
    assert_eq!(parse(&[b"\x1b[4:3;1m"]), vec![csi(&[&[Some(4), Some(3)], &[Some(1)]], 0, b"", b'm')]);
}

#[test]
fn param_overflow_saturates_and_caps_count() {
    let ev = parse(&[b"\x1b[99999999999m"]);
    assert_eq!(ev, vec![csi(&[&[Some(65535)]], 0, b"", b'm')]);
    let mut s = b"\x1b[".to_vec();
    for _ in 0..100 {
        s.extend_from_slice(b"1;");
    }
    s.push(b'm');
    match &parse(&[&s])[0] {
        Ev::Csi { groups, .. } => assert!(groups.len() <= 32),
        e => panic!("{:?}", e),
    }
}

#[test]
fn c0_inside_csi_executes_without_aborting() {
    assert_eq!(parse(&[b"\x1b[1\n;2H"]), vec![Ev::Exec(10), csi(&[&[Some(1)], &[Some(2)]], 0, b"", b'H')]);
}

#[test]
fn can_and_sub_abort_sequences() {
    assert_eq!(parse(&[b"\x1b[12\x18x"]), vec![Ev::Exec(0x18), Ev::Print('x')]);
    assert_eq!(parse(&[b"\x1b[12\x1ax"]), vec![Ev::Exec(0x1a), Ev::Print('x')]);
}

#[test]
fn esc_restarts_sequence() {
    assert_eq!(parse(&[b"\x1b[12\x1b[3A"]), vec![csi(&[&[Some(3)]], 0, b"", b'A')]);
}

#[test]
fn invalid_csi_is_ignored_until_final() {
    // intermediate then a digit => CSI_IGNORE: swallowed entirely
    assert_eq!(parse(&[b"\x1b[ 1mX"]), vec![Ev::Print('X')]);
    // marker in the wrong place
    assert_eq!(parse(&[b"\x1b[1?mX"]), vec![Ev::Print('X')]);
}

#[test]
fn esc_sequences() {
    assert_eq!(parse(&[b"\x1b7\x1b(0\x1b#8"]), vec![
        Ev::Esc { inter: vec![], fin: b'7' },
        Ev::Esc { inter: vec![b'('], fin: b'0' },
        Ev::Esc { inter: vec![b'#'], fin: b'8' },
    ]);
}

#[test]
fn osc_terminated_by_bel_and_st() {
    assert_eq!(parse(&[b"\x1b]0;title\x07"]), vec![Ev::Osc(b"0;title".to_vec())]);
    assert_eq!(parse(&[b"\x1b]2;t2\x1b\\"]), vec![Ev::Osc(b"2;t2".to_vec()), Ev::Esc { inter: vec![], fin: b'\\' }]);
}

#[test]
fn osc_split_across_chunks_and_utf8_payload() {
    let ev = parse(&[b"\x1b]0;h\xc3", b"\xa9llo\x07"]);
    assert_eq!(ev, vec![Ev::Osc("0;héllo".as_bytes().to_vec())]);
}

#[test]
fn osc_aborted_by_can_is_not_dispatched() {
    assert_eq!(parse(&[b"\x1b]0;nope\x18ok"]), vec![Ev::Exec(0x18), Ev::Print('o'), Ev::Print('k')]);
}

#[test]
fn oversized_osc_is_dropped_not_truncated() {
    let mut s = b"\x1b]0;".to_vec();
    s.extend(std::iter::repeat(b'a').take(2_000_000));
    s.push(7);
    s.extend_from_slice(b"z");
    assert_eq!(parse(&[&s]), vec![Ev::Print('z')]);
}

#[test]
fn dcs_passthrough() {
    let ev = parse(&[b"\x1bP$qm\x1b\\"]);
    assert_eq!(ev[0], Ev::Dcs { fin: b'q', inter: vec![b'$'], data: b"m".to_vec() });
}

#[test]
fn sos_pm_apc_are_swallowed() {
    assert_eq!(parse(&[b"\x1b_Gsomething\x1b\\x"]), vec![Ev::Esc { inter: vec![], fin: b'\\' }, Ev::Print('x')]);
}

#[test]
fn utf8_decoding_basic_and_split() {
    assert_eq!(parse(&["é日😀".as_bytes()]), vec![Ev::Print('é'), Ev::Print('日'), Ev::Print('😀')]);
    let b = "😀".as_bytes();
    assert_eq!(parse(&[&b[..1], &b[1..3], &b[3..]]), vec![Ev::Print('😀')]);
}

#[test]
fn utf8_invalid_sequences_become_replacement_chars() {
    let r = '\u{FFFD}';
    assert_eq!(parse(&[b"\x80"]), vec![Ev::Print(r)]); // stray continuation
    assert_eq!(parse(&[b"\xc0\xaf"]), vec![Ev::Print(r), Ev::Print(r)]); // overlong
    assert_eq!(parse(&[b"\xe2\x82x"]), vec![Ev::Print(r), Ev::Print('x')]); // truncated then ASCII
    assert_eq!(parse(&[b"\xed\xa0\x80"]), vec![Ev::Print(r)]); // surrogate
    assert_eq!(parse(&[b"\xf4\x90\x80\x80"]), vec![Ev::Print(r)]); // > U+10FFFF
    assert_eq!(parse(&[b"\xff"]), vec![Ev::Print(r)]);
}

#[test]
fn truncated_utf8_before_escape_sequence() {
    let ev = parse(&[b"\xe2\x1b[1A"]);
    assert_eq!(ev, vec![Ev::Print('\u{FFFD}'), csi(&[&[Some(1)]], 0, b"", b'A')]);
}

#[test]
fn del_is_ignored_everywhere() {
    assert_eq!(parse(&[b"a\x7fb"]), vec![Ev::Print('a'), Ev::Print('b')]);
    assert_eq!(parse(&[b"\x1b[1\x7f2A"]), vec![csi(&[&[Some(12)]], 0, b"", b'A')]);
}

#[test]
fn byte_at_a_time_equals_whole_buffer() {
    let data = "\x1b[1;31mhé\x1b]0;t\x07\x1b[?25l日本\x1bP$qm\x1b\\\x1b(0q\r\n".as_bytes();
    let whole = parse(&[data]);
    let chunks: Vec<&[u8]> = data.chunks(1).collect();
    assert_eq!(parse(&chunks), whole);
}
