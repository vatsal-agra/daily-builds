//! Differential tests against real tmux. Skipped (with a loud message) if tmux is not installed.
use cathode::tmuxdiff::{compare, compare_with, minimize, tmux_available, Opts};

fn check(name: &str, stream: &[u8], cols: usize, rows: usize) {
    if !tmux_available() {
        eprintln!("SKIPPED {}: tmux not installed", name);
        return;
    }
    let rep = compare(stream, cols, rows, true).unwrap_or_else(|e| panic!("{}: {}", name, e));
    assert!(rep.ok(), "{}: {} mismatches in {} cells:\n{}\nstream: {:?}", name, rep.mismatches.len(), rep.cells_compared, rep.mismatches.join("\n"), String::from_utf8_lossy(stream));
}

#[test]
fn plain_text_and_wrapping() {
    check("wrap", b"hello world this is longer than twenty columns wide\r\nsecond\r\n", 20, 6);
}

#[test]
fn colors_and_attributes() {
    check("sgr", b"\x1b[1;31mred\x1b[0m \x1b[44m  \x1b[0m \x1b[38;5;200mx\x1b[0m \x1b[38;2;1;2;3my\x1b[0m \x1b[3;4;9mz\x1b[0m\r\n\x1b[7minv\x1b[0m \x1b[2mdim\x1b[0m\r\n", 40, 5);
}

#[test]
fn cursor_motion_and_erase() {
    check("cup", b"\x1b[2J\x1b[3;5Hmid\x1b[1;1Htop\x1b[10;1H\x1b[1Kx\x1b[3;1H\x1b[K\x1b[5;5Hq\x1b[1A\x1b[2D*", 30, 8);
}

#[test]
fn insert_delete_and_scroll_regions() {
    check(
        "regions",
        b"1\r\n2\r\n3\r\n4\r\n5\r\n6\x1b[2;5r\x1b[3;1H\x1b[L\x1b[M\x1b[M\x1b[2S\x1b[T\x1b[4;1H\n\n\x1b[r\x1b[1;3H\x1b[2@AB\x1b[2P",
        12,
        6,
    );
}

#[test]
fn wide_and_combining() {
    check("wide", "日本語テキスト\r\ne\u{301}x \u{3042}\u{3044}\x1b[2;2HX\x1b[1;5H\x1b[2K\r\n".as_bytes(), 16, 4);
}

#[test]
fn insert_characters_within_the_line() {
    check("ich", b"abcdef\x1b[1;2H\x1b[1@\x1b[2;1Habcdef\x1b[2;1H\x1b[2@Z", 12, 3);
}

#[test]
fn tabs_and_tab_stops() {
    check("tabs", b"\ta\tb\x1b[3g\x1b[1;9H\x1bH\x1b[2;1H\tc\tx\x1b[0g", 30, 4);
}

#[test]
fn dec_special_graphics_and_save_restore() {
    check("acs", b"\x1b(0lqqqk\r\nx   x\r\nmqqqj\x1b(B\x1b7\x1b[1;1H\x1b[1mZ\x1b8Q", 20, 5);
}

#[test]
fn alternate_screen_and_restore() {
    check("alt", b"main text\x1b[?1049h\x1b[2J\x1b[3;3Halt screen\x1b[?1049lback\r\n", 30, 6);
}

// ---- generated streams ---------------------------------------------------------------------

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
    fn n(&mut self, max: usize) -> usize {
        1 + self.below(max)
    }
}

/// A random stream drawn from sequences on which xterm and tmux are documented to agree.
fn gen_stream(seed: u64, cols: usize, rows: usize, wide: bool) -> Vec<u8> {
    let mut r = Rng(seed.wrapping_mul(0x9E3779B97F4A7C15) | 1);
    let mut s = String::new();
    let mut autowrap = true;
    let mut region = (1usize, rows);
    // "wide" streams add double-width text but then restrict themselves to operations that cannot
    // split a wide character: tmux leaves an inconsistent grid there, xterm blanks both halves.
    let words: Vec<&str> = if wide {
        vec!["alpha", "日本語", "テスト", "x", "é日", "The quick 日本 fox", "~!@#$%", "ab\u{301}c"]
    } else {
        vec!["alpha", "beta", "gamma delta", "x", "0123456789", "The quick brown fox", "~!@#$%", "é", "ab\u{301}c"]
    };
    for _ in 0..(20 + r.below(60)) {
        let op = r.below(30);
        match op {
            0..=5 => {
                let w = words[r.below(words.len())];
                s.push_str(if autowrap || w.is_ascii() { w } else { "x" });
            }
            6 => s.push_str("\r\n"),
            7 => s.push('\r'),
            // CUP / CHA / VPA: tmux keeps a deferred wrap through VPA; xterm ends it. CHA after VPA
            // makes the following text land in the same place for both.
            8 => s.push_str(&format!("\x1b[{};{}H", r.n(rows), if wide { 1 } else { r.n(cols) })),
            9 if !wide => s.push_str(&format!("\x1b[{}{}", r.n(4), ['A', 'B', 'C', 'D'][r.below(4)])),
            9 => s.push_str(&format!("\x1b[{}{}", r.n(4), ['A', 'B'][r.below(2)])),
            // Erase ops run at arbitrary cursor states, including the deferred-wrap state.
            10 if !wide => s.push_str(&format!("\x1b[{}J", r.below(3))),
            11 if !wide => s.push_str(&format!("\x1b[{}K", r.below(3))),
            10 | 11 => s.push_str(if op == 10 { "\x1b[2J" } else { "\x1b[2K" }),
            // ICH is left out of the random mix: tmux ignores it whenever the shifted text would
            // reach past the used part of the line, xterm shifts (fixed ICH cases below).
            12 if !wide => s.push_str(&format!("\x1b[{}{}", r.n(3), ['P', 'X'][r.below(2)])),
            // IL/DL only with the cursor inside the scroll region: tmux applies them outside the
            // region to the whole screen, xterm ignores them.
            13 => {
                let row = region.0 + r.below(region.1 - region.0 + 1);
                s.push_str(&format!("\x1b[{};1H\x1b[{}{}\x1b[1G", row, r.n(3), ['L', 'M'][r.below(2)]))
            }
            14 => s.push_str(&format!("\x1b[{}{}", r.n(3), ['S', 'T'][r.below(2)])),
            15 => {
                let t = r.n(rows);
                let b = t + r.below(rows - t + 1);
                s.push_str(&format!("\x1b[{};{}r", t, b.min(rows)));
                if t < b.min(rows) {
                    region = (t, b.min(rows));
                }
            }
            16 => {
                region = (1, rows);
                s.push_str("\x1b[r")
            }
            17..=19 => {
                // Background colours are only used on text spans: tmux does not apply
                // background-colour-erase to wrap fillers and scrolls (xterm does; screen.rs tests).
                let codes = ["0", "1", "3", "4", "7", "9", "31", "38;5;99", "22", "24", "39", "91"];
                s.push_str(&format!("\x1b[{}m", codes[r.below(codes.len())]));
            }
            // IND/NEL/RI end a deferred wrap in xterm but not in tmux; CHA normalises the column.
            20 => s.push_str(&format!("{}\x1b[1G", ["\x1bD", "\x1bE", "\x1bM"][r.below(3)])),
            29 if r.below(2) == 0 => {
                let w = words[r.below(words.len())];
                let w = if autowrap || w.is_ascii() { w } else { "x" };
                s.push_str(&format!("\x1b[{}m{}\x1b[0m", ["42", "48;2;9;8;7", "104", "41;1"][r.below(4)], w))
            }
            21 => s.push_str("\x1b7"),
            22 => s.push_str("\x1b8"),
            23 => s.push_str(&format!("\x1b[{}G", if wide { 1 } else { r.n(cols) })),
            24 => s.push_str(&format!("\x1b[{}d\x1b[1G", r.n(rows))),
            25 if !wide => s.push('\t'),
            26 => {
                autowrap = false;
                s.push_str("\x1b[?7l\x1b[1G")
            }
            27 => {
                autowrap = true;
                s.push_str("\x1b[?7h\x1b[1G")
            }
            28 => s.push_str(&"w".repeat(cols + r.below(5))),
            _ => s.push_str("\x1b[?25l"),
        }
    }
    // Column of the final cursor is not compared (see the IL/DL note in README.md).
    s.push_str("\x1b[1G");
    s.into_bytes()
}

fn fuzz_range(lo: u64, hi: u64, wide: bool) {
    if !tmux_available() {
        eprintln!("SKIPPED fuzz: tmux not installed");
        return;
    }
    // CATHODE_ORACLE_OFFSET shifts the seed range so a longer soak can explore fresh streams.
    let off: u64 = std::env::var("CATHODE_ORACLE_OFFSET").ok().and_then(|v| v.parse().ok()).unwrap_or(0);
    let (lo, hi) = (lo + off, hi + off);
    let mut failures = Vec::new();
    for seed in lo..hi {
        let (cols, rows) = (10 + (seed as usize * 7) % 23, 4 + (seed as usize * 3) % 9);
        let stream = gen_stream(seed, cols, rows, wide);
        let opts = Opts { cursor: true, blank_bg: false };
        let rep = compare_with(&stream, cols, rows, opts).unwrap_or_else(|e| panic!("seed {}: {}", seed, e));
        if !rep.ok() {
            let min = if failures.len() < 3 { minimize(&stream, |c| compare_with(c, cols, rows, opts).map(|r| !r.ok()).unwrap_or(false)) } else { stream.clone() };
            let mrep = compare_with(&min, cols, rows, opts).unwrap();
            failures.push(format!("seed {} ({}x{}) minimal stream {:?}\n    {}", seed, cols, rows, String::from_utf8_lossy(&min), mrep.mismatches.iter().take(3).cloned().collect::<Vec<_>>().join("\n    ")));
        }
    }
    assert!(failures.is_empty(), "{} of {} generated streams disagree with tmux:\n{}", failures.len(), hi - lo, failures.iter().take(5).cloned().collect::<Vec<_>>().join("\n\n"));
}

#[test]
fn generated_streams_narrow_a() {
    fuzz_range(0, 50, false);
}
#[test]
fn generated_streams_narrow_b() {
    fuzz_range(50, 100, false);
}
#[test]
fn generated_streams_narrow_c() {
    fuzz_range(100, 150, false);
}
#[test]
fn generated_streams_wide_a() {
    fuzz_range(1000, 1040, true);
}
#[test]
fn generated_streams_wide_b() {
    fuzz_range(1040, 1080, true);
}

/// Debug helper: `CATHODE_ORACLE_SEED=301024 CATHODE_ORACLE_WIDE=1 cargo test --test tmux_oracle one_seed -- --nocapture`
#[test]
fn one_seed() {
    let Ok(seed) = std::env::var("CATHODE_ORACLE_SEED") else { return };
    let seed: u64 = seed.parse().expect("numeric seed");
    let wide = std::env::var("CATHODE_ORACLE_WIDE").is_ok();
    let (cols, rows) = (10 + (seed as usize * 7) % 23, 4 + (seed as usize * 3) % 9);
    let stream = gen_stream(seed, cols, rows, wide);
    let rep = compare_with(&stream, cols, rows, Opts { cursor: true, blank_bg: false }).unwrap();
    println!("{}x{} stream: {:?}", cols, rows, String::from_utf8_lossy(&stream));
    println!("{}", rep.mismatches.join("\n"));
}
