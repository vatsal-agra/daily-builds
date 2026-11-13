/* Inkgrid engine — nonogram solving, rating and generation. No dependencies.
 * Cell encoding: -1 unknown, 0 empty, 1 filled.  UMD: works in Node and <script>. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Inkgrid = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  const U = -1;

  // ---------- clues ----------
  function lineClue(cells) {
    const out = []; let run = 0;
    for (const c of cells) {
      if (c === 1) run++;
      else if (run) { out.push(run); run = 0; }
    }
    if (run) out.push(run);
    return out;
  }
  function cluesFromGrid(grid) {
    const h = grid.length, w = h ? grid[0].length : 0;
    const rows = grid.map(lineClue);
    const cols = [];
    for (let x = 0; x < w; x++) cols.push(lineClue(grid.map(r => r[x])));
    return { rows, cols };
  }
  function validatePuzzle(p) {
    if (!p || !Array.isArray(p.rows) || !Array.isArray(p.cols)) throw new Error('puzzle needs rows and cols arrays');
    const w = p.cols.length, h = p.rows.length;
    if (!w || !h) throw new Error('puzzle must have at least one row and one column');
    if (w > 60 || h > 60) throw new Error('puzzle too large (max 60x60)');
    const chk = (clues, n, name) => clues.forEach((c, i) => {
      if (!Array.isArray(c)) throw new Error(name + ' ' + (i + 1) + ': clue must be a list');
      for (const v of c) if (!Number.isInteger(v) || v < 1) throw new Error(name + ' ' + (i + 1) + ': clue values must be positive integers');
      const need = c.reduce((a, b) => a + b, 0) + Math.max(0, c.length - 1);
      if (need > n) throw new Error(name + ' ' + (i + 1) + ': clue [' + c.join(' ') + '] needs ' + need + ' cells but line has ' + n);
    });
    chk(p.rows, w, 'row'); chk(p.cols, h, 'column');
    const sr = p.rows.flat().reduce((a, b) => a + b, 0), sc = p.cols.flat().reduce((a, b) => a + b, 0);
    if (sr !== sc) throw new Error('row clues total ' + sr + ' filled cells but column clues total ' + sc);
    return { w, h };
  }

  // ---------- line solver (DP) ----------
  // Returns null on contradiction, else new array with all forced cells set.
  // Also reports whether anything changed via out.changed when `out` passed.
  function lineSolve(clue, line) {
    const n = line.length, k = clue.length;
    if (k === 0) {
      for (let i = 0; i < n; i++) if (line[i] === 1) return null;
      return new Array(n).fill(0);
    }
    // run[i] = number of consecutive non-empty (not 0) cells starting at i
    const free = new Int32Array(n + 1);
    for (let i = n - 1; i >= 0; i--) free[i] = line[i] === 0 ? 0 : free[i + 1] + 1;
    const fits = (s, j) => {
      const len = clue[j], e = s + len;
      return e <= n && free[s] >= len && (e === n || line[e] !== 1);
    };
    const W = k + 1;
    // F[i*W+j]: cells i.. can hold blocks j..
    const F = new Uint8Array((n + 2) * W);
    F[n * W + k] = 1;
    for (let i = n - 1; i >= 0; i--) {
      for (let j = k; j >= 0; j--) {
        let ok = 0;
        if (line[i] !== 1 && F[(i + 1) * W + j]) ok = 1;
        if (!ok && j < k && fits(i, j)) {
          const e = i + clue[j];
          ok = F[(e === n ? n : e + 1) * W + j + 1];
        }
        F[i * W + j] = ok;
      }
    }
    if (!F[0]) return null;
    // G[i*W+j]: cells 0..i-1 hold blocks 0..j-1 (cell i-1 is empty/boundary)
    const G = new Uint8Array((n + 2) * W);
    G[0] = 1;
    const canFill = new Int32Array(n + 1), canEmpty = new Uint8Array(n);
    for (let i = 0; i <= n; i++) {
      for (let j = 0; j <= k; j++) {
        if (!G[i * W + j]) continue;
        if (i < n && line[i] !== 1) {
          G[(i + 1) * W + j] = 1;
          if (F[(i + 1) * W + j]) canEmpty[i] = 1;
        }
        if (j < k && i < n && fits(i, j)) {
          const e = i + clue[j], nx = e === n ? n : e + 1;
          G[nx * W + j + 1] = 1;
          if (F[nx * W + j + 1]) {
            canFill[i]++; canFill[e]--;
            if (e < n) canEmpty[e] = 1;
          }
        }
      }
    }
    const out = new Array(n);
    let run = 0;
    for (let i = 0; i < n; i++) {
      run += canFill[i];
      const f = run > 0, e = canEmpty[i] === 1;
      if (!f && !e) return null;
      out[i] = f && e ? U : f ? 1 : 0;
    }
    return out;
  }

  // ---------- board propagation ----------
  function makeBoard(p) {
    const w = p.cols.length, h = p.rows.length;
    return { w, h, cells: new Int8Array(w * h).fill(U), p };
  }
  const cloneBoard = b => ({ w: b.w, h: b.h, cells: Int8Array.from(b.cells), p: b.p });
  const rowOf = (b, y) => Array.from(b.cells.subarray(y * b.w, (y + 1) * b.w));
  const colOf = (b, x) => { const a = new Array(b.h); for (let y = 0; y < b.h; y++) a[y] = b.cells[y * b.w + x]; return a; };

  // Propagate to a fixpoint. Returns {ok, rounds, solves, steps?}. Dirty-queue driven.
  // opts.trace: record each line deduction; opts.dirty: preset queue [{t:'r'|'c', i}]
  function propagate(b, opts) {
    opts = opts || {};
    const { w, h, p } = b;
    const dirtyR = new Uint8Array(h), dirtyC = new Uint8Array(w);
    if (opts.dirty) for (const d of opts.dirty) (d.t === 'r' ? dirtyR : dirtyC)[d.i] = 1;
    else { dirtyR.fill(1); dirtyC.fill(1); }
    let rounds = 0, solves = 0;
    const steps = opts.trace ? [] : null;
    for (;;) {
      let any = false;
      rounds++;
      for (let y = 0; y < h; y++) {
        if (!dirtyR[y]) continue; dirtyR[y] = 0; solves++;
        const cur = rowOf(b, y), nw = lineSolve(p.rows[y], cur);
        if (!nw) return { ok: false, rounds, solves, steps, bad: { t: 'r', i: y } };
        const ch = [];
        for (let x = 0; x < w; x++) if (nw[x] !== cur[x]) { b.cells[y * w + x] = nw[x]; dirtyC[x] = 1; any = true; ch.push(x); }
        if (steps && ch.length) steps.push({ t: 'r', i: y, cells: ch.map(x => [x, y, nw[x]]) });
      }
      for (let x = 0; x < w; x++) {
        if (!dirtyC[x]) continue; dirtyC[x] = 0; solves++;
        const cur = colOf(b, x), nw = lineSolve(p.cols[x], cur);
        if (!nw) return { ok: false, rounds, solves, steps, bad: { t: 'c', i: x } };
        const ch = [];
        for (let y = 0; y < h; y++) if (nw[y] !== cur[y]) { b.cells[y * w + x] = nw[y]; dirtyR[y] = 1; any = true; ch.push(y); }
        if (steps && ch.length) steps.push({ t: 'c', i: x, cells: ch.map(y => [x, y, nw[y]]) });
      }
      if (!any) break;
    }
    return { ok: true, rounds, solves, steps };
  }
  const isSolved = b => !b.cells.includes(U);

  // ---------- full solver ----------
  // Counts solutions up to opts.limit (default 2). Returns
  // {count, solutions:[grid..], stats:{rounds, lineSolves, guesses, maxDepth, probes}, truncated}
  function solve(p, opts) {
    opts = opts || {};
    validatePuzzle(p);
    const limit = opts.limit || 2, maxNodes = opts.maxNodes || 200000;
    const stats = { rounds: 0, lineSolves: 0, guesses: 0, maxDepth: 0 };
    const sols = []; let nodes = 0, truncated = false;
    const toGrid = b => { const g = []; for (let y = 0; y < b.h; y++) g.push(rowOf(b, y)); return g; };

    function rec(b, depth, dirty) {
      if (sols.length >= limit) return;
      if (++nodes > maxNodes) { truncated = true; return; }
      const r = propagate(b, { dirty });
      stats.rounds += r.rounds; stats.lineSolves += r.solves;
      if (!r.ok) return;
      if (isSolved(b)) { sols.push(toGrid(b)); return; }
      // choose the unknown cell in the most constrained line (fewest unknowns, ties -> first)
      let best = -1, bestScore = 1e9;
      for (let i = 0; i < b.cells.length; i++) {
        if (b.cells[i] !== U) continue;
        const x = i % b.w, y = (i / b.w) | 0;
        let ur = 0, uc = 0;
        for (let t = 0; t < b.w; t++) if (b.cells[y * b.w + t] === U) ur++;
        for (let t = 0; t < b.h; t++) if (b.cells[t * b.w + x] === U) uc++;
        const s = Math.min(ur, uc) * 1000 + Math.max(ur, uc);
        if (s < bestScore) { bestScore = s; best = i; }
      }
      const x = best % b.w, y = (best / b.w) | 0;
      stats.guesses++; stats.maxDepth = Math.max(stats.maxDepth, depth + 1);
      for (const v of [1, 0]) {
        const c = cloneBoard(b); c.cells[best] = v;
        rec(c, depth + 1, [{ t: 'r', i: y }, { t: 'c', i: x }]);
        if (sols.length >= limit) return;
      }
    }
    rec(makeBoard(p), 0, null);
    return { count: sols.length, solutions: sols, stats, truncated, exhaustive: !truncated && sols.length < limit };
  }


  // ---------- hints ----------
  // marks: Int8Array/array of w*h with -1 unknown, 1 filled, 0 crossed.
  // Returns {kind:'mistake'|'line'|'probe'|'none', ...}. Never reveals anything the clues don't force.
  function findHint(p, marks) {
    const { w, h } = validatePuzzle(p);
    const b = makeBoard(p); b.cells.set(marks);
    const lines = [];
    for (let y = 0; y < h; y++) lines.push({ t: 'r', i: y, clue: p.rows[y], cur: rowOf(b, y) });
    for (let x = 0; x < w; x++) lines.push({ t: 'c', i: x, clue: p.cols[x], cur: colOf(b, x) });
    let best = null;
    for (const L of lines) {
      const nw = lineSolve(L.clue, L.cur);
      if (!nw) return { kind: 'mistake', t: L.t, i: L.i, message: (L.t === 'r' ? 'Row ' : 'Column ') + (L.i + 1) + ' [' + (L.clue.join(' ') || '0') + '] can no longer satisfy its clue — something in it is wrong.' };
      const cells = [];
      nw.forEach((v, k) => { if (v !== L.cur[k]) cells.push(L.t === 'r' ? [k, L.i, v] : [L.i, k, v]); });
      if (!cells.length) continue;
      const known = L.cur.filter(v => v !== U).length;
      const sum = L.clue.reduce((a, c) => a + c, 0), filled = L.cur.filter(v => v === 1).length;
      const slack = L.cur.length - sum - Math.max(0, L.clue.length - 1);
      let why;
      if (!L.clue.length) why = 'its clue is empty, so every cell is empty';
      else if (filled === sum) why = 'all ' + sum + ' filled cells are already placed, so the rest must be empty';
      else if (known === 0 && slack === 0) why = 'the blocks plus gaps exactly fill the line, so there is only one arrangement';
      else if (known === 0) why = 'the blocks can only slide ' + slack + ' cell' + (slack === 1 ? '' : 's') + ', so the middle of any block longer than that is always filled';
      else why = 'with the cells already known, the blocks can only be arranged in ways that agree on these cells';
      const cand = { score: known === 0 ? 1e6 : -known - cells.length * 0.01, kind: 'line', t: L.t, i: L.i, cells, message: (L.t === 'r' ? 'Row ' : 'Column ') + (L.i + 1) + ' [' + L.clue.join(' ') + ']: ' + why + '.' };
      if (!best || cand.score < best.score) best = cand;
    }
    if (best) return best;
    if (!b.cells.includes(U)) return { kind: 'none', message: 'Nothing left to deduce.' };
    for (let i = 0; i < b.cells.length; i++) {
      if (b.cells[i] !== U) continue;
      const x = i % w, y = (i / w) | 0;
      for (const v of [1, 0]) {
        const c = cloneBoard(b); c.cells[i] = v;
        const pr = propagate(c, { dirty: [{ t: 'r', i: y }, { t: 'c', i: x }] });
        if (!pr.ok) {
          const where = (pr.bad.t === 'r' ? 'row ' : 'column ') + (pr.bad.i + 1);
          return { kind: 'probe', cells: [[x, y, v ? 0 : 1]], t: pr.bad.t, i: pr.bad.i, message: 'No single line decides this, but if (' + (x + 1) + ',' + (y + 1) + ') were ' + (v ? 'filled' : 'empty') + ', ' + where + ' would become impossible — so it must be ' + (v ? 'empty' : 'filled') + '.' };
        }
      }
    }
    return { kind: 'none', message: 'This needs deeper guessing; no one-step deduction exists.' };
  }

  // ---------- difficulty ----------
  // tier 0: line logic only. tier 1: needs one-level contradiction probing. tier 2: needs deeper search.
  function rate(p, opts) {
    const { w, h } = validatePuzzle(p);
    if (w * h > 1600 && !(opts && opts.force)) return { solvable: true, unique: true, tier: -2, label: 'unrated', score: 0 };
    const b = makeBoard(p);
    const r = propagate(b);
    if (!r.ok) return { solvable: false, unique: false, tier: -1, label: 'contradictory', score: 0 };
    if (isSolved(b)) {
      const score = Math.round(10 * r.rounds + r.solves / 4 + (w * h) / 10);
      return { solvable: true, unique: true, tier: 0, rounds: r.rounds, lineSolves: r.solves, score, label: r.rounds <= 3 ? 'easy' : r.rounds <= 6 ? 'medium' : 'hard' };
    }
    // probing: for every unknown cell try both values; keep forced consequences
    let probes = 0, changed = true;
    while (changed && !isSolved(b)) {
      changed = false;
      for (let i = 0; i < b.cells.length; i++) {
        if (b.cells[i] !== U) continue;
        const x = i % w, y = (i / w) | 0;
        const bad = [];
        for (const v of [1, 0]) {
          const c = cloneBoard(b); c.cells[i] = v; probes++;
          const pr = propagate(c, { dirty: [{ t: 'r', i: y }, { t: 'c', i: x }] });
          if (!pr.ok) bad.push(v);
        }
        if (bad.length === 2) return { solvable: false, unique: false, tier: -1, label: 'contradictory', score: 0 };
        if (bad.length === 1) {
          b.cells[i] = bad[0] === 1 ? 0 : 1;
          const pr = propagate(b, { dirty: [{ t: 'r', i: y }, { t: 'c', i: x }] });
          if (!pr.ok) return { solvable: false, unique: false, tier: -1, label: 'contradictory', score: 0 };
          changed = true;
        }
      }
    }
    if (isSolved(b)) return { solvable: true, unique: true, tier: 1, probes, rounds: r.rounds, score: 100 + Math.round(probes / 4 + r.rounds * 5), label: 'expert' };
    const s = solve(p, { limit: 2 });
    return { solvable: s.count > 0, unique: s.count === 1 && !s.truncated, tier: 2, guesses: s.stats.guesses, probes, score: 300 + s.stats.guesses * 3, label: s.count === 1 && !s.truncated ? 'brutal (needs guessing)' : s.count > 1 ? 'ambiguous' : 'unsolvable' };
  }
  const TIER_FOR = { easy: 0, medium: 0, hard: 0, expert: 1 };
  function meetsDifficulty(r, want) {
    if (!r.unique) return false;
    if (!want || want === 'any') return true;
    if (want === 'expert') return r.tier === 1;
    if (want === 'brutal') return r.tier === 2;
    return r.tier === 0 && r.label === want;
  }

  // ---------- PRNG & generator ----------
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a; t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hashSeed(s) {
    if (typeof s === 'number') return s >>> 0;
    let h = 2166136261;
    for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  // blobby picture: value-noise at a few octaves, thresholded to hit target density
  function blobGrid(w, h, density, rnd) {
    const field = new Float64Array(w * h);
    for (const [cell, amp] of [[Math.max(2, Math.round(Math.max(w, h) / 2.5)), 1], [Math.max(2, Math.round(Math.max(w, h) / 5)), 0.6], [2, 0.35]]) {
      const gw = Math.ceil(w / cell) + 2, gh = Math.ceil(h / cell) + 2;
      const g = Array.from({ length: gw * gh }, rnd);
      const sm = t => t * t * (3 - 2 * t);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const fx = x / cell, fy = y / cell, ix = fx | 0, iy = fy | 0, tx = sm(fx - ix), ty = sm(fy - iy);
        const a = g[iy * gw + ix], b = g[iy * gw + ix + 1], c = g[(iy + 1) * gw + ix], d = g[(iy + 1) * gw + ix + 1];
        field[y * w + x] += amp * ((a + (b - a) * tx) * (1 - ty) + (c + (d - c) * tx) * ty);
      }
    }
    return thresholdField(field, w, h, density);
  }
  function thresholdField(field, w, h, density) {
    const sorted = Float64Array.from(field).sort();
    const cut = sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(sorted.length * (1 - density))))];
    const grid = [];
    for (let y = 0; y < h; y++) { const r = []; for (let x = 0; x < w; x++) r.push(field[y * w + x] >= cut ? 1 : 0); grid.push(r); }
    return grid;
  }

  // Make a picture uniquely solvable by flipping cells where two solutions differ.
  function makeUnique(grid, rnd, maxIter) {
    const g = grid.map(r => r.slice());
    for (let it = 0; it < (maxIter || 400); it++) {
      const p = cluesFromGrid(g);
      if (p.rows.every(c => !c.length) && p.cols.every(c => !c.length)) return null;
      const s = solve(p, { limit: 2, maxNodes: 20000 });
      if (s.truncated) return null;
      if (s.count === 1) return g;
      const [a, b] = s.solutions;
      const diff = [];
      for (let y = 0; y < g.length; y++) for (let x = 0; x < g[0].length; x++) if (a[y][x] !== b[y][x]) diff.push([x, y]);
      // flip a differing cell to the value in the *other* solution: the target changes so these two stop colliding
      const [x, y] = diff[Math.floor(rnd() * diff.length)];
      g[y][x] = g[y][x] ? 0 : 1;
    }
    return null;
  }

  // opts: {w,h,density,seed,difficulty,attempts}
  function generate(opts) {
    const w = opts.w | 0, h = opts.h | 0;
    if (w < 2 || h < 2 || w > 40 || h > 40) throw new Error('size must be between 2x2 and 40x40');
    const density = opts.density == null ? 0.55 : opts.density;
    if (!(density > 0.05 && density < 0.95)) throw new Error('density must be between 0.05 and 0.95');
    const seed = hashSeed(opts.seed == null ? 1 : opts.seed);
    const attempts = opts.attempts || 60;
    const want = opts.difficulty || 'any';
    let best = null;
    for (let a = 0; a < attempts; a++) {
      const rnd = mulberry32(seed + a * 7919);
      const dens = Math.min(0.9, Math.max(0.1, density + (rnd() - 0.5) * 0.1 * Math.min(a, 6)));
      let pic;
      if (a % 3 === 2) { pic = []; for (let y = 0; y < h; y++) { const r = []; for (let x = 0; x < w; x++) r.push(rnd() < dens ? 1 : 0); pic.push(r); } }
      else pic = blobGrid(w, h, dens, rnd);
      const uni = makeUnique(pic, rnd);
      if (!uni) continue;
      const p = cluesFromGrid(uni), r = rate(p);
      const cand = { grid: uni, rows: p.rows, cols: p.cols, rating: r, seed: opts.seed == null ? 1 : opts.seed, attempt: a };
      if (meetsDifficulty(r, want)) return cand;
      if (!best || Math.abs(r.score - (opts.targetScore || 0)) < Math.abs(best.rating.score - (opts.targetScore || 0))) best = cand;
    }
    if (opts.strict) throw new Error('could not generate a ' + want + ' ' + w + 'x' + h + ' puzzle in ' + attempts + ' attempts');
    if (!best) throw new Error('generation failed; try another seed');
    best.relaxed = true; // difficulty target not met, still unique
    return best;
  }

  // ---------- image -> grid ----------
  // rgba: Uint8ClampedArray of w*h*4 resampled by box average into gw x gh.
  function gridFromRGBA(rgba, w, h, gw, gh, opts) {
    opts = opts || {};
    const lum = new Float64Array(gw * gh);
    for (let gy = 0; gy < gh; gy++) for (let gx = 0; gx < gw; gx++) {
      const x0 = Math.floor(gx * w / gw), x1 = Math.max(x0 + 1, Math.floor((gx + 1) * w / gw));
      const y0 = Math.floor(gy * h / gh), y1 = Math.max(y0 + 1, Math.floor((gy + 1) * h / gh));
      let s = 0, n = 0;
      for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
        const i = (y * w + x) * 4, a = rgba[i + 3] / 255;
        s += (255 - (0.299 * rgba[i] + 0.587 * rgba[i + 1] + 0.114 * rgba[i + 2])) * a; n++;
      }
      lum[gy * gw + gx] = s / n; // darkness 0..255
    }
    let cut = opts.threshold;
    if (cut == null) { // Otsu
      const hist = new Array(256).fill(0); for (const v of lum) hist[Math.min(255, Math.round(v))]++;
      let sum = 0; for (let i = 0; i < 256; i++) sum += i * hist[i];
      let wB = 0, sB = 0, mx = -1; cut = 128; const tot = lum.length;
      for (let t = 0; t < 256; t++) {
        wB += hist[t]; if (!wB) continue; const wF = tot - wB; if (!wF) break;
        sB += t * hist[t]; const mB = sB / wB, mF = (sum - sB) / wF, v = wB * wF * (mB - mF) * (mB - mF);
        if (v > mx) { mx = v; cut = t + 0.5; }
      }
    }
    const grid = [];
    for (let y = 0; y < gh; y++) { const r = []; for (let x = 0; x < gw; x++) r.push(lum[y * gw + x] > cut ? 1 : 0); grid.push(r); }
    return grid;
  }

  // ---------- formats ----------
  function parsePuzzle(text) {
    text = String(text).trim();
    if (!text) throw new Error('nothing to import');
    if (text[0] === '{') {
      let o; try { o = JSON.parse(text); } catch (e) { throw new Error('invalid JSON: ' + e.message); }
      if (o.grid && !o.rows) Object.assign(o, cluesFromGrid(o.grid));
      if (Array.isArray(o.rows) && Array.isArray(o.cols)) {
        const nz = c => Array.isArray(c) ? c.filter(v => v !== 0) : c; // [0] means an empty line
        o.rows = o.rows.map(nz); o.cols = o.cols.map(nz);
      }
      validatePuzzle(o); return { rows: o.rows, cols: o.cols, title: o.title };
    }
    // .non format
    const lines = text.split(/\r?\n/).map(s => s.trim());
    const o = { rows: null, cols: null, title: '' }; let mode = null, buf = [];
    const flush = () => { if (mode === 'rows') o.rows = buf; if (mode === 'columns') o.cols = buf; buf = []; };
    for (const ln of lines) {
      if (!ln) continue;
      const m = /^(width|height|title|by|rows|columns|goal|copyright|licence|license)\b\s*(.*)$/i.exec(ln);
      if (m) {
        flush(); const key = m[1].toLowerCase(); mode = null;
        if (key === 'rows' || key === 'columns') mode = key;
        else if (key === 'title') o.title = m[2].replace(/^"|"$/g, '');
        continue;
      }
      if (mode) {
        if (ln === '0' || ln === '-') buf.push([]);
        else {
          const parts = ln.split(/[,\s]+/).filter(Boolean).map(Number);
          if (parts.some(n => !Number.isInteger(n))) throw new Error('bad clue line: "' + ln + '"');
          buf.push(parts);
        }
      }
    }
    flush();
    if (!o.rows || !o.cols) throw new Error('could not find "rows" and "columns" sections');
    o.rows = o.rows.map(c => c.filter(v => v !== 0)); o.cols = o.cols.map(c => c.filter(v => v !== 0));
    validatePuzzle(o); return o;
  }
  function toNon(p, title) {
    const f = a => a.map(c => c.length ? c.join(',') : '0').join('\n');
    return 'title "' + (title || 'Inkgrid puzzle') + '"\nwidth ' + p.cols.length + '\nheight ' + p.rows.length + '\n\nrows\n' + f(p.rows) + '\n\ncolumns\n' + f(p.cols) + '\n';
  }
  function render(grid, on, off) {
    return grid.map(r => r.map(c => c === 1 ? (on || '██') : c === 0 ? (off || '··') : '??').join('')).join('\n');
  }
  // compact share token: clues only, base64url of JSON
  function encodeShare(p) {
    const s = JSON.stringify({ r: p.rows, c: p.cols });
    const b = typeof Buffer !== 'undefined' ? Buffer.from(s, 'utf8').toString('base64') : btoa(unescape(encodeURIComponent(s)));
    return b.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function decodeShare(tok) {
    let b = String(tok).replace(/-/g, '+').replace(/_/g, '/'); while (b.length % 4) b += '=';
    let s; try { s = typeof Buffer !== 'undefined' ? Buffer.from(b, 'base64').toString('utf8') : decodeURIComponent(escape(atob(b))); } catch (e) { throw new Error('corrupt share link'); }
    let o; try { o = JSON.parse(s); } catch (e) { throw new Error('corrupt share link'); }
    const p = { rows: o.r, cols: o.c }; validatePuzzle(p); return p;
  }

  return {
    UNKNOWN: U, lineClue, cluesFromGrid, validatePuzzle, lineSolve, makeBoard, cloneBoard, propagate, isSolved,
    solve, rate, findHint, meetsDifficulty, mulberry32, hashSeed, blobGrid, makeUnique, generate, gridFromRGBA,
    parsePuzzle, toNon, render, encodeShare, decodeShare, rowOf, colOf,
  };
});
