//! `Term` = parser + screen: decodes escape sequences into screen operations and builds the
//! replies a real terminal would send back to the application (cursor reports, device attributes, ...).

use crate::cell::*;
use crate::parser::{Params, Parser, Perform};
use crate::screen::*;

pub const MAX_PENDING_REPLY: usize = 64 * 1024;
pub const MAX_TITLE: usize = 1024;
pub const VERSION: &str = "0.1.0";

pub struct Term {
    parser: Parser,
    pub screen: Screen,
    /// Bytes the terminal wants to send to the application (answers to queries).
    pub out: Vec<u8>,
    /// Latest OSC 7 working-directory report, if any.
    pub cwd: Option<String>,
    /// Cell size in pixels reported to XTWINOPS queries.
    pub cell_px: (usize, usize),
}

impl Term {
    pub fn new(cols: usize, rows: usize) -> Term {
        Term { parser: Parser::new(), screen: Screen::new(cols, rows), out: Vec::new(), cwd: None, cell_px: (8, 16) }
    }

    pub fn feed(&mut self, bytes: &[u8]) {
        let mut h = Handler { screen: &mut self.screen, out: &mut self.out, cwd: &mut self.cwd, cell_px: self.cell_px };
        self.parser.advance(&mut h, bytes);
    }

    /// Take (and clear) the pending reply bytes.
    pub fn take_output(&mut self) -> Vec<u8> {
        std::mem::take(&mut self.out)
    }

    pub fn resize(&mut self, cols: usize, rows: usize) {
        self.screen.resize(cols, rows);
    }
}

struct Handler<'a> {
    screen: &'a mut Screen,
    out: &'a mut Vec<u8>,
    cwd: &'a mut Option<String>,
    cell_px: (usize, usize),
}

/// Parse an X11-style colour spec (`rgb:r/g/b` with 1–4 hex digits per channel, or `#rgb`, `#rrggbb`, ...).
pub fn parse_color_spec(s: &str) -> Option<(u8, u8, u8)> {
    fn scale(h: &str) -> Option<u8> {
        if h.is_empty() || h.len() > 4 || !h.bytes().all(|b| b.is_ascii_hexdigit()) {
            return None;
        }
        let v = u32::from_str_radix(h, 16).ok()?;
        let max = (1u32 << (4 * h.len())) - 1;
        Some(((v * 255 + max / 2) / max) as u8)
    }
    if let Some(rest) = s.strip_prefix("rgb:") {
        let p: Vec<&str> = rest.split('/').collect();
        if p.len() != 3 {
            return None;
        }
        return Some((scale(p[0])?, scale(p[1])?, scale(p[2])?));
    }
    if let Some(h) = s.strip_prefix('#') {
        if h.is_empty() || h.len() % 3 != 0 || h.len() > 12 {
            return None;
        }
        let n = h.len() / 3;
        return Some((scale(&h[..n])?, scale(&h[n..2 * n])?, scale(&h[2 * n..])?));
    }
    None
}

fn color_reply(c: (u8, u8, u8)) -> String {
    format!("rgb:{:02x}{:02x}/{:02x}{:02x}/{:02x}{:02x}", c.0, c.0, c.1, c.1, c.2, c.2)
}

/// Apply one SGR parameter string to `pen`.
pub fn apply_sgr(pen: &mut Pen, params: &Params) {
    let groups = params.groups();
    if groups.is_empty() {
        let link = pen.link;
        *pen = Pen { link, ..Pen::default() };
        return;
    }
    let ext = |g: &Vec<Option<u16>>, groups: &Vec<Vec<Option<u16>>>, i: &mut usize| -> Option<Color> {
        let c8 = |v: Option<u16>| v.unwrap_or(0).min(255) as u8;
        if g.len() > 1 {
            // colon form
            match g[1] {
                Some(5) => Some(Color::Idx(c8(g.get(2).copied().flatten()))),
                Some(2) => {
                    let o = if g.len() >= 6 { 3 } else { 2 };
                    let at = |k: usize| c8(g.get(o + k).copied().flatten());
                    Some(Color::Rgb(at(0), at(1), at(2)))
                }
                _ => None,
            }
        } else {
            // semicolon form consumes following groups
            let v = |k: usize| groups.get(*i + k).and_then(|g| g[0]);
            match v(1) {
                Some(5) => {
                    let c = Color::Idx(c8(v(2)));
                    *i += 2;
                    Some(c)
                }
                Some(2) => {
                    let c = Color::Rgb(c8(v(2)), c8(v(3)), c8(v(4)));
                    *i += 4;
                    Some(c)
                }
                _ => {
                    *i += 1;
                    None
                }
            }
        }
    };
    let mut i = 0;
    while i < groups.len() {
        let g = &groups[i];
        let p = g[0].unwrap_or(0);
        match p {
            0 => {
                let link = pen.link;
                *pen = Pen { link, ..Pen::default() };
            }
            1 => pen.attrs |= BOLD,
            2 => pen.attrs |= DIM,
            3 => pen.attrs |= ITALIC,
            4 => {
                pen.attrs &= !ANY_UL;
                match g.get(1).copied().flatten() {
                    None | Some(1) => pen.attrs |= UNDERLINE,
                    Some(0) => {}
                    Some(2) => pen.attrs |= DOUBLE_UL,
                    Some(3) => pen.attrs |= CURLY_UL,
                    Some(4) => pen.attrs |= DOTTED_UL,
                    Some(5) => pen.attrs |= DASHED_UL,
                    Some(_) => pen.attrs |= UNDERLINE,
                }
            }
            5 | 6 => pen.attrs |= BLINK,
            7 => pen.attrs |= INVERSE,
            8 => pen.attrs |= HIDDEN,
            9 => pen.attrs |= STRIKE,
            21 => {
                pen.attrs &= !ANY_UL;
                pen.attrs |= DOUBLE_UL;
            }
            22 => pen.attrs &= !(BOLD | DIM),
            23 => pen.attrs &= !ITALIC,
            24 => pen.attrs &= !ANY_UL,
            25 => pen.attrs &= !BLINK,
            27 => pen.attrs &= !INVERSE,
            28 => pen.attrs &= !HIDDEN,
            29 => pen.attrs &= !STRIKE,
            30..=37 => pen.fg = Color::Idx((p - 30) as u8),
            38 => {
                if let Some(c) = ext(g, &groups, &mut i) {
                    pen.fg = c;
                }
            }
            39 => pen.fg = Color::Default,
            40..=47 => pen.bg = Color::Idx((p - 40) as u8),
            48 => {
                if let Some(c) = ext(g, &groups, &mut i) {
                    pen.bg = c;
                }
            }
            49 => pen.bg = Color::Default,
            53 => pen.attrs |= OVERLINE,
            55 => pen.attrs &= !OVERLINE,
            58 => {
                if let Some(c) = ext(g, &groups, &mut i) {
                    pen.ul = c;
                }
            }
            59 => pen.ul = Color::Default,
            90..=97 => pen.fg = Color::Idx((p - 90 + 8) as u8),
            100..=107 => pen.bg = Color::Idx((p - 100 + 8) as u8),
            _ => {}
        }
        i += 1;
    }
}

/// Serialise a pen as the parameters of an SGR sequence (`0;1;38;5;9`).
pub fn sgr_string(pen: &Pen) -> String {
    let mut v: Vec<String> = vec!["0".into()];
    let flags: [(u16, &str); 8] = [(BOLD, "1"), (DIM, "2"), (ITALIC, "3"), (BLINK, "5"), (INVERSE, "7"), (HIDDEN, "8"), (STRIKE, "9"), (OVERLINE, "53")];
    for (f, s) in flags {
        if pen.attrs & f != 0 {
            v.push(s.into());
        }
    }
    if pen.attrs & UNDERLINE != 0 {
        v.push("4".into());
    }
    if pen.attrs & DOUBLE_UL != 0 {
        v.push("4:2".into());
    }
    if pen.attrs & CURLY_UL != 0 {
        v.push("4:3".into());
    }
    if pen.attrs & DOTTED_UL != 0 {
        v.push("4:4".into());
    }
    if pen.attrs & DASHED_UL != 0 {
        v.push("4:5".into());
    }
    let col = |c: Color, base: u8, v: &mut Vec<String>| match c {
        Color::Default => {}
        Color::Idx(i) if i < 8 => v.push((base + i).to_string()),
        Color::Idx(i) if i < 16 => v.push((base + 60 + i - 8).to_string()),
        Color::Idx(i) => v.push(format!("{};5;{}", base + 8, i)),
        Color::Rgb(r, g, b) => v.push(format!("{};2;{};{};{}", base + 8, r, g, b)),
    };
    col(pen.fg, 30, &mut v);
    col(pen.bg, 40, &mut v);
    match pen.ul {
        Color::Idx(i) => v.push(format!("58;5;{}", i)),
        Color::Rgb(r, g, b) => v.push(format!("58;2;{};{};{}", r, g, b)),
        Color::Default => {}
    }
    v.join(";")
}

impl<'a> Handler<'a> {
    fn reply(&mut self, s: &str) {
        // Bounded: a hostile stream full of queries must not grow memory if nobody drains `out`.
        if self.out.len() + s.len() <= MAX_PENDING_REPLY {
            self.out.extend_from_slice(s.as_bytes());
        }
    }

    fn set_mode(&mut self, private: bool, n: u16, on: bool) {
        let s = &mut *self.screen;
        if !private {
            match n {
                4 => s.modes.insert = on,
                20 => s.modes.newline = on,
                _ => {}
            }
            return;
        }
        match n {
            1 => s.modes.app_cursor = on,
            5 => s.modes.reverse_video = on,
            6 => {
                s.modes.origin = on;
                s.cup(1, 1);
            }
            7 => {
                s.modes.autowrap = on;
                if !on {
                    s.pending_wrap = false;
                }
            }
            9 => s.modes.mouse = if on { MouseMode::X10 } else if s.modes.mouse == MouseMode::X10 { MouseMode::None } else { s.modes.mouse },
            12 => s.modes.cursor_blink = on,
            25 => s.modes.cursor_visible = on,
            47 | 1047 => {
                if on {
                    s.enter_alt(false, false);
                } else {
                    s.leave_alt(false, n == 1047);
                }
            }
            1000 | 1002 | 1003 => {
                let m = match n {
                    1000 => MouseMode::Normal,
                    1002 => MouseMode::Button,
                    _ => MouseMode::Any,
                };
                if on {
                    s.modes.mouse = m;
                } else if s.modes.mouse == m {
                    s.modes.mouse = MouseMode::None;
                }
            }
            1004 => s.modes.focus_events = on,
            1005 | 1006 | 1015 => {
                let e = match n {
                    1005 => MouseEnc::Utf8,
                    1006 => MouseEnc::Sgr,
                    _ => MouseEnc::Urxvt,
                };
                if on {
                    s.modes.mouse_enc = e;
                } else if s.modes.mouse_enc == e {
                    s.modes.mouse_enc = MouseEnc::Default;
                }
            }
            1048 => {
                if on {
                    s.save_cursor()
                } else {
                    s.restore_cursor()
                }
            }
            1049 => {
                if on {
                    s.enter_alt(true, true);
                } else {
                    s.leave_alt(true, false);
                }
            }
            2004 => s.modes.bracketed_paste = on,
            2026 => s.modes.sync_output = on,
            _ => {}
        }
    }

    /// DECRQM status: 0 unknown, 1 set, 2 reset, 3 permanently set, 4 permanently reset.
    fn mode_status(&self, private: bool, n: u16) -> u8 {
        let m = &self.screen.modes;
        let b = |v: bool| if v { 1 } else { 2 };
        if !private {
            return match n {
                4 => b(m.insert),
                20 => b(m.newline),
                2 | 12 => 4,
                _ => 0,
            };
        }
        match n {
            1 => b(m.app_cursor),
            3 | 69 => 4,
            5 => b(m.reverse_video),
            6 => b(m.origin),
            7 => b(m.autowrap),
            9 => b(m.mouse == MouseMode::X10),
            12 => b(m.cursor_blink),
            25 => b(m.cursor_visible),
            47 | 1047 | 1049 => b(self.screen.alt_active),
            1000 => b(m.mouse == MouseMode::Normal),
            1002 => b(m.mouse == MouseMode::Button),
            1003 => b(m.mouse == MouseMode::Any),
            1004 => b(m.focus_events),
            1005 => b(m.mouse_enc == MouseEnc::Utf8),
            1006 => b(m.mouse_enc == MouseEnc::Sgr),
            1015 => b(m.mouse_enc == MouseEnc::Urxvt),
            1048 => 2,
            2004 => b(m.bracketed_paste),
            2026 => b(m.sync_output),
            _ => 0,
        }
    }

    fn cursor_report(&self) -> (usize, usize) {
        let s = &*self.screen;
        let row = if s.modes.origin { s.cy.saturating_sub(s.top) } else { s.cy };
        (row + 1, s.cx + 1)
    }

    fn csi_plain(&mut self, params: &Params, fin: u8) {
        let n1 = |d: u16| params.get_nz(0, d) as usize;
        let s = &mut *self.screen;
        match fin {
            b'@' => s.insert_chars(n1(1)),
            b'A' => s.cursor_up(n1(1)),
            b'B' | b'e' => s.cursor_down(n1(1)),
            b'C' | b'a' => s.cursor_forward(n1(1)),
            b'D' => s.cursor_back(n1(1)),
            b'E' => {
                s.cursor_down(n1(1));
                s.carriage_return();
            }
            b'F' => {
                s.cursor_up(n1(1));
                s.carriage_return();
            }
            b'G' | b'`' => s.set_x(n1(1) - 1),
            b'H' | b'f' => s.cup(params.get_nz(0, 1) as usize, params.get_nz(1, 1) as usize),
            b'I' => s.tab_forward(n1(1)),
            b'J' => s.erase_display(params.get(0, 0)),
            b'K' => s.erase_line(params.get(0, 0)),
            b'L' => s.insert_lines(n1(1)),
            b'M' => s.delete_lines(n1(1)),
            b'P' => s.delete_chars(n1(1)),
            b'S' => s.scroll_up(n1(1)),
            b'T' => {
                if params.len() <= 1 {
                    s.scroll_down(n1(1))
                }
            }
            b'X' => s.erase_chars(n1(1)),
            b'Z' => s.tab_back(n1(1)),
            b'b' => {
                if let Some(c) = s.last_char {
                    for _ in 0..n1(1).min(65535) {
                        s.print(c);
                    }
                }
            }
            b'c' => {
                if params.get(0, 0) == 0 {
                    self.reply("\x1b[?62;22c");
                }
            }
            b'd' => s.set_row(n1(1)),
            b'g' => match params.get(0, 0) {
                0 => s.clear_tab(false),
                3 => s.clear_tab(true),
                _ => {}
            },
            b'h' | b'l' => {
                for p in params.flat() {
                    self.set_mode(false, p, fin == b'h');
                }
            }
            b'm' => apply_sgr(&mut s.pen, params),
            b'n' => match params.get(0, 0) {
                5 => self.reply("\x1b[0n"),
                6 => {
                    let (r, c) = self.cursor_report();
                    self.reply(&format!("\x1b[{};{}R", r, c));
                }
                _ => {}
            },
            b'r' => s.set_margins(params.get(0, 1) as usize, params.get(1, 0) as usize),
            b's' => s.save_cursor(),
            b'u' => s.restore_cursor(),
            b't' => {
                let (cw, ch) = self.cell_px;
                let (cols, rows) = (s.cols, s.rows);
                match params.get(0, 0) {
                    14 => self.reply(&format!("\x1b[4;{};{}t", rows * ch, cols * cw)),
                    16 => self.reply(&format!("\x1b[6;{};{}t", ch, cw)),
                    18 | 19 => self.reply(&format!("\x1b[{};{};{}t", 8, rows, cols)),
                    _ => {}
                }
            }
            _ => {}
        }
    }

    fn csi_private(&mut self, params: &Params, fin: u8) {
        match fin {
            b'h' | b'l' => {
                for p in params.flat() {
                    self.set_mode(true, p, fin == b'h');
                }
            }
            b'n' => {
                if params.get(0, 0) == 6 {
                    let (r, c) = self.cursor_report();
                    self.reply(&format!("\x1b[?{};{}R", r, c));
                }
            }
            b'J' => self.screen.erase_display(params.get(0, 0)),
            b'K' => self.screen.erase_line(params.get(0, 0)),
            _ => {}
        }
    }

    fn osc_color_query(&mut self, code: u32, c: (u8, u8, u8)) {
        self.reply(&format!("\x1b]{};{}\x1b\\", code, color_reply(c)));
    }
}

impl<'a> Perform for Handler<'a> {
    fn print(&mut self, c: char) {
        self.screen.print(c);
    }

    fn execute(&mut self, b: u8) {
        let s = &mut *self.screen;
        match b {
            0x07 => s.bell_count += 1,
            0x08 => s.backspace(),
            0x09 => s.tab_forward(1),
            0x0A | 0x0B | 0x0C => s.linefeed(),
            0x0D => s.carriage_return(),
            0x0E => s.gl = 1,
            0x0F => s.gl = 0,
            _ => {}
        }
    }

    fn csi(&mut self, params: &Params, marker: u8, inter: &[u8], fin: u8) {
        match (marker, inter) {
            (0, []) => self.csi_plain(params, fin),
            (b'?', []) => self.csi_private(params, fin),
            (b'>', []) => match fin {
                b'c' => self.reply("\x1b[>1;10;0c"),
                b'q' => self.reply(&format!("\x1bP>|cathode({})\x1b\\", VERSION)),
                _ => {}
            },
            (b'=', []) => {
                if fin == b'c' {
                    self.reply("\x1bP!|00000000\x1b\\");
                }
            }
            (0, [b'$']) if fin == b'p' => {
                let n = params.get(0, 0);
                let st = self.mode_status(false, n);
                self.reply(&format!("\x1b[{};{}$y", n, st));
            }
            (b'?', [b'$']) if fin == b'p' => {
                let n = params.get(0, 0);
                let st = self.mode_status(true, n);
                self.reply(&format!("\x1b[?{};{}$y", n, st));
            }
            (0, [b' ']) if fin == b'q' => {
                let v = params.get(0, 0);
                if v <= 6 {
                    self.screen.cursor_style = v as u8;
                }
            }
            (0, [b'!']) if fin == b'p' => self.screen.soft_reset(),
            _ => {}
        }
    }

    fn esc(&mut self, inter: &[u8], fin: u8) {
        let s = &mut *self.screen;
        match (inter, fin) {
            ([], b'7') => s.save_cursor(),
            ([], b'8') => s.restore_cursor(),
            ([], b'D') => {
                s.index();
                s.pending_wrap = false;
            }
            ([], b'E') => s.next_line(),
            ([], b'H') => s.set_tab(),
            ([], b'M') => s.reverse_index(),
            ([], b'c') => s.hard_reset(),
            ([], b'=') => s.modes.app_keypad = true,
            ([], b'>') => s.modes.app_keypad = false,
            ([b'#'], b'8') => s.alignment_test(),
            ([g @ (b'(' | b')' | b'*' | b'+')], f) => {
                let slot = match g {
                    b'(' => 0,
                    b')' => 1,
                    b'*' => 2,
                    _ => 3,
                };
                s.charsets[slot] = match f {
                    b'0' => Charset::DecGraphics,
                    b'A' => Charset::Uk,
                    _ => Charset::Ascii,
                };
            }
            _ => {}
        }
    }

    fn osc(&mut self, data: &[u8]) {
        let text = String::from_utf8_lossy(data).into_owned();
        let (cmd, rest) = match text.split_once(';') {
            Some((c, r)) => (c.to_string(), r.to_string()),
            None => (text.clone(), String::new()),
        };
        let code: u32 = match cmd.parse() {
            Ok(c) => c,
            Err(_) => return,
        };
        match code {
            0 | 2 => self.screen.title = rest.chars().take(MAX_TITLE).collect(),
            1 => {}
            4 => {
                let parts: Vec<&str> = rest.split(';').collect();
                for pair in parts.chunks(2) {
                    if pair.len() < 2 {
                        break;
                    }
                    let Ok(idx) = pair[0].parse::<usize>() else { continue };
                    if idx > 255 {
                        continue;
                    }
                    if pair[1] == "?" {
                        let c = self.screen.palette[idx];
                        self.reply(&format!("\x1b]4;{};{}\x1b\\", idx, color_reply(c)));
                    } else if let Some(c) = parse_color_spec(pair[1]) {
                        self.screen.palette[idx] = c;
                    }
                }
            }
            7 => {
                let p = rest.strip_prefix("file://").map(|r| r.find('/').map(|i| &r[i..]).unwrap_or(r)).unwrap_or(&rest);
                *self.cwd = Some(p.to_string());
            }
            8 => {
                if let Some((params, uri)) = rest.split_once(';') {
                    let id = params.split(':').find_map(|kv| kv.strip_prefix("id=")).unwrap_or("");
                    self.screen.set_link(id, uri);
                }
            }
            10 | 11 => {
                let s = &mut *self.screen;
                let cur = if code == 10 { s.default_fg } else { s.default_bg };
                if rest == "?" {
                    self.osc_color_query(code, cur);
                } else if let Some(c) = parse_color_spec(&rest) {
                    if code == 10 {
                        s.default_fg = c;
                    } else {
                        s.default_bg = c;
                    }
                }
            }
            104 => {
                if rest.is_empty() {
                    self.screen.palette = (0..=255u8).map(xterm_rgb).collect();
                } else {
                    for p in rest.split(';') {
                        if let Ok(i) = p.parse::<usize>() {
                            if i < 256 {
                                self.screen.palette[i] = xterm_rgb(i as u8);
                            }
                        }
                    }
                }
            }
            110 => self.screen.default_fg = (229, 229, 229),
            111 => self.screen.default_bg = (0, 0, 0),
            _ => {} // OSC 52 (clipboard) is deliberately not honoured.
        }
    }

    fn dcs(&mut self, _params: &Params, marker: u8, inter: &[u8], fin: u8, data: &[u8]) {
        match (marker, inter, fin) {
            (0, [b'$'], b'q') => {
                let s = &*self.screen;
                let body = match data {
                    b"m" => Some(format!("{}m", sgr_string(&s.pen))),
                    b"r" => Some(format!("{};{}r", s.top + 1, s.bottom + 1)),
                    b" q" => Some(format!("{} q", s.cursor_style)),
                    _ => None,
                };
                match body {
                    Some(b) => self.reply(&format!("\x1bP1$r{}\x1b\\", b)),
                    None => self.reply("\x1bP0$r\x1b\\"),
                }
            }
            (0, [b'+'], b'q') => self.reply("\x1bP0+r\x1b\\"),
            _ => {}
        }
    }
}
