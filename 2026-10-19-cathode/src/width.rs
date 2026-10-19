//! Display width of a code point in terminal cells (0, 1 or 2), wcwidth-style.
use crate::width_table::{WIDE, ZERO};

fn in_table(t: &[(u32, u32)], c: u32) -> bool {
    t.binary_search_by(|&(lo, hi)| {
        if c < lo {
            std::cmp::Ordering::Greater
        } else if c > hi {
            std::cmp::Ordering::Less
        } else {
            std::cmp::Ordering::Equal
        }
    })
    .is_ok()
}

/// Width of `c` in cells. Control characters report 0 (callers handle them before printing).
pub fn char_width(c: char) -> usize {
    let u = c as u32;
    if u < 0x20 || (0x7F..0xA0).contains(&u) {
        return 0;
    }
    if u < 0x300 {
        return 1;
    }
    if in_table(&ZERO, u) {
        0
    } else if in_table(&WIDE, u) {
        2
    } else {
        1
    }
}

pub fn str_width(s: &str) -> usize {
    s.chars().map(char_width).sum()
}
