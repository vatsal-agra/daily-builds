//! Paul Williams' DEC-compatible ANSI escape-sequence state machine
//! (<https://vt100.net/emu/dec_ansi_parser>) with an incremental UTF-8 decoder in the ground state.
//!
//! The parser is pure: it turns bytes into calls on a [`Perform`] sink and keeps no screen state.

pub const MAX_PARAMS: usize = 32;
const MAX_INTERMEDIATES: usize = 4;
const MAX_STRING: usize = 1 << 20;

/// Parameter list of a CSI/DCS sequence. Parameters separated by `:` are sub-parameters of the
/// preceding `;`-separated parameter.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Params {
    vals: Vec<u16>,
    /// `sub[i]` is true if `vals[i]` was introduced by ':' (a sub-parameter of the previous value).
    sub: Vec<bool>,
    /// Value is present (an omitted param like the first in `;5` is stored as 0 with `set == false`).
    set: Vec<bool>,
}

impl Params {
    pub fn len(&self) -> usize {
        self.vals.len()
    }
    pub fn is_empty(&self) -> bool {
        self.vals.is_empty()
    }
    /// Top-level (`;`-separated) groups, each a slice of its sub-parameter values.
    pub fn groups(&self) -> Vec<Vec<Option<u16>>> {
        let mut out: Vec<Vec<Option<u16>>> = Vec::new();
        for i in 0..self.vals.len() {
            let v = if self.set[i] { Some(self.vals[i]) } else { None };
            if self.sub[i] && !out.is_empty() {
                out.last_mut().unwrap().push(v);
            } else {
                out.push(vec![v]);
            }
        }
        out
    }
    /// First value of group `n` with a default if omitted or 0 (the usual CSI "default 1" rule uses `get_nz`).
    pub fn get(&self, n: usize, default: u16) -> u16 {
        self.groups().get(n).and_then(|g| g[0]).unwrap_or(default)
    }
    /// Like `get` but treats an explicit 0 as the default (cursor movement counts).
    pub fn get_nz(&self, n: usize, default: u16) -> u16 {
        match self.groups().get(n).and_then(|g| g[0]) {
            Some(0) | None => default,
            Some(v) => v,
        }
    }
    pub fn flat(&self) -> Vec<u16> {
        (0..self.vals.len()).map(|i| if self.set[i] { self.vals[i] } else { 0 }).collect()
    }
    fn clear(&mut self) {
        self.vals.clear();
        self.sub.clear();
        self.set.clear();
    }
    fn push_new(&mut self, sub: bool) {
        if self.vals.len() < MAX_PARAMS {
            self.vals.push(0);
            self.sub.push(sub);
            self.set.push(false);
        }
    }
    fn digit(&mut self, d: u8) {
        if let Some(v) = self.vals.last_mut() {
            *v = (*v as u32 * 10 + d as u32).min(65535) as u16;
            *self.set.last_mut().unwrap() = true;
        }
    }
}

/// Event sink for the parser.
pub trait Perform {
    fn print(&mut self, c: char);
    /// C0 control (and DEL is ignored by the parser, never delivered).
    fn execute(&mut self, byte: u8);
    /// `marker` is the private-parameter prefix byte (`?`, `>`, `<`, `=`) or 0.
    fn csi(&mut self, params: &Params, marker: u8, inter: &[u8], fin: u8);
    fn esc(&mut self, inter: &[u8], fin: u8);
    /// OSC string payload (without the introducer and terminator).
    fn osc(&mut self, data: &[u8]);
    /// A complete DCS sequence: params, intermediates, final byte, and data string.
    fn dcs(&mut self, params: &Params, marker: u8, inter: &[u8], fin: u8, data: &[u8]);
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum St {
    Ground,
    Escape,
    EscapeInter,
    CsiEntry,
    CsiParam,
    CsiInter,
    CsiIgnore,
    DcsEntry,
    DcsParam,
    DcsInter,
    DcsPassthrough,
    DcsIgnore,
    OscString,
    /// SOS / PM / APC: consumed and discarded until ST.
    SosPmApc,
}

pub struct Parser {
    st: St,
    params: Params,
    marker: u8,
    inter: Vec<u8>,
    fin: u8,
    string: Vec<u8>,
    string_overflow: bool,
    // UTF-8 decoder
    u_acc: u32,
    u_need: u8,
    u_min: u32,
}

impl Default for Parser {
    fn default() -> Self {
        Parser::new()
    }
}

impl Parser {
    pub fn new() -> Parser {
        Parser {
            st: St::Ground,
            params: Params::default(),
            marker: 0,
            inter: Vec::new(),
            fin: 0,
            string: Vec::new(),
            string_overflow: false,
            u_acc: 0,
            u_need: 0,
            u_min: 0,
        }
    }

    pub fn advance<P: Perform>(&mut self, p: &mut P, bytes: &[u8]) {
        for &b in bytes {
            self.byte(p, b);
        }
    }

    fn clear(&mut self) {
        self.params.clear();
        self.marker = 0;
        self.inter.clear();
        self.fin = 0;
    }

    fn collect(&mut self, b: u8) {
        if self.inter.len() < MAX_INTERMEDIATES {
            self.inter.push(b);
        } else {
            self.inter.push(0xFF); // overflow marker: dispatch will see an unknown intermediate
            self.inter.truncate(MAX_INTERMEDIATES);
        }
    }

    fn utf8_abort<P: Perform>(&mut self, p: &mut P) {
        if self.u_need != 0 {
            self.u_need = 0;
            p.print('\u{FFFD}');
        }
    }

    fn byte<P: Perform>(&mut self, p: &mut P, b: u8) {
        // CAN / SUB cancel any sequence; ESC restarts one (except inside strings, where it may start ST).
        if self.st == St::Ground {
            self.ground(p, b);
            return;
        }
        // Non-ASCII bytes cannot be part of a control sequence (we are UTF-8 only).
        // Inside strings they are payload; elsewhere they abort the sequence and re-enter the ground state.
        if b >= 0x80 {
            match self.st {
                St::OscString | St::DcsPassthrough => {
                    self.push_string(b);
                }
                St::DcsIgnore | St::SosPmApc => {}
                _ => {
                    self.st = St::Ground;
                    self.ground(p, b);
                }
            }
            return;
        }
        match b {
            0x18 | 0x1A => {
                // Abort without dispatching.
                self.st = St::Ground;
                p.execute(b);
                return;
            }
            0x1B => {
                self.finish_string(p);
                self.clear();
                self.st = St::Escape;
                return;
            }
            _ => {}
        }
        match self.st {
            St::Ground => unreachable!(),
            St::Escape => self.escape(p, b),
            St::EscapeInter => match b {
                0x00..=0x1F => p.execute(b),
                0x20..=0x2F => self.collect(b),
                0x30..=0x7E => {
                    p.esc(&self.inter, b);
                    self.st = St::Ground;
                }
                _ => {}
            },
            St::CsiEntry | St::CsiParam | St::CsiInter | St::CsiIgnore => self.csi_byte(p, b),
            St::DcsEntry | St::DcsParam | St::DcsInter | St::DcsIgnore => self.dcs_byte(p, b),
            St::DcsPassthrough => {
                if b != 0x7F {
                    self.push_string(b);
                }
            }
            St::OscString => match b {
                0x07 => {
                    self.finish_string(p);
                    self.st = St::Ground;
                }
                0x00..=0x1F => {}
                _ => self.push_string(b),
            },
            St::SosPmApc => {}
        }
    }

    fn push_string(&mut self, b: u8) {
        if self.string.len() < MAX_STRING {
            self.string.push(b);
        } else {
            self.string_overflow = true;
        }
    }

    /// Dispatch an OSC/DCS string that is being terminated (by ST, BEL or by an interrupting ESC).
    fn finish_string<P: Perform>(&mut self, p: &mut P) {
        match self.st {
            St::OscString => {
                if !self.string_overflow {
                    p.osc(&self.string);
                }
            }
            St::DcsPassthrough => {
                if !self.string_overflow {
                    p.dcs(&self.params, self.marker, &self.inter, self.fin, &self.string);
                }
            }
            _ => {}
        }
        self.string.clear();
        self.string_overflow = false;
    }

    fn ground<P: Perform>(&mut self, p: &mut P, b: u8) {
        if self.u_need > 0 {
            if b & 0xC0 == 0x80 {
                self.u_acc = (self.u_acc << 6) | (b & 0x3F) as u32;
                self.u_need -= 1;
                if self.u_need == 0 {
                    let cp = self.u_acc;
                    let ok = cp >= self.u_min && char::from_u32(cp).is_some();
                    p.print(if ok { char::from_u32(cp).unwrap() } else { '\u{FFFD}' });
                }
                return;
            }
            // Truncated sequence: emit one replacement, then treat this byte afresh.
            self.utf8_abort(p);
        }
        match b {
            0x1B => {
                self.clear();
                self.st = St::Escape;
            }
            0x18 | 0x1A => p.execute(b),
            0x00..=0x1F => p.execute(b),
            0x20..=0x7E => p.print(b as char),
            0x7F => {}
            0x80..=0xBF => p.print('\u{FFFD}'), // stray continuation
            0xC0 | 0xC1 | 0xF5..=0xFF => p.print('\u{FFFD}'),
            0xC2..=0xDF => {
                self.u_acc = (b & 0x1F) as u32;
                self.u_need = 1;
                self.u_min = 0x80;
            }
            0xE0..=0xEF => {
                self.u_acc = (b & 0x0F) as u32;
                self.u_need = 2;
                self.u_min = 0x800;
            }
            0xF0..=0xF4 => {
                self.u_acc = (b & 0x07) as u32;
                self.u_need = 3;
                self.u_min = 0x10000;
            }
        }
    }

    fn escape<P: Perform>(&mut self, p: &mut P, b: u8) {
        match b {
            0x00..=0x1F => p.execute(b),
            0x20..=0x2F => {
                self.collect(b);
                self.st = St::EscapeInter;
            }
            b'[' => {
                self.clear();
                self.st = St::CsiEntry;
            }
            b']' => {
                self.clear();
                self.string.clear();
                self.string_overflow = false;
                self.st = St::OscString;
            }
            b'P' => {
                self.clear();
                self.string.clear();
                self.string_overflow = false;
                self.st = St::DcsEntry;
            }
            b'X' | b'^' | b'_' => {
                self.st = St::SosPmApc;
            }
            0x7F => {}
            _ => {
                // includes '\\' (ST) which is a harmless ESC dispatch
                p.esc(&self.inter, b);
                self.st = St::Ground;
            }
        }
    }

    fn csi_byte<P: Perform>(&mut self, p: &mut P, b: u8) {
        match b {
            0x00..=0x1F => {
                // C0 controls execute in place without disturbing the sequence.
                p.execute(b);
            }
            0x7F => {}
            0x20..=0x2F => {
                if self.st != St::CsiIgnore {
                    self.collect(b);
                    self.st = St::CsiInter;
                }
            }
            0x30..=0x39 => match self.st {
                St::CsiEntry => {
                    self.params.push_new(false);
                    self.params.digit(b - b'0');
                    self.st = St::CsiParam;
                }
                St::CsiParam => {
                    if self.params.is_empty() {
                        self.params.push_new(false);
                    }
                    self.params.digit(b - b'0');
                }
                St::CsiInter => self.st = St::CsiIgnore,
                _ => {}
            },
            b':' | b';' => match self.st {
                St::CsiEntry => {
                    self.params.push_new(false); // omitted first param
                    self.params.push_new(b == b':');
                    self.st = St::CsiParam;
                }
                St::CsiParam => {
                    if self.params.is_empty() {
                        self.params.push_new(false);
                    }
                    self.params.push_new(b == b':');
                }
                St::CsiInter => self.st = St::CsiIgnore,
                _ => {}
            },
            b'<' | b'=' | b'>' | b'?' => match self.st {
                St::CsiEntry => {
                    self.marker = b;
                    self.st = St::CsiParam;
                }
                St::CsiIgnore => {}
                _ => self.st = St::CsiIgnore,
            },
            0x40..=0x7E => {
                if self.st != St::CsiIgnore {
                    p.csi(&self.params, self.marker, &self.inter, b);
                }
                self.st = St::Ground;
            }
            _ => {}
        }
    }

    fn dcs_byte<P: Perform>(&mut self, _p: &mut P, b: u8) {
        match b {
            0x00..=0x1F | 0x7F => {}
            0x20..=0x2F => {
                if self.st != St::DcsIgnore {
                    self.collect(b);
                    self.st = St::DcsInter;
                }
            }
            0x30..=0x39 => match self.st {
                St::DcsEntry => {
                    self.params.push_new(false);
                    self.params.digit(b - b'0');
                    self.st = St::DcsParam;
                }
                St::DcsParam => self.params.digit(b - b'0'),
                St::DcsInter => self.st = St::DcsIgnore,
                _ => {}
            },
            b':' | b';' => match self.st {
                St::DcsEntry => {
                    self.params.push_new(false);
                    self.params.push_new(b == b':');
                    self.st = St::DcsParam;
                }
                St::DcsParam => {
                    if self.params.is_empty() {
                        self.params.push_new(false);
                    }
                    self.params.push_new(b == b':');
                }
                St::DcsInter => self.st = St::DcsIgnore,
                _ => {}
            },
            b'<' | b'=' | b'>' | b'?' => match self.st {
                St::DcsEntry => {
                    self.marker = b;
                    self.st = St::DcsParam;
                }
                St::DcsIgnore => {}
                _ => self.st = St::DcsIgnore,
            },
            0x40..=0x7E => {
                if self.st == St::DcsIgnore {
                    self.st = St::DcsIgnore;
                } else {
                    self.fin = b;
                    self.string.clear();
                    self.string_overflow = false;
                    self.st = St::DcsPassthrough;
                }
            }
            _ => {}
        }
    }
}
