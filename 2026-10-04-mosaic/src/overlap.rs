//! Overlapping model: patterns are all NxN windows (plus symmetries) of a sample image.

use crate::samples::Image;
use crate::solver::{Model, Pins, DX, DY};
use std::collections::HashMap;

pub struct Overlap {
    pub n: usize,
    pub patterns: Vec<Vec<u32>>,
    pub model: Model,
    /// pattern index of the sample's bottom-left window (for `ground`)
    pub ground: Option<usize>,
}

fn rotate(p: &[u32], n: usize) -> Vec<u32> {
    let mut o = vec![0; n * n];
    for y in 0..n {
        for x in 0..n {
            o[y * n + x] = p[(n - 1 - x) * n + y];
        }
    }
    o
}
fn reflect(p: &[u32], n: usize) -> Vec<u32> {
    let mut o = vec![0; n * n];
    for y in 0..n {
        for x in 0..n {
            o[y * n + x] = p[y * n + (n - 1 - x)];
        }
    }
    o
}

/// All `symmetry` (1..=8) variants of a pattern: rotations 0..3, then mirrored rotations.
pub fn variants(p: &[u32], n: usize, symmetry: usize) -> Vec<Vec<u32>> {
    let mut v = Vec::new();
    let mut cur = p.to_vec();
    let mut rots = vec![cur.clone()];
    for _ in 0..3 {
        cur = rotate(&cur, n);
        rots.push(cur.clone());
    }
    for k in 0..symmetry.clamp(1, 8) {
        if k < 4 {
            v.push(rots[k].clone());
        } else {
            v.push(reflect(&rots[k - 4], n));
        }
    }
    v
}

fn window(img: &Image, x0: usize, y0: usize, n: usize, wrap: bool) -> Option<Vec<u32>> {
    let mut o = Vec::with_capacity(n * n);
    for dy in 0..n {
        for dx in 0..n {
            let (mut x, mut y) = (x0 + dx, y0 + dy);
            if wrap {
                x %= img.w;
                y %= img.h;
            } else if x >= img.w || y >= img.h {
                return None;
            }
            o.push(img.px[y * img.w + x]);
        }
    }
    Some(o)
}

fn agree(a: &[u32], b: &[u32], n: usize, dx: i32, dy: i32) -> bool {
    let n = n as i32;
    for y in 0.max(dy)..n.min(n + dy) {
        for x in 0.max(dx)..n.min(n + dx) {
            if a[(y * n + x) as usize] != b[((y - dy) * n + (x - dx)) as usize] {
                return false;
            }
        }
    }
    true
}

impl Overlap {
    pub fn new(img: &Image, n: usize, symmetry: usize, wrap_input: bool) -> Result<Overlap, String> {
        if n < 2 {
            return Err("pattern size N must be at least 2".into());
        }
        if !wrap_input && (n > img.w || n > img.h) {
            return Err(format!("pattern size {} larger than sample {}x{} (use --wrap-in or smaller --n)", n, img.w, img.h));
        }
        let mut index: HashMap<Vec<u32>, usize> = HashMap::new();
        let mut patterns: Vec<Vec<u32>> = Vec::new();
        let mut counts: Vec<f64> = Vec::new();
        let (xmax, ymax) = if wrap_input { (img.w, img.h) } else { (img.w - n + 1, img.h - n + 1) };
        for y in 0..ymax {
            for x in 0..xmax {
                let base = window(img, x, y, n, wrap_input).unwrap();
                for v in variants(&base, n, symmetry) {
                    let id = *index.entry(v.clone()).or_insert_with(|| {
                        patterns.push(v);
                        counts.push(0.0);
                        patterns.len() - 1
                    });
                    counts[id] += 1.0;
                }
            }
        }
        // bottom-left window of the sample, used by the `ground` option
        let ground = window(img, 0, img.h - n, n, wrap_input).and_then(|w| index.get(&w).copied());
        let t = patterns.len();
        let mut prop: [Vec<Vec<u32>>; 4] = [vec![vec![]; t], vec![vec![]; t], vec![vec![]; t], vec![vec![]; t]];
        for d in 0..4 {
            for a in 0..t {
                for b in 0..t {
                    if agree(&patterns[a], &patterns[b], n, DX[d], DY[d]) {
                        prop[d][a].push(b as u32);
                    }
                }
            }
        }
        Ok(Overlap { n, patterns, model: Model { weights: counts, prop }, ground })
    }

    /// Dimensions of the pattern grid for a requested pixel size.
    pub fn grid_for(&self, out_w: usize, out_h: usize, periodic: bool) -> (usize, usize) {
        if periodic {
            (out_w, out_h)
        } else {
            (out_w + 1 - self.n, out_h + 1 - self.n)
        }
    }

    /// Pins for the ground option: bottom row is the ground pattern, nowhere else.
    pub fn ground_pins(&self, gw: usize, gh: usize) -> Result<Pins, String> {
        let g = self.ground.ok_or("sample has no bottom-left window to use as ground")?;
        let t = self.patterns.len();
        let mut pins = Vec::new();
        for y in 0..gh {
            for x in 0..gw {
                let mask: Vec<bool> = (0..t).map(|p| (p == g) == (y == gh - 1)).collect();
                pins.push((y * gw + x, mask));
            }
        }
        Ok(pins)
    }

    /// Pin the pattern cell (x,y) so that its top-left pixel has `color`.
    pub fn pin_color(&self, gw: usize, gh: usize, x: usize, y: usize, color: u32) -> Result<(usize, Vec<bool>), String> {
        if x >= gw || y >= gh {
            return Err(format!("pin ({},{}) is outside the {}x{} cell grid", x, y, gw, gh));
        }
        let mask: Vec<bool> = self.patterns.iter().map(|p| p[0] == color).collect();
        if !mask.iter().any(|&b| b) {
            return Err(format!("no pattern has top-left colour #{:06x}; pin impossible", color));
        }
        Ok((y * gw + x, mask))
    }

    /// Render pixels. `allowed(cell, p)` tells which patterns are still possible; fully collapsed
    /// cells reproduce exact pixels, partial ones show the average colour of what is still possible.
    pub fn render(&self, out_w: usize, out_h: usize, periodic: bool, allowed: &dyn Fn(usize, usize) -> bool) -> Vec<u32> {
        let (gw, gh) = self.grid_for(out_w, out_h, periodic);
        let n = self.n;
        let t = self.patterns.len();
        // per-cell list of allowed patterns, computed once
        let lists: Vec<Vec<usize>> = (0..gw * gh).map(|c| (0..t).filter(|&p| allowed(c, p)).collect()).collect();
        let mut out = vec![0u32; out_w * out_h];
        for y in 0..out_h {
            for x in 0..out_w {
                let (mut r, mut g, mut b, mut k) = (0u64, 0u64, 0u64, 0u64);
                for dy in 0..n {
                    for dx in 0..n {
                        let (cx, cy) = if periodic {
                            ((x + out_w - dx) % out_w, (y + out_h - dy) % out_h)
                        } else {
                            if x < dx || y < dy {
                                continue;
                            }
                            (x - dx, y - dy)
                        };
                        if cx >= gw || cy >= gh {
                            continue;
                        }
                        for &p in &lists[cy * gw + cx] {
                            let col = self.patterns[p][dy * n + dx];
                            r += (col >> 16 & 255) as u64;
                            g += (col >> 8 & 255) as u64;
                            b += (col & 255) as u64;
                            k += 1;
                        }
                    }
                }
                out[y * out_w + x] = if k == 0 { 0xFF00FF } else { ((r / k) as u32) << 16 | ((g / k) as u32) << 8 | (b / k) as u32 };
            }
        }
        out
    }
}

pub fn to_ascii(img_glyphs: &HashMap<u32, char>, w: usize, px: &[u32]) -> String {
    let mut s = String::new();
    for row in px.chunks(w) {
        for c in row {
            s.push(*img_glyphs.get(c).unwrap_or(&'#'));
        }
        s.push('\n');
    }
    s
}
