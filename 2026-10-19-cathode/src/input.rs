//! Keyboard input: a tiny script language (`ihello<Esc>:wq<CR>`) and key → byte encoding that
//! depends on the terminal's current modes (application cursor keys, ...).

use crate::screen::{Modes, MouseEnc, MouseMode};

pub const SHIFT: u8 = 1;
pub const ALT: u8 = 2;
pub const CTRL: u8 = 4;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Key {
    Char(char),
    Esc,
    Enter,
    Tab,
    Backspace,
    Delete,
    Insert,
    Up,
    Down,
    Left,
    Right,
    Home,
    End,
    PageUp,
    PageDown,
    F(u8),
}

/// One step of an input script.
#[derive(Clone, Debug, PartialEq)]
pub enum Item {
    Key(Key, u8),
    /// Literal text, sent as typed.
    Text(String),
    Wait(u64),
    /// Block until the screen contains the text (or the step's timeout expires).
    Until(String),
    Resize(usize, usize),
    Mouse(MouseEvent),
    /// Pasted text (bracketed when the application enabled DECSET 2004).
    Paste(String),
    Focus(bool),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MouseButton {
    Left,
    Middle,
    Right,
    WheelUp,
    WheelDown,
    None,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MouseKind {
    Press,
    Release,
    Move,
}

/// A mouse event at 0-based cell coordinates.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MouseEvent {
    pub kind: MouseKind,
    pub button: MouseButton,
    pub x: usize,
    pub y: usize,
    pub mods: u8,
}

fn key_by_name(name: &str) -> Option<Key> {
    Some(match name.to_ascii_lowercase().as_str() {
        "esc" | "escape" => Key::Esc,
        "cr" | "enter" | "return" => Key::Enter,
        "nl" => Key::Char('\n'),
        "tab" => Key::Tab,
        "bs" | "backspace" => Key::Backspace,
        "del" | "delete" => Key::Delete,
        "ins" | "insert" => Key::Insert,
        "up" => Key::Up,
        "down" => Key::Down,
        "left" => Key::Left,
        "right" => Key::Right,
        "home" => Key::Home,
        "end" => Key::End,
        "pageup" | "pgup" => Key::PageUp,
        "pagedown" | "pgdn" => Key::PageDown,
        "space" => Key::Char(' '),
        "lt" => Key::Char('<'),
        "gt" => Key::Char('>'),
        n => {
            let num = n.strip_prefix('f')?.parse::<u8>().ok()?;
            if (1..=12).contains(&num) {
                Key::F(num)
            } else {
                return None;
            }
        }
    })
}

/// Parse `<...>` key specs: `<C-x>`, `<M-b>`, `<S-Tab>`, `<C-S-Up>`, `<F5>`, `<wait 300>`, `<until "text">`, `<resize 100x30>`.
fn parse_angle(inner: &str) -> Result<Item, String> {
    let lower = inner.to_ascii_lowercase();
    if let Some(rest) = lower.strip_prefix("wait ") {
        return rest.trim().parse::<u64>().map(Item::Wait).map_err(|_| format!("bad <wait>: {:?}", inner));
    }
    if let Some(rest) = lower.strip_prefix("resize ") {
        let (c, r) = rest.trim().split_once('x').ok_or_else(|| format!("bad <resize>: {:?}", inner))?;
        let (c, r) = (c.parse::<usize>(), r.parse::<usize>());
        return match (c, r) {
            (Ok(c), Ok(r)) if c > 0 && r > 0 => Ok(Item::Resize(c, r)),
            _ => Err(format!("bad <resize>: {:?}", inner)),
        };
    }
    if inner.len() >= 6 && inner[..6].eq_ignore_ascii_case("until ") {
        let q = inner[6..].trim();
        if q.len() >= 2 && q.starts_with('"') && q.ends_with('"') {
            return Ok(Item::Until(q[1..q.len() - 1].replace("\\\"", "\"")));
        }
        return Err(format!("<until> needs a quoted string: {:?}", inner));
    }
    if let Some(rest) = lower.strip_prefix("mouse ") {
        return parse_mouse(rest).ok_or_else(|| format!("bad <mouse ...>: {:?} (e.g. <mouse press left 10,5>, <mouse move 3,4>, <mouse wheel up 3,4>)", inner));
    }
    if inner.len() >= 6 && inner[..6].eq_ignore_ascii_case("paste ") {
        let q = inner[6..].trim();
        if q.len() >= 2 && q.starts_with('"') && q.ends_with('"') {
            return Ok(Item::Paste(q[1..q.len() - 1].replace("\\\"", "\"").replace("\\n", "\n")));
        }
        return Err(format!("<paste> needs a quoted string: {:?}", inner));
    }
    match lower.as_str() {
        "focus in" | "focus-in" => return Ok(Item::Focus(true)),
        "focus out" | "focus-out" => return Ok(Item::Focus(false)),
        _ => {}
    }
    // modifiers: C-, S-, M-/A- prefixes
    let mut mods = 0u8;
    let mut rest = inner;
    loop {
        let b = rest.as_bytes();
        if b.len() > 2 && b[1] == b'-' {
            match b[0].to_ascii_lowercase() {
                b'c' => mods |= CTRL,
                b's' => mods |= SHIFT,
                b'm' | b'a' => mods |= ALT,
                _ => break,
            }
            rest = &rest[2..];
        } else {
            break;
        }
    }
    if let Some(k) = key_by_name(rest) {
        return Ok(Item::Key(k, mods));
    }
    let mut it = rest.chars();
    if let (Some(c), None) = (it.next(), it.next()) {
        return Ok(Item::Key(Key::Char(c), mods));
    }
    Err(format!("unknown key <{}>", inner))
}

fn parse_mouse(rest: &str) -> Option<Item> {
    let w: Vec<&str> = rest.split_whitespace().collect();
    let pos = |s: &str| -> Option<(usize, usize)> {
        let (x, y) = s.split_once(',')?;
        Some((x.parse().ok()?, y.parse().ok()?))
    };
    let btn = |s: &str| match s {
        "left" => Some(MouseButton::Left),
        "middle" => Some(MouseButton::Middle),
        "right" => Some(MouseButton::Right),
        _ => None,
    };
    let ev = match w.as_slice() {
        ["press", b, p] => MouseEvent { kind: MouseKind::Press, button: btn(b)?, x: pos(p)?.0, y: pos(p)?.1, mods: 0 },
        ["release", b, p] => MouseEvent { kind: MouseKind::Release, button: btn(b)?, x: pos(p)?.0, y: pos(p)?.1, mods: 0 },
        ["drag", b, p] => MouseEvent { kind: MouseKind::Move, button: btn(b)?, x: pos(p)?.0, y: pos(p)?.1, mods: 0 },
        ["move", p] => MouseEvent { kind: MouseKind::Move, button: MouseButton::None, x: pos(p)?.0, y: pos(p)?.1, mods: 0 },
        ["wheel", d, p] => MouseEvent {
            kind: MouseKind::Press,
            button: match *d {
                "up" => MouseButton::WheelUp,
                "down" => MouseButton::WheelDown,
                _ => return None,
            },
            x: pos(p)?.0,
            y: pos(p)?.1,
            mods: 0,
        },
        _ => return None,
    };
    Some(Item::Mouse(ev))
}

/// Parse an input script. Anything outside `<...>` is literal text; `<lt>` produces a literal `<`.
pub fn parse_script(src: &str) -> Result<Vec<Item>, String> {
    let mut items = Vec::new();
    let mut text = String::new();
    let mut chars = src.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        if c == '<' {
            // find the closing '>' (respecting a quoted string inside)
            let rest = &src[i + 1..];
            let mut end = None;
            let mut in_q = false;
            let mut prev = ' ';
            for (j, ch) in rest.char_indices() {
                if ch == '"' && prev != '\\' {
                    in_q = !in_q;
                }
                if ch == '>' && !in_q {
                    end = Some(j);
                    break;
                }
                prev = ch;
            }
            let Some(e) = end else {
                text.push('<');
                continue;
            };
            let inner = &rest[..e];
            if inner.is_empty() || inner.contains('\n') {
                text.push('<');
                continue;
            }
            // `a <b> c` in typed text is not a key spec: only things that look like one are parsed
            // (and a typo like <Escc> is then an error rather than silently typed).
            let looks_like_spec = {
                let l = inner.to_ascii_lowercase();
                l.starts_with("wait ") || l.starts_with("until ") || l.starts_with("resize ") || l.starts_with("mouse ") || l.starts_with("paste ") || l == "focus in" || l == "focus out" || {
                    let core = inner.rsplit('-').next().unwrap_or(inner);
                    inner.chars().all(|c| c.is_ascii_alphanumeric() || c == '-') && (core.chars().count() > 1 || inner.contains('-'))
                }
            };
            if !looks_like_spec {
                text.push('<');
                continue;
            }
            let item = parse_angle(inner)?;
            if !text.is_empty() {
                items.push(Item::Text(std::mem::take(&mut text)));
            }
            items.push(item);
            // skip consumed chars
            let consumed = e + 1;
            let target = i + 1 + consumed;
            while let Some(&(k, _)) = chars.peek() {
                if k < target {
                    chars.next();
                } else {
                    break;
                }
            }
        } else {
            text.push(c);
        }
    }
    if !text.is_empty() {
        items.push(Item::Text(text));
    }
    Ok(items)
}

fn xterm_mod(mods: u8) -> u8 {
    1 + mods
}

/// Encode a key press as the bytes an xterm would send.
pub fn encode_key(modes: &Modes, key: &Key, mods: u8) -> Vec<u8> {
    let alt = mods & ALT != 0;
    let ctrl = mods & CTRL != 0;
    let shift = mods & SHIFT != 0;
    let mut out: Vec<u8> = Vec::new();
    let csi_mod = |final_: char, num: Option<u8>, out: &mut Vec<u8>| {
        // CSI [num] ; mod final   or SS3/CSI plain
        let m = mods;
        if m != 0 {
            out.extend_from_slice(format!("\x1b[{};{}{}", num.unwrap_or(1), xterm_mod(m), final_).as_bytes());
        } else if let Some(n) = num {
            out.extend_from_slice(format!("\x1b[{}{}", n, final_).as_bytes());
        } else if modes.app_cursor {
            out.extend_from_slice(format!("\x1bO{}", final_).as_bytes());
        } else {
            out.extend_from_slice(format!("\x1b[{}", final_).as_bytes());
        }
    };
    match key {
        Key::Char(c) => {
            let mut c = *c;
            if ctrl {
                let b = match c {
                    'a'..='z' => Some(c as u8 - b'a' + 1),
                    'A'..='Z' => Some(c as u8 - b'A' + 1),
                    '@' | ' ' | '2' => Some(0),
                    '[' | '3' => Some(0x1b),
                    '\\' | '4' => Some(0x1c),
                    ']' | '5' => Some(0x1d),
                    '^' | '6' => Some(0x1e),
                    '_' | '7' | '/' => Some(0x1f),
                    '?' | '8' => Some(0x7f),
                    _ => None,
                };
                if let Some(b) = b {
                    if alt {
                        out.push(0x1b);
                    }
                    out.push(b);
                    return out;
                }
            }
            if shift && c.is_ascii_lowercase() {
                c = c.to_ascii_uppercase();
            }
            if alt {
                out.push(0x1b);
            }
            let mut buf = [0u8; 4];
            out.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
        }
        Key::Esc => {
            if alt {
                out.push(0x1b);
            }
            out.push(0x1b);
        }
        Key::Enter => {
            if alt {
                out.push(0x1b);
            }
            out.push(b'\r');
        }
        Key::Tab => {
            if shift {
                out.extend_from_slice(b"\x1b[Z");
            } else {
                if alt {
                    out.push(0x1b);
                }
                out.push(b'\t');
            }
        }
        Key::Backspace => {
            if alt {
                out.push(0x1b);
            }
            out.push(if ctrl { 0x08 } else { 0x7f });
        }
        Key::Up => csi_mod('A', None, &mut out),
        Key::Down => csi_mod('B', None, &mut out),
        Key::Right => csi_mod('C', None, &mut out),
        Key::Left => csi_mod('D', None, &mut out),
        Key::Home => csi_mod('H', None, &mut out),
        Key::End => csi_mod('F', None, &mut out),
        Key::Insert => csi_mod('~', Some(2), &mut out),
        Key::Delete => csi_mod('~', Some(3), &mut out),
        Key::PageUp => csi_mod('~', Some(5), &mut out),
        Key::PageDown => csi_mod('~', Some(6), &mut out),
        Key::F(n) => {
            let n = *n;
            match n {
                1..=4 => {
                    let f = [b'P', b'Q', b'R', b'S'][n as usize - 1] as char;
                    if mods != 0 {
                        out.extend_from_slice(format!("\x1b[1;{}{}", xterm_mod(mods), f).as_bytes());
                    } else {
                        out.extend_from_slice(format!("\x1bO{}", f).as_bytes());
                    }
                }
                5..=12 => {
                    let code = [15, 17, 18, 19, 20, 21, 23, 24][n as usize - 5];
                    csi_mod('~', Some(code), &mut out);
                }
                _ => {}
            }
        }
    }
    out
}

/// Encode a mouse event for the application, or `None` if the current mouse mode does not report it
/// (or the coordinates cannot be represented in the active encoding).
pub fn encode_mouse(modes: &Modes, ev: &MouseEvent) -> Option<Vec<u8>> {
    let wheel = matches!(ev.button, MouseButton::WheelUp | MouseButton::WheelDown);
    match modes.mouse {
        MouseMode::None => return None,
        MouseMode::X10 => {
            if ev.kind != MouseKind::Press || wheel || ev.button == MouseButton::None {
                return None;
            }
        }
        MouseMode::Normal => {
            if ev.kind == MouseKind::Move {
                return None;
            }
        }
        MouseMode::Button => {
            if ev.kind == MouseKind::Move && ev.button == MouseButton::None {
                return None;
            }
        }
        MouseMode::Any => {}
    }
    let base = match ev.button {
        MouseButton::Left => 0,
        MouseButton::Middle => 1,
        MouseButton::Right => 2,
        MouseButton::WheelUp => 64,
        MouseButton::WheelDown => 65,
        MouseButton::None => 3,
    };
    let sgr = modes.mouse_enc == MouseEnc::Sgr;
    // legacy encodings cannot say which button was released
    let mut cb = if ev.kind == MouseKind::Release && !sgr { 3 } else { base };
    if modes.mouse != MouseMode::X10 {
        if ev.mods & SHIFT != 0 {
            cb += 4;
        }
        if ev.mods & ALT != 0 {
            cb += 8;
        }
        if ev.mods & CTRL != 0 {
            cb += 16;
        }
    }
    if ev.kind == MouseKind::Move {
        cb += 32;
    }
    let (cx, cy) = (ev.x + 1, ev.y + 1);
    let mut out: Vec<u8> = Vec::new();
    match modes.mouse_enc {
        MouseEnc::Sgr => {
            let fin = if ev.kind == MouseKind::Release { 'm' } else { 'M' };
            out.extend_from_slice(format!("\x1b[<{};{};{}{}", cb, cx, cy, fin).as_bytes());
        }
        MouseEnc::Urxvt => out.extend_from_slice(format!("\x1b[{};{};{}M", cb + 32, cx, cy).as_bytes()),
        MouseEnc::Utf8 => {
            if cx + 32 > 2047 || cy + 32 > 2047 {
                return None;
            }
            out.extend_from_slice(b"\x1b[M");
            out.push((cb + 32) as u8);
            for v in [cx + 32, cy + 32] {
                let mut buf = [0u8; 4];
                out.extend_from_slice(char::from_u32(v as u32)?.encode_utf8(&mut buf).as_bytes());
            }
        }
        MouseEnc::Default => {
            if cx + 32 > 255 || cy + 32 > 255 {
                return None;
            }
            out.extend_from_slice(b"\x1b[M");
            out.extend_from_slice(&[(cb + 32) as u8, (cx + 32) as u8, (cy + 32) as u8]);
        }
    }
    Some(out)
}

/// Bytes for pasting `text`. With bracketed paste on, the text is wrapped in `ESC[200~ … ESC[201~`
/// and any embedded end-marker is removed (so pasted text cannot break out of the bracket);
/// otherwise line breaks become CR as xterm does.
pub fn encode_paste(modes: &Modes, text: &str) -> Vec<u8> {
    if modes.bracketed_paste {
        let mut clean = text.to_string();
        while clean.contains("\x1b[201~") {
            clean = clean.replace("\x1b[201~", "");
        }
        let mut out = b"\x1b[200~".to_vec();
        out.extend_from_slice(clean.as_bytes());
        out.extend_from_slice(b"\x1b[201~");
        out
    } else {
        text.replace("\r\n", "\r").replace('\n', "\r").into_bytes()
    }
}

/// Focus in/out report (DECSET 1004).
pub fn encode_focus(modes: &Modes, focused: bool) -> Option<Vec<u8>> {
    if !modes.focus_events {
        return None;
    }
    Some(if focused { b"\x1b[I".to_vec() } else { b"\x1b[O".to_vec() })
}
