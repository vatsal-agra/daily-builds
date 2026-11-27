import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import http from 'node:http';
import { analyzeGame } from '../src/analysis.js';
import { runBench } from '../src/bench.js';
import { parseBoard, parseArgs, configFrom, renderProbabilities } from '../src/cli.js';
import { Game } from '../src/board.js';
import { solve } from '../src/solver.js';
import { bundle } from '../build.js';
import { createServer } from '../serve.js';

const CLI = new URL('../src/cli.js', import.meta.url).pathname;
const run = (...args) => spawnSync('node', [CLI, ...args], { encoding: 'utf8', input: '' });

// ---------- luck analyzer ----------
test('analysis: pure logic win', () => {
  const a = analyzeGame([{ first: true, p: null }, { cell: 1, p: 0, bestP: 0, hadSafe: true }], 'won');
  assert.equal(a.risks, 0); assert.equal(a.survival, 1); assert.match(a.verdict, /Pure logic/);
});
test('analysis: lucky win survives several coin-flips', () => {
  const mv = [{ first: true, p: null }, ...Array(3).fill({ cell: 1, p: 0.5, bestP: 0.5, hadSafe: false })];
  const a = analyzeGame(mv, 'won');
  assert.ok(Math.abs(a.survival - 0.125) < 1e-12); assert.match(a.verdict, /Lucky/); assert.equal(a.risks, 3);
});
test('analysis: unlucky loss vs avoidable loss vs forced gamble', () => {
  const base = [{ first: true, p: null }];
  assert.match(analyzeGame([...base, { cell: 2, p: 0.1, bestP: 0.1, hadSafe: false, boom: true }], 'lost').verdict, /Unlucky/);
  assert.match(analyzeGame([...base, { cell: 2, p: 0.4, bestP: 0.4, hadSafe: false, boom: true }], 'lost').verdict, /Forced gamble/);
  const av = analyzeGame([...base, { cell: 2, p: 0.3, bestP: 0, hadSafe: true, boom: true }], 'lost');
  assert.match(av.verdict, /Avoidable/); assert.equal(av.reckless, 1);
  const sub = analyzeGame([...base, { cell: 2, p: 0.5, bestP: 0.2, hadSafe: false, boom: true }], 'lost');
  assert.equal(sub.suboptimal, 1);
});
test('analysis: worst risks sorted, empty history safe', () => {
  const a = analyzeGame([{ first: true, p: null }, { cell: 1, p: 0.2 }, { cell: 2, p: 0.7 }, { cell: 3, p: 0.4 }, { cell: 4, p: 0.05 }], 'won');
  assert.deepEqual(a.worst.map(m => m.cell), [2, 3, 1]);
  assert.doesNotThrow(() => analyzeGame([], 'lost'));
});
test('analysis on a real solver game: every recorded guess risk equals the solver probability', () => {
  const g = new Game({ w: 9, h: 9, mines: 10, seed: 'an1' }); g.reveal(40);
  const moves = [];
  while (g.status === 'playing') {
    const v = g.view(), r = solve(v, 9, 9, 10);
    let best = -1, bp = 2; for (let i = 0; i < 81; i++) if (v[i] < 0 && r.prob[i] < bp) { bp = r.prob[i]; best = i; }
    moves.push({ cell: best, p: bp, bestP: bp, hadSafe: r.certainSafe.length > 0, boom: false });
    if (g.reveal(best).boom) moves[moves.length - 1].boom = true;
  }
  const a = analyzeGame(moves, g.status);
  assert.equal(a.reckless, 0); assert.equal(a.suboptimal, 0);
});

// ---------- benchmark ----------
test('bench: deterministic, sane win rates, validates input', () => {
  const a = runBench({ level: 'beginner', games: 40, seed: 'tb' }), b = runBench({ level: 'beginner', games: 40, seed: 'tb' });
  assert.equal(a.wins, b.wins); assert.equal(a.avgGuesses, b.avgGuesses);
  assert.ok(a.winRate > 0.8, 'beginner win rate ' + a.winRate);
  const ng = runBench({ level: 'intermediate', games: 6, seed: 'tn', noGuess: true });
  assert.equal(ng.wins, 6); assert.equal(ng.avgGuesses, 0); assert.equal(ng.zeroGuessWins, 6);
  assert.throws(() => runBench({ level: 'nightmare' }), RangeError);
  assert.throws(() => runBench({ games: 0 }), RangeError);
});

// ---------- CLI ----------
test('cli: parseBoard and errors', () => {
  const { view, w, h } = parseBoard('# 1 .\n# 2 1\n');
  assert.equal(w, 3); assert.equal(h, 2); assert.deepEqual([...view], [-1, 1, 0, -1, 2, 1]);
  assert.throws(() => parseBoard(''), /empty/);
  assert.throws(() => parseBoard('# 1\n# 2 1'), /row 2/);
  assert.throws(() => parseBoard('# x\n# 1'), /unexpected character/);
  assert.throws(() => parseBoard('#\n#'), /2x2/);
});
test('cli: args and configs', () => {
  assert.deepEqual(parseArgs(['bench', '--games', '5', '--no-guess']), { pos: ['bench'], opt: { games: '5', 'no-guess': true } });
  assert.throws(() => parseArgs(['--games']), /needs a value/);
  assert.deepEqual(configFrom({ size: '5x6x7' }), { w: 5, h: 6, mines: 7 });
  assert.throws(() => configFrom({ size: 'abc' }), /--size/);
  assert.throws(() => configFrom({ level: 'x' }), /unknown level/);
});
test('cli: solve command agrees with the solver on a real position', () => {
  const g = new Game({ w: 8, h: 8, mines: 8, seed: 'cli1' }); g.reveal(27);
  const rows = []; for (let y = 0; y < 8; y++) { let r = ''; for (let x = 0; x < 8; x++) { const i = y * 8 + x; r += g.state[i] === 1 ? (g.adj[i] || '.') : '#'; } rows.push(r.split('').join(' ')); }
  const f = join(mkdtempSync(join(tmpdir(), 'fathom-')), 'b.txt'); writeFileSync(f, rows.join('\n'));
  const out = run('solve', f, '--mines', '8');
  assert.equal(out.status, 0, out.stderr);
  const res = solve(g.view(), 8, 8, 8);
  assert.match(out.stdout, new RegExp(`layouts\\s+: ${res.stats.solutions}`));
  for (const c of res.certainSafe) assert.match(out.stdout, new RegExp(`\\(${(c % 8) + 1},${Math.floor(c / 8) + 1}\\)`));
  assert.equal(renderProbabilities(g.view(), 8, 8, res).split('\n').length, 8);
});
test('cli: inconsistent boards exit 3; bad usage exits 2', () => {
  const f = join(mkdtempSync(join(tmpdir(), 'fathom-')), 'bad.txt'); writeFileSync(f, '# #\n# 8\n');
  assert.equal(run('solve', f, '--mines', '1').status, 3);
  assert.equal(run('solve', f).status, 2);
  assert.equal(run('frobnicate').status, 2);
  assert.equal(run('generate', '--size', '3x3x9').status, 2);
  assert.equal(run('generate', '--first', '99,99').status, 2);
});
test('cli: generate --no-guess --json yields a layout the solver can clear with no guesses', async () => {
  const out = run('generate', '--level', 'intermediate', '--seed', 'cg', '--no-guess', '--json');
  assert.equal(out.status, 0, out.stderr);
  const j = JSON.parse(out.stdout);
  assert.equal(j.mines.length, 40); assert.equal(j.noGuessFailed, false);
  const { autoPlay } = await import('../src/generator.js');
  const g = Game.fromLayout(j.w, j.h, j.mines);
  const first = (j.first[1] - 1) * j.w + (j.first[0] - 1);
  assert.equal(g.mine[first], 0);
  assert.equal(autoPlay(g, { allowGuess: false, first }).won, true);
});
test('cli: bench and help run', () => {
  assert.match(run('bench', '--level', 'beginner', '--games', '5').stdout, /5 games|\/5 won/);
  assert.match(run().stdout, /fathom/);
});
test('cli: interactive play session is scripted end-to-end (flag, reveal, hint, luck report)', () => {
  const r = spawnSync('node', [CLI, 'play', '--level', 'beginner', '--seed', 'pl1'], { encoding: 'utf8', input: 'r 5 5\nf 1 1\nr 0 0\nhint\nodds\nstep\nstep\nstep\nstep\nstep\nstep\nstep\nstep\nstep\nstep\nq\n', timeout: 20000 });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /coordinates must be integers/);
  assert.match(r.stdout, /mines left/);
  assert.match(r.stdout, /certainly safe|best guess|Luck report/);
});

// ---------- bundle & server ----------
test('bundle: single self-contained html with no module imports left', () => {
  const html = bundle();
  assert.ok(!/^import /m.test(html) && !/^export /m.test(html));
  assert.ok(!html.includes('href="style.css"') && html.includes('<style>') && html.includes('analyzeGame'));
  assert.ok(html.length < 400 * 1024);
});
test('serve: serves app files, blocks path traversal and non-public dirs', async () => {
  const srv = createServer(); await new Promise(r => srv.listen(0, r));
  const port = srv.address().port;
  const get = p => new Promise(res => http.get({ port, path: p }, r => { r.resume(); res(r.statusCode); }));
  assert.equal(await get('/web/index.html'), 200);
  assert.equal(await get('/src/solver.js'), 200);
  assert.equal(await get('/package.json'), 404);
  assert.equal(await get('/web/../package.json'), 404);
  assert.equal(await get('/%2e%2e/%2e%2e/etc/passwd'), 404);
  assert.equal(await get('/test/engine.test.js'), 404);
  srv.close();
});
