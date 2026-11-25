'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { Flock, Rng } = require('../engine');

const place = (f, pts) => { pts.forEach(([x, y, vx = 1, vy = 0], i) => { f.x[i] = x; f.y[i] = y; f.vx[i] = vx; f.vy[i] = vy; }); f.rebuildIndex(); };

test('spatial hash radius query == brute force (torus+wall, many sizes)', () => {
  for (const boundary of ['torus', 'wall']) for (const [w, h, R, n] of [[600, 400, 50, 200], [90, 70, 40, 60], [37, 500, 30, 90], [1000, 1000, 8, 300]]) {
    const f = new Flock({ n, width: w, height: h, radius: R, boundary, seed: 4 });
    f.rebuildIndex();
    const out = [], d2 = [];
    for (let i = 0; i < n; i++) {
      f.queryRadius(i, R, out, d2);
      const got = out.map((j, q) => [j, d2[q]]).sort((a, b) => a[0] - b[0]);
      const want = f.bruteRadius(i, R).sort((a, b) => a[0] - b[0]);
      assert.deepEqual(got, want, `${boundary} ${w}x${h} R=${R} agent ${i}`);
    }
  }
});

test('exact kNN == brute force incl. tie-breaking, sparse and dense, torus+wall', () => {
  for (const boundary of ['torus', 'wall']) for (const [w, h, n, k] of [[600, 400, 150, 7], [600, 400, 12, 7], [100, 100, 400, 20], [300, 40, 50, 3], [600, 400, 5, 50]]) {
    const f = new Flock({ n, width: w, height: h, boundary, seed: 9, radius: 30 });
    f.rebuildIndex();
    const out = [], d2 = [];
    for (let i = 0; i < n; i++) {
      f.queryKNN(i, k, out, d2);
      const want = f.bruteKNN(i, k);
      assert.deepEqual(out, want.map((e) => e[0]), `${boundary} n=${n} k=${k} agent ${i}`);
      assert.deepEqual(d2, want.map((e) => e[1]));
    }
  }
});

test('kNN with duplicate positions and zero-agent / single-agent flocks do not crash', () => {
  const f = new Flock({ n: 6, seed: 1 }); place(f, [[10, 10], [10, 10], [10, 10], [300, 200], [300, 200], [590, 390]]);
  const out = [], d2 = []; f.queryKNN(0, 3, out, d2);
  assert.deepEqual(out, [1, 2, 3 === 3 ? 3 : 3].slice(0, 2).concat([out[2]]));
  assert.equal(new Flock({ n: 0 }).run(5).polarization(), 0);
  const one = new Flock({ n: 1 }); one.run(10); assert.equal(one.meanNNDist(), 0);
});

test('torus minimum-image distances wrap across the seam', () => {
  const f = new Flock({ n: 2, width: 100, height: 100, boundary: 'torus' });
  place(f, [[1, 50], [99, 50]]);
  const [dx, dy] = f.delta(f.x[0], f.y[0], f.x[1], f.y[1]);
  assert.equal(dx, -2); assert.equal(dy, 0);
  const out = [], d2 = []; f.queryRadius(0, 5, out, d2); assert.deepEqual(out, [1]);
  const w = new Flock({ n: 2, width: 100, height: 100, boundary: 'wall' }); place(w, [[1, 50], [99, 50]]);
  w.queryRadius(0, 5, out, d2); assert.deepEqual(out, []);
});

test('simulation is deterministic: same seed → identical hash; different seed differs', () => {
  const a = new Flock({ n: 120, seed: 21 }).run(100).hash(), b = new Flock({ n: 120, seed: 21 }).run(100).hash(), c = new Flock({ n: 120, seed: 22 }).run(100).hash();
  assert.equal(a, b); assert.notEqual(a, c);
});

test('agents stay inside the world and keep finite state (both boundaries, both modes)', () => {
  for (const boundary of ['torus', 'wall']) for (const mode of ['metric', 'topological']) {
    const f = new Flock({ n: 150, boundary, mode, seed: 2, noise: 0.3 }); f.addPredator(300, 200); f.run(200);
    for (let i = 0; i < f.n; i++) {
      assert.ok(f.x[i] >= 0 && f.x[i] <= f.p.width && f.y[i] >= 0 && f.y[i] <= f.p.height, `${boundary} oob`);
      assert.ok(Number.isFinite(f.vx[i]) && Number.isFinite(f.vy[i]));
      const s = Math.hypot(f.vx[i], f.vy[i]); assert.ok(s <= f.p.maxSpeed + 1e-9 && s >= f.p.minSpeed - 1e-9);
    }
  }
});

test('metrics: aligned flock → polarization 1; opposed halves → 0; ring → angular momentum 1', () => {
  const f = new Flock({ n: 4 }); place(f, [[10, 10, 5, 0], [50, 10, 5, 0], [10, 50, 5, 0], [50, 50, 5, 0]]);
  assert.ok(Math.abs(f.polarization() - 1) < 1e-12);
  place(f, [[10, 10, 5, 0], [50, 10, -5, 0], [10, 50, 0, 5], [50, 50, 0, -5]]);
  assert.ok(f.polarization() < 1e-12);
  const g = new Flock({ n: 8, boundary: 'wall', width: 400, height: 400 });
  place(g, Array.from({ length: 8 }, (_, i) => { const a = i / 8 * 2 * Math.PI; return [200 + 80 * Math.cos(a), 200 + 80 * Math.sin(a), -Math.sin(a) * 30, Math.cos(a) * 30]; }));
  assert.ok(Math.abs(g.angularMomentum() - 1) < 1e-9);
  assert.ok(g.polarization() < 1e-9, 'milling ring has ~0 net polarization');
});

test('metrics: clusters via union-find, NN distance, close pairs', () => {
  const f = new Flock({ n: 6, boundary: 'wall', width: 400, height: 400 });
  place(f, [[10, 10], [20, 10], [30, 10], [300, 300], [305, 300], [200, 100]]);
  const c = f.clusters(12);
  assert.equal(c.count, 3); assert.deepEqual(c.sizes, [3, 2, 1]); assert.equal(c.largestFrac, 0.5);
  assert.equal(f.clusters(1000).count, 1);
  assert.equal(f.closePairs(6), 1);   // only (300,300)-(305,300)
  const nn = f.meanNNDist(); assert.ok(Math.abs(nn - (10 + 10 + 10 + 5 + 5 + Math.hypot(95, 200 - 100 - 0) * 0 + (() => { const d = [[10,10],[20,10],[30,10],[300,300],[305,300]].map(([x,y]) => Math.hypot(x-200,y-100)); return Math.min(...d); })()) / 6) < 1e-9);
});

test('separation pushes two overlapping agents apart; alignment aligns two near agents', () => {
  const f = new Flock({ n: 2, wAli: 0, wCoh: 0, noise: 0, boundary: 'wall', width: 400, height: 400 });
  place(f, [[200, 200, 0, 40], [204, 200, 0, 40]]);
  const d0 = 4; f.run(15); assert.ok(Math.abs(f.x[1] - f.x[0]) > d0 * 2, 'agents moved apart');
  const g = new Flock({ n: 2, wSep: 0, wCoh: 0, noise: 0, wAli: 2, boundary: 'wall', width: 400, height: 400, radius: 60, minSpeed: 10 });
  place(g, [[200, 200, 40, 0], [220, 200, 0, 40]]);
  const a0 = g.polarization(); g.run(40); assert.ok(g.polarization() > a0 + 0.25, `pol ${a0} → ${g.polarization()}`);
});

test('topological mode: an isolated agent still follows its k nearest; metric mode does not', () => {
  const mk = (mode) => { const f = new Flock({ n: 3, mode, k: 2, radius: 20, wSep: 0, wCoh: 0, wAli: 3, noise: 0, boundary: 'wall', width: 1000, height: 1000, minSpeed: 5 });
    place(f, [[100, 500, 40, 0], [800, 500, 0, 40], [800, 520, 0, 40]]); f.run(30); return f; };
  const t = mk('topological'), m = mk('metric');
  assert.ok(t.vy[0] > 10, 'topological agent turned toward far-away neighbours: vy=' + t.vy[0]);
  assert.ok(Math.abs(m.vy[0]) < 1e-9 && m.vx[0] > 39, 'metric agent saw nobody and kept heading');
});

test('predator catches prey, respawns them, and honours the cooldown', () => {
  const f = new Flock({ n: 1, boundary: 'wall', width: 400, height: 400, noise: 0, wFlee: 0, predCooldown: 20 });
  place(f, [[200, 200, 0, 0]]); f.vx[0] = 30; f.vy[0] = 0;
  f.addPredator(180, 200); f.predators[0].vx = 66; f.predators[0].vy = 0;
  f.run(60); assert.ok(f.caught >= 1, 'caught ' + f.caught);
  const c = f.caught; f.predators[0].cool = 10; f.predators[0].x = f.x[0]; f.predators[0].y = f.y[0]; f.step(); assert.equal(f.caught, c, 'no catch during cooldown');
});

test('prey flee: flocks near a predator disperse away from it', () => {
  const f = new Flock({ n: 1, boundary: 'wall', width: 800, height: 800, noise: 0, wFlee: 8, wAli: 0, wCoh: 0, minSpeed: 5 });
  place(f, [[400, 400, 0, 1]]); f.addPredator(370, 400); f.predators[0].vx = 0; f.predators[0].vy = 0; f.p.predSpeed = 0;
  f.predators[0].cool = 1e6; f.run(40); assert.ok(f.vx[0] > 20, 'fled in +x: ' + f.vx[0]);
});

test('obstacles are never penetrated; flock flows around', () => {
  const f = new Flock({ n: 200, seed: 8, boundary: 'wall' }); f.addObstacle(300, 200, 50);
  for (let s = 0; s < 300; s++) { f.step(); for (let i = 0; i < f.n; i++) assert.ok(Math.hypot(f.x[i] - 300, f.y[i] - 200) >= 50 - 1e-6, `step ${s} agent ${i} inside`); }
  assert.equal(f.removeObstacleAt(300, 200), true); assert.equal(f.removeObstacleAt(10, 10), false);
});

test('snapshot → JSON → restore continues bit-identically', () => {
  const a = new Flock({ n: 100, seed: 5 }); a.addObstacle(200, 100, 30); a.addPredator(100, 100); a.run(50);
  const snap = JSON.parse(JSON.stringify(a.snapshot()));
  const b = Flock.restore(snap); assert.equal(a.hash(), b.hash());
  a.run(80); b.run(80); assert.equal(a.hash(), b.hash()); assert.equal(a.caught, b.caught);
});

test('restore rejects corrupt snapshots', () => {
  const s = new Flock({ n: 5 }).snapshot();
  assert.throws(() => Flock.restore(null)); assert.throws(() => Flock.restore({ ...s, v: 2 }));
  assert.throws(() => Flock.restore({ ...s, x: s.x.slice(1) })); assert.throws(() => Flock.restore({ ...s, vy: s.vy.map(() => NaN) }));
});

test('parameter validation rejects nonsense', () => {
  for (const bad of [{ n: -1 }, { n: 1.5 }, { n: NaN }, { radius: 0 }, { mode: 'x' }, { boundary: 'y' }, { dt: 0 }, { width: 5 }, { k: 0 }, { minSpeed: 100, maxSpeed: 10 }, { noise: -1 }, { wSep: Infinity }])
    assert.throws(() => new Flock(bad), RangeError, JSON.stringify(bad));
  const f = new Flock({ n: 10 });
  assert.throws(() => f.setParams({ n: 20 })); assert.throws(() => f.setParams({ radius: -3 })); assert.throws(() => f.addObstacle(1, 1, 0)); assert.throws(() => f.addPredator(NaN, 1));
});

test('live setParams / resize keep the simulation consistent', () => {
  const f = new Flock({ n: 50, seed: 1 }); f.run(20);
  f.setParams({ radius: 120, mode: 'topological', boundary: 'wall' }); f.run(20);
  f.resize(80); assert.equal(f.n, 80); f.run(10); f.resize(10); assert.equal(f.n, 10); f.run(5);
  for (let i = 0; i < f.n; i++) assert.ok(Number.isFinite(f.x[i]));
});

test('Rng is uniform-ish and gauss has ~unit variance', () => {
  const r = new Rng(3); let s = 0, s2 = 0; const N = 20000;
  for (let i = 0; i < N; i++) { const g = r.gauss(); s += g; s2 += g * g; }
  assert.ok(Math.abs(s / N) < 0.05 && Math.abs(s2 / N - 1) < 0.06);
});
