//! Keyboard input: a tiny script language (`ihello<Esc>:wq<CR>`) and key → byte encoding that
//! depends on the terminal's current modes (application cursor keys, ...).

use crate::screen::Modes;

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
