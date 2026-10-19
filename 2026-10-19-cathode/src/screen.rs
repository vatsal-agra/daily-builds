//! The screen model: grid, cursor, margins, modes, tab stops, alternate screen and scrollback.
//! All operations are plain Rust methods; escape-sequence decoding lives in `term.rs`.

use crate::cell::*;
use crate::width::char_width;
use std::collections::VecDeque;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Line {
    pub cells: Vec<Cell>,
    /// True if this row was soft-wrapped onto the next one (its text continues there).
    pub wrapped: bool,
}

impl Line {
    pub fn blank(cols: usize, bg: Color) -> Line {
        Line { cells: vec![Cell::blank(bg); cols], wrapped: false }
    }
    /// Length ignoring trailing plain blanks.
    pub fn used_len(&self) -> usize {
        let mut n = self.cells.len();
        while n > 0 && self.cells[n - 1].is_plain_blank() {
            n -= 1;
        }
        n
    }
    pub fn text(&self) -> String {
        let mut s = String::new();
        for c in &self.cells[..self.used_len()] {
            if c.width != 0 {
                c.push_text(&mut s);
            }
        }
        s
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Charset {
    Ascii,
    DecGraphics,
    Uk,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum MouseMode {
    None,
    X10,
    Normal,
    Button,
    Any,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum MouseEnc {
    Default,
    Utf8,
    Sgr,
    Urxvt,
}

#[derive(Clone, Debug)]
pub struct Modes {
    pub autowrap: bool,
    pub origin: bool,
    pub insert: bool,
    pub newline: bool,
    pub app_cursor: bool,
    pub app_keypad: bool,
    pub cursor_visible: bool,
    pub cursor_blink: bool,
    pub reverse_video: bool,
    pub bracketed_paste: bool,
    pub focus_events: bool,
    pub sync_output: bool,
    pub mouse: MouseMode,
    pub mouse_enc: MouseEnc,
}

impl Default for Modes {
    fn default() -> Modes {
        Modes {
            autowrap: true,
            origin: false,
            insert: false,
            newline: false,
            app_cursor: false,
            app_keypad: false,
            cursor_visible: true,
            cursor_blink: true,
            reverse_video: false,
            bracketed_paste: false,
            focus_events: false,
            sync_output: false,
            mouse: MouseMode::None,
            mouse_enc: MouseEnc::Default,
        }
    }
}

#[derive(Clone, Debug)]
struct Saved {
    cx: usize,
    cy: usize,
    pen: Pen,
    pending_wrap: bool,
    origin: bool,
    charsets: [Charset; 4],
    gl: usize,
}

#[derive(Clone, Debug)]
pub struct Buf {
    pub lines: Vec<Line>,
    pub scrollback: VecDeque<Line>,
}

#[derive(Clone, Debug)]
pub struct Link {
    pub id: String,
    pub uri: String,
}

#[derive(Clone)]
pub struct Screen {
    pub cols: usize,
    pub rows: usize,
    pub main: Buf,
    pub alt: Buf,
    pub alt_active: bool,
    pub cx: usize,
    pub cy: usize,
    pub pending_wrap: bool,
    pub pen: Pen,
    /// Scroll region, 0-based inclusive.
    pub top: usize,
    pub bottom: usize,
    pub tabs: Vec<bool>,
    pub modes: Modes,
    pub charsets: [Charset; 4],
    pub gl: usize,
    saved: [Option<Saved>; 2],
    pub links: Vec<Link>,
    pub title: String,
    pub bell_count: u64,
    pub last_char: Option<char>,
    pub scrollback_limit: usize,
    pub cursor_style: u8,
    pub palette: Vec<(u8, u8, u8)>,
    pub default_fg: (u8, u8, u8),
    pub default_bg: (u8, u8, u8),
}

fn default_tabs(cols: usize) -> Vec<bool> {
    (0..cols).map(|i| i % 8 == 0 && i != 0).collect()
}

const DEC_GFX: [char; 32] = [
    ' ', '◆', '▒', '␉', '␌', '␍', '␊', '°', '±', '␤', '␋', '┘', '┐', '┌', '└', '┼', '⎺', '⎻', '─', '⎼', '⎽', '├', '┤', '┴', '┬', '│', '≤', '≥', 'π',
    '≠', '£', '·',
];

impl Screen {
    pub fn new(cols: usize, rows: usize) -> Screen {
        let cols = cols.max(1);
        let rows = rows.max(1);
        let mk = || Buf { lines: (0..rows).map(|_| Line::blank(cols, Color::Default)).collect(), scrollback: VecDeque::new() };
        Screen {
            cols,
            rows,
            main: mk(),
            alt: mk(),
            alt_active: false,
            cx: 0,
            cy: 0,
            pending_wrap: false,
            pen: Pen::default(),
            top: 0,
            bottom: rows - 1,
            tabs: default_tabs(cols),
            modes: Modes::default(),
            charsets: [Charset::Ascii; 4],
            gl: 0,
            saved: [None, None],
            links: vec![Link { id: String::new(), uri: String::new() }],
            title: String::new(),
            bell_count: 0,
            last_char: None,
            scrollback_limit: 10_000,
            cursor_style: 0,
            palette: (0..=255u8).map(xterm_rgb).collect(),
            default_fg: (229, 229, 229),
            default_bg: (0, 0, 0),
        }
    }

    // ---- accessors ------------------------------------------------------------------

    pub fn buf(&self) -> &Buf {
        if self.alt_active {
            &self.alt
        } else {
            &self.main
        }
    }
    pub fn buf_mut(&mut self) -> &mut Buf {
        if self.alt_active {
            &mut self.alt
        } else {
            &mut self.main
        }
    }
    pub fn line(&self, y: usize) -> &Line {
        &self.buf().lines[y]
    }
    pub fn line_mut(&mut self, y: usize) -> &mut Line {
        &mut self.buf_mut().lines[y]
    }
    pub fn cell(&self, x: usize, y: usize) -> &Cell {
        &self.buf().lines[y].cells[x]
    }
    pub fn scrollback_len(&self) -> usize {
        self.buf().scrollback.len()
    }
    pub fn row_text(&self, y: usize) -> String {
        self.line(y).text()
    }
    /// Visible rows as text, each trimmed of trailing blanks, joined with '\n'.
    pub fn text(&self) -> String {
        (0..self.rows).map(|y| self.row_text(y)).collect::<Vec<_>>().join("\n")
    }
    pub fn blank_cell(&self) -> Cell {
        Cell::blank(self.pen.bg)
    }
    fn blank_line(&self) -> Line {
        Line::blank(self.cols, self.pen.bg)
    }

    // ---- wide-character hygiene -------------------------------------------------------

    /// Make sure no wide-character half is orphaned in `line` (blank any that are).
    fn fix_wide(line: &mut Line, bg: Color) {
        let n = line.cells.len();
        for i in 0..n {
            let w = line.cells[i].width;
            if w == 0 && (i == 0 || line.cells[i - 1].width != 2) {
                line.cells[i] = Cell::blank(bg);
            } else if w == 2 && (i + 1 >= n || line.cells[i + 1].width != 0) {
                line.cells[i] = Cell::blank(bg);
            }
        }
    }

    /// Prepare to overwrite cell `x` of `line`: blank the partner half of a wide char.
    fn clear_wide_at(line: &mut Line, x: usize, bg: Color) {
        let n = line.cells.len();
        match line.cells[x].width {
            0 if x > 0 => line.cells[x - 1] = Cell::blank(bg),
            2 if x + 1 < n => line.cells[x + 1] = Cell::blank(bg),
            _ => {}
        }
    }

    // ---- printing ----------------------------------------------------------------------

    fn map_charset(&self, c: char) -> char {
        match self.charsets[self.gl] {
            Charset::Ascii => c,
            Charset::DecGraphics => {
                let u = c as u32;
                if (0x5F..=0x7E).contains(&u) {
                    DEC_GFX[(u - 0x5F) as usize]
                } else {
                    c
                }
            }
            Charset::Uk => {
                if c == '#' {
                    '£'
                } else {
                    c
                }
            }
        }
    }

    pub fn print(&mut self, c: char) {
        let c = self.map_charset(c);
        let w = char_width(c);
        if w == 0 {
            self.attach_combining(c);
            return;
        }
        self.last_char = Some(c);
        if self.pending_wrap {
            if self.modes.autowrap {
                let cy = self.cy;
                self.line_mut(cy).wrapped = true;
                self.cx = 0;
                self.index();
            }
            self.pending_wrap = false;
        }
        if w == 2 && self.cx + 1 >= self.cols {
            if self.cols < 2 {
                return;
            }
            if self.modes.autowrap {
                let (cx, cy, bg) = (self.cx, self.cy, self.pen.bg);
                let line = self.line_mut(cy);
                Self::clear_wide_at(line, cx, bg);
                line.cells[cx] = Cell::blank(bg);
                line.wrapped = true;
                self.cx = 0;
                self.index();
            } else {
                self.cx = self.cols - 2;
            }
        }
        let (cx, cy, bg) = (self.cx, self.cy, self.pen.bg);
        let pen = self.pen;
        let insert = self.modes.insert;
        let cols = self.cols;
        let line = self.line_mut(cy);
        if insert {
            for _ in 0..w {
                line.cells.pop();
                line.cells.insert(cx, Cell::blank(bg));
            }
            Self::fix_wide(line, bg);
        }
        Self::clear_wide_at(line, cx, bg);
        if w == 2 {
            Self::clear_wide_at(line, cx + 1, bg);
            line.cells[cx] = Cell::with_pen(c, 2, &pen);
            line.cells[cx + 1] = Cell::with_pen(' ', 0, &pen);
        } else {
            line.cells[cx] = Cell::with_pen(c, 1, &pen);
        }
        if cx + w >= cols {
            self.cx = cols - 1;
            self.pending_wrap = self.modes.autowrap;
        } else {
            self.cx = cx + w;
        }
    }

    fn attach_combining(&mut self, c: char) {
        let mut x = if self.pending_wrap {
            self.cx
        } else if self.cx > 0 {
            self.cx - 1
        } else {
            return;
        };
        let cy = self.cy;
        let line = self.line_mut(cy);
        if line.cells[x].width == 0 && x > 0 {
            x -= 1;
        }
        let cell = &mut line.cells[x];
        let s = cell.comb.get_or_insert_with(|| Box::new(String::new()));
        if s.chars().count() < 8 {
            s.push(c);
        }
    }

    // ---- cursor & scrolling --------------------------------------------------------------

    /// Move the cursor to 1-based (row, col), honouring origin mode.
    pub fn cup(&mut self, row: usize, col: usize) {
        let (rt, rb) = if self.modes.origin { (self.top, self.bottom) } else { (0, self.rows - 1) };
        self.cy = (rt + row.max(1) - 1).min(rb);
        self.cx = (col.max(1) - 1).min(self.cols - 1);
        self.pending_wrap = false;
    }
    pub fn set_x(&mut self, x: usize) {
        self.cx = x.min(self.cols - 1);
        self.pending_wrap = false;
    }
    /// Absolute row (1-based, origin-relative when DECOM is set), column unchanged.
    pub fn set_row(&mut self, row: usize) {
        let (rt, rb) = if self.modes.origin { (self.top, self.bottom) } else { (0, self.rows - 1) };
        self.cy = (rt + row.max(1) - 1).min(rb);
        self.pending_wrap = false;
    }
    pub fn cursor_up(&mut self, n: usize) {
        let limit = if self.cy >= self.top { self.top } else { 0 };
        self.cy = self.cy.saturating_sub(n).max(limit);
        self.pending_wrap = false;
    }
    pub fn cursor_down(&mut self, n: usize) {
        let limit = if self.cy <= self.bottom { self.bottom } else { self.rows - 1 };
        self.cy = (self.cy + n).min(limit);
        self.pending_wrap = false;
    }
    pub fn cursor_forward(&mut self, n: usize) {
        self.cx = (self.cx + n).min(self.cols - 1);
        self.pending_wrap = false;
    }
    pub fn cursor_back(&mut self, n: usize) {
        self.cx = self.cx.saturating_sub(n);
        self.pending_wrap = false;
    }
    pub fn carriage_return(&mut self) {
        self.cx = 0;
        self.pending_wrap = false;
    }
    pub fn backspace(&mut self) {
        self.cx = self.cx.saturating_sub(1);
        self.pending_wrap = false;
    }

    /// IND: move down, scrolling the region if at its bottom margin.
    pub fn index(&mut self) {
        if self.cy == self.bottom {
            self.scroll_up(1);
        } else if self.cy + 1 < self.rows {
            self.cy += 1;
        }
    }
    /// RI: move up, scrolling the region down if at its top margin.
    pub fn reverse_index(&mut self) {
        if self.cy == self.top {
            self.scroll_down(1);
        } else if self.cy > 0 {
            self.cy -= 1;
        }
        self.pending_wrap = false;
    }
    /// LF / VT / FF.
    pub fn linefeed(&mut self) {
        self.index();
        if self.modes.newline {
            self.cx = 0;
        }
        self.pending_wrap = false;
    }
    /// NEL.
    pub fn next_line(&mut self) {
        self.index();
        self.cx = 0;
        self.pending_wrap = false;
    }

    fn full_region(&self) -> bool {
        self.top == 0 && self.bottom == self.rows - 1
    }

    /// Scroll the scroll region up by `n` lines (SU, or LF at the bottom margin).
    pub fn scroll_up(&mut self, n: usize) {
        let (t, b) = (self.top, self.bottom);
        let history = !self.alt_active && self.full_region();
        self.scroll_up_in(t, b, n, history);
    }
    pub fn scroll_down(&mut self, n: usize) {
        let (t, b) = (self.top, self.bottom);
        self.scroll_down_in(t, b, n);
    }

    fn scroll_up_in(&mut self, t: usize, b: usize, n: usize, history: bool) {
        let n = n.min(b - t + 1);
        let limit = self.scrollback_limit;
        for _ in 0..n {
            let blank = self.blank_line();
            let buf = self.buf_mut();
            let old = buf.lines.remove(t);
            buf.lines.insert(b, blank);
            if history && limit > 0 {
                buf.scrollback.push_back(old);
                if buf.scrollback.len() > limit {
                    buf.scrollback.pop_front();
                }
            }
        }
    }
    fn scroll_down_in(&mut self, t: usize, b: usize, n: usize) {
        let n = n.min(b - t + 1);
        for _ in 0..n {
            let blank = self.blank_line();
            let buf = self.buf_mut();
            buf.lines.remove(b);
            buf.lines.insert(t, blank);
        }
    }

    pub fn set_margins(&mut self, top1: usize, bottom1: usize) {
        let t = top1.max(1);
        let b = if bottom1 == 0 || bottom1 > self.rows { self.rows } else { bottom1 };
        if t < b {
            self.top = t - 1;
            self.bottom = b - 1;
            self.cup(1, 1);
        }
    }

    // ---- tabs ---------------------------------------------------------------------------

    pub fn tab_forward(&mut self, n: usize) {
        for _ in 0..n {
            let mut x = self.cx + 1;
            while x < self.cols - 1 && !self.tabs[x] {
                x += 1;
            }
            self.cx = x.min(self.cols - 1);
        }
        self.pending_wrap = false;
    }
    pub fn tab_back(&mut self, n: usize) {
        for _ in 0..n {
            let mut x = self.cx;
            while x > 0 {
                x -= 1;
                if self.tabs[x] {
                    break;
                }
            }
            self.cx = x;
        }
        self.pending_wrap = false;
    }
    pub fn set_tab(&mut self) {
        self.tabs[self.cx] = true;
    }
    pub fn clear_tab(&mut self, all: bool) {
        if all {
            self.tabs.iter_mut().for_each(|t| *t = false);
        } else {
            self.tabs[self.cx] = false;
        }
    }

    // ---- erase / insert / delete ----------------------------------------------------------

    /// Erase cells `x0..x1` of row `y` (BCE colour). Clears the soft-wrap flag when the erase reaches the end.
    pub fn erase_cells(&mut self, y: usize, x0: usize, x1: usize) {
        let x1 = x1.min(self.cols);
        if x0 >= x1 {
            return;
        }
        let bg = self.pen.bg;
        let cols = self.cols;
        let line = self.line_mut(y);
        for c in &mut line.cells[x0..x1] {
            *c = Cell::blank(bg);
        }
        if x1 == cols {
            line.wrapped = false;
        }
        Self::fix_wide(line, bg);
    }
    pub fn erase_line(&mut self, mode: u16) {
        let (cx, cy, cols) = (self.cx, self.cy, self.cols);
        match mode {
            0 => self.erase_cells(cy, cx, cols),
            1 => self.erase_cells(cy, 0, cx + 1),
            _ => {
                self.erase_cells(cy, 0, cols);
            }
        }
        self.pending_wrap = false;
    }
    pub fn erase_display(&mut self, mode: u16) {
        let (cx, cy, cols, rows) = (self.cx, self.cy, self.cols, self.rows);
        match mode {
            0 => {
                self.erase_cells(cy, cx, cols);
                for y in cy + 1..rows {
                    self.erase_cells(y, 0, cols);
                }
            }
            1 => {
                for y in 0..cy {
                    self.erase_cells(y, 0, cols);
                }
                self.erase_cells(cy, 0, cx + 1);
            }
            2 => {
                for y in 0..rows {
                    self.erase_cells(y, 0, cols);
                }
            }
            3 => self.buf_mut().scrollback.clear(),
            _ => {}
        }
        self.pending_wrap = false;
    }
    pub fn erase_chars(&mut self, n: usize) {
        let (cx, cy) = (self.cx, self.cy);
        self.erase_cells(cy, cx, cx.saturating_add(n));
        self.pending_wrap = false;
    }
    pub fn insert_chars(&mut self, n: usize) {
        let (cx, cy, bg, cols) = (self.cx, self.cy, self.pen.bg, self.cols);
        let n = n.min(cols - cx);
        let line = self.line_mut(cy);
        for _ in 0..n {
            line.cells.pop();
            line.cells.insert(cx, Cell::blank(bg));
        }
        Self::fix_wide(line, bg);
        self.pending_wrap = false;
    }
    pub fn delete_chars(&mut self, n: usize) {
        let (cx, cy, bg, cols) = (self.cx, self.cy, self.pen.bg, self.cols);
        let n = n.min(cols - cx);
        let line = self.line_mut(cy);
        line.cells.drain(cx..cx + n);
        line.cells.extend((0..n).map(|_| Cell::blank(bg)));
        Self::fix_wide(line, bg);
        self.pending_wrap = false;
    }
    pub fn insert_lines(&mut self, n: usize) {
        if self.cy < self.top || self.cy > self.bottom {
            return;
        }
        let (cy, b) = (self.cy, self.bottom);
        self.scroll_down_in(cy, b, n);
        self.cx = 0;
        self.pending_wrap = false;
    }
    pub fn delete_lines(&mut self, n: usize) {
        if self.cy < self.top || self.cy > self.bottom {
            return;
        }
        let (cy, b) = (self.cy, self.bottom);
        self.scroll_up_in(cy, b, n, false);
        self.cx = 0;
        self.pending_wrap = false;
    }
    /// DECALN: fill the screen with 'E'.
    pub fn alignment_test(&mut self) {
        let pen = Pen::default();
        for y in 0..self.rows {
            for c in &mut self.line_mut(y).cells {
                *c = Cell::with_pen('E', 1, &pen);
            }
        }
        self.top = 0;
        self.bottom = self.rows - 1;
        self.cx = 0;
        self.cy = 0;
        self.pending_wrap = false;
    }

    // ---- save / restore, charsets, alt screen -----------------------------------------------

    pub fn save_cursor(&mut self) {
        let s = Saved {
            cx: self.cx,
            cy: self.cy,
            pen: self.pen,
            pending_wrap: self.pending_wrap,
            origin: self.modes.origin,
            charsets: self.charsets,
            gl: self.gl,
        };
        self.saved[self.alt_active as usize] = Some(s);
    }
    pub fn restore_cursor(&mut self) {
        match self.saved[self.alt_active as usize].clone() {
            Some(s) => {
                self.cx = s.cx.min(self.cols - 1);
                self.cy = s.cy.min(self.rows - 1);
                self.pen = s.pen;
                self.pending_wrap = s.pending_wrap;
                self.modes.origin = s.origin;
                self.charsets = s.charsets;
                self.gl = s.gl;
            }
            None => {
                self.cx = 0;
                self.cy = 0;
                self.pen = Pen::default();
                self.pending_wrap = false;
                self.modes.origin = false;
                self.charsets = [Charset::Ascii; 4];
                self.gl = 0;
            }
        }
    }

    pub fn enter_alt(&mut self, save: bool, clear: bool) {
        if self.alt_active {
            return;
        }
        if save {
            self.save_cursor();
        }
        self.alt_active = true;
        if clear {
            let saved_pen = self.pen;
            self.pen = Pen::default();
            self.erase_display(2);
            self.pen = saved_pen;
        }
        self.pending_wrap = false;
    }
    pub fn leave_alt(&mut self, restore: bool, clear: bool) {
        if !self.alt_active {
            return;
        }
        if clear {
            let saved_pen = self.pen;
            self.pen = Pen::default();
            self.erase_display(2);
            self.pen = saved_pen;
        }
        self.alt_active = false;
        if restore {
            self.restore_cursor();
        }
        self.pending_wrap = false;
    }

    // ---- hyperlinks -----------------------------------------------------------------------

    pub fn set_link(&mut self, id: &str, uri: &str) {
        if uri.is_empty() {
            self.pen.link = 0;
            return;
        }
        if let Some(i) = self.links.iter().position(|l| l.uri == uri && l.id == id) {
            self.pen.link = i as u32;
        } else {
            self.links.push(Link { id: id.to_string(), uri: uri.to_string() });
            self.pen.link = (self.links.len() - 1) as u32;
        }
    }

    // ---- resets -----------------------------------------------------------------------------

    /// DECSTR: soft terminal reset.
    pub fn soft_reset(&mut self) {
        self.modes = Modes { mouse: self.modes.mouse, mouse_enc: self.modes.mouse_enc, ..Modes::default() };
        self.pen = Pen::default();
        self.top = 0;
        self.bottom = self.rows - 1;
        self.charsets = [Charset::Ascii; 4];
        self.gl = 0;
        self.saved = [None, None];
        self.cursor_style = 0;
        self.pending_wrap = false;
    }
    /// RIS: full reset (keeps size, title and scrollback limit).
    pub fn hard_reset(&mut self) {
        let limit = self.scrollback_limit;
        *self = Screen::new(self.cols, self.rows);
        self.scrollback_limit = limit;
    }

    // ---- resize -----------------------------------------------------------------------------

    pub fn resize(&mut self, cols: usize, rows: usize) {
        let cols = cols.max(1);
        let rows = rows.max(1);
        if cols == self.cols && rows == self.rows {
            return;
        }
        let bg = Color::Default;
        // columns: truncate / pad
        for buf in [&mut self.main, &mut self.alt] {
            for l in buf.lines.iter_mut().chain(buf.scrollback.iter_mut()) {
                l.cells.resize(cols, Cell::blank(bg));
                Self::fix_wide(l, bg);
            }
        }
        // rows
        {
            let (old_rows, cy) = (self.rows, self.cy);
            let mut cy = cy;
            if !self.alt_active {
                let main = &mut self.main;
                while main.lines.len() > rows {
                    let last_blank = main.lines.last().map(|l| l.used_len() == 0).unwrap_or(false);
                    if last_blank && main.lines.len() - 1 > cy {
                        main.lines.pop();
                    } else {
                        let top = main.lines.remove(0);
                        main.scrollback.push_back(top);
                        cy = cy.saturating_sub(1);
                    }
                }
                while main.lines.len() < rows {
                    if let Some(l) = main.scrollback.pop_back() {
                        main.lines.insert(0, l);
                        cy += 1;
                    } else {
                        main.lines.push(Line::blank(cols, bg));
                    }
                }
                self.alt.lines.truncate(rows);
                while self.alt.lines.len() < rows {
                    self.alt.lines.push(Line::blank(cols, bg));
                }
            } else {
                let alt = &mut self.alt;
                alt.lines.truncate(rows);
                while alt.lines.len() < rows {
                    alt.lines.push(Line::blank(cols, bg));
                }
                self.main.lines.truncate(rows);
                while self.main.lines.len() < rows {
                    self.main.lines.push(Line::blank(cols, bg));
                }
            }
            let _ = old_rows;
            self.cy = cy;
        }
        let old_cols = self.cols;
        self.cols = cols;
        self.rows = rows;
        self.top = 0;
        self.bottom = rows - 1;
        self.cx = self.cx.min(cols - 1);
        self.cy = self.cy.min(rows - 1);
        self.pending_wrap = false;
        self.tabs.resize(cols, false);
        for x in old_cols.min(cols)..cols {
            self.tabs[x] = x % 8 == 0;
        }
        for s in self.saved.iter_mut().flatten() {
            s.cx = s.cx.min(cols - 1);
            s.cy = s.cy.min(rows - 1);
        }
    }
}
