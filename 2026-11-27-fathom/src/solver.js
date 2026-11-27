// Exact Minesweeper probability engine.
//
// Given the numbers currently showing on a board and the total mine count, compute for
// every hidden cell the exact probability that it holds a mine, under the uniform
// distribution over all mine placements consistent with what is showing.
//
//  1. Hidden cells touching a revealed number are the *frontier*; all other hidden cells
//     are the *interior* (unconstrained except through the global mine total).
//  2. The frontier splits into independent connected *components* (cells linked by sharing a
//     constraint). Each component is enumerated exactly by backtracking with constraint
//     pruning, tallying, for each mine count k, the number of solutions and how many of them
//     put a mine on each cell.
//  3. Components are convolved over k, and each total frontier mine count f is weighted by
//     C(U, M-f) — the number of ways to scatter the remaining mines over the U interior cells.
//  4. All arithmetic on counts is BigInt, so there is no floating-point drift; a probability
//     is exactly 0 or 1 iff the cell is *certain*.
//
// Flags are deliberately ignored: a player's flag is a belief, not information.
import { neighborTable } from './board.js';

const nbCache = new Map();
function neighbors(w, h) {
  const key = w + 'x' + h;
  let t = nbCache.get(key);
  if (!t) { t = neighborTable(w, h); nbCache.set(key, t); }
  return t;
}

export class InconsistentBoard extends Error {
  constructor(msg) { super(msg); this.name = 'InconsistentBoard'; }
}

const SCALE = 10n ** 30n;
function ratio(a, b) {
  if (a === 0n) return 0;
  if (a >= b) return 1;
  const p = Number((a * SCALE) / b) / 1e30;
  return Math.min(Math.max(p, 1e-30), 1 - 1e-15);
}

/** Row of binomials C(U, r) for r = 0..maxR as BigInt (0n beyond U). */
function binomRow(U, maxR) {
  const row = new Array(maxR + 1).fill(0n);
  row[0] = 1n;
  for (let r = 0; r < maxR; r++) {
    if (r >= U) break;
    row[r + 1] = (row[r] * BigInt(U - r)) / BigInt(r + 1);
  }
  return row;
}

/** Enumerate all solutions of one component. Returns {N:number[], tally:Float64Array[], nodes, truncated}. */
function enumerateComponent(cells, cons, maxNodes, mineCap) {
  const m = cells.length;
  const local = new Map(cells.map((c, i) => [c, i]));
  const consOf = cells.map(() => []);
  const need = new Int32Array(cons.length), unk = new Int32Array(cons.length);
  cons.forEach((k, ci) => {
    need[ci] = k.need; unk[ci] = k.cells.length;
    for (const c of k.cells) consOf[local.get(c)].push(ci);
  });
  // Order: BFS through constraints starting from the most constrained cell, to prune early.
  const order = [], seen = new Uint8Array(m), consSeen = new Uint8Array(cons.length);
  const lcons = cons.map(k => k.cells.map(c => local.get(c)));
  const startOrder = [...Array(m).keys()].sort((a, b) => consOf[b].length - consOf[a].length || a - b);
  for (const s of startOrder) {
    if (seen[s]) continue;
    seen[s] = 1; const q = [s];
    while (q.length) {
      const c = q.shift(); order.push(c);
      for (const ci of consOf[c]) {
        if (consSeen[ci]) continue; consSeen[ci] = 1;
        for (const d of lcons[ci]) if (!seen[d]) { seen[d] = 1; q.push(d); }
      }
    }
  }
  const N = new Array(m + 1).fill(0);
  const tally = Array.from({ length: m + 1 }, () => null);
  const assign = new Int8Array(m);
  let nodes = 0, truncated = false;

  function rec(d, mines) {
    if (truncated) return;
    if (d === m) {
      N[mines]++;
      let t = tally[mines];
      if (!t) t = tally[mines] = new Float64Array(m);
      for (let i = 0; i < m; i++) if (assign[i]) t[i]++;
      return;
    }
    if (++nodes > maxNodes) { truncated = true; return; }
    const c = order[d];
    for (let v = 0; v <= 1; v++) {
      if (v && mines + 1 > mineCap) continue;
      let ok = true, done = 0;
      const list = consOf[c];
      for (; done < list.length; done++) {
        const ci = list[done];
        need[ci] -= v; unk[ci]--;
        if (need[ci] < 0 || need[ci] > unk[ci]) { ok = false; done++; break; }
      }
      if (ok) { assign[c] = v; rec(d + 1, mines + v); assign[c] = 0; }
      for (let t = 0; t < done; t++) { const ci = list[t]; need[ci] += v; unk[ci]++; }
      if (truncated) return;
    }
  }
  rec(0, 0);
  return { N, tally, nodes, truncated, local };
}

/**
 * @param {Int8Array|number[]} view  -1 = hidden (or flagged), 0..8 = revealed number
 * @returns result with prob (Float64Array, NaN on revealed cells), certainSafe, certainMine, exact...
 */
export function solve(view, w, h, totalMines, opts = {}) {
  const maxNodes = opts.maxNodes ?? 20_000_000;
  const nb = neighbors(w, h);
  const n = w * h;
  if (view.length !== n) throw new RangeError('view size does not match board');
  const prob = new Float64Array(n).fill(NaN);

  // Build constraints (deduplicated by cell set).
  const consMap = new Map();
  const isFrontier = new Uint8Array(n);
  let hiddenCount = 0;
  for (let i = 0; i < n; i++) {
    if (view[i] < 0) { hiddenCount++; continue; }
    const hid = nb[i].filter(j => view[j] < 0);
    if (view[i] > hid.length) throw new InconsistentBoard(`cell ${i} shows ${view[i]} but has only ${hid.length} hidden neighbours`);
    if (hid.length === 0) continue;
    const key = hid.join(',') + ':' + view[i];
    if (!consMap.has(key)) consMap.set(key, { cells: hid, need: view[i] });
    for (const j of hid) isFrontier[j] = 1;
  }
  const cons = [...consMap.values()];
  // Conflicting duplicate constraints (same cells, different need) are caught by enumeration (no solutions).

  const frontier = [], interior = [];
  for (let i = 0; i < n; i++) if (view[i] < 0) (isFrontier[i] ? frontier : interior).push(i);
  const U = interior.length;
  const M = totalMines;
  if (M < 0 || M > hiddenCount) throw new InconsistentBoard('mine total impossible for number of hidden cells');

  // Connected components over frontier cells.
  const parent = new Map(frontier.map(c => [c, c]));
  const find = x => { while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); } return x; };
  for (const k of cons) for (let i = 1; i < k.cells.length; i++) parent.set(find(k.cells[i]), find(k.cells[0]));
  const groups = new Map();
  for (const c of frontier) { const r = find(c); if (!groups.has(r)) groups.set(r, { cells: [], cons: [] }); groups.get(r).cells.push(c); }
  for (const k of cons) groups.get(find(k.cells[0])).cons.push(k);

  let nodes = 0, exact = true;
  const comps = [];
  const approx = []; // components we could not enumerate
  for (const g of groups.values()) {
    const e = enumerateComponent(g.cells, g.cons, maxNodes, M);
    nodes += e.nodes;
    if (e.truncated) { exact = false; approx.push(g); continue; }
    comps.push({ ...g, ...e });
  }

  // Convolve component mine-count distributions.
  const toBig = arr => arr.map(x => BigInt(x));
  const convolve = (A, B) => {
    const out = new Array(A.length + B.length - 1).fill(0n);
    for (let i = 0; i < A.length; i++) if (A[i]) for (let j = 0; j < B.length; j++) if (B[j]) out[i + j] += A[i] * B[j];
    return out;
  };
  const compN = comps.map(c => { const a = toBig(c.N); while (a.length > 1 && a[a.length - 1] === 0n) a.pop(); return a; });
  const convOf = skip => {
    let acc = [1n];
    compN.forEach((a, i) => { if (i !== skip) acc = convolve(acc, a); });
    return acc;
  };
  const all = convOf(-1);
  const C = binomRow(U, M);
  let Z = 0n, interiorNum = 0n;
  for (let f = 0; f < all.length && f <= M; f++) {
    if (!all[f]) continue;
    const r = M - f;
    const w_ = all[f] * C[r];
    Z += w_; interiorNum += w_ * BigInt(r);
  }
  if (Z === 0n) throw new InconsistentBoard('no mine placement is consistent with this board');

  let certainSafe = [], certainMine = [];
  for (let ci = 0; ci < comps.length; ci++) {
    const comp = comps[ci];
    const others = convOf(ci);
    for (let li = 0; li < comp.cells.length; li++) {
      const cell = comp.cells[li];
      let wt = 0n;
      for (let k = 0; k < comp.tally.length; k++) {
        const t = comp.tally[k];
        if (!t || !t[li]) continue;
        const cnt = BigInt(t[li]);
        for (let j = 0; j < others.length; j++) {
          if (!others[j]) continue;
          const r = M - k - j;
          if (r < 0 || r > U) continue;
          wt += cnt * others[j] * C[r];
        }
      }
      prob[cell] = ratio(wt, Z);
    }
  }
  if (U > 0) {
    const p = ratio(interiorNum, Z * BigInt(U));
    for (const c of interior) prob[c] = p;
  }
  // Components we could not enumerate: fall back to a local estimate and flag the result inexact.
  for (const g of approx) for (const c of g.cells) {
    let s = 0, cnt = 0;
    for (const k of g.cons) if (k.cells.includes(c)) { s += k.need / k.cells.length; cnt++; }
    prob[c] = cnt ? Math.min(0.999, Math.max(0.001, s / cnt)) : 0.5;
  }
  for (let i = 0; i < n; i++) {
    if (view[i] >= 0) continue;
    if (prob[i] === 0 && exact) certainSafe.push(i);
    else if (prob[i] === 1 && exact) certainMine.push(i);
  }
  return {
    prob, certainSafe, certainMine, exact,
    stats: { w, h, hidden: hiddenCount, frontier: frontier.length, interior: U, components: groups.size, nodes, solutions: Z },
  };
}

/**
 * Pick the next move from a solve() result.
 * @returns {{kind:'safe'|'guess'|'none', cells:number[], p:number}}
 */
export function chooseMove(result, view, w, h) {
  if (result.certainSafe.length) return { kind: 'safe', cells: result.certainSafe.slice(), p: 0 };
  const nb = neighbors(w, h);
  let best = -1, bestP = Infinity, bestZ = -1;
  for (let i = 0; i < view.length; i++) {
    if (view[i] >= 0) continue;
    const p = result.prob[i];
    if (p >= 1) continue;
    // Tie-break: probability the cell would be a zero (opens an area), approximated by independence.
    let z = 1 - p;
    for (const j of nb[i]) if (view[j] < 0) z *= 1 - result.prob[j];
    if (p < bestP - 1e-12 || (Math.abs(p - bestP) <= 1e-12 && z > bestZ + 1e-12)) { best = i; bestP = p; bestZ = z; }
  }
  if (best < 0) return { kind: 'none', cells: [], p: 1 };
  return { kind: 'guess', cells: [best], p: bestP };
}

/** Brute-force reference: enumerate every placement of M mines over hidden cells. For tests only (tiny boards). */
export function bruteForce(view, w, h, M) {
  const nb = neighbors(w, h);
  const hidden = []; for (let i = 0; i < view.length; i++) if (view[i] < 0) hidden.push(i);
  const tallies = new Map(hidden.map(c => [c, 0]));
  let total = 0;
  const chosen = new Uint8Array(view.length);
  const check = () => {
    for (let i = 0; i < view.length; i++) {
      if (view[i] < 0) continue;
      let c = 0; for (const j of nb[i]) c += chosen[j];
      if (c !== view[i]) return false;
    }
    return true;
  };
  (function rec(pos, left) {
    if (left === 0) { if (check()) { total++; for (const c of hidden) if (chosen[c]) tallies.set(c, tallies.get(c) + 1); } return; }
    if (hidden.length - pos < left) return;
    for (let k = pos; k < hidden.length; k++) { chosen[hidden[k]] = 1; rec(k + 1, left - 1); chosen[hidden[k]] = 0; }
  })(0, M);
  return { total, prob: new Map(hidden.map(c => [c, total ? tallies.get(c) / total : NaN])) };
}
