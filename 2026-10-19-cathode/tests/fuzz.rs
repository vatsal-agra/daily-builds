//! Robustness: random and semi-structured byte streams must never panic or corrupt the grid.
use cathode::cell::*;
use cathode::term::Term;

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
}

/// Every structural invariant the screen promises.
pub fn check_invariants(t: &Term) {
    let s = &t.screen;
    for (name, buf) in [("main", &s.main), ("alt", &s.alt)] {
        assert_eq!(buf.lines.len(), s.rows, "{} row count", name);
        for (y, l) in buf.lines.iter().enumerate() {
            assert_eq!(l.cells.len(), s.cols, "{} line {} width", name, y);
            for x in 0..s.cols {
                let c = &l.cells[x];
                match c.width {
                    0 => assert!(x > 0 && l.cells[x - 1].width == 2, "{} orphan continuation at {},{}", name, x, y),
                    2 => assert!(x + 1 < s.cols && l.cells[x + 1].width == 0, "{} orphan lead at {},{}", name, x, y),
                    1 => {}
                    w => panic!("bad width {}", w),
                }
                assert!((c.link as usize) < s.links.len(), "dangling link id");
            }
        }
        for l in &buf.scrollback {
            assert_eq!(l.cells.len(), s.cols, "{} scrollback width", name);
        }
    }
    assert!(s.cx < s.cols && s.cy < s.rows, "cursor out of bounds {},{} in {}x{}", s.cx, s.cy, s.cols, s.rows);
    assert!(s.top < s.bottom || (s.rows == 1 && s.top == 0 && s.bottom == 0), "bad region {}..{}", s.top, s.bottom);
    assert!(s.bottom < s.rows);
    assert_eq!(s.tabs.len(), s.cols);
}

const SNIPPETS: &[&str] = &[
    "\x1b[", "\x1b]0;", "\x1b]8;;http://x\x07", "\x1bP$q", "\x1b\\", "\x07", "\x1b[m", "\x1b[1;31m", "\x1b[38;5;", "\x1b[38;2;", "\x1b[?1049h", "\x1b[?1049l",
    "\x1b[?47h", "\x1b[?1047l", "\x1b[2J", "\x1b[3J", "\x1b[K", "\x1b[1K", "\x1b[L", "\x1b[M", "\x1b[P", "\x1b[@", "\x1b[X", "\x1b[S", "\x1b[T", "\x1bM", "\x1bD",
    "\x1bE", "\x1b7", "\x1b8", "\x1bc", "\x1b[!p", "\x1b#8", "\x1b(0", "\x1b(B", "\x0e", "\x0f", "\t", "\r", "\n", "\x08", "\x1b[?6h", "\x1b[?6l", "\x1b[?7l",
    "\x1b[?7h", "\x1b[4h", "\x1b[4l", "\x1b[20h", "\x1b[3g", "\x1bH", "\x1b[Z", "\x1b[I", "\x1b[5b", "日", "本", "é", "e\u{301}", "😀", "\u{200d}", "x", "yy", "あ",
    "\u{ffff}", "\x1b[999;999H", "\x1b[0;0r", "\x1b[2;3r", "\x1b[99r", "\x1b[1;1r", "\x1b[6n", "\x1b[c", "\x1b[>c", "\x1b[?25$p", "\x1b[18t", ";", ":", "9", "99999",
];

fn run(seed: u64, resizes: bool) {
    let mut r = Rng(seed | 1);
    let (cols, rows) = (1 + r.below(30), 1 + r.below(12));
    let mut t = Term::new(cols, rows);
    for step in 0..400 {
        match r.below(10) {
            0..=6 => t.feed(SNIPPETS[r.below(SNIPPETS.len())].as_bytes()),
            7 => {
                let n = r.below(20);
                let b: Vec<u8> = (0..n).map(|_| r.next() as u8).collect();
                t.feed(&b);
            }
            8 if resizes => t.resize(1 + r.below(40), 1 + r.below(16)),
            _ => t.feed(b"abc"),
        }
        t.take_output();
        if step % 7 == 0 {
            check_invariants(&t);
        }
    }
    check_invariants(&t);
}

#[test]
fn structured_fuzz_keeps_invariants() {
    for seed in 1..3000u64 {
        run(seed.wrapping_mul(0x9E3779B97F4A7C15), false);
    }
}

#[test]
fn fuzz_with_resizes_keeps_invariants() {
    for seed in 1..3000u64 {
        run(seed.wrapping_mul(0xD1B54A32D192ED03), true);
    }
}

#[test]
fn pure_random_bytes_never_panic() {
    let mut r = Rng(0xDEADBEEF);
    for _ in 0..300 {
        let mut t = Term::new(1 + r.below(50), 1 + r.below(20));
        let n = r.below(4000);
        let b: Vec<u8> = (0..n).map(|_| r.next() as u8).collect();
        t.feed(&b);
        check_invariants(&t);
    }
}

#[test]
fn huge_counts_do_not_hang_or_explode() {
    let mut t = Term::new(80, 24);
    let start = std::time::Instant::now();
    t.feed(b"x\x1b[65535b\x1b[65535@\x1b[65535P\x1b[65535L\x1b[65535M\x1b[65535S\x1b[65535T\x1b[65535X\x1b[65535I\x1b[65535Z\x1b[65535A\x1b[65535B");
    assert!(start.elapsed().as_secs() < 5);
    check_invariants(&t);
    assert_eq!(t.screen.pen, Pen::default());
}
