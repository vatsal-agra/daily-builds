//! Independent output validators — they do not use the solver's propagator tables.

use crate::overlap::variants;
use crate::samples::Image;
use crate::tiled::{sockets_match, TileSet};
use std::collections::HashSet;

/// Every NxN window of `out` must occur in the sample (under the chosen symmetries).
/// Returns the number of offending windows and the first bad window position.
pub fn overlap_windows(
    sample: &Image,
    n: usize,
    symmetry: usize,
    wrap_input: bool,
    out: &[u32],
    ow: usize,
    oh: usize,
    wrap_output: bool,
) -> (usize, Option<(usize, usize)>) {
    let get = |img_w: usize, img_h: usize, px: &[u32], x0: usize, y0: usize, wrap: bool| -> Option<Vec<u32>> {
        let mut v = Vec::with_capacity(n * n);
        for dy in 0..n {
            for dx in 0..n {
                let (x, y) = (x0 + dx, y0 + dy);
                if wrap {
                    v.push(px[(y % img_h) * img_w + x % img_w]);
                } else if x < img_w && y < img_h {
                    v.push(px[y * img_w + x]);
                } else {
                    return None;
                }
            }
        }
        Some(v)
    };
    let mut allowed: HashSet<Vec<u32>> = HashSet::new();
    let (sx, sy) = if wrap_input { (sample.w, sample.h) } else { (sample.w + 1 - n, sample.h + 1 - n) };
    for y in 0..sy {
        for x in 0..sx {
            if let Some(win) = get(sample.w, sample.h, &sample.px, x, y, wrap_input) {
                for v in variants(&win, n, symmetry) {
                    allowed.insert(v);
                }
            }
        }
    }
    let (ox, oy) = if wrap_output { (ow, oh) } else { (ow + 1 - n, oh + 1 - n) };
    let mut bad = 0;
    let mut first = None;
    for y in 0..oy {
        for x in 0..ox {
            let win = get(ow, oh, out, x, y, wrap_output).unwrap();
            if !allowed.contains(&win) {
                bad += 1;
                first.get_or_insert((x, y));
            }
        }
    }
    (bad, first)
}

/// Every pair of neighbouring tiles must have matching sockets. Returns (violations, first cell).
pub fn tiled_edges(ts: &TileSet, cells: &[usize], w: usize, h: usize, periodic: bool) -> (usize, Option<(usize, usize)>) {
    let mut bad = 0;
    let mut first = None;
    for y in 0..h {
        for x in 0..w {
            let a = &ts.tiles[cells[y * w + x]];
            // east neighbour: our socket 2 vs their 0; south neighbour: our 1 vs their 3
            for (dx, dy) in [(1usize, 0usize), (0, 1)] {
                let (nx, ny) = (x + dx, y + dy);
                let (nx, ny) = if periodic { (nx % w, ny % h) } else { (nx, ny) };
                if nx >= w || ny >= h {
                    continue;
                }
                let b = &ts.tiles[cells[ny * w + nx]];
                // for dy=1 the direction from a to b is south (1) and from b to a is north (3)
                let (ma, tb) = if dx == 1 { (2, 0) } else { (1, 3) };
                if !sockets_match(&a.sockets[ma], &b.sockets[tb]) {
                    bad += 1;
                    first.get_or_insert((x, y));
                }
            }
        }
    }
    (bad, first)
}
