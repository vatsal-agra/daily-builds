'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs'); const os = require('node:os'); const path = require('node:path');
const CLI = path.join(__dirname, '..', 'murmur.js');
const run = (...a) => spawnSync('node', [CLI, ...a], { encoding: 'utf8' });
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'murmur-'));

test('help and unknown command', () => {
  assert.match(run('help').stdout, /usage: node murmur.js/);
  const r = run('bogus'); assert.equal(r.status, 64); assert.match(r.stderr, /unknown command/);
});

test('run prints metrics and a hash; same args → same hash', () => {
  const a = run('run', '--n', '60', '--steps', '50', '--seed', '3'), b = run('run', '--n', '60', '--steps', '50', '--seed', '3');
  assert.equal(a.status, 0); assert.match(a.stdout, /state hash: [0-9a-f]{16}/); assert.equal(a.stdout, b.stdout);
});

test('bad input is rejected with a clear message and non-zero status', () => {
  for (const [args, re] of [[['run', '--nosie', '1'], /unknown option --nosie/], [['run', '--steps', '-1'], /--steps expects/], [['run', '--noise', 'x'], /--noise expects a number/],
    [['run', '--mode', 'zzz'], /mode must be/], [['sweep', '--out'], /--out expects/], [['sweep', '--noise', '1'], /--noises/], [['compare', '--ns', '1'], />= 2/], [['replay'], /needs --snapshot/], [['run', '--n', '1.5'], /integer/]]) {
    const r = run(...args); assert.notEqual(r.status, 0, args.join(' ')); assert.match(r.stderr, re, args.join(' '));
  }
});

test('snapshot → replay reproduces the hash; --expect detects tampering', () => {
  const d = tmp(), snap = path.join(d, 's.json');
  assert.equal(run('run', '--n', '80', '--steps', '40', '--seed', '9', '--predators', '1', '--snapshot', snap).status, 0);
  const direct = run('run', '--n', '80', '--steps', '100', '--seed', '9', '--predators', '1');
  const want = direct.stdout.match(/state hash: (\w+)/)[1];
  const rp = run('replay', '--snapshot', snap, '--steps', '60', '--expect', want);
  assert.equal(rp.status, 0, rp.stderr); assert.match(rp.stdout, /hash matches expected/);
  const bad = run('replay', '--snapshot', snap, '--steps', '60', '--expect', '0000000000000000'); assert.equal(bad.status, 2); assert.match(bad.stderr, /MISMATCH/);
  const j = JSON.parse(fs.readFileSync(snap, 'utf8')); j.x[0] = 'oops'; fs.writeFileSync(snap, JSON.stringify(j));
  const c = run('replay', '--snapshot', snap); assert.notEqual(c.status, 0); assert.match(c.stderr, /corrupt/);
  fs.writeFileSync(snap, '{not json'); assert.match(run('replay', '--snapshot', snap).stderr, /cannot read snapshot/);
});

test('sweep / compare / hunt / bench write artefacts and succeed', () => {
  const d = tmp();
  let r = run('sweep', '--out', d, '--noises', '0,0.5', '--reps', '1', '--n', '60', '--steps', '100'); assert.equal(r.status, 0, r.stderr);
  assert.ok(fs.readFileSync(path.join(d, 'sweep.csv'), 'utf8').startsWith('noise,polarization')); assert.ok(fs.readFileSync(path.join(d, 'sweep.svg'), 'utf8').startsWith('<svg'));
  r = run('compare', '--out', d, '--ns', '40,80', '--reps', '1'); assert.equal(r.status, 0, r.stderr); assert.ok(fs.existsSync(path.join(d, 'compare.svg')));
  r = run('hunt', '--n', '100', '--steps', '300'); assert.equal(r.status, 0); assert.match(r.stdout, /catches=\d+/);
  r = run('bench', '--n', '500'); assert.equal(r.status, 0); assert.match(r.stdout, /kNN mismatches vs brute: 0/);
});

test('tune writes tuned.json + svg', () => {
  const d = tmp(); const r = run('tune', '--gens', '2', '--pop', '4', '--n', '40', '--out', d);
  assert.equal(r.status, 0, r.stderr); const j = JSON.parse(fs.readFileSync(path.join(d, 'tuned.json'), 'utf8'));
  assert.ok(j.best && j.history.length === 3 && j.heldOut); assert.ok(fs.readFileSync(path.join(d, 'tune.svg'), 'utf8').includes('<polyline'));
});
