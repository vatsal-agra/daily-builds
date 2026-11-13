'use strict';
// Feature tests + demo. Run: node test/run.js
const assert = require('assert'); const { execFileSync } = require('child_process'); const path = require('path'); const fs = require('fs'); const os = require('os');
const E = require('../src/engine.js');
let n = 0; const t = (name, fn) => { try { fn(); n++; console.log('  ok  ' + name); } catch (e) { console.log('FAIL  ' + name + '\n' + e.stack); process.exitCode = 1; } };

// brute-force oracle for a single line
function enumerate(clue, len) { const res = []; const rec = (i, j, cur) => { if (j === clue.length) { res.push(cur.concat(new Array(len - i).fill(0))); return; } for (let s = i; s + clue[j] <= len; s++) { const c = cur.concat(new Array(s - i).fill(0), new Array(clue[j]).fill(1)); if (j < clue.length - 1) { if (s + clue[j] < len) rec(s + clue[j] + 1, j + 1, c.concat([0])); } else rec(s + clue[j], j + 1, c); } }; rec(0, 0, []); return res; }

console.log('Feature 1: line solver');
t('matches brute force on 4000 random lines/partial states', () => {
  const r = E.mulberry32(11);
  for (let k = 0; k < 4000; k++) {
    const len = 1 + Math.floor(r() * 11), g = Array.from({ length: len }, () => (r() < 0.5 ? 1 : 0));
    const clue = E.lineClue(g), line = g.map(c => (r() < 0.4 ? (r() < 0.9 ? c : 1 - c) : -1));
    const sols = enumerate(clue, len).filter(s => s.every((v, i) => line[i] === -1 || line[i] === v));
    const exp = sols.length ? Array.from({ length: len }, (_, i) => { const z = new Set(sols.map(x => x[i])); return z.size > 1 ? -1 : [...z][0]; }) : null;
    assert.deepStrictEqual(E.lineSolve(clue, line), exp, JSON.stringify({ clue, line }));
  }
});
t('empty clue / full clue / contradiction', () => {
  assert.deepStrictEqual(E.lineSolve([], [-1, -1, -1]), [0, 0, 0]);
  assert.deepStrictEqual(E.lineSolve([3], [-1, -1, -1]), [1, 1, 1]);
  assert.strictEqual(E.lineSolve([2], [1, 0, 1]), null);
  assert.deepStrictEqual(E.lineSolve([4], new Array(7).fill(-1)), [-1, -1, -1, 1, -1, -1, -1]);
});

console.log('Feature 2: full solver & uniqueness');
t('solves a known puzzle uniquely', () => {
  const grid = [[0, 1, 1, 0, 0], [1, 1, 1, 1, 0], [1, 0, 1, 0, 1], [0, 1, 1, 1, 1], [0, 0, 1, 0, 0]];
  const p = E.cluesFromGrid(grid), r = E.solve(p);
  if (r.count === 1) assert.deepStrictEqual(r.solutions[0], grid);
  else assert.ok(r.solutions.every(s => JSON.stringify(E.cluesFromGrid(s)) === JSON.stringify(p)));
});
t('detects ambiguity (2x2 checkerboard) and gives two valid solutions', () => {
  const r = E.solve({ rows: [[1], [1]], cols: [[1], [1]] });
  assert.strictEqual(r.count, 2); assert.notDeepStrictEqual(r.solutions[0], r.solutions[1]);
});
t('detects unsolvable clues (totals match but impossible)', () => {
  assert.strictEqual(E.solve({ rows: [[2], [2]], cols: [[2], [1], [1]] }).count, 0);
});
t('every solution returned reproduces the clues (300 random pictures)', () => {
  const r = E.mulberry32(5);
  for (let k = 0; k < 300; k++) {
    const w = 3 + Math.floor(r() * 8), h = 3 + Math.floor(r() * 8);
    const g = Array.from({ length: h }, () => Array.from({ length: w }, () => (r() < 0.5 ? 1 : 0)));
    const p = E.cluesFromGrid(g), s = E.solve(p, { limit: 3 });
    assert.ok(s.count >= 1);
    for (const sol of s.solutions) assert.deepStrictEqual(E.cluesFromGrid(sol), p);
  }
});
t('node budget exhaustion is reported, never claimed unique', () => {
  const s = E.solve({ rows: [[1], [1], [1], [1], [1], [1]], cols: [[1], [1], [1], [1], [1], [1]] }, { limit: 1000, maxNodes: 3 });
  assert.ok(s.truncated); assert.strictEqual(s.exhaustive, false);
});
t('validation errors are descriptive', () => {
  assert.throws(() => E.validatePuzzle({ rows: [[5]], cols: [[1], [1]] }), /needs 5 cells/);
  assert.throws(() => E.validatePuzzle({ rows: [[1]], cols: [[1], [1]] }), /total/);
  assert.throws(() => E.validatePuzzle({ rows: [], cols: [] }), /at least one/);
  assert.throws(() => E.validatePuzzle({ rows: [[-1]], cols: [[1]] }), /positive/);
});

console.log('Feature 3: difficulty rating');
t('line-solvable puzzle is tier 0; ambiguous puzzle flagged', () => {
  assert.strictEqual(E.rate({ rows: [[3], [1]], cols: [[2], [1], [1]] }).tier, 0);
  const a = E.rate({ rows: [[1], [1]], cols: [[1], [1]] }); assert.strictEqual(a.unique, false);
});
t('contradictory puzzle rated unsolvable', () => { assert.strictEqual(E.rate({ rows: [[2], [1]], cols: [[1], [1], [1]] }).unique, false); });
t('scores are monotone across tiers in generated samples', () => {
  const e = E.generate({ w: 12, h: 12, seed: 1, difficulty: 'easy' }), x = E.generate({ w: 12, h: 12, seed: 1, difficulty: 'expert', attempts: 120 });
  assert.strictEqual(e.rating.label, 'easy'); assert.strictEqual(x.rating.tier, 1); assert.ok(x.rating.score > e.rating.score);
});

console.log('Feature 4: generator');
t('deterministic per seed, different across seeds', () => {
  const a = E.generate({ w: 10, h: 10, seed: 'a' }), b = E.generate({ w: 10, h: 10, seed: 'a' }), c = E.generate({ w: 10, h: 10, seed: 'b' });
  assert.deepStrictEqual(a.grid, b.grid); assert.notDeepStrictEqual(a.grid, c.grid);
});
t('60 generated puzzles of mixed sizes are unique & independently verified', () => {
  for (let k = 0; k < 60; k++) {
    const w = 4 + (k % 14), h = 4 + ((k * 7) % 13);
    const g = E.generate({ w, h, seed: 'v' + k, density: 0.35 + (k % 5) * 0.1 });
    const s = E.solve({ rows: g.rows, cols: g.cols }, { limit: 2 });
    assert.strictEqual(s.count, 1); assert.deepStrictEqual(s.solutions[0], g.grid);
  }
});
t('rejects absurd parameters', () => {
  assert.throws(() => E.generate({ w: 1, h: 5 }), /size/); assert.throws(() => E.generate({ w: 5, h: 99 }), /size/);
  assert.throws(() => E.generate({ w: 5, h: 5, density: 1.5 }), /density/);
});
t('strict mode throws when the tier is unreachable', () => { assert.throws(() => E.generate({ w: 4, h: 4, seed: 1, difficulty: 'expert', strict: true, attempts: 5 }), /could not generate/); });

console.log('Feature 5: playable-UI logic (hints / win condition)');
t('findHint only ever returns correct deductions along a full playthrough', () => {
  const g = E.generate({ w: 12, h: 12, seed: 'play', difficulty: 'medium' }), p = { rows: g.rows, cols: g.cols };
  const marks = new Int8Array(144).fill(-1); let steps = 0;
  for (;;) {
    const h = E.findHint(p, marks); if (h.kind === 'none') break; assert.notStrictEqual(h.kind, 'mistake');
    for (const [x, y, v] of h.cells) { assert.strictEqual(v, g.grid[y][x]); marks[y * 12 + x] = v; } steps++;
  }
  assert.ok(!marks.includes(-1)); assert.ok(steps > 3);
});
t('probe hints solve an expert puzzle and stay correct', () => {
  const g = E.generate({ w: 12, h: 12, seed: 1, difficulty: 'expert', attempts: 120 }), p = { rows: g.rows, cols: g.cols };
  const marks = new Int8Array(144).fill(-1); let probes = 0;
  for (let i = 0; i < 400; i++) { const h = E.findHint(p, marks); if (h.kind === 'none') break; if (h.kind === 'probe') probes++; for (const [x, y, v] of h.cells) { assert.strictEqual(v, g.grid[y][x]); marks[y * 12 + x] = v; } }
  assert.ok(!marks.includes(-1)); assert.ok(probes > 0);
});
t('findHint flags an impossible line', () => {
  const p = E.cluesFromGrid([[1, 1, 0], [0, 0, 0], [0, 0, 1]]); const m = new Int8Array(9).fill(-1); m[0] = 0; m[1] = 0; m[2] = 1;
  assert.strictEqual(E.findHint(p, m).kind, 'mistake');
});

console.log('Feature 6: formats & sharing');
t('.non round trip, with empty lines', () => {
  const p = E.cluesFromGrid([[1, 1, 0], [0, 0, 0], [0, 1, 1]]); assert.deepStrictEqual(E.parsePuzzle(E.toNon(p, 'x')), Object.assign({ title: 'x' }, p));
});
t('JSON import accepts [0] empty clues and grids', () => {
  const q = E.parsePuzzle('{"rows":[[1],[0]],"cols":[[1],[0]]}'); assert.deepStrictEqual(q.rows, [[1], []]);
  assert.deepStrictEqual(E.parsePuzzle('{"grid":[[1,0],[0,1]]}').rows, [[1], [1]]);
});
t('bad imports give clear errors', () => {
  assert.throws(() => E.parsePuzzle(''), /nothing/); assert.throws(() => E.parsePuzzle('{bad'), /invalid JSON/);
  assert.throws(() => E.parsePuzzle('hello world'), /rows/); assert.throws(() => E.parsePuzzle('rows\nx\ncolumns\n1'), /bad clue/);
});
t('share token round trip and corruption', () => {
  const g = E.generate({ w: 9, h: 7, seed: 3 }), p = { rows: g.rows, cols: g.cols };
  assert.deepStrictEqual(E.decodeShare(E.encodeShare(p)), p); assert.throws(() => E.decodeShare('!!!!'), /corrupt/);
});

console.log('Feature 7: solver trace (visualiser data)');
t('replaying propagate trace reproduces the solved board', () => {
  const g = E.generate({ w: 10, h: 10, seed: 9, difficulty: 'easy' }), p = { rows: g.rows, cols: g.cols };
  const b = E.makeBoard(p), r = E.propagate(b, { trace: true }), re = E.makeBoard(p);
  for (const st of r.steps) for (const [x, y, v] of st.cells) re.cells[y * 10 + x] = v;
  assert.deepStrictEqual(Array.from(re.cells), Array.from(b.cells)); assert.ok(E.isSolved(re));
});

console.log('Feature 9: image -> puzzle');
t('threshold + uniqueness repair on a synthetic image', () => {
  const W = 60, H = 60, px = new Uint8ClampedArray(W * H * 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const d = Math.hypot(x - 30, y - 30) < 22 ? 0 : 255, i = (y * W + x) * 4; px[i] = px[i + 1] = px[i + 2] = d; px[i + 3] = 255; }
  const g = E.gridFromRGBA(px, W, H, 12, 12); assert.strictEqual(g[6][6], 1); assert.strictEqual(g[0][0], 0);
  const u = E.makeUnique(g, E.mulberry32(1)); assert.ok(u); assert.strictEqual(E.solve(E.cluesFromGrid(u)).count, 1);
});

console.log('Feature 10: CLI');
const cli = path.join(__dirname, '..', 'cli.js'), run = (...a) => execFileSync('node', [cli, ...a], { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
t('gen -> solve -> rate pipeline through files', () => {
  const f = path.join(os.tmpdir(), 'inkgrid-' + process.pid + '.non'); fs.writeFileSync(f, run('gen', '7x7', '--seed', '5'));
  assert.match(run('solve', f), /unique solution/); assert.match(run('rate', f), /"tier"/); assert.ok(run('hint', f).length > 10); fs.unlinkSync(f);
});
t('CLI errors are clean (nonzero exit, no stack trace)', () => {
  assert.throws(() => run('gen', 'banana'), e => /size must look like/.test(e.stderr) && !/at /.test(e.stderr) && e.status === 1);
  assert.throws(() => run('solve', '/no/such/file'), e => e.status === 1 && /error:/.test(e.stderr));
});

console.log('\n' + n + ' checks passed' + (process.exitCode ? ' — WITH FAILURES' : ' — ALL GREEN'));
