//! Colors, attributes and the screen cell.

#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Color {
    #[default]
    Default,
    Idx(u8),
    Rgb(u8, u8, u8),
}

pub const BOLD: u16 = 1 << 0;
pub const DIM: u16 = 1 << 1;
pub const ITALIC: u16 = 1 << 2;
pub const UNDERLINE: u16 = 1 << 3;
pub const BLINK: u16 = 1 << 4;
pub const INVERSE: u16 = 1 << 5;
pub const HIDDEN: u16 = 1 << 6;
pub const STRIKE: u16 = 1 << 7;
pub const DOUBLE_UL: u16 = 1 << 8;
pub const CURLY_UL: u16 = 1 << 9;
pub const OVERLINE: u16 = 1 << 10;
pub const DOTTED_UL: u16 = 1 << 11;
pub const DASHED_UL: u16 = 1 << 12;
/// Any of the underline-style bits.
pub const ANY_UL: u16 = UNDERLINE | DOUBLE_UL | CURLY_UL | DOTTED_UL | DASHED_UL;

/// Drawing state applied to newly printed cells (the "pen").
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Pen {
    pub fg: Color,
    pub bg: Color,
    pub ul: Color,
    pub attrs: u16,
    /// Index into `Screen::links`, 0 = none.
    pub link: u32,
}

#[derive(Clone, PartialEq, Eq, Debug)]
pub struct Cell {
    pub ch: char,
    /// 1 normal, 2 = leading half of a wide char, 0 = trailing half (continuation) of a wide char.
    pub width: u8,
    pub fg: Color,
    pub bg: Color,
    pub ul: Color,
    pub attrs: u16,
    pub link: u32,
    /// Combining characters attached to `ch`.
    pub comb: Option<Box<String>>,
}

impl Default for Cell {
    fn default() -> Self {
        Cell::blank(Color::Default)
    }
}

impl Cell {
    /// A blank cell as produced by an erase: current background colour only (BCE).
    pub fn blank(bg: Color) -> Cell {
        Cell { ch: ' ', width: 1, fg: Color::Default, bg, ul: Color::Default, attrs: 0, link: 0, comb: None }
    }
    pub fn with_pen(ch: char, width: u8, pen: &Pen) -> Cell {
        Cell { ch, width, fg: pen.fg, bg: pen.bg, ul: pen.ul, attrs: pen.attrs, link: pen.link, comb: None }
    }
    pub fn is_continuation(&self) -> bool {
        self.width == 0
    }
    pub fn pen(&self) -> Pen {
        Pen { fg: self.fg, bg: self.bg, ul: self.ul, attrs: self.attrs, link: self.link }
    }
    /// Appends the full grapheme (base + combining marks) to `out`.
    pub fn push_text(&self, out: &mut String) {
        out.push(self.ch);
        if let Some(c) = &self.comb {
            out.push_str(c);
        }
    }
    /// True if the cell shows nothing and has default styling (safe to trim).
    pub fn is_plain_blank(&self) -> bool {
        self.ch == ' ' && self.comb.is_none() && self.bg == Color::Default && self.attrs & (INVERSE | ANY_UL | STRIKE | OVERLINE) == 0 && self.link == 0
    }
}

/// The xterm 256-colour palette entry `i` as RGB.
pub fn xterm_rgb(i: u8) -> (u8, u8, u8) {
    const BASE: [(u8, u8, u8); 16] = [
        (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
        (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
    ];
    match i {
        0..=15 => BASE[i as usize],
        16..=231 => {
            let n = i - 16;
            let lv = |v: u8| if v == 0 { 0 } else { 55 + 40 * v };
            (lv(n / 36), lv((n / 6) % 6), lv(n % 6))
        }
        _ => {
            let v = 8 + 10 * (i - 232);
            (v, v, v)
        }
    }
}
