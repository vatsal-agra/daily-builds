//! Differential oracle: feed the same byte stream to Cathode and to a real `tmux` pane and compare
//! the resulting screens cell by cell. tmux is itself a terminal emulator, so agreement on a corpus
//! of sequences is strong evidence the screen model is right.
//!
//! The comparison goes through `tmux capture-pane -p -e -N` (text with SGR escapes), which is parsed
//! by a *fresh* Cathode terminal, so colours/attributes are compared semantically, not textually.

use crate::cell::*;
use crate::term::Term;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::{Duration, Instant};

static COUNTER: AtomicU32 = AtomicU32::new(0);

#[derive(Debug, Default)]
pub struct Report {
    pub mismatches: Vec<String>,
    pub cells_compared: usize,
}

impl Report {
    pub fn ok(&self) -> bool {
        self.mismatches.is_empty()
    }
}

pub fn tmux_available() -> bool {
    Command::new("tmux").arg("-V").output().map(|o| o.status.success()).unwrap_or(false)
}

struct Server {
    sock: String,
    dir: PathBuf,
}

impl Server {
    fn tmux(&self) -> Command {
        let mut c = Command::new("tmux");
        c.arg("-L").arg(&self.sock).arg("-f").arg("/dev/null");
        c.env_remove("TMUX");
        c
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.tmux().arg("kill-server").output();
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

/// Run `stream` through a tmux pane of the given size and return the pane's screen as a `Term`
/// (parsed from `capture-pane -e`) plus tmux's cursor position / visibility.
pub fn tmux_screen(stream: &[u8], cols: usize, rows: usize) -> Result<(Term, (usize, usize), bool), String> {
    let id = COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!("cathode-oracle-{}-{}", std::process::id(), id));
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let srv = Server { sock: format!("cathode-{}-{}", std::process::id(), id), dir: dir.clone() };
    let input = dir.join("in.bin");
    let done = dir.join("done");
    std::fs::write(&input, stream).map_err(|e| e.to_string())?;
    // -opost: pass bytes through the pty untouched (no LF -> CRLF), exactly what Cathode sees.
    let script = format!("stty -opost -echo; cat '{}'; touch '{}'; sleep 120", input.display(), done.display());
    let st = srv
        .tmux()
        .args(["new-session", "-d", "-x", &cols.to_string(), "-y", &rows.to_string(), "-s", "o", &script])
        .output()
        .map_err(|e| format!("cannot run tmux: {}", e))?;
    if !st.status.success() {
        return Err(format!("tmux new-session failed: {}", String::from_utf8_lossy(&st.stderr)));
    }
    let deadline = Instant::now() + Duration::from_secs(20);
    while !done.exists() {
        if Instant::now() > deadline {
            return Err("timed out waiting for tmux pane to consume the stream".into());
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    // The pane has been written to; wait until tmux's own view stops changing.
    let capture = |srv: &Server| -> Result<Vec<u8>, String> {
        let o = srv.tmux().args(["capture-pane", "-p", "-e", "-N", "-t", "o"]).output().map_err(|e| e.to_string())?;
        if !o.status.success() {
            return Err(format!("capture-pane failed: {}", String::from_utf8_lossy(&o.stderr)));
        }
        Ok(o.stdout)
    };
    let mut prev = capture(&srv)?;
    let mut stable = 0;
    while stable < 3 {
        std::thread::sleep(Duration::from_millis(25));
        let cur = capture(&srv)?;
        if cur == prev {
            stable += 1;
        } else {
            stable = 0;
            prev = cur;
        }
        if Instant::now() > deadline {
            return Err("tmux screen never stabilised".into());
        }
    }
    let info = srv.tmux().args(["display-message", "-p", "-t", "o", "#{cursor_x} #{cursor_y} #{cursor_flag}"]).output().map_err(|e| e.to_string())?;
    let info = String::from_utf8_lossy(&info.stdout).to_string();
    let nums: Vec<usize> = info.split_whitespace().filter_map(|w| w.parse().ok()).collect();
    if nums.len() != 3 {
        return Err(format!("unexpected cursor info {:?}", info));
    }
    // Parse the capture into a Term: lines are separated by '\n'; add CR so columns reset.
    let text = String::from_utf8_lossy(&prev).to_string();
    let mut t = Term::new(cols, rows);
    // tmux's capture shifts with SO/SI and assumes G1 was set to line drawing by the terminal's `enacs`.
    t.feed(b"\x1b)0");
    let mut lines: Vec<&str> = text.split('\n').collect();
    if lines.last() == Some(&"") {
        lines.pop();
    }
    for (i, l) in lines.iter().enumerate() {
        // No SGR reset between lines: `capture-pane -e` carries attribute state across lines.
        t.feed(format!("\x1b[{};1H{}", i + 1, l).as_bytes());
    }
    Ok((t, (nums[0], nums[1]), nums[2] == 1))
}

/// Visible-attribute mask used for comparison: underline styles collapse to one bit.
fn norm_attrs(a: u16, blank: bool) -> u16 {
    let mut n = a & (BOLD | DIM | ITALIC | BLINK | INVERSE | HIDDEN | STRIKE | OVERLINE);
    if a & ANY_UL != 0 {
        n |= UNDERLINE;
    }
    if blank {
        // attributes that draw nothing on a blank cell
        n &= INVERSE | STRIKE | OVERLINE | UNDERLINE;
    }
    n
}

fn describe(c: &Cell) -> String {
    let mut s = String::new();
    c.push_text(&mut s);
    format!("{:?} fg={:?} bg={:?} attrs={:#x}", s, c.fg, c.bg, c.attrs)
}

/// What to compare.
#[derive(Clone, Copy, Debug)]
pub struct Opts {
    /// Compare cursor position and visibility.
    pub cursor: bool,
    /// Compare the background colour of blank cells. tmux does not apply background-colour-erase
    /// to wrap fillers and scroll-created lines; xterm (and Cathode) do.
    pub blank_bg: bool,
}

impl Opts {
    pub fn strict() -> Opts {
        Opts { cursor: true, blank_bg: true }
    }
}

/// Compare Cathode's screen against tmux's for the same stream. `check_cursor` also compares the cursor.
pub fn compare(stream: &[u8], cols: usize, rows: usize, check_cursor: bool) -> Result<Report, String> {
    compare_with(stream, cols, rows, Opts { cursor: check_cursor, blank_bg: true })
}

pub fn compare_with(stream: &[u8], cols: usize, rows: usize, opts: Opts) -> Result<Report, String> {
    let mut ours = Term::new(cols, rows);
    ours.feed(stream);
    let (theirs, tcur, tvis) = tmux_screen(stream, cols, rows)?;
    Ok(compare_screens(&ours, &theirs, (tcur, tvis), opts))
}

pub fn compare_screens(ours: &Term, theirs: &Term, tcur: ((usize, usize), bool), opts: Opts) -> Report {
    let check_cursor = opts.cursor;
    let mut rep = Report::default();
    let (a, b) = (&ours.screen, &theirs.screen);
    for y in 0..a.rows {
        for x in 0..a.cols {
            let (ca, cb) = (a.cell(x, y), b.cell(x, y));
            rep.cells_compared += 1;
            // A wide character that does not fit at the end of a row wraps; Cathode blanks the cell
            // it skipped (like VTE/kitty), tmux leaves whatever was there.
            if x == a.cols - 1 && ca.ch == ' ' && a.line(y).wrapped {
                continue;
            }
            let (mut ta, mut tb) = (String::new(), String::new());
            if ca.width != 0 {
                ca.push_text(&mut ta);
            }
            if cb.width != 0 {
                cb.push_text(&mut tb);
            }
            let blank = ta.trim().is_empty() && tb.trim().is_empty();
            let same = ta == tb
                && ca.width == cb.width
                && (ca.bg == cb.bg || (blank && !opts.blank_bg))
                && (blank || ca.fg == cb.fg)
                && norm_attrs(ca.attrs, blank) == norm_attrs(cb.attrs, blank);
            if !same {
                rep.mismatches.push(format!("cell ({},{}): cathode {}  |  tmux {}", x, y, describe(ca), describe(cb)));
                if rep.mismatches.len() >= 12 {
                    return rep;
                }
            }
        }
    }
    if check_cursor {
        let ((tx, ty), tv) = tcur;
        // tmux reports the cursor inside the pending-wrap column the same way xterm does.
        // In the deferred-wrap state tmux reports the cursor one column past the edge; xterm and
        // Cathode report the last column. Same state, different bookkeeping.
        let x_ok = a.cx == tx || (a.pending_wrap && tx == a.cx + 1);
        if !(x_ok && a.cy == ty) {
            rep.mismatches.push(format!("cursor: cathode ({},{}) tmux ({},{})", a.cx, a.cy, tx, ty));
        }
        if a.modes.cursor_visible != tv {
            rep.mismatches.push(format!("cursor visibility: cathode {} tmux {}", a.modes.cursor_visible, tv));
        }
    }
    rep
}

/// Split a stream into atoms: whole escape sequences, or single (UTF-8) characters.
pub fn tokenize(stream: &[u8]) -> Vec<Vec<u8>> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < stream.len() {
        let st = i;
        if stream[i] == 0x1b && i + 1 < stream.len() {
            i += 1;
            match stream[i] {
                b'[' => {
                    i += 1;
                    while i < stream.len() && !(0x40..=0x7e).contains(&stream[i]) {
                        i += 1;
                    }
                    i = (i + 1).min(stream.len());
                }
                b'(' | b')' | b'#' => i = (i + 2).min(stream.len()),
                _ => i += 1,
            }
        } else {
            i += 1;
            while i < stream.len() && stream[i] & 0xC0 == 0x80 {
                i += 1;
            }
        }
        out.push(stream[st..i].to_vec());
    }
    out
}

/// Greedy delta-debugging: remove atoms (in shrinking chunks) while `still_fails` holds, to get a
/// minimal reproducer of a disagreement.
pub fn minimize(stream: &[u8], mut still_fails: impl FnMut(&[u8]) -> bool) -> Vec<u8> {
    let mut toks = tokenize(stream);
    let mut chunk = toks.len().max(1) / 2;
    while chunk >= 1 {
        let mut i = 0;
        let mut progressed = false;
        while i < toks.len() {
            let end = (i + chunk).min(toks.len());
            let cand: Vec<u8> = toks[..i].iter().chain(toks[end..].iter()).flatten().copied().collect();
            if still_fails(&cand) {
                toks.drain(i..end);
                progressed = true;
            } else {
                i += chunk;
            }
        }
        if chunk == 1 && !progressed {
            break;
        }
        if chunk > 1 {
            chunk /= 2;
        }
    }
    toks.concat()
}
