import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Game } from '../src/board.js';
import { solve, bruteForce, chooseMove, InconsistentBoard } from '../src/solver.js';
import { makeRng } from '../src/rng.js';

// Play a few random safe-ish moves on a small board to get a mid-game position.
function randomPosition(w, h, mines, seed, steps) {
  const rng = makeRng(seed);
  const g = new Game({ w, h, mines, seed });
  g.reveal(Math.floor(rng() * g.n));
  for (let s = 0; s < steps && g.status === 'playing'; s++) {
    const hid = []; for (let i = 0; i < g.n; i++) if (g.state[i] === 0 && !g.mine[i]) hid.push(i);
    if (!hid.length) break;
    g.reveal(hid[Math.floor(rng() * hid.length)]);
  }
  return g;
}

test('solver matches brute force on 150 random small positions', () => {
  let checked = 0;
  for (let s = 0; s < 150; s++) {
    const w = 4 + (s % 3), h = 4 + (s % 2), mines = 3 + (s % 4);
    const g = randomPosition(w, h, mines, 's' + s, 1 + (s % 4));
    if (g.status !== 'playing') continue;
    const view = g.view();
    const res = solve(view, w, h, mines);
    const ref = bruteForce(view, w, h, mines);
    assert.ok(ref.total > 0);
    assert.equal(res.stats.solutions, BigInt(ref.total), `solution count seed ${s}`);
    for (const [c, p] of ref.prob) assert.ok(Math.abs(res.prob[c] - p) < 1e-12, `seed ${s} cell ${c}: ${res.prob[c]} vs ${p}`);
    checked++;
  }
  assert.ok(checked > 100, 'enough positions exercised: ' + checked);
});

test('certain cells are never wrong on the real layout', () => {
  for (let s = 0; s < 60; s++) {
    const g = randomPosition(9, 9, 10, 'c' + s, 6);
    if (g.status !== 'playing') continue;
    const r = solve(g.view(), 9, 9, 10);
    for (const c of r.certainSafe) assert.equal(g.mine[c], 0);
    for (const c of r.certainMine) assert.equal(g.mine[c], 1);
  }
});

test('empty board: every cell has probability mines/cells', () => {
  const r = solve(new Int8Array(30 * 16).fill(-1), 30, 16, 99);
  assert.ok(Math.abs(r.prob[5] - 99 / 480) < 1e-12);
});

test('classic 1-2-1 pattern is resolved exactly', () => {
  // Row 0 hidden, row 1 shows 1 2 1 -> mines at the two ends' ... verify by brute force on a 3-wide strip
  const w = 5, h = 2, M = 3;
  const view = new Int8Array(10).fill(-1);
  view[5] = 1; view[6] = 2; view[7] = 1; // revealed second row middle three, hidden elsewhere
  const r = solve(view, w, h, M);
  const ref = bruteForce(view, w, h, M);
  for (const [c, p] of ref.prob) assert.ok(Math.abs(r.prob[c] - p) < 1e-12);
});

test('global mine count creates certainty (all mines accounted for -> interior safe)', () => {
  // 1 mine total, a "1" touches 2 hidden cells; the far hidden cells must be safe.
  const w = 6, h = 1, M = 1;
  const view = new Int8Array(6).fill(-1);
  view[0] = 1; // neighbours: cell 1 only -> cell 1 is a mine
  const r = solve(view, w, h, M);
  assert.deepEqual(r.certainMine, [1]);
  assert.deepEqual(r.certainSafe, [2, 3, 4, 5]);
});

test('inconsistent boards throw', () => {
  const view = new Int8Array(9).fill(-1);
  view[4] = 5; view[0] = 0; // 0 next to hidden cells that the 5 requires to be mines? 0 touches cell 1,3
  assert.throws(() => solve(view, 3, 3, 2), InconsistentBoard);
  assert.throws(() => solve(new Int8Array(9).fill(-1), 3, 3, 10), InconsistentBoard);
});

test('chooseMove prefers certain-safe cells, else lowest probability', () => {
  const g = randomPosition(9, 9, 10, 'move', 3);
  const v = g.view(); const r = solve(v, 9, 9, 10);
  const m = chooseMove(r, v, 9, 9);
  if (r.certainSafe.length) assert.equal(m.kind, 'safe');
  else { assert.equal(m.kind, 'guess'); assert.equal(m.p, Math.min(...[...r.prob].filter(x => !Number.isNaN(x)))); }
});
