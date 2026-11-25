'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const T = require('../tools');

test('noise sweep shows the order→disorder transition', () => {
  const rows = T.noiseSweep({ noises: [0, 0.05, 0.3, 1.0], reps: 2, base: { n: 150 }, burn: 250, window: 100 });
  const by = Object.fromEntries(rows.map((r) => [r.noise, r.polarization]));
  assert.ok(by[0] > 0.6, 'ordered at zero noise: ' + by[0]);
  assert.ok(by[1.0] < 0.2, 'disordered at high noise: ' + by[1.0]);
  assert.ok(by[0] > by[0.3] && by[0.3] > by[1.0] - 0.05, 'roughly monotone');
  assert.throws(() => T.noiseSweep({ noises: [] }), RangeError);
});

test('density sweep is paired, reports spread, and is deterministic', () => {
  const a = T.densitySweep({ ns: [60, 150], reps: 2, burn: 150, window: 60 }), b = T.densitySweep({ ns: [60, 150], reps: 2, burn: 150, window: 60 });
  assert.equal(a.length, 4); assert.deepEqual(a, b);
  for (const r of a) { assert.ok(r.largestFrac > 0 && r.largestFrac <= 1); assert.ok(r.largestStd >= 0); assert.ok(r.nnDist > 0); }
});

test('predator experiment: catches happen and are deterministic; no predator → no catches', () => {
  const a = T.predatorTrial({ base: { n: 120, seed: 3 }, steps: 800 }), b = T.predatorTrial({ base: { n: 120, seed: 3 }, steps: 800 });
  assert.deepEqual(a, b); assert.ok(a.catches > 0, 'catches ' + a.catches);
  assert.equal(T.predatorTrial({ base: { n: 120, seed: 3 }, steps: 400, predators: 0 }).catches, 0);
  const two = T.predatorTrial({ base: { n: 120, seed: 3 }, steps: 800, predators: 3 });
  assert.ok(two.catches >= a.catches, 'more predators catch at least as much: ' + two.catches + ' vs ' + a.catches);
});

test('predator trial with obstacles stays valid', () => {
  const r = T.predatorTrial({ base: { n: 100, seed: 4, boundary: 'wall' }, steps: 300, obstacles: [{ x: 300, y: 200, r: 40 }] });
  assert.ok(Number.isFinite(r.finalPolarization));
});

test('genetic tuner is deterministic, elitist, and beats the defaults on held-out seeds', () => {
  const opts = { generations: 3, popSize: 6, seed: 2, base: { n: 50 }, evalOpts: { steps: 200, seeds: [11] } };
  const a = T.tune(opts), b = T.tune(opts);
  assert.deepEqual(a, b);
  for (let i = 1; i < a.history.length; i++) assert.ok(a.history[i].best >= a.history[i - 1].best - 1e-12, 'best never regresses');
  for (const g of T.GENES) { assert.ok(a.best[g.key] >= g.lo && a.best[g.key] <= g.hi); if (g.int) assert.ok(Number.isInteger(a.best[g.key])); }
  assert.ok(a.bestFitness >= a.baselineFitness);
  assert.ok(a.heldOut.best > a.heldOut.baseline - 0.05, `held-out best ${a.heldOut.best} vs baseline ${a.heldOut.baseline}`);
  assert.throws(() => T.tune({ popSize: 2 }), RangeError);
});

test('svgChart produces valid-looking SVG, escapes text, rejects empty data; CSV round-trips', () => {
  const svg = T.svgChart({ title: 'a<b&"c"', xlabel: 'x', ylabel: 'y', series: [{ name: 's', color: '#fff', pts: [[0, 0.1, 0.05], [1, 0.9, 0]] }] });
  assert.ok(svg.startsWith('<svg') && svg.endsWith('</svg>')); assert.ok(svg.includes('a&lt;b&amp;&quot;c&quot;')); assert.ok(!svg.includes('NaN'));
  assert.throws(() => T.svgChart({ title: 't', xlabel: 'x', ylabel: 'y', series: [] }), RangeError);
  assert.equal(T.toCSV([]), ''); assert.equal(T.toCSV([{ a: 1, b: 'x' }, { a: 2.5, b: 'y' }]), 'a,b\n1,x\n2.5,y\n');
  assert.ok(!T.svgChart({ title: 't', xlabel: 'x', ylabel: 'y', series: [{ name: 's', color: '#fff', pts: [[3, 0.5, 0]] }] }).includes('NaN'), 'single-point series');
});
