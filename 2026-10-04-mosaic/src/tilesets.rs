//! Procedurally drawn tilesets (no image assets needed).

use crate::tiled::{expand, Tile, TileSet};

pub fn names() -> Vec<(&'static str, &'static str)> {
    vec![
        ("circuit", "PCB traces: wires, corners, tees, crossings, bridges and pads (7px tiles, rotations)"),
        ("terrain", "81 Wang tiles over 3 corner levels (water/sand/grass) with smooth coastlines (10px tiles)"),
    ]
}

pub fn get(name: &str) -> Result<TileSet, String> {
    match name {
        "circuit" => Ok(circuit()),
        "terrain" => Ok(terrain()),
        _ => Err(format!("unknown tileset '{}' (available: circuit, terrain)", name)),
    }
}

// ---------------------------------------------------------------- circuit

const S: usize = 7;
const BOARD: u32 = 0x0b3d2e;
const TRACE: u32 = 0xd4a017;
const HIGH: u32 = 0xf2f2f2;
const BRIDGE: u32 = 0xe0703a;

/// Draw arms from the centre towards each open side (W,S,E,N).
fn draw(open: [bool; 4], color: u32, px: &mut Vec<u32>) {
    let c = S / 2;
    px[c * S + c] = color;
    for k in 0..=c {
        if open[0] {
            px[c * S + k] = color;
        }
        if open[2] {
            px[c * S + (S - 1 - k)] = color;
        }
        if open[3] {
            px[k * S + c] = color;
        }
        if open[1] {
            px[(S - 1 - k) * S + c] = color;
        }
    }
}

fn circuit() -> TileSet {
    let n = || "n".to_string();
    let w = || "w".to_string();
    let mut tiles = Vec::new();
    let mut add = |name: &str, px: Vec<u32>, sockets: [String; 4], rot: usize, weight: f64| {
        let base = Tile { name: name.to_string(), px, sockets, weight };
        tiles.extend(expand(&base, S, rot));
    };
    let blank = || vec![BOARD; S * S];

    add("empty", blank(), [n(), n(), n(), n()], 1, 7.0);

    let mut p = blank();
    draw([false, true, false, true], TRACE, &mut p);
    add("line", p, [n(), w(), n(), w()], 2, 5.0);

    let mut p = blank();
    draw([false, false, true, true], TRACE, &mut p);
    add("corner", p, [n(), n(), w(), w()], 4, 3.0);

    let mut p = blank();
    draw([true, false, true, true], TRACE, &mut p);
    add("tee", p, [w(), n(), w(), w()], 4, 1.0);

    let mut p = blank();
    draw([true, true, true, true], TRACE, &mut p);
    add("cross", p, [w(), w(), w(), w()], 1, 0.3);

    // dead-end with a pad
    let mut p = blank();
    draw([false, false, false, true], TRACE, &mut p);
    for (x, y) in [(2, 2), (3, 2), (4, 2), (2, 3), (4, 3), (2, 4), (3, 4), (4, 4)] {
        p[y * S + x] = TRACE;
    }
    p[3 * S + 3] = HIGH;
    add("pad", p, [n(), n(), n(), w()], 4, 1.0);

    // bridge: vertical trace hops over horizontal trace, no connection
    let mut p = blank();
    draw([true, false, true, false], TRACE, &mut p);
    draw([false, true, false, true], BRIDGE, &mut p);
    p[3 * S + 3] = BRIDGE;
    add("bridge", p, [w(), w(), w(), w()], 2, 0.5);

    TileSet { name: "circuit", size: S, tiles }
}

// ---------------------------------------------------------------- terrain

const TS: usize = 10;

fn hash2(a: u32, b: u32) -> u32 {
    let mut h = a.wrapping_mul(0x9E37_79B1) ^ b.wrapping_mul(0x85EB_CA6B);
    h ^= h >> 13;
    h = h.wrapping_mul(0xC2B2_AE35);
    h ^ (h >> 16)
}

fn terrain() -> TileSet {
    // corners: nw, ne, se, sw; each 0 = water, 1 = sand, 2 = grass
    let mut tiles = Vec::new();
    for code in 0..81u32 {
        let nw = code % 3;
        let ne = (code / 3) % 3;
        let se = (code / 9) % 3;
        let sw = (code / 27) % 3;
        let c = [nw, ne, se, sw];
        let mut px = vec![0u32; TS * TS];
        for y in 0..TS {
            for x in 0..TS {
                let fx = (x as f64 + 0.5) / TS as f64;
                let fy = (y as f64 + 0.5) / TS as f64;
                let top = nw as f64 * (1.0 - fx) + ne as f64 * fx;
                let bot = sw as f64 * (1.0 - fx) + se as f64 * fx;
                let mut v = top * (1.0 - fy) + bot * fy;
                let h = hash2(code * 131 + 7, (y * TS + x) as u32);
                v += ((h & 0xFF) as f64 / 255.0 - 0.5) * 0.12;
                let col = if v < 0.4 {
                    0x1f5f9c
                } else if v < 0.8 {
                    0x3b82c4
                } else if v < 1.35 {
                    0xe6d49a
                } else if v < 1.5 {
                    0x9bbf4a
                } else {
                    // grass with the occasional tree
                    if v > 1.9 && (h >> 8) % 23 == 0 {
                        0x1d5c27
                    } else if (h >> 8) % 5 == 0 {
                        0x4f9a3a
                    } else {
                        0x5aa845
                    }
                };
                px[y * TS + x] = col;
            }
        }
        let sk = |a: u32, b: u32| format!("{}{}", a, b);
        // W (top->bottom): nw,sw   S (left->right): sw,se   E (top->bottom): ne,se   N (left->right): nw,ne
        let sockets = [sk(nw, sw), sk(sw, se), sk(ne, se), sk(nw, ne)];
        let ring = [(c[0], c[1]), (c[1], c[2]), (c[2], c[3]), (c[3], c[0])];
        let rough: f64 = ring.iter().map(|&(a, b)| ((a as f64) - (b as f64)).powi(2)).sum();
        let weight = 6.0 * (-0.8 * rough).exp();
        tiles.push(Tile { name: format!("t{}{}{}{}", nw, ne, se, sw), px, sockets, weight });
    }
    TileSet { name: "terrain", size: TS, tiles }
}
