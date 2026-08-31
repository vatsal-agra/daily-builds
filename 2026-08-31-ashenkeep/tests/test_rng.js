'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { RNG } = require('../src/rng.js');

test('same seed produces identical stream', () => {
  const a = new RNG(12345);
  const b = new RNG(12345);
  for (let i = 0; i < 200; i++) {
    assert.equal(a.next(), b.next());
  }
});

test('different seeds diverge', () => {
  const a = new RNG(1);
  const b = new RNG(2);
  const seqA = Array.from({ length: 20 }, () => a.next());
  const seqB = Array.from({ length: 20 }, () => b.next());
  assert.notDeepEqual(seqA, seqB);
});

test('next() stays within [0, 1)', () => {
  const rng = new RNG(999);
  for (let i = 0; i < 5000; i++) {
    const v = rng.next();
    assert.ok(v >= 0 && v < 1, `value ${v} out of range`);
  }
});

test('int(min, max) is inclusive on both ends and never out of range', () => {
  const rng = new RNG(42);
  let sawMin = false;
  let sawMax = false;
  for (let i = 0; i < 2000; i++) {
    const v = rng.int(1, 3);
    assert.ok(v >= 1 && v <= 3);
    if (v === 1) sawMin = true;
    if (v === 3) sawMax = true;
  }
  assert.ok(sawMin && sawMax, 'expected to see both endpoints over 2000 draws');
});

test('int throws when max < min', () => {
  const rng = new RNG(1);
  assert.throws(() => rng.int(5, 1), RangeError);
});

test('pick throws on empty array', () => {
  const rng = new RNG(1);
  assert.throws(() => rng.pick([]), RangeError);
});

test('weighted respects zero-weight exclusion', () => {
  const rng = new RNG(7);
  for (let i = 0; i < 500; i++) {
    const v = rng.weighted([
      { weight: 1, value: 'a' },
      { weight: 0, value: 'never' },
    ]);
    assert.notEqual(v, 'never');
  }
});

test('getState/setState round-trips the exact stream', () => {
  const rng = new RNG(555);
  rng.next();
  rng.next();
  const snapshot = rng.getState();
  const expected = rng.next();
  const restored = new RNG(0);
  restored.setState(snapshot);
  assert.equal(restored.next(), expected);
});
