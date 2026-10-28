//! Affine-gap pairwise alignment (Gotoh) with traceback: global (Needleman–Wunsch),
//! local (Smith–Waterman) and semi-global (query fully aligned, target ends free).
//! An optional diagonal band restricts the DP for long, nearly-colinear inputs.
//!
//! Conventions: a gap of length L costs `gap_open + L * gap_ext` (both negative or
//! zero). `q` is the query (rows), `t` the target (columns). Op `I` consumes only the
//! query, `D` only the target. Code 0 (ambiguous) never matches anything.

const NEG: i32 = i32::MIN / 4;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Scoring {
    pub matched: i32,
    pub mismatch: i32,
    pub gap_open: i32,
    pub gap_ext: i32,
}

impl Default for Scoring {
    /// BWA-MEM's defaults: +1 / -4, gap open -6, extend -1.
    fn default() -> Scoring {
        Scoring { matched: 1, mismatch: -4, gap_open: -6, gap_ext: -1 }
    }
}

impl Scoring {
    pub fn validate(&self) -> Result<(), String> {
        if self.matched <= 0 {
            return Err("match score must be positive".into());
        }
        if self.mismatch > 0 || self.gap_open > 0 || self.gap_ext > 0 {
            return Err("mismatch / gap penalties must be <= 0".into());
        }
        if self.gap_ext == 0 && self.gap_open == 0 {
            return Err("gaps must cost something (gap_open and gap_ext are both 0)".into());
        }
        Ok(())
    }

    #[inline]
    fn sub(&self, a: u8, b: u8) -> i32 {
        if a == b && a != 0 {
            self.matched
        } else {
            self.mismatch
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Global,
    Local,
    /// Query aligned end to end; target prefix/suffix free (read-against-window).
    SemiGlobal,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Alignment {
    pub score: i32,
    pub q_start: usize,
    pub q_end: usize,
    pub t_start: usize,
    pub t_end: usize,
    /// run-length ops over '=' 'X' 'I' 'D'
    pub ops: Vec<(u8, usize)>,
}

impl Alignment {
    /// Merge '=' and 'X' into 'M' (SAM-style). Soft clips added from q_start / qlen-q_end.
    pub fn cigar(&self, qlen: usize) -> String {
        let mut out = String::new();
        if self.q_start > 0 {
            out.push_str(&format!("{}S", self.q_start));
        }
        let mut merged: Vec<(u8, usize)> = Vec::new();
        for &(op, n) in &self.ops {
            let op = if op == b'=' || op == b'X' { b'M' } else { op };
            match merged.last_mut() {
                Some((o, c)) if *o == op => *c += n,
                _ => merged.push((op, n)),
            }
        }
        for (op, n) in merged {
            out.push_str(&format!("{}{}", n, op as char));
        }
        if qlen > self.q_end {
            out.push_str(&format!("{}S", qlen - self.q_end));
        }
        out
    }

    /// Number of target bases covered.
    pub fn ref_span(&self) -> usize {
        self.t_end - self.t_start
    }

    /// Extended CIGAR with '=' / 'X'.
    pub fn cigar_ext(&self) -> String {
        self.ops.iter().map(|&(o, n)| format!("{}{}", n, o as char)).collect()
    }

    /// Edit distance: mismatches + inserted + deleted bases.
    pub fn edit_distance(&self) -> usize {
        self.ops.iter().filter(|&&(o, _)| o != b'=').map(|&(_, n)| n).sum()
    }

    pub fn matches(&self) -> usize {
        self.ops.iter().filter(|&&(o, _)| o == b'=').map(|&(_, n)| n).sum()
    }

    pub fn columns(&self) -> usize {
        self.ops.iter().map(|&(_, n)| n).sum()
    }

    pub fn identity(&self) -> f64 {
        let c = self.columns();
        if c == 0 {
            0.0
        } else {
            self.matches() as f64 / c as f64
        }
    }

    /// Recompute the score from the ops alone (independent of the DP).
    pub fn rescore(&self, sc: &Scoring) -> i32 {
        let mut s = 0;
        for &(o, n) in &self.ops {
            match o {
                b'=' => s += sc.matched * n as i32,
                b'X' => s += sc.mismatch * n as i32,
                _ => s += sc.gap_open + sc.gap_ext * n as i32,
            }
        }
        s
    }
}

fn push_op(ops: &mut Vec<(u8, usize)>, op: u8) {
    // ops are built in reverse order, merged at the tail
    match ops.last_mut() {
        Some((o, n)) if *o == op => *n += 1,
        _ => ops.push((op, 1)),
    }
}

/// Align `q` against `t`. `band` = Some((lo,hi)) restricts to diagonals lo <= j-i <= hi.
/// Returns Ok(None) only when a band excludes every possible alignment.
pub fn align(q: &[u8], t: &[u8], mode: Mode, sc: &Scoring, band: Option<(i64, i64)>) -> Result<Option<Alignment>, String> {
    sc.validate()?;
    let n = q.len();
    let m = t.len();
    let (lo, hi) = band.unwrap_or((-(n as i64) - 1, m as i64 + 1));
    if lo > hi {
        return Err("invalid band: lo > hi".into());
    }
    let row_lo = |i: usize| -> usize { (i as i64 + lo).max(0).min(m as i64 + 1) as usize };
    let row_hi = |i: usize| -> i64 { (i as i64 + hi).min(m as i64) }; // may be < row_lo => empty row
    let width = ((hi - lo + 1).min(m as i64 + 1)) as usize;
    let cells = (n as u64 + 1) * width as u64;
    if cells > 600_000_000 {
        return Err(format!(
            "alignment of {} x {} needs {} MB of traceback; use --band to restrict the DP",
            n, m, cells / 1_000_000
        ));
    }
    let mut tb = vec![0u8; cells as usize];
    let go = sc.gap_open;
    let ge = sc.gap_ext;

    let mut h_prev = vec![NEG; m + 2];
    let mut f_prev = vec![NEG; m + 2];
    let mut h_cur = vec![NEG; m + 2];
    let mut f_cur = vec![NEG; m + 2];

    // row 0
    {
        let jl = row_lo(0);
        let jh = row_hi(0);
        for j in jl as i64..=jh {
            let j = j as usize;
            h_prev[j] = match mode {
                Mode::Global => {
                    if j == 0 {
                        0
                    } else {
                        go + ge * j as i32
                    }
                }
                _ => 0,
            };
        }
    }
    let mut best = NEG;
    let (mut bi, mut bj) = (0usize, 0usize);
    let consider_end = |mode: Mode, i: usize, j: usize, h: i32, best: &mut i32, bi: &mut usize, bj: &mut usize| match mode {
        Mode::Local => {
            if h > *best {
                *best = h;
                *bi = i;
                *bj = j;
            }
        }
        Mode::SemiGlobal => {
            if i == n && h > *best {
                *best = h;
                *bi = i;
                *bj = j;
            }
        }
        Mode::Global => {
            if i == n && j == m {
                *best = h;
                *bi = i;
                *bj = j;
            }
        }
    };
    if n == 0 {
        // only row 0 exists
        let jl = row_lo(0);
        let jh = row_hi(0);
        for j in jl as i64..=jh {
            consider_end(mode, 0, j as usize, h_prev[j as usize], &mut best, &mut bi, &mut bj);
        }
    } else if mode == Mode::Local {
        let jl = row_lo(0);
        let jh = row_hi(0);
        for j in jl as i64..=jh {
            consider_end(mode, 0, j as usize, 0, &mut best, &mut bi, &mut bj);
        }
    }

    for i in 1..=n {
        let jl = row_lo(i);
        let jh = row_hi(i);
        // sentinels just outside the band
        if jl >= 1 {
            h_cur[jl - 1] = NEG;
            f_cur[jl - 1] = NEG;
        }
        if jh >= -1 && (jh + 1) as usize <= m {
            h_cur[(jh + 1) as usize] = NEG;
            f_cur[(jh + 1) as usize] = NEG;
        }
        let mut e = NEG;
        let qi = q[i - 1];
        let mut j = jl;
        while (j as i64) <= jh {
            let idx = i * width + (j - jl);
            let mut flags = 0u8;
            if j == 0 {
                // left boundary column
                let h0 = match mode {
                    Mode::Local => 0,
                    _ => go + ge * i as i32,
                };
                h_cur[0] = h0;
                f_cur[0] = if mode == Mode::Local { NEG } else { h0 };
                e = NEG;
                tb[idx] = if mode == Mode::Local { 3 } else { 2 };
                consider_end(mode, i, 0, h0, &mut best, &mut bi, &mut bj);
                j += 1;
                continue;
            }
            // E: gap consuming target (deletion), from the left in this row
            let e_open = h_cur[j - 1].saturating_add(go + ge);
            let e_ext = e.saturating_add(ge);
            if e_ext > e_open {
                e = e_ext;
                flags |= 4;
            } else {
                e = e_open;
            }
            // F: gap consuming query (insertion), from the row above
            let f_open = h_prev[j].saturating_add(go + ge);
            let f_ext = f_prev[j].saturating_add(ge);
            let f;
            if f_ext > f_open {
                f = f_ext;
                flags |= 8;
            } else {
                f = f_open;
            }
            let diag = h_prev[j - 1].saturating_add(sc.sub(qi, t[j - 1]));
            let mut h = diag;
            let mut src = 0u8;
            if e > h {
                h = e;
                src = 1;
            }
            if f > h {
                h = f;
                src = 2;
            }
            if mode == Mode::Local && h <= 0 {
                h = 0;
                src = 3;
            }
            flags |= src;
            tb[idx] = flags;
            h_cur[j] = h;
            f_cur[j] = f;
            consider_end(mode, i, j, h, &mut best, &mut bi, &mut bj);
            j += 1;
        }
        // E must not leak across rows: it is re-initialised at the top of each row (e = NEG).
        std::mem::swap(&mut h_prev, &mut h_cur);
        std::mem::swap(&mut f_prev, &mut f_cur);
    }

    if best <= NEG / 2 {
        return Ok(None);
    }
    if mode == Mode::Local && best <= 0 {
        return Ok(Some(Alignment { score: 0, q_start: 0, q_end: 0, t_start: 0, t_end: 0, ops: vec![] }));
    }

    // traceback
    let mut ops: Vec<(u8, usize)> = Vec::new();
    let (mut i, mut j) = (bi, bj);
    let mut state = 0u8; // 0=H 1=E 2=F
    loop {
        if state == 0 {
            if i == 0 || j == 0 {
                if mode == Mode::Local {
                    break;
                }
                if i == 0 {
                    if mode == Mode::Global {
                        for _ in 0..j {
                            push_op(&mut ops, b'D');
                        }
                        j = 0;
                    }
                    break;
                }
                // j == 0, i > 0: leading insertions (global & semi-global)
                for _ in 0..i {
                    push_op(&mut ops, b'I');
                }
                i = 0;
                break;
            }
            let jl = row_lo(i);
            let flags = tb[i * width + (j - jl)];
            match flags & 3 {
                0 => {
                    push_op(&mut ops, if q[i - 1] == t[j - 1] && q[i - 1] != 0 { b'=' } else { b'X' });
                    i -= 1;
                    j -= 1;
                }
                1 => state = 1,
                2 => state = 2,
                _ => break,
            }
        } else if state == 1 {
            let jl = row_lo(i);
            let flags = tb[i * width + (j - jl)];
            push_op(&mut ops, b'D');
            j -= 1;
            if flags & 4 == 0 {
                state = 0;
            }
        } else {
            let jl = row_lo(i);
            let flags = tb[i * width + (j - jl)];
            push_op(&mut ops, b'I');
            i -= 1;
            if flags & 8 == 0 {
                state = 0;
            }
        }
    }
    ops.reverse();
    Ok(Some(Alignment { score: best, q_start: i, q_end: bi, t_start: j, t_end: bj, ops }))
}

/// Three-line text rendering (target / match bars / query), wrapped at `width` columns.
pub fn format_alignment(q: &[u8], t: &[u8], a: &Alignment, width: usize) -> String {
    let (mut top, mut mid, mut bot) = (Vec::new(), Vec::new(), Vec::new());
    let (mut qi, mut ti) = (a.q_start, a.t_start);
    for &(op, n) in &a.ops {
        for _ in 0..n {
            match op {
                b'=' | b'X' => {
                    top.push(crate::seq::decode(t[ti]));
                    bot.push(crate::seq::decode(q[qi]));
                    mid.push(if op == b'=' { b'|' } else { b'.' });
                    qi += 1;
                    ti += 1;
                }
                b'I' => {
                    top.push(b'-');
                    bot.push(crate::seq::decode(q[qi]));
                    mid.push(b' ');
                    qi += 1;
                }
                _ => {
                    top.push(crate::seq::decode(t[ti]));
                    bot.push(b'-');
                    mid.push(b' ');
                    ti += 1;
                }
            }
        }
    }
    let mut out = String::new();
    let width = width.max(10);
    let (mut tpos, mut qpos) = (a.t_start, a.q_start);
    let mut k = 0;
    while k < top.len() {
        let e = (k + width).min(top.len());
        let tcount = top[k..e].iter().filter(|&&c| c != b'-').count();
        let qcount = bot[k..e].iter().filter(|&&c| c != b'-').count();
        out.push_str(&format!("target {:>8} {}\n", tpos + 1, String::from_utf8_lossy(&top[k..e])));
        out.push_str(&format!("       {:>8} {}\n", "", String::from_utf8_lossy(&mid[k..e])));
        out.push_str(&format!("query  {:>8} {}\n\n", qpos + 1, String::from_utf8_lossy(&bot[k..e])));
        tpos += tcount;
        qpos += qcount;
        k = e;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rng::Rng;
    use crate::seq::to_codes;

    fn c(s: &str) -> Vec<u8> {
        to_codes(s.as_bytes()).0
    }

    /// Exhaustively enumerate every alignment path (tiny inputs only) and return the best score.
    fn brute(q: &[u8], t: &[u8], mode: Mode, sc: &Scoring) -> i32 {
        // state: 0 = in match/start, 1 = in D run, 2 = in I run
        fn rec(q: &[u8], t: &[u8], i: usize, j: usize, st: u8, started: bool, mode: Mode, sc: &Scoring, acc: i32, best: &mut i32) {
            let n = q.len();
            let m = t.len();
            let end_ok = match mode {
                Mode::Global => i == n && j == m,
                Mode::SemiGlobal => i == n,
                Mode::Local => true,
            };
            if end_ok && (mode != Mode::Local || started) {
                *best = (*best).max(acc);
            }
            if i < n && j < m {
                let s = sc.sub(q[i], t[j]);
                rec(q, t, i + 1, j + 1, 0, true, mode, sc, acc + s, best);
            }
            if j < m {
                let cost = if st == 1 { sc.gap_ext } else { sc.gap_open + sc.gap_ext };
                // a deletion at the very start of a semi-global/local alignment is pointless but legal in global
                rec(q, t, i, j + 1, 1, true, mode, sc, acc + cost, best);
            }
            if i < n {
                let cost = if st == 2 { sc.gap_ext } else { sc.gap_open + sc.gap_ext };
                rec(q, t, i + 1, j, 2, true, mode, sc, acc + cost, best);
            }
        }
        let mut best = i32::MIN;
        let n = q.len();
        let m = t.len();
        match mode {
            Mode::Global => rec(q, t, 0, 0, 0, true, mode, sc, 0, &mut best),
            Mode::SemiGlobal => {
                for j in 0..=m {
                    rec(q, t, 0, j, 0, true, mode, sc, 0, &mut best);
                }
            }
            Mode::Local => {
                best = 0;
                for i in 0..=n {
                    for j in 0..=m {
                        rec(q, t, i, j, 0, false, mode, sc, 0, &mut best);
                    }
                }
            }
        }
        best
    }

    fn check_consistency(q: &[u8], t: &[u8], a: &Alignment, sc: &Scoring, mode: Mode) {
        assert_eq!(a.rescore(sc), a.score, "rescore mismatch {:?}", a);
        let qc: usize = a.ops.iter().filter(|(o, _)| *o != b'D').map(|&(_, n)| n).sum();
        let tc: usize = a.ops.iter().filter(|(o, _)| *o != b'I').map(|&(_, n)| n).sum();
        assert_eq!(a.q_end - a.q_start, qc);
        assert_eq!(a.t_end - a.t_start, tc);
        // '=' / 'X' labels must agree with the sequences
        let (mut qi, mut ti) = (a.q_start, a.t_start);
        for &(o, n) in &a.ops {
            for _ in 0..n {
                match o {
                    b'=' => {
                        assert!(q[qi] == t[ti] && q[qi] != 0);
                        qi += 1;
                        ti += 1;
                    }
                    b'X' => {
                        assert!(q[qi] != t[ti]);
                        qi += 1;
                        ti += 1;
                    }
                    b'I' => qi += 1,
                    _ => ti += 1,
                }
            }
        }
        match mode {
            Mode::Global => assert!(a.q_start == 0 && a.q_end == q.len() && a.t_start == 0 && a.t_end == t.len()),
            Mode::SemiGlobal => assert!(a.q_start == 0 && a.q_end == q.len()),
            Mode::Local => {}
        }
    }

    #[test]
    fn matches_brute_force_on_tiny_random() {
        let mut rng = Rng::new(11);
        let scorings = [
            Scoring::default(),
            Scoring { matched: 2, mismatch: -1, gap_open: -2, gap_ext: -1 },
            Scoring { matched: 3, mismatch: -3, gap_open: 0, gap_ext: -2 },
        ];
        for _ in 0..500 {
            let n = rng.below(6);
            let m = rng.below(7);
            let q: Vec<u8> = (0..n).map(|_| 1 + rng.below(3) as u8).collect();
            let t: Vec<u8> = (0..m).map(|_| 1 + rng.below(3) as u8).collect();
            for sc in &scorings {
                for mode in [Mode::Global, Mode::Local, Mode::SemiGlobal] {
                    let a = align(&q, &t, mode, sc, None).unwrap().unwrap();
                    let b = brute(&q, &t, mode, sc);
                    assert_eq!(a.score, b, "mode {:?} q={:?} t={:?} sc={:?}", mode, q, t, sc);
                    check_consistency(&q, &t, &a, sc, mode);
                }
            }
        }
    }

    #[test]
    fn known_cigars() {
        let sc = Scoring::default();
        let a = align(&c("ACGTACGT"), &c("ACGTACGT"), Mode::Global, &sc, None).unwrap().unwrap();
        assert_eq!(a.cigar(8), "8M");
        assert_eq!(a.score, 8);
        // single deletion in the query relative to target: gap placed leftmost in a homopolymer
        let a = align(&c("ACGTTTGCA"), &c("ACGTTTTGCA"), Mode::Global, &sc, None).unwrap().unwrap();
        assert_eq!(a.cigar_ext(), "3=1D6=");
        // insertion
        let a = align(&c("GATTACAGATTACA"), &c("GATTACAGGATTACA"), Mode::Global, &sc, None).unwrap().unwrap();
        assert_eq!(a.cigar(14), "7M1D7M");
        let a = align(&c("ACGGGT"), &c("ACGGT"), Mode::Global, &sc, None).unwrap().unwrap();
        assert!(a.cigar(6).contains('I'));
        // soft clipping in local mode
        let a = align(&c("TTTTTACGTACGTAC"), &c("GGGACGTACGTACCC"), Mode::Local, &sc, None).unwrap().unwrap();
        assert_eq!(a.q_start, 5);
        assert_eq!(a.cigar(15), "5S10M");
    }

    #[test]
    fn empty_inputs() {
        let sc = Scoring::default();
        let a = align(&[], &[], Mode::Global, &sc, None).unwrap().unwrap();
        assert_eq!(a.score, 0);
        let a = align(&[], &c("ACG"), Mode::Global, &sc, None).unwrap().unwrap();
        assert_eq!(a.score, -6 - 3);
        assert_eq!(a.cigar_ext(), "3D");
        let a = align(&c("ACG"), &[], Mode::Global, &sc, None).unwrap().unwrap();
        assert_eq!(a.cigar_ext(), "3I");
        let a = align(&c("ACG"), &[], Mode::Local, &sc, None).unwrap().unwrap();
        assert_eq!(a.score, 0);
        let a = align(&c("ACG"), &[], Mode::SemiGlobal, &sc, None).unwrap().unwrap();
        assert_eq!(a.cigar_ext(), "3I");
    }

    #[test]
    fn banded_equals_full_when_band_contains_optimum() {
        let mut rng = Rng::new(5);
        let sc = Scoring::default();
        for _ in 0..200 {
            let n = 30 + rng.below(40);
            let q: Vec<u8> = (0..n).map(|_| 1 + rng.below(4) as u8).collect();
            let mut t = q.clone();
            for _ in 0..rng.below(4) {
                let p = rng.below(t.len());
                match rng.below(3) {
                    0 => t[p] = 1 + rng.below(4) as u8,
                    1 => {
                        t.remove(p);
                    }
                    _ => t.insert(p, 1 + rng.below(4) as u8),
                }
            }
            let full = align(&q, &t, Mode::Global, &sc, None).unwrap().unwrap();
            let banded = align(&q, &t, Mode::Global, &sc, Some((-6, 6))).unwrap().unwrap();
            assert_eq!(full.score, banded.score);
            check_consistency(&q, &t, &banded, &sc, Mode::Global);
            let semi_full = align(&q, &t, Mode::SemiGlobal, &sc, None).unwrap().unwrap();
            let semi_band = align(&q, &t, Mode::SemiGlobal, &sc, Some((-8, 8))).unwrap().unwrap();
            assert_eq!(semi_full.score, semi_band.score);
        }
    }

    #[test]
    fn band_that_excludes_everything_is_none_or_worse() {
        let sc = Scoring::default();
        // target is 30 longer than query; global needs diagonal +30 to be reachable
        let q = c("ACGTACGTAC");
        let t = c(&"ACGTACGTAC".repeat(4));
        assert!(align(&q, &t, Mode::Global, &sc, Some((-2, 2))).unwrap().is_none());
        assert!(align(&q, &t, Mode::Global, &sc, Some((5, 1))).is_err());
    }

    #[test]
    fn rejects_bad_scoring_and_huge_matrices() {
        let bad = Scoring { matched: 0, ..Scoring::default() };
        assert!(align(&c("A"), &c("A"), Mode::Global, &bad, None).is_err());
        let pos = Scoring { gap_ext: 1, ..Scoring::default() };
        assert!(align(&c("A"), &c("A"), Mode::Global, &pos, None).is_err());
        let big = vec![1u8; 30_000];
        assert!(align(&big, &big, Mode::Global, &Scoring::default(), None).is_err());
    }

    #[test]
    fn ambiguous_never_matches() {
        let sc = Scoring::default();
        let a = align(&[0, 1], &[0, 1], Mode::Global, &sc, None).unwrap().unwrap();
        assert_eq!(a.cigar_ext(), "1X1=");
    }

    #[test]
    fn long_banded_alignment_is_cheap() {
        let mut rng = Rng::new(2);
        let q: Vec<u8> = (0..20_000).map(|_| 1 + rng.below(4) as u8).collect();
        let mut t = q.clone();
        t.remove(5000);
        t[10_000] = 1 + (t[10_000] % 4);
        let a = align(&q, &t, Mode::Global, &Scoring::default(), Some((-20, 20))).unwrap().unwrap();
        assert_eq!(a.edit_distance(), 2);
    }

    #[test]
    fn format_roundtrip_smoke() {
        let q = c("ACGTTGCA");
        let t = c("ACGTGCA");
        let a = align(&q, &t, Mode::Global, &Scoring::default(), None).unwrap().unwrap();
        let s = format_alignment(&q, &t, &a, 60);
        assert!(s.contains("ACGTTGCA") && s.contains("ACG-TGCA"), "{}", s);
    }
}
