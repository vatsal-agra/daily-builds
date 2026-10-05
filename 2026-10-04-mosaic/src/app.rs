//! High-level generation API shared by the CLI and the tests.

use crate::anim::Recorder;
use crate::overlap::{self, Overlap};
use crate::samples;
use crate::solver::{self, Config, Pins, SolveError, Solver, Stats};
use crate::tilesets;
use crate::verify;

#[derive(Clone, Debug)]
pub struct Common {
    pub w: usize,
    pub h: usize,
    pub seed: u64,
    pub periodic: bool,
    pub backtrack: bool,
    pub max_backtracks: usize,
    pub max_restarts: usize,
    pub pins: Vec<String>,
    /// 0 disables animation recording
    pub anim_frames: usize,
}

impl Common {
    pub fn new(w: usize, h: usize) -> Common {
        Common { w, h, seed: 1, periodic: false, backtrack: true, max_backtracks: 100, max_restarts: 40, pins: vec![], anim_frames: 0 }
    }
}

#[derive(Clone, Debug)]
pub struct OverlapOpts {
    pub common: Common,
    pub sample: String,
    pub n: usize,
    pub symmetry: usize,
    pub wrap_in: bool,
    pub ground: bool,
}

#[derive(Clone, Debug)]
pub struct TiledOpts {
    pub common: Common,
    pub set: String,
}

#[derive(Debug)]
pub struct Report {
    pub w: usize,
    pub h: usize,
    pub px: Vec<u32>,
    pub cells: Vec<usize>,
    pub grid: (usize, usize),
    pub stats: Stats,
    pub violations: usize,
    pub first_violation: Option<(usize, usize)>,
    pub frames: Vec<(usize, usize, Vec<u32>)>,
    pub ascii: Option<String>,
    pub patterns: usize,
}

const MAX_CELLS: usize = 250_000;
const MAX_STATE: usize = 12_000_000; // cells x patterns held in the wave
const MAX_PATTERNS: usize = 4_000;

fn check_state(cells: usize, t: usize) -> Result<(), String> {
    if cells * t > MAX_STATE {
        return Err(format!("{} cells x {} patterns is too much state (limit {}); use a smaller --size", cells, t, MAX_STATE));
    }
    Ok(())
}

fn check_size(w: usize, h: usize) -> Result<(), String> {
    if w == 0 || h == 0 {
        return Err("size must be at least 1x1".into());
    }
    if w * h > MAX_CELLS {
        return Err(format!("size {}x{} is too large (limit {} cells/pixels)", w, h, MAX_CELLS));
    }
    Ok(())
}

fn split_pin(s: &str) -> Result<(usize, usize, &str), String> {
    let mut it = s.splitn(3, ',');
    let (x, y, v) = (it.next(), it.next(), it.next());
    match (x, y, v) {
        (Some(x), Some(y), Some(v)) if !v.is_empty() => Ok((
            x.trim().parse().map_err(|_| format!("bad pin '{}': x must be a number", s))?,
            y.trim().parse().map_err(|_| format!("bad pin '{}': y must be a number", s))?,
            v,
        )),
        _ => Err(format!("bad pin '{}': expected x,y,value", s)),
    }
}

fn map_err(e: SolveError, overlap: bool) -> String {
    match e {
        SolveError::Unsatisfiable if overlap => "unsatisfiable: no arrangement of the sample's patterns can fill this grid with these pins/ground (try a smaller --n, --wrap-in, more --symmetry, another size, or fewer pins)".into(),
        SolveError::Unsatisfiable => "unsatisfiable: no arrangement of the tiles can fill this grid with these pins (pinned tiles that touch must have matching sockets)".into(),
        SolveError::Exhausted => "no solution found within the restart budget; try another --seed, a different size, or a higher --restarts/--max-backtracks".into(),
    }
}

fn config(c: &Common, gw: usize, gh: usize) -> Config {
    Config { w: gw, h: gh, periodic: c.periodic, backtrack: c.backtrack, max_backtracks: c.max_backtracks, max_restarts: c.max_restarts }
}

pub fn run_overlap(o: &OverlapOpts) -> Result<Report, String> {
    let c = &o.common;
    check_size(c.w, c.h)?;
    let img = samples::load(&o.sample)?;
    if o.symmetry == 0 || o.symmetry > 8 {
        return Err("--symmetry must be between 1 and 8".into());
    }
    let ov = Overlap::new(&img, o.n, o.symmetry, o.wrap_in)?;
    if ov.patterns.len() > MAX_PATTERNS {
        return Err(format!("sample yields {} unique patterns (limit {}); use a smaller/simpler sample or lower --n/--symmetry", ov.patterns.len(), MAX_PATTERNS));
    }
    if c.w < o.n || c.h < o.n {
        return Err(format!("output {}x{} is smaller than the pattern size {}", c.w, c.h, o.n));
    }
    let (gw, gh) = ov.grid_for(c.w, c.h, c.periodic);
    let mut pins: Pins = Vec::new();
    if o.ground {
        if c.periodic {
            return Err("--ground needs a non-periodic output".into());
        }
        pins.extend(ov.ground_pins(gw, gh)?);
    }
    for p in &c.pins {
        let (x, y, v) = split_pin(p)?;
        let color = if let Some(hex) = v.strip_prefix('#') {
            u32::from_str_radix(hex, 16).map_err(|_| format!("bad colour in pin '{}'", p))?
        } else {
            let mut it = v.chars();
            let ch = it.next().unwrap();
            if it.next().is_some() {
                return Err(format!("pin '{}': value must be one glyph or #rrggbb", p));
            }
            *img.chars.get(&ch).ok_or_else(|| format!("pin '{}': glyph '{}' is not in the sample (only ASCII samples have glyphs; use #rrggbb)", p, ch))?
        };
        pins.push(ov.pin_color(gw, gh, x, y, color)?);
    }
    // merge pins on the same cell (intersection)
    let pins = merge_pins(pins, ov.patterns.len());
    check_state(gw * gh, ov.patterns.len())?;
    let cfg = config(c, gw, gh);
    let mut rec = recorder(c, &ov.model, &cfg, &pins);
    let render_state = |s: &Solver| (c.w, c.h, ov.render(c.w, c.h, c.periodic, &|cell, p| s.allowed(cell, p)));
    let solved = solver::run(&ov.model, &cfg, &pins, c.seed, &mut |s| {
        if let Some(r) = rec.as_mut() {
            r.offer(|| render_state(s));
        }
    })
    .map_err(|e| map_err(e, true))?;
    let px = ov.render(c.w, c.h, c.periodic, &|cell, p| solved.cells[cell] == p);
    let (violations, first_violation) = verify::overlap_windows(&img, o.n, o.symmetry, o.wrap_in, &px, c.w, c.h, c.periodic);
    let mut frames = Vec::new();
    if let Some(mut r) = rec {
        r.finish((c.w, c.h, px.clone()));
        frames = r.frames;
    }
    Ok(Report {
        w: c.w,
        h: c.h,
        ascii: Some(overlap::to_ascii(&img.glyphs, c.w, &px)),
        px,
        cells: solved.cells,
        grid: (gw, gh),
        stats: solved.stats,
        violations,
        first_violation,
        frames,
        patterns: ov.patterns.len(),
    })
}

pub fn run_tiled(o: &TiledOpts) -> Result<Report, String> {
    let c = &o.common;
    check_size(c.w, c.h)?;
    let ts = tilesets::get(&o.set)?;
    let model = ts.model();
    let mut pins: Pins = Vec::new();
    for p in &c.pins {
        let (x, y, v) = split_pin(p)?;
        pins.push(ts.pin(c.w, c.h, x, y, v.trim())?);
    }
    let pins = merge_pins(pins, ts.tiles.len());
    check_state(c.w * c.h, ts.tiles.len())?;
    let cfg = config(c, c.w, c.h);
    let mut rec = recorder(c, &model, &cfg, &pins);
    let (pw, ph) = (c.w * ts.size, c.h * ts.size);
    let solved = solver::run(&model, &cfg, &pins, c.seed, &mut |s| {
        if let Some(r) = rec.as_mut() {
            r.offer(|| (pw, ph, ts.render(c.w, c.h, &|cell, p| s.allowed(cell, p))));
        }
    })
    .map_err(|e| map_err(e, false))?;
    let px = ts.render(c.w, c.h, &|cell, p| solved.cells[cell] == p);
    let (violations, first_violation) = verify::tiled_edges(&ts, &solved.cells, c.w, c.h, c.periodic);
    let mut frames = Vec::new();
    if let Some(mut r) = rec {
        r.finish((pw, ph, px.clone()));
        frames = r.frames;
    }
    Ok(Report { w: pw, h: ph, px, cells: solved.cells, grid: (c.w, c.h), stats: solved.stats, violations, first_violation, frames, ascii: None, patterns: ts.tiles.len() })
}

/// Animation recorder: the solve is deterministic per seed, so a dry run counts the observable
/// events and frames are then sampled evenly across them.
fn recorder(c: &Common, model: &solver::Model, cfg: &Config, pins: &Pins) -> Option<Recorder> {
    if c.anim_frames == 0 {
        return None;
    }
    let mut events = 0usize;
    let _ = solver::run(model, cfg, pins, c.seed, &mut |_| events += 1);
    Some(Recorder::new(events.div_ceil(c.anim_frames).max(1), c.anim_frames))
}

fn merge_pins(pins: Pins, _t: usize) -> Pins {
    let mut out: Pins = Vec::new();
    for (c, mask) in pins {
        if let Some(e) = out.iter_mut().find(|(oc, _)| *oc == c) {
            for (a, b) in e.1.iter_mut().zip(mask) {
                *a = *a && b;
            }
        } else {
            out.push((c, mask));
        }
    }
    out
}
