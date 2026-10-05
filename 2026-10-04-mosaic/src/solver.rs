//! Model-agnostic Wave Function Collapse solver with trail-based backtracking.
//!
//! A *model* supplies `t` patterns, a weight per pattern and a directional propagator:
//! `prop[d][p]` lists every pattern allowed in the neighbouring cell lying in direction `d`
//! of a cell holding pattern `p`. Directions: 0 = west, 1 = south, 2 = east, 3 = north.
//! The tables must be symmetric: `q in prop[d][p]  <=>  p in prop[opp(d)][q]`.

use crate::rng::Rng;

pub const DX: [i32; 4] = [-1, 0, 1, 0];
pub const DY: [i32; 4] = [0, 1, 0, -1];
pub fn opp(d: usize) -> usize {
    (d + 2) % 4
}

#[derive(Clone)]
pub struct Model {
    pub weights: Vec<f64>,
    pub prop: [Vec<Vec<u32>>; 4],
}

impl Model {
    pub fn t(&self) -> usize {
        self.weights.len()
    }
}

#[derive(Clone, Debug)]
pub struct Config {
    pub w: usize,
    pub h: usize,
    pub periodic: bool,
    /// Use the trail/decision-stack to repair contradictions; otherwise restart from scratch.
    pub backtrack: bool,
    /// Maximum backtracks inside one attempt before giving up and restarting.
    pub max_backtracks: usize,
    /// Maximum fresh attempts.
    pub max_restarts: usize,
}

#[derive(Clone, Debug, Default)]
pub struct Stats {
    pub decisions: usize,
    pub backtracks: usize,
    pub restarts: usize,
    pub bans: usize,
}

#[derive(Debug, PartialEq)]
pub enum SolveError {
    /// Constraints (pins / model) are inconsistent before any decision was taken.
    Unsatisfiable,
    /// Ran out of restarts.
    Exhausted,
}

struct Decision {
    trail_len: usize,
    cell: u32,
    pat: u32,
}

pub struct Solver<'a> {
    m: &'a Model,
    pub w: usize,
    pub h: usize,
    periodic: bool,
    t: usize,
    wave: Vec<bool>,
    compat: Vec<[i32; 4]>,
    remaining: Vec<u32>,
    sum_w: Vec<f64>,
    sum_wlogw: Vec<f64>,
    trail: Vec<(u32, u32)>,
    decisions: Vec<Decision>,
    work: Vec<(u32, u32)>,
    contradiction: bool,
    pub stats: Stats,
}

impl<'a> Solver<'a> {
    /// Build a fresh solver. Prunes patterns that have no possible support in an
    /// existing neighbour direction. Returns Err(Unsatisfiable) if that empties a cell.
    pub fn new(m: &'a Model, w: usize, h: usize, periodic: bool) -> Result<Solver<'a>, SolveError> {
        let t = m.t();
        let n = w * h;
        let wl: Vec<f64> = m.weights.iter().map(|&x| x * x.ln()).collect();
        let tot_w: f64 = m.weights.iter().sum();
        let tot_wl: f64 = wl.iter().sum();
        let mut compat = Vec::with_capacity(n * t);
        for _ in 0..n {
            for q in 0..t {
                compat.push([
                    m.prop[0][q].len() as i32,
                    m.prop[1][q].len() as i32,
                    m.prop[2][q].len() as i32,
                    m.prop[3][q].len() as i32,
                ]);
            }
        }
        let mut s = Solver {
            m,
            w,
            h,
            periodic,
            t,
            wave: vec![true; n * t],
            compat,
            remaining: vec![t as u32; n],
            sum_w: vec![tot_w; n],
            sum_wlogw: vec![tot_wl; n],
            trail: Vec::new(),
            decisions: Vec::new(),
            work: Vec::new(),
            contradiction: false,
            stats: Stats::default(),
        };
        for c in 0..n {
            for q in 0..t {
                for e in 0..4 {
                    if s.neighbor(c, e).is_some() && s.m.prop[e][q].is_empty() {
                        s.work.push((c as u32, q as u32));
                        break;
                    }
                }
            }
        }
        s.propagate();
        if s.contradiction {
            return Err(SolveError::Unsatisfiable);
        }
        Ok(s)
    }

    pub fn neighbor(&self, c: usize, d: usize) -> Option<usize> {
        let (x, y) = ((c % self.w) as i32 + DX[d], (c / self.w) as i32 + DY[d]);
        let (w, h) = (self.w as i32, self.h as i32);
        if self.periodic {
            Some((y.rem_euclid(h) * w + x.rem_euclid(w)) as usize)
        } else if x < 0 || y < 0 || x >= w || y >= h {
            None
        } else {
            Some((y * w + x) as usize)
        }
    }

    pub fn allowed(&self, c: usize, p: usize) -> bool {
        self.wave[c * self.t + p]
    }
    pub fn remaining(&self, c: usize) -> usize {
        self.remaining[c] as usize
    }
    pub fn weight(&self, p: usize) -> f64 {
        self.m.weights[p]
    }
    pub fn t(&self) -> usize {
        self.t
    }

    fn ban(&mut self, c: usize, p: usize) {
        if !self.wave[c * self.t + p] {
            return;
        }
        self.wave[c * self.t + p] = false;
        self.remaining[c] -= 1;
        let wp = self.m.weights[p];
        self.sum_w[c] -= wp;
        self.sum_wlogw[c] -= wp * wp.ln();
        self.trail.push((c as u32, p as u32));
        self.stats.bans += 1;
        if self.remaining[c] == 0 {
            self.contradiction = true;
        }
        for d in 0..4 {
            if let Some(n) = self.neighbor(c, d) {
                let e = opp(d);
                for &q in &self.m.prop[d][p] {
                    let idx = n * self.t + q as usize;
                    self.compat[idx][e] -= 1;
                    if self.compat[idx][e] == 0 && self.wave[idx] {
                        self.work.push((n as u32, q));
                    }
                }
            }
        }
    }

    fn propagate(&mut self) {
        while let Some((c, p)) = self.work.pop() {
            if self.contradiction {
                self.work.clear();
                return;
            }
            self.ban(c as usize, p as usize);
        }
    }

    fn undo_to(&mut self, len: usize) {
        while self.trail.len() > len {
            let (c, p) = self.trail.pop().unwrap();
            let (c, p) = (c as usize, p as usize);
            self.wave[c * self.t + p] = true;
            self.remaining[c] += 1;
            let wp = self.m.weights[p];
            self.sum_w[c] += wp;
            self.sum_wlogw[c] += wp * wp.ln();
            for d in 0..4 {
                if let Some(n) = self.neighbor(c, d) {
                    let e = opp(d);
                    for &q in &self.m.prop[d][p] {
                        self.compat[n * self.t + q as usize][e] += 1;
                    }
                }
            }
        }
        self.contradiction = false;
        self.work.clear();
    }

    /// Restrict a cell to the allowed set (used for pins, at decision level 0).
    pub fn restrict(&mut self, c: usize, keep: &[bool]) -> Result<(), SolveError> {
        for p in 0..self.t {
            if !keep[p] {
                self.ban(c, p);
            }
        }
        self.propagate();
        if self.contradiction {
            Err(SolveError::Unsatisfiable)
        } else {
            Ok(())
        }
    }

    fn entropy(&self, c: usize) -> f64 {
        self.sum_w[c].ln() - self.sum_wlogw[c] / self.sum_w[c]
    }

    /// Lowest-entropy undecided cell (with tiny noise to break ties), or None if all collapsed.
    fn pick_cell(&self, rng: &mut Rng) -> Option<usize> {
        let mut best = None;
        let mut best_e = f64::INFINITY;
        for c in 0..self.w * self.h {
            if self.remaining[c] > 1 {
                let e = self.entropy(c) + rng.f64() * 1e-6;
                if e < best_e {
                    best_e = e;
                    best = Some(c);
                }
            }
        }
        best
    }

    fn pick_pattern(&self, c: usize, rng: &mut Rng) -> usize {
        let mut r = rng.f64() * self.sum_w[c];
        let mut last = 0;
        for p in 0..self.t {
            if self.wave[c * self.t + p] {
                last = p;
                r -= self.m.weights[p];
                if r <= 0.0 {
                    return p;
                }
            }
        }
        last
    }

    /// One attempt. `obs` is called after every state change worth drawing.
    fn attempt(&mut self, rng: &mut Rng, cfg: &Config, obs: &mut dyn FnMut(&Solver)) -> bool {
        let mut local_backtracks = 0usize;
        loop {
            let Some(c) = self.pick_cell(rng) else { return true };
            let p = self.pick_pattern(c, rng);
            self.stats.decisions += 1;
            self.decisions.push(Decision { trail_len: self.trail.len(), cell: c as u32, pat: p as u32 });
            for q in 0..self.t {
                if q != p {
                    self.ban(c, q);
                }
            }
            self.propagate();
            obs(self);
            while self.contradiction {
                if !cfg.backtrack || local_backtracks >= cfg.max_backtracks {
                    return false;
                }
                let Some(d) = self.decisions.pop() else { return false };
                self.undo_to(d.trail_len);
                self.stats.backtracks += 1;
                local_backtracks += 1;
                // The failed choice is now forbidden at the parent level.
                self.ban(d.cell as usize, d.pat as usize);
                self.propagate();
                obs(self);
            }
        }
    }

    /// Final pattern per cell (valid once solved).
    pub fn result(&self) -> Vec<usize> {
        (0..self.w * self.h)
            .map(|c| (0..self.t).find(|&p| self.wave[c * self.t + p]).unwrap_or(0))
            .collect()
    }
}

pub struct Solved {
    pub cells: Vec<usize>,
    pub stats: Stats,
}

/// Pins: (cell, allowed-pattern mask).
pub type Pins = Vec<(usize, Vec<bool>)>;

/// Solve with restarts. Deterministic for a given seed.
pub fn run(
    m: &Model,
    cfg: &Config,
    pins: &Pins,
    seed: u64,
    obs: &mut dyn FnMut(&Solver),
) -> Result<Solved, SolveError> {
    let mut rng = Rng::new(seed);
    let mut total = Stats::default();
    for attempt in 0..cfg.max_restarts.max(1) {
        let mut s = Solver::new(m, cfg.w, cfg.h, cfg.periodic)?;
        for (c, mask) in pins {
            s.restrict(*c, mask)?;
        }
        obs(&s);
        let ok = s.attempt(&mut rng, cfg, obs);
        total.decisions += s.stats.decisions;
        total.backtracks += s.stats.backtracks;
        total.bans += s.stats.bans;
        total.restarts = attempt;
        if ok {
            return Ok(Solved { cells: s.result(), stats: total });
        }
    }
    Err(SolveError::Exhausted)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Two patterns that must alternate in every direction (checkerboard).
    fn checker() -> Model {
        let other = vec![vec![1u32], vec![0u32]];
        Model { weights: vec![1.0, 1.0], prop: [other.clone(), other.clone(), other.clone(), other] }
    }

    #[test]
    fn checkerboard_even_torus_solves_and_alternates() {
        let m = checker();
        let cfg = Config { w: 6, h: 4, periodic: true, backtrack: true, max_backtracks: 100, max_restarts: 5 };
        let r = run(&m, &cfg, &vec![], 7, &mut |_| {}).unwrap();
        for y in 0..4 {
            for x in 0..6 {
                assert_ne!(r.cells[y * 6 + x], r.cells[y * 6 + (x + 1) % 6]);
                assert_ne!(r.cells[y * 6 + x], r.cells[((y + 1) % 4) * 6 + x]);
            }
        }
    }

    #[test]
    fn checkerboard_odd_torus_is_impossible() {
        let m = checker();
        let cfg = Config { w: 3, h: 3, periodic: true, backtrack: true, max_backtracks: 100, max_restarts: 3 };
        assert_eq!(run(&m, &cfg, &vec![], 1, &mut |_| {}).err(), Some(SolveError::Exhausted));
    }

    #[test]
    fn pins_that_conflict_are_unsatisfiable() {
        let m = checker();
        let cfg = Config { w: 2, h: 1, periodic: false, backtrack: true, max_backtracks: 10, max_restarts: 2 };
        let pins: Pins = vec![(0, vec![true, false]), (1, vec![true, false])];
        assert_eq!(run(&m, &cfg, &pins, 1, &mut |_| {}).err(), Some(SolveError::Unsatisfiable));
    }

    /// Decide, propagate, then undo: every piece of bookkeeping must return exactly to its start.
    #[test]
    fn undo_restores_state_exactly() {
        let img = crate::samples::load("dungeon").unwrap();
        let ov = crate::overlap::Overlap::new(&img, 3, 1, false).unwrap();
        let mut s = Solver::new(&ov.model, 12, 12, false).unwrap();
        let (wave, compat, rem) = (s.wave.clone(), s.compat.clone(), s.remaining.clone());
        let (sw, swl) = (s.sum_w.clone(), s.sum_wlogw.clone());
        let base = s.trail.len();
        let mut rng = Rng::new(3);
        for _ in 0..5 {
            let before = s.trail.len();
            let c = s.pick_cell(&mut rng).unwrap();
            let p = s.pick_pattern(c, &mut rng);
            for q in 0..s.t {
                if q != p {
                    s.ban(c, q);
                }
            }
            s.propagate();
            assert!(s.trail.len() > before);
        }
        s.undo_to(base);
        assert_eq!(s.wave, wave);
        assert_eq!(s.compat, compat);
        assert_eq!(s.remaining, rem);
        for c in 0..144 {
            assert!((s.sum_w[c] - sw[c]).abs() < 1e-9 && (s.sum_wlogw[c] - swl[c]).abs() < 1e-9);
        }
    }

    #[test]
    fn collapsed_wave_has_one_pattern_per_cell() {
        let img = crate::samples::load("flowers").unwrap();
        let ov = crate::overlap::Overlap::new(&img, 3, 1, false).unwrap();
        let cfg = Config { w: 20, h: 20, periodic: false, backtrack: true, max_backtracks: 100, max_restarts: 10 };
        let mut last = None;
        run(&ov.model, &cfg, &vec![], 2, &mut |s| last = Some((0..400).all(|c| s.remaining(c) >= 1))).unwrap();
        assert_eq!(last, Some(true));
    }
}
