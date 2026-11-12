//! A reduced ordered BDD manager.
//!
//! * Nodes are hash-consed in a unique table, so equal functions are the same `Bdd` index.
//! * Variables (`u32` ids) are decoupled from *levels* (positions in the order), which is what
//!   makes dynamic reordering possible: nodes store the variable id, comparisons go through `level`.
//! * Reordering swaps adjacent levels **in place**, so every `Bdd` handle held by a caller stays valid.
//! * Garbage collection is explicit mark-and-sweep from a pin stack plus caller-supplied roots.

use std::collections::HashMap;

pub type Bdd = u32;
pub const FALSE: Bdd = 0;
pub const TRUE: Bdd = 1;

const TERM: u32 = u32::MAX;
const DEAD: u32 = u32::MAX - 1;

#[derive(Clone, Copy, Debug)]
struct Node {
    var: u32,
    lo: Bdd,
    hi: Bdd,
}

const OP_AND: u8 = 0;
const OP_OR: u8 = 1;
const OP_NOT: u8 = 2;
const OP_ITE: u8 = 3;
const OP_EX: u8 = 4;
const OP_AE: u8 = 5;

pub struct Manager {
    nodes: Vec<Node>,
    unique: HashMap<(u32, Bdd, Bdd), Bdd>,
    free: Vec<Bdd>,
    level: Vec<u32>,
    at_level: Vec<u32>,
    cache: HashMap<(u8, Bdd, Bdd, Bdd), Bdd>,
    pins: Vec<Bdd>,
    gc_threshold: usize,
    /// When set, `maybe_gc` collects every time it is called (used to flush out missing roots in tests).
    pub gc_stress: bool,
    pub gc_runs: usize,
    pub swaps: usize,
}

impl Default for Manager {
    fn default() -> Self {
        Self::new()
    }
}

impl Manager {
    pub fn new() -> Manager {
        let t = Node { var: TERM, lo: FALSE, hi: FALSE };
        Manager {
            nodes: vec![t, t],
            unique: HashMap::new(),
            free: Vec::new(),
            level: Vec::new(),
            at_level: Vec::new(),
            cache: HashMap::new(),
            pins: Vec::new(),
            gc_threshold: 400_000,
            gc_stress: false,
            gc_runs: 0,
            swaps: 0,
        }
    }

    // ---------------------------------------------------------------- variables

    /// Create a fresh variable at the bottom of the order.
    pub fn new_var(&mut self) -> u32 {
        let v = self.level.len() as u32;
        self.level.push(v);
        self.at_level.push(v);
        v
    }

    pub fn num_vars(&self) -> usize {
        self.level.len()
    }

    pub fn level_of(&self, var: u32) -> u32 {
        self.level[var as usize]
    }

    pub fn var_at_level(&self, level: usize) -> u32 {
        self.at_level[level]
    }

    /// Variables in current order, top to bottom.
    pub fn order(&self) -> Vec<u32> {
        self.at_level.clone()
    }

    pub fn var(&mut self, v: u32) -> Bdd {
        self.mk(v, FALSE, TRUE)
    }

    pub fn nvar(&mut self, v: u32) -> Bdd {
        self.mk(v, TRUE, FALSE)
    }

    // ---------------------------------------------------------------- node access

    #[inline]
    fn lvl(&self, f: Bdd) -> u32 {
        if f < 2 {
            TERM
        } else {
            self.level[self.nodes[f as usize].var as usize]
        }
    }

    #[inline]
    pub fn top_var(&self, f: Bdd) -> Option<u32> {
        if f < 2 {
            None
        } else {
            Some(self.nodes[f as usize].var)
        }
    }

    #[inline]
    pub fn low(&self, f: Bdd) -> Bdd {
        self.nodes[f as usize].lo
    }

    #[inline]
    pub fn high(&self, f: Bdd) -> Bdd {
        self.nodes[f as usize].hi
    }

    fn mk(&mut self, var: u32, lo: Bdd, hi: Bdd) -> Bdd {
        if lo == hi {
            return lo;
        }
        debug_assert!(self.lvl(lo) > self.level[var as usize] && self.lvl(hi) > self.level[var as usize]);
        if let Some(&n) = self.unique.get(&(var, lo, hi)) {
            return n;
        }
        let node = Node { var, lo, hi };
        let idx = if let Some(i) = self.free.pop() {
            self.nodes[i as usize] = node;
            i
        } else {
            self.nodes.push(node);
            (self.nodes.len() - 1) as u32
        };
        self.unique.insert((var, lo, hi), idx);
        idx
    }

    /// Cofactors of `f` with respect to the variable at level `lv`.
    #[inline]
    fn cof(&self, f: Bdd, lv: u32) -> (Bdd, Bdd) {
        if self.lvl(f) == lv {
            let n = self.nodes[f as usize];
            (n.lo, n.hi)
        } else {
            (f, f)
        }
    }

    // ---------------------------------------------------------------- boolean operations

    pub fn not(&mut self, f: Bdd) -> Bdd {
        if f < 2 {
            return 1 - f;
        }
        if let Some(&r) = self.cache.get(&(OP_NOT, f, 0, 0)) {
            return r;
        }
        let n = self.nodes[f as usize];
        let lo = self.not(n.lo);
        let hi = self.not(n.hi);
        let r = self.mk(n.var, lo, hi);
        self.cache.insert((OP_NOT, f, 0, 0), r);
        r
    }

    pub fn and(&mut self, f: Bdd, g: Bdd) -> Bdd {
        if f == FALSE || g == FALSE {
            return FALSE;
        }
        if f == TRUE || f == g {
            return g;
        }
        if g == TRUE {
            return f;
        }
        let (f, g) = if f < g { (f, g) } else { (g, f) };
        if let Some(&r) = self.cache.get(&(OP_AND, f, g, 0)) {
            return r;
        }
        let lv = self.lvl(f).min(self.lvl(g));
        let (f0, f1) = self.cof(f, lv);
        let (g0, g1) = self.cof(g, lv);
        let lo = self.and(f0, g0);
        let hi = self.and(f1, g1);
        let var = self.at_level[lv as usize];
        let r = self.mk(var, lo, hi);
        self.cache.insert((OP_AND, f, g, 0), r);
        r
    }

    pub fn or(&mut self, f: Bdd, g: Bdd) -> Bdd {
        if f == TRUE || g == TRUE {
            return TRUE;
        }
        if f == FALSE || f == g {
            return g;
        }
        if g == FALSE {
            return f;
        }
        let (f, g) = if f < g { (f, g) } else { (g, f) };
        if let Some(&r) = self.cache.get(&(OP_OR, f, g, 0)) {
            return r;
        }
        let lv = self.lvl(f).min(self.lvl(g));
        let (f0, f1) = self.cof(f, lv);
        let (g0, g1) = self.cof(g, lv);
        let lo = self.or(f0, g0);
        let hi = self.or(f1, g1);
        let var = self.at_level[lv as usize];
        let r = self.mk(var, lo, hi);
        self.cache.insert((OP_OR, f, g, 0), r);
        r
    }

    pub fn ite(&mut self, f: Bdd, g: Bdd, h: Bdd) -> Bdd {
        if f == TRUE {
            return g;
        }
        if f == FALSE {
            return h;
        }
        if g == h {
            return g;
        }
        if g == TRUE && h == FALSE {
            return f;
        }
        if g == FALSE && h == TRUE {
            return self.not(f);
        }
        if let Some(&r) = self.cache.get(&(OP_ITE, f, g, h)) {
            return r;
        }
        let lv = self.lvl(f).min(self.lvl(g)).min(self.lvl(h));
        let (f0, f1) = self.cof(f, lv);
        let (g0, g1) = self.cof(g, lv);
        let (h0, h1) = self.cof(h, lv);
        let lo = self.ite(f0, g0, h0);
        let hi = self.ite(f1, g1, h1);
        let var = self.at_level[lv as usize];
        let r = self.mk(var, lo, hi);
        self.cache.insert((OP_ITE, f, g, h), r);
        r
    }

    pub fn xor(&mut self, f: Bdd, g: Bdd) -> Bdd {
        let ng = self.not(g);
        self.ite(f, ng, g)
    }

    pub fn iff(&mut self, f: Bdd, g: Bdd) -> Bdd {
        let ng = self.not(g);
        self.ite(f, g, ng)
    }

    pub fn imp(&mut self, f: Bdd, g: Bdd) -> Bdd {
        let nf = self.not(f);
        self.or(nf, g)
    }

    /// `f ∧ ¬g`
    pub fn diff(&mut self, f: Bdd, g: Bdd) -> Bdd {
        let ng = self.not(g);
        self.and(f, ng)
    }

    pub fn and_all(&mut self, fs: &[Bdd]) -> Bdd {
        let mut r = TRUE;
        for &f in fs {
            r = self.and(r, f);
        }
        r
    }

    pub fn or_all(&mut self, fs: &[Bdd]) -> Bdd {
        let mut r = FALSE;
        for &f in fs {
            r = self.or(r, f);
        }
        r
    }

    // ---------------------------------------------------------------- quantification

    /// Conjunction of the positive literals of `vars` — the "cube" argument of the quantifiers.
    pub fn cube(&mut self, vars: &[u32]) -> Bdd {
        let mut vs: Vec<u32> = vars.to_vec();
        vs.sort_by_key(|&v| std::cmp::Reverse(self.level[v as usize]));
        vs.dedup();
        let mut acc = TRUE;
        for v in vs {
            acc = self.mk(v, FALSE, acc);
        }
        acc
    }

    /// The conjunction of literals described by `(var, value)` pairs (later pairs must not repeat a var).
    pub fn literals(&mut self, lits: &[(u32, bool)]) -> Bdd {
        let mut ls: Vec<(u32, bool)> = lits.to_vec();
        ls.sort_by_key(|&(v, _)| std::cmp::Reverse(self.level[v as usize]));
        let mut acc = TRUE;
        for (v, b) in ls {
            acc = if b { self.mk(v, FALSE, acc) } else { self.mk(v, acc, FALSE) };
        }
        acc
    }

    pub fn exists(&mut self, f: Bdd, cube: Bdd) -> Bdd {
        if f < 2 || cube == TRUE {
            return f;
        }
        let lf = self.lvl(f);
        let mut cube = cube;
        while cube != TRUE && self.lvl(cube) < lf {
            cube = self.nodes[cube as usize].hi;
        }
        if cube == TRUE {
            return f;
        }
        if let Some(&r) = self.cache.get(&(OP_EX, f, cube, 0)) {
            return r;
        }
        let n = self.nodes[f as usize];
        let r = if self.lvl(cube) == lf {
            let c2 = self.nodes[cube as usize].hi;
            let a = self.exists(n.lo, c2);
            if a == TRUE {
                TRUE
            } else {
                let b = self.exists(n.hi, c2);
                self.or(a, b)
            }
        } else {
            let lo = self.exists(n.lo, cube);
            let hi = self.exists(n.hi, cube);
            self.mk(n.var, lo, hi)
        };
        self.cache.insert((OP_EX, f, cube, 0), r);
        r
    }

    pub fn forall(&mut self, f: Bdd, cube: Bdd) -> Bdd {
        let nf = self.not(f);
        let e = self.exists(nf, cube);
        self.not(e)
    }

    /// `∃ cube. f ∧ g` computed without building the intermediate conjunction (relational product).
    pub fn and_exists(&mut self, f: Bdd, g: Bdd, cube: Bdd) -> Bdd {
        if f == FALSE || g == FALSE {
            return FALSE;
        }
        if cube == TRUE {
            return self.and(f, g);
        }
        if f == TRUE {
            return self.exists(g, cube);
        }
        if g == TRUE || f == g {
            return self.exists(f, cube);
        }
        let (f, g) = if f < g { (f, g) } else { (g, f) };
        let lv = self.lvl(f).min(self.lvl(g));
        let mut cube = cube;
        while cube != TRUE && self.lvl(cube) < lv {
            cube = self.nodes[cube as usize].hi;
        }
        if cube == TRUE {
            return self.and(f, g);
        }
        if let Some(&r) = self.cache.get(&(OP_AE, f, g, cube)) {
            return r;
        }
        let (f0, f1) = self.cof(f, lv);
        let (g0, g1) = self.cof(g, lv);
        let r = if self.lvl(cube) == lv {
            let c2 = self.nodes[cube as usize].hi;
            let a = self.and_exists(f0, g0, c2);
            if a == TRUE {
                TRUE
            } else {
                let b = self.and_exists(f1, g1, c2);
                self.or(a, b)
            }
        } else {
            let lo = self.and_exists(f0, g0, cube);
            let hi = self.and_exists(f1, g1, cube);
            let var = self.at_level[lv as usize];
            self.mk(var, lo, hi)
        };
        self.cache.insert((OP_AE, f, g, cube), r);
        r
    }

    // ---------------------------------------------------------------- substitution

    /// Rename variables according to `map` (variables not in the map are unchanged). The map may be
    /// any function on variables — the result is built with ITE so ordering does not matter.
    pub fn rename(&mut self, f: Bdd, map: &HashMap<u32, u32>) -> Bdd {
        let mut memo = HashMap::new();
        self.rename_rec(f, map, &mut memo)
    }

    fn rename_rec(&mut self, f: Bdd, map: &HashMap<u32, u32>, memo: &mut HashMap<Bdd, Bdd>) -> Bdd {
        if f < 2 {
            return f;
        }
        if let Some(&r) = memo.get(&f) {
            return r;
        }
        let n = self.nodes[f as usize];
        let lo = self.rename_rec(n.lo, map, memo);
        let hi = self.rename_rec(n.hi, map, memo);
        let nv = *map.get(&n.var).unwrap_or(&n.var);
        let v = self.var(nv);
        let r = self.ite(v, hi, lo);
        memo.insert(f, r);
        r
    }

    /// Cofactor `f` by a set of literals.
    pub fn restrict(&mut self, f: Bdd, lits: &HashMap<u32, bool>) -> Bdd {
        let mut memo = HashMap::new();
        self.restrict_rec(f, lits, &mut memo)
    }

    fn restrict_rec(&mut self, f: Bdd, lits: &HashMap<u32, bool>, memo: &mut HashMap<Bdd, Bdd>) -> Bdd {
        if f < 2 {
            return f;
        }
        if let Some(&r) = memo.get(&f) {
            return r;
        }
        let n = self.nodes[f as usize];
        let r = match lits.get(&n.var) {
            Some(true) => self.restrict_rec(n.hi, lits, memo),
            Some(false) => self.restrict_rec(n.lo, lits, memo),
            None => {
                let lo = self.restrict_rec(n.lo, lits, memo);
                let hi = self.restrict_rec(n.hi, lits, memo);
                self.mk(n.var, lo, hi)
            }
        };
        memo.insert(f, r);
        r
    }

    // ---------------------------------------------------------------- inspection

    pub fn support(&self, f: Bdd) -> Vec<u32> {
        let mut seen = std::collections::HashSet::new();
        let mut vars = std::collections::BTreeSet::new();
        let mut stack = vec![f];
        while let Some(x) = stack.pop() {
            if x < 2 || !seen.insert(x) {
                continue;
            }
            let n = self.nodes[x as usize];
            vars.insert(n.var);
            stack.push(n.lo);
            stack.push(n.hi);
        }
        vars.into_iter().collect()
    }

    /// Number of nodes reachable from `roots` (terminals not counted).
    pub fn dag_size(&self, roots: &[Bdd]) -> usize {
        let mut seen = std::collections::HashSet::new();
        let mut stack: Vec<Bdd> = roots.to_vec();
        while let Some(x) = stack.pop() {
            if x < 2 || !seen.insert(x) {
                continue;
            }
            let n = self.nodes[x as usize];
            stack.push(n.lo);
            stack.push(n.hi);
        }
        seen.len()
    }

    /// Total live (allocated, not freed) nodes, including garbage not yet collected.
    pub fn allocated(&self) -> usize {
        self.nodes.len() - 2 - self.free.len()
    }

    pub fn eval(&self, f: Bdd, assign: &dyn Fn(u32) -> bool) -> bool {
        let mut x = f;
        while x >= 2 {
            let n = self.nodes[x as usize];
            x = if assign(n.var) { n.hi } else { n.lo };
        }
        x == TRUE
    }

    /// Number of assignments to `vars` satisfying `f`. `f`'s support must be contained in `vars`.
    /// Saturates at `u128::MAX`.
    pub fn sat_count(&self, f: Bdd, vars: &[u32]) -> u128 {
        let mut vs: Vec<u32> = vars.to_vec();
        vs.sort_by_key(|&v| self.level[v as usize]);
        vs.dedup();
        let n = vs.len();
        let mut pos: HashMap<u32, usize> = HashMap::new();
        for (i, &v) in vs.iter().enumerate() {
            pos.insert(v, i);
        }
        fn p2(k: usize) -> u128 {
            if k >= 128 {
                u128::MAX
            } else {
                1u128 << k
            }
        }
        fn rec(m: &Manager, f: Bdd, n: usize, pos: &HashMap<u32, usize>, memo: &mut HashMap<Bdd, u128>) -> u128 {
            if f == FALSE {
                return 0;
            }
            if f == TRUE {
                return 1;
            }
            if let Some(&c) = memo.get(&f) {
                return c;
            }
            let nd = m.nodes[f as usize];
            let me = *pos.get(&nd.var).unwrap_or_else(|| panic!("sat_count: variable {} not in the counting set", nd.var));
            let pl = if nd.lo < 2 { n } else { pos[&m.nodes[nd.lo as usize].var] };
            let ph = if nd.hi < 2 { n } else { pos[&m.nodes[nd.hi as usize].var] };
            let a = rec(m, nd.lo, n, pos, memo).saturating_mul(p2(pl - me - 1));
            let b = rec(m, nd.hi, n, pos, memo).saturating_mul(p2(ph - me - 1));
            let r = a.saturating_add(b);
            memo.insert(f, r);
            r
        }
        if f == FALSE {
            return 0;
        }
        let mut memo = HashMap::new();
        let top = if f < 2 { n } else { pos[&self.nodes[f as usize].var] };
        rec(self, f, n, &pos, &mut memo).saturating_mul(p2(top))
    }

    /// One satisfying assignment over `vars` (unconstrained variables are `false`). Deterministic:
    /// prefers the `false` branch at every node.
    pub fn pick_one(&self, f: Bdd, vars: &[u32]) -> Option<Vec<bool>> {
        if f == FALSE {
            return None;
        }
        let mut chosen: HashMap<u32, bool> = HashMap::new();
        let mut x = f;
        while x >= 2 {
            let n = self.nodes[x as usize];
            if n.lo != FALSE {
                chosen.insert(n.var, false);
                x = n.lo;
            } else {
                chosen.insert(n.var, true);
                x = n.hi;
            }
        }
        Some(vars.iter().map(|v| *chosen.get(v).unwrap_or(&false)).collect())
    }

    /// Enumerate satisfying cubes (partial assignments). Stops after `limit` cubes.
    pub fn all_sat(&self, f: Bdd, limit: usize) -> Vec<Vec<(u32, bool)>> {
        let mut out = Vec::new();
        let mut path = Vec::new();
        self.all_sat_rec(f, &mut path, &mut out, limit);
        out
    }

    fn all_sat_rec(&self, f: Bdd, path: &mut Vec<(u32, bool)>, out: &mut Vec<Vec<(u32, bool)>>, limit: usize) {
        if out.len() >= limit || f == FALSE {
            return;
        }
        if f == TRUE {
            out.push(path.clone());
            return;
        }
        let n = self.nodes[f as usize];
        path.push((n.var, false));
        self.all_sat_rec(n.lo, path, out, limit);
        path.pop();
        path.push((n.var, true));
        self.all_sat_rec(n.hi, path, out, limit);
        path.pop();
    }

    /// Graphviz rendering of the functions rooted at `roots` (with display names).
    pub fn to_dot(&self, roots: &[(String, Bdd)], var_name: &dyn Fn(u32) -> String) -> String {
        let mut s = String::from("digraph bdd {\n  rankdir=TB;\n  node [shape=circle, fontname=\"Helvetica\"];\n");
        let mut seen = std::collections::HashSet::new();
        let mut stack = Vec::new();
        for (i, (name, r)) in roots.iter().enumerate() {
            s.push_str(&format!("  r{} [shape=plaintext,label=\"{}\"];\n  r{} -> n{};\n", i, name, i, r));
            stack.push(*r);
        }
        s.push_str("  n0 [shape=box,label=\"0\"];\n  n1 [shape=box,label=\"1\"];\n");
        // group by level so the picture reflects the order
        let mut by_level: std::collections::BTreeMap<u32, Vec<Bdd>> = Default::default();
        let mut body = String::new();
        while let Some(x) = stack.pop() {
            if x < 2 || !seen.insert(x) {
                continue;
            }
            let n = self.nodes[x as usize];
            by_level.entry(self.level[n.var as usize]).or_default().push(x);
            body.push_str(&format!("  n{} [label=\"{}\"];\n", x, var_name(n.var)));
            body.push_str(&format!("  n{} -> n{} [style=dashed];\n  n{} -> n{};\n", x, n.lo, x, n.hi));
            stack.push(n.lo);
            stack.push(n.hi);
        }
        s.push_str(&body);
        for (_, ns) in by_level {
            s.push_str("  { rank=same; ");
            for n in ns {
                s.push_str(&format!("n{}; ", n));
            }
            s.push_str("}\n");
        }
        s.push_str("}\n");
        s
    }

    // ---------------------------------------------------------------- garbage collection

    /// Push a root that must survive collections. Returns its argument for chaining.
    pub fn pin(&mut self, f: Bdd) -> Bdd {
        self.pins.push(f);
        f
    }

    pub fn pin_mark(&self) -> usize {
        self.pins.len()
    }

    pub fn pin_release(&mut self, mark: usize) {
        self.pins.truncate(mark);
    }

    /// Collect if the heap grew past the threshold (or always, in stress mode).
    pub fn maybe_gc(&mut self, extra: &[Bdd]) {
        if self.gc_stress || self.allocated() > self.gc_threshold {
            self.gc(extra);
            let live = self.allocated();
            self.gc_threshold = (live * 2).max(400_000);
        }
    }

    /// Mark-and-sweep. Roots are the pin stack plus `extra`. All computed-table entries are dropped.
    pub fn gc(&mut self, extra: &[Bdd]) {
        self.gc_runs += 1;
        let mut marked = vec![false; self.nodes.len()];
        let mut stack: Vec<Bdd> = self.pins.iter().chain(extra.iter()).copied().collect();
        while let Some(x) = stack.pop() {
            if x < 2 || marked[x as usize] {
                continue;
            }
            marked[x as usize] = true;
            let n = self.nodes[x as usize];
            stack.push(n.lo);
            stack.push(n.hi);
        }
        for i in 2..self.nodes.len() {
            let n = self.nodes[i];
            if n.var == DEAD || marked[i] {
                continue;
            }
            self.unique.remove(&(n.var, n.lo, n.hi));
            self.nodes[i] = Node { var: DEAD, lo: FALSE, hi: FALSE };
            self.free.push(i as u32);
        }
        self.cache.clear();
    }

    // ---------------------------------------------------------------- reordering

    /// Swap the variables at `level` and `level + 1`, in place.
    pub fn swap_levels(&mut self, level: usize) {
        self.swaps += 1;
        let x = self.at_level[level];
        let y = self.at_level[level + 1];
        let xs: Vec<Bdd> = (2..self.nodes.len() as u32).filter(|&i| self.nodes[i as usize].var == x).collect();
        // Flip the order first: `mk` below checks child levels against the *new* order.
        self.at_level[level] = y;
        self.at_level[level + 1] = x;
        self.level[x as usize] = (level + 1) as u32;
        self.level[y as usize] = level as u32;
        for n in xs {
            let Node { lo, hi, .. } = self.nodes[n as usize];
            let lo_y = lo >= 2 && self.nodes[lo as usize].var == y;
            let hi_y = hi >= 2 && self.nodes[hi as usize].var == y;
            if !lo_y && !hi_y {
                continue; // node stays on x; x is now one level lower, which is still legal
            }
            let (f00, f01) = if lo_y { (self.nodes[lo as usize].lo, self.nodes[lo as usize].hi) } else { (lo, lo) };
            let (f10, f11) = if hi_y { (self.nodes[hi as usize].lo, self.nodes[hi as usize].hi) } else { (hi, hi) };
            self.unique.remove(&(x, lo, hi));
            let nlo = self.mk(x, f00, f10);
            let nhi = self.mk(x, f01, f11);
            debug_assert_ne!(nlo, nhi);
            self.nodes[n as usize] = Node { var: y, lo: nlo, hi: nhi };
            let prev = self.unique.insert((y, nlo, nhi), n);
            debug_assert!(prev.is_none(), "swap produced a duplicate node");
        }
        self.cache.clear();
    }

    fn live_size(&self, roots: &[Bdd]) -> usize {
        let mut all: Vec<Bdd> = self.pins.clone();
        all.extend_from_slice(roots);
        self.dag_size(&all)
    }

    /// Move the contiguous block of `a` levels starting at `s` below the `b` levels that follow it.
    fn swap_blocks(&mut self, s: usize, a: usize, b: usize) {
        for j in (0..a).rev() {
            for k in 0..b {
                self.swap_levels(s + j + k);
            }
        }
    }

    /// Rudell sifting over *blocks* of variables that must stay contiguous and in internal order
    /// (we use it with {x, x'} pairs). Each block in turn is moved through every position and parked
    /// where the shared DAG (reachable from the pins and `roots`) was smallest.
    /// Returns (size before, size after).
    pub fn sift_blocks(&mut self, blocks: &[Vec<u32>], roots: &[Bdd]) -> (usize, usize) {
        self.gc(roots);
        let before = self.live_size(roots);
        // current block order (by level of the block's first var); sizes in levels
        let mut order: Vec<usize> = (0..blocks.len()).collect();
        order.sort_by_key(|&b| self.level[blocks[b][0] as usize]);
        // sift heaviest blocks first
        let mut weight: Vec<(usize, usize)> = (0..blocks.len())
            .map(|b| {
                let w = (2..self.nodes.len()).filter(|&i| blocks[b].contains(&self.nodes[i].var)).count();
                (w, b)
            })
            .collect();
        weight.sort_by_key(|&(w, b)| (std::cmp::Reverse(w), b));
        let start_of = |order: &[usize], pos: usize| -> usize { order[..pos].iter().map(|&b| blocks[b].len()).sum() };
        for &(_, b) in &weight {
            let mut pos = order.iter().position(|&x| x == b).unwrap();
            let mut best = self.live_size(roots);
            let mut best_pos = pos;
            let limit = best.saturating_mul(2).max(best + 64);
            // go down to the bottom
            while pos + 1 < order.len() {
                let s = start_of(&order, pos);
                let other = order[pos + 1];
                self.swap_blocks(s, blocks[b].len(), blocks[other].len());
                order.swap(pos, pos + 1);
                pos += 1;
                self.gc(roots);
                let sz = self.live_size(roots);
                if sz < best {
                    best = sz;
                    best_pos = pos;
                }
                if sz > limit {
                    break;
                }
            }
            // go up to the top
            while pos > 0 {
                let s = start_of(&order, pos - 1);
                let other = order[pos - 1];
                self.swap_blocks(s, blocks[other].len(), blocks[b].len());
                order.swap(pos, pos - 1);
                pos -= 1;
                self.gc(roots);
                let sz = self.live_size(roots);
                if sz < best {
                    best = sz;
                    best_pos = pos;
                }
                if sz > limit && pos < best_pos {
                    break;
                }
            }
            // settle at the best position
            while pos < best_pos {
                let s = start_of(&order, pos);
                let other = order[pos + 1];
                self.swap_blocks(s, blocks[b].len(), blocks[other].len());
                order.swap(pos, pos + 1);
                pos += 1;
            }
            while pos > best_pos {
                let s = start_of(&order, pos - 1);
                let other = order[pos - 1];
                self.swap_blocks(s, blocks[other].len(), blocks[b].len());
                order.swap(pos, pos - 1);
                pos -= 1;
            }
            self.gc(roots);
        }
        let after = self.live_size(roots);
        (before, after)
    }

    /// Check structural invariants (used by tests): ordering, reduction, unique-table consistency.
    pub fn check_invariants(&self) -> Result<(), String> {
        let mut live = 0;
        for i in 2..self.nodes.len() {
            let n = self.nodes[i];
            if n.var == DEAD {
                continue;
            }
            live += 1;
            if n.lo == n.hi {
                return Err(format!("node {} not reduced", i));
            }
            if self.lvl(n.lo) <= self.level[n.var as usize] || self.lvl(n.hi) <= self.level[n.var as usize] {
                return Err(format!("node {} violates order", i));
            }
            if self.unique.get(&(n.var, n.lo, n.hi)) != Some(&(i as u32)) {
                return Err(format!("node {} missing from unique table", i));
            }
        }
        if live != self.unique.len() {
            return Err(format!("unique table has {} entries for {} live nodes", self.unique.len(), live));
        }
        Ok(())
    }
}
