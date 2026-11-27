import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Game, placeMines, DIFFICULTIES, HIDDEN, REVEALED, FLAGGED, validateConfig } from '../src/board.js';
import { makeRng } from '../src/rng.js';
import { generateNoGuess, newGame, autoPlay } from '../src/generator.js';

test('first click is never a mine and never touches one (roomy boards)', () => {
  for (let s = 0; s < 200; s++) {
    const g = new Game({ ...DIFFICULTIES.beginner, seed: 'fc' + s });
    const first = (s * 7) % g.n;
    const r = g.reveal(first);
    assert.equal(r.boom, false);
    assert.equal(g.adj[first], 0, 'first click opens a zero');
    assert.ok(r.opened.length >= 2);
    assert.equal(g.mine.reduce((a, b) => a + b, 0), 10);
  }
});

test('layouts are deterministic per seed and differ across seeds', () => {
  const a = placeMines(16, 16, 40, 5, makeRng('a')), b = placeMines(16, 16, 40, 5, makeRng('a')), c = placeMines(16, 16, 40, 5, makeRng('b'));
  assert.deepEqual(a, b); assert.notDeepEqual(a, c);
});

test('dense boards fall back to protecting only the clicked cell', () => {
  const g = new Game({ w: 3, h: 3, mines: 8, seed: 'dense' });
  const r = g.reveal(4);
  assert.equal(r.boom, false);
  assert.equal(g.status, 'won'); // 8 mines, 1 safe cell: revealing it wins
});

test('flood fill, adjacency counts and win detection on a hand-made layout', () => {
  // 4x4, mines at corners 0 and 15
  const g = Game.fromLayout(4, 4, [0, 15]);
  assert.equal(g.adj[1], 1); assert.equal(g.adj[5], 1); assert.equal(g.adj[3], 0);
  g.reveal(1);
  assert.equal(g.status, 'playing'); assert.equal(g.revealedCount, 1, 'a numbered cell does not flood');
  g.reveal(3);
  assert.ok(g.revealedCount > 1, 'a zero cell floods');
  assert.equal(g.status, 'won', 'flood opened every safe cell');
  assert.equal(g.state[0], FLAGGED, 'mines auto-flagged on win');
  assert.equal(g.reveal(0).boom, false, 'no moves after win');
});

test('stepping on a mine loses and records the explosion', () => {
  const g = Game.fromLayout(3, 3, [0, 8]);
  g.reveal(2);
  const r = g.reveal(0);
  assert.equal(r.boom, true); assert.equal(g.status, 'lost'); assert.equal(g.exploded, 0);
  assert.equal(g.toggleFlag(4), false, 'no flagging after loss');
});

test('flood fill respects flags; revealing a flagged cell directly is refused', () => {
  const g = Game.fromLayout(5, 5, [24]);
  g.toggleFlag(0); assert.equal(g.flagCount, 1);
  g.reveal(12);
  assert.equal(g.flagCount, 1); assert.equal(g.state[0], FLAGGED, 'flagged cell survives the flood');
  assert.equal(g.status, 'playing', 'game not won while a safe cell is still flagged');
  assert.deepEqual(g.reveal(0).opened, []);
  g.toggleFlag(0); g.reveal(0);
  assert.equal(g.status, 'won');
});

test('chording opens neighbours only when flags match, and can explode on a wrong flag', () => {
  const g = Game.fromLayout(4, 4, [0, 5]);
  g.reveal(15);            // flood opens everything not adjacent to mines... find a number cell
  const numCell = [...Array(16).keys()].find(i => g.state[i] === REVEALED && g.adj[i] > 0 && g.nb[i].some(j => g.state[j] === HIDDEN));
  assert.ok(numCell !== undefined);
  assert.deepEqual(g.chord(numCell).opened, [], 'no flags -> nothing');
  // flag wrongly: flag a safe hidden neighbour rather than the mine
  const mineNb = g.nb[numCell].filter(j => g.mine[j] && g.state[j] === HIDDEN);
  const safeHid = g.nb[numCell].filter(j => !g.mine[j] && g.state[j] === HIDDEN);
  if (g.adj[numCell] === 1 && safeHid.length) {
    g.toggleFlag(safeHid[0]);
    const r = g.chord(numCell);
    assert.equal(r.boom, true, 'chord with a misplaced flag detonates the real mine');
    assert.equal(g.status, 'lost');
  } else assert.ok(mineNb.length >= 0);
});

test('config validation', () => {
  assert.throws(() => validateConfig({ w: 1, h: 5, mines: 1 }), RangeError);
  assert.throws(() => validateConfig({ w: 5, h: 5, mines: 25 }), RangeError);
  assert.throws(() => validateConfig({ w: 5, h: 5, mines: 0 }), RangeError);
  assert.throws(() => validateConfig({ w: 5.5, h: 5, mines: 2 }), RangeError);
  assert.throws(() => new Game({ w: 5, h: 5, mines: 2 }).reveal(99), RangeError);
  assert.throws(() => Game.fromLayout(3, 3, [1, 1]), RangeError);
});

test('no-guess generator: certain-only solver wins every generated board, and replay is deterministic', () => {
  for (const [name, cfg] of Object.entries(DIFFICULTIES)) {
    for (let s = 0; s < 4; s++) {
      const first = Math.floor(cfg.w * cfg.h / 2) + s;
      const r = generateNoGuess(cfg.w, cfg.h, cfg.mines, first, `ng-${name}-${s}`);
      assert.ok(r, `${name} generated`);
      const g = Game.fromLayout(cfg.w, cfg.h, r.layout);
      const res = autoPlay(g, { allowGuess: false, first });
      assert.equal(res.won, true, `${name}/${s} solved without guessing`);
      assert.equal(res.guesses, 0);
      const again = generateNoGuess(cfg.w, cfg.h, cfg.mines, first, `ng-${name}-${s}`);
      assert.deepEqual(again.layout, r.layout);
    }
  }
});

test('newGame with noGuess makes the first click safe and the board guess-free', () => {
  const g = newGame({ ...DIFFICULTIES.intermediate, seed: 'ngame', noGuess: true });
  g.reveal(100);
  assert.equal(g.status, 'playing');
  const r = autoPlay(g, { allowGuess: false });
  assert.equal(r.won, true);
});

test('ordinary random boards usually DO need guesses (so the generator is doing real work)', () => {
  let needGuess = 0;
  for (let s = 0; s < 20; s++) {
    const g = new Game({ ...DIFFICULTIES.expert, seed: 'plain' + s });
    g.reveal(240);
    if (g.status !== 'playing') continue;
    if (!autoPlay(g, { allowGuess: false }).won) needGuess++;
  }
  assert.ok(needGuess >= 8, `expected many guess-requiring expert boards, got ${needGuess}/20`);
});

test('chord does nothing when flags exceed the number (over-flagged) or on zeros/hidden cells', () => {
  const g = Game.fromLayout(5, 5, [0, 24]);
  g.reveal(6); // a "1" next to the corner mine
  assert.equal(g.adj[6], 1);
  const hid = g.nb[6].filter(j => g.state[j] === HIDDEN);
  assert.ok(hid.length >= 2);
  g.toggleFlag(hid[0]); g.toggleFlag(hid[1]);
  const before = g.revealedCount;
  assert.deepEqual(g.chord(6).opened, []);
  assert.equal(g.revealedCount, before);
  assert.deepEqual(g.chord(12).opened, [], 'chord on a hidden cell is a no-op');
});
