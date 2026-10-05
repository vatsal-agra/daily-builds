//! Simple tiled model: tiles carry one socket label per side; neighbours must have
//! compatible sockets on the shared edge. Rotations are expanded automatically.
//!
//! Socket order matches solver directions: 0 = west, 1 = south, 2 = east, 3 = north.
//! Sockets are read clockwise around the tile, so an asymmetric socket pair is written
//! `name+` / `name-`; everything else must match exactly.

use crate::solver::{opp, Model};

#[derive(Clone, Debug)]
pub struct Tile {
    pub name: String,
    pub px: Vec<u32>,
    pub sockets: [String; 4],
    pub weight: f64,
}

#[derive(Clone)]
pub struct TileSet {
    pub name: &'static str,
    pub size: usize,
    pub tiles: Vec<Tile>,
}

pub fn sockets_match(a: &str, b: &str) -> bool {
    if let (Some(sa), Some(sb)) = (a.strip_suffix('+'), b.strip_suffix('-')) {
        return sa == sb;
    }
    if let (Some(sa), Some(sb)) = (a.strip_suffix('-'), b.strip_suffix('+')) {
        return sa == sb;
    }
    a == b && !a.ends_with('+') && !a.ends_with('-')
}

pub fn rotate_px(px: &[u32], s: usize) -> Vec<u32> {
    let mut o = vec![0; s * s];
    for y in 0..s {
        for x in 0..s {
            o[y * s + x] = px[(s - 1 - x) * s + y]; // 90 degrees clockwise
        }
    }
    o
}

/// Expand a base tile into `rot` (1, 2 or 4) distinct rotations named `name_r0..`.
pub fn expand(base: &Tile, size: usize, rot: usize) -> Vec<Tile> {
    let mut out: Vec<Tile> = Vec::new();
    let mut cur = base.clone();
    for r in 0..rot {
        cur.name = format!("{}_r{}", base.name, r);
        out.push(cur.clone());
        let px = rotate_px(&cur.px, size);
        // clockwise rotation: old north -> east, old east -> south, ... so new[d] = old[(d+1)%4]
        let s = [cur.sockets[1].clone(), cur.sockets[2].clone(), cur.sockets[3].clone(), cur.sockets[0].clone()];
        cur = Tile { name: String::new(), px, sockets: s, weight: base.weight };
    }
    out
}

impl TileSet {
    pub fn model(&self) -> Model {
        let t = self.tiles.len();
        let mut prop: [Vec<Vec<u32>>; 4] = [vec![vec![]; t], vec![vec![]; t], vec![vec![]; t], vec![vec![]; t]];
        for d in 0..4 {
            for a in 0..t {
                for b in 0..t {
                    if sockets_match(&self.tiles[a].sockets[d], &self.tiles[b].sockets[opp(d)]) {
                        prop[d][a].push(b as u32);
                    }
                }
            }
        }
        Model { weights: self.tiles.iter().map(|t| t.weight).collect(), prop }
    }

    /// Tiles whose name is `name` or a rotation variant `name_rK`.
    pub fn find(&self, name: &str) -> Vec<usize> {
        self.tiles
            .iter()
            .enumerate()
            .filter(|(_, t)| {
                t.name == name || t.name.rsplit_once("_r").map_or(false, |(b, k)| b == name && !k.is_empty() && k.chars().all(|c| c.is_ascii_digit()))
            })
            .map(|(i, _)| i)
            .collect()
    }

    pub fn pin(&self, gw: usize, gh: usize, x: usize, y: usize, name: &str) -> Result<(usize, Vec<bool>), String> {
        if x >= gw || y >= gh {
            return Err(format!("pin ({},{}) is outside the {}x{} grid", x, y, gw, gh));
        }
        let ids = self.find(name);
        if ids.is_empty() {
            return Err(format!("tileset '{}' has no tile named '{}' (see `mosaic list`)", self.name, name));
        }
        let mut mask = vec![false; self.tiles.len()];
        for i in ids {
            mask[i] = true;
        }
        Ok((y * gw + x, mask))
    }

    pub fn render(&self, gw: usize, gh: usize, allowed: &dyn Fn(usize, usize) -> bool) -> Vec<u32> {
        let s = self.size;
        let mut out = vec![0u32; gw * s * gh * s];
        for cy in 0..gh {
            for cx in 0..gw {
                let c = cy * gw + cx;
                let ids: Vec<usize> = (0..self.tiles.len()).filter(|&p| allowed(c, p)).collect();
                for y in 0..s {
                    for x in 0..s {
                        let col = if ids.is_empty() {
                            0xFF00FF
                        } else {
                            let (mut r, mut g, mut b) = (0u32, 0u32, 0u32);
                            for &p in &ids {
                                let v = self.tiles[p].px[y * s + x];
                                r += v >> 16 & 255;
                                g += v >> 8 & 255;
                                b += v & 255;
                            }
                            let k = ids.len() as u32;
                            (r / k) << 16 | (g / k) << 8 | b / k
                        };
                        out[(cy * s + y) * gw * s + cx * s + x] = col;
                    }
                }
            }
        }
        out
    }
}
