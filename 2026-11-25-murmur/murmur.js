#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const { Flock, DEFAULTS } = require('./engine');
const T = require('./tools');

const USAGE = `murmur — flocking laboratory

usage: node murmur.js <command> [--key value ...]

  run      simulate and print metrics        --n --steps --mode metric|topological --boundary torus|wall
                                             --noise --seed --predators --every --snapshot FILE
  sweep    noise → polarization phase plot   --out DIR --reps --steps --n
  compare  metric vs topological by density  --out DIR --reps --ns 60,120,240,480
  hunt     predator catch-rate experiment    --n --predators --steps --mode
  tune     genetic tuner for flock params    --gens --pop --seed --out DIR
  bench    spatial hash vs brute force       --n
  replay   resume a snapshot, verify hash    --snapshot FILE --steps N [--expect HASH]
  help
Any engine parameter (see engine.js DEFAULTS) can be passed as --name value.`;

function parseArgs(argv) {
  const o = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      if (i + 1 >= argv.length || argv[i + 1].startsWith('--')) o[k] = true; else o[k] = argv[++i];
    } else o._.push(a);
  }
  return o;
}
const CLI_FLAGS = new Set(['out', 'reps', 'steps', 'every', 'ns', 'noises', 'predators', 'snapshot', 'expect', 'gens', 'pop', 'help']);
function checkFlags(args) {
  for (const k of Object.keys(args)) {
    if (k === '_' || CLI_FLAGS.has(k) || k in DEFAULTS) continue;
    throw new Error(`unknown option --${k} (run "node murmur.js help")`);
  }
}
function engineOpts(args) {
  const o = {};
  for (const k of Object.keys(DEFAULTS)) {
    if (args[k] === undefined) continue;
    const d = DEFAULTS[k];
    if (typeof d === 'number') {
      const v = Number(args[k]);
      if (args[k] === true || !Number.isFinite(v)) throw new Error(`--${k} expects a number (got ${args[k]})`);
      o[k] = v;
    } else if (typeof d === 'boolean') o[k] = args[k] === true || args[k] === 'true' || args[k] === '1';
    else o[k] = String(args[k]);
  }
  return o;
}
function intArg(args, k, d, lo = 0) {
  if (args[k] === undefined) return d;
  const v = Number(args[k]);
  if (!Number.isInteger(v) || v < lo) throw new Error(`--${k} expects an integer >= ${lo} (got ${args[k]})`);
  return v;
}
function listArg(args, k, d) {
  if (args[k] === undefined) return d;
  const l = String(args[k]).split(',').map(Number);
  if (!l.length || l.some((v) => !Number.isFinite(v))) throw new Error(`--${k} expects comma-separated numbers (got ${args[k]})`);
  return l;
}
function outDir(args) {
  if (args.out === true) throw new Error('--out expects a directory path');
  const d = args.out || 'out'; fs.mkdirSync(d, { recursive: true }); return d;
}
const f3 = (v) => v.toFixed(3);

function cmdRun(args) {
  const steps = intArg(args, 'steps', 600), every = intArg(args, 'every', 100, 1);
  const f = new Flock(engineOpts(args));
  const np = intArg(args, 'predators', 0);
  for (let i = 0; i < np; i++) f.addPredator(f.p.width * (0.25 + 0.5 * f.rng.next()), f.p.height * (0.25 + 0.5 * f.rng.next()));
  console.log(`n=${f.n} mode=${f.p.mode} boundary=${f.p.boundary} noise=${f.p.noise} seed=${f.p.seed} predators=${np}`);
  console.log('step   polariz  angmom   nnDist  clusters largest  caught coll');
  const row = () => { const m = f.metrics(); console.log(`${String(m.step).padEnd(6)} ${f3(m.polarization).padEnd(8)} ${f3(m.angularMomentum).padEnd(8)} ${m.nnDist.toFixed(2).padEnd(7)} ${String(m.clusters).padEnd(8)} ${f3(m.largestFrac).padEnd(8)} ${String(m.caught).padEnd(6)} ${m.collisions}`); };
  row();
  for (let s = 1; s <= steps; s++) { f.step(); if (s % every === 0 || s === steps) row(); }
  console.log('state hash:', f.hash());
  if (args.snapshot) { fs.writeFileSync(args.snapshot, JSON.stringify(f.snapshot())); console.log('snapshot →', args.snapshot); }
}

function cmdSweep(args) {
  const noises = listArg(args, 'noises', [0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.45, 0.6, 0.9, 1.3]);
  const base = engineOpts(args);
  if (base.noise !== undefined) throw new Error('--noise conflicts with sweep (use --noises a,b,c)');
  if (base.n === undefined) base.n = 200;
  const rows = T.noiseSweep({ noises, reps: intArg(args, 'reps', 3, 1), base, burn: intArg(args, 'steps', 300), window: 150 });
  console.log('noise   polarization ±std   largest-cluster');
  for (const r of rows) console.log(`${String(r.noise).padEnd(7)} ${f3(r.polarization)} ±${f3(r.polStd)}       ${f3(r.largestFrac)}`);
  const d = outDir(args);
  fs.writeFileSync(path.join(d, 'sweep.csv'), T.toCSV(rows));
  fs.writeFileSync(path.join(d, 'sweep.svg'), T.svgChart({ title: 'Order–disorder transition (constant-speed flock)', xlabel: 'heading noise σ per step (rad)', ylabel: 'polarization',
    series: [{ name: 'polarization', color: '#5ec8ff', pts: rows.map((r) => [r.noise, r.polarization, r.polStd]) }, { name: 'largest cluster', color: '#ffb454', pts: rows.map((r) => [r.noise, r.largestFrac, 0]) }] }));
  console.log(`wrote ${d}/sweep.csv, ${d}/sweep.svg`);
}

function cmdCompare(args) {
  const ns = listArg(args, 'ns', [60, 120, 240, 480]).map((v) => Math.round(v));
  const base = engineOpts(args);
  if (base.n !== undefined || base.mode !== undefined) throw new Error('compare sets n and mode itself (use --ns a,b,c)');
  if (ns.some((v) => v < 2)) throw new Error('--ns values must be >= 2');
  const rows = T.densitySweep({ ns, reps: intArg(args, 'reps', 5, 1), base });
  console.log('n     mode          polariz  largest ±std     clusters  mean-NN');
  for (const r of rows) console.log(`${String(r.n).padEnd(5)} ${r.mode.padEnd(13)} ${f3(r.polarization).padEnd(8)} ${f3(r.largestFrac)} ±${f3(r.largestStd).padEnd(8)} ${r.clusters.toFixed(1).padEnd(9)} ${r.nnDist.toFixed(1)}`);
  const d = outDir(args);
  fs.writeFileSync(path.join(d, 'compare.csv'), T.toCSV(rows));
  const pick = (mode, key) => rows.filter((r) => r.mode === mode).map((r) => [r.n, r[key], key === 'largestFrac' ? r.largestStd : 0]);
  fs.writeFileSync(path.join(d, 'compare.svg'), T.svgChart({ title: 'Cohesion vs density: metric radius vs 7-nearest', xlabel: 'flock size N (fixed area)', ylabel: 'largest-cluster fraction',
    series: [{ name: 'metric', color: '#ff6b81', pts: pick('metric', 'largestFrac') }, { name: 'topological', color: '#5ee6a8', pts: pick('topological', 'largestFrac') }] }));
  console.log(`wrote ${d}/compare.csv, ${d}/compare.svg`);
}

function cmdHunt(args) {
  const base = engineOpts(args);
  const r = T.predatorTrial({ base, steps: intArg(args, 'steps', 1500), predators: intArg(args, 'predators', 1, 1) });
  console.log(`catches=${r.catches}  per1000=${r.per1000.toFixed(2)}  final polarization=${f3(r.finalPolarization)}  hash=${r.hash}`);
}

function cmdTune(args) {
  const base = engineOpts(args); if (base.n === undefined) base.n = 80;
  const res = T.tune({ generations: intArg(args, 'gens', 8, 1), popSize: intArg(args, 'pop', 14, 4), seed: intArg(args, 'seed', 5), base,
    onGen: (h) => console.log(`gen ${String(h.gen).padEnd(3)} best=${f3(h.best)} mean=${f3(h.mean)}`) });
  console.log('baseline (engine defaults) fitness:', f3(res.baselineFitness));
  console.log('best fitness:', f3(res.bestFitness));
  console.log('best genes:', JSON.stringify(Object.fromEntries(Object.entries(res.best).map(([k, v]) => [k, +v.toFixed(3)]))));
  const d = outDir(args);
  fs.writeFileSync(path.join(d, 'tuned.json'), JSON.stringify(res, null, 2));
  const ys = res.history.flatMap((h) => [h.best, h.mean]);
  fs.writeFileSync(path.join(d, 'tune.svg'), T.svgChart({ title: 'Genetic tuner convergence', xlabel: 'generation', ylabel: 'fitness', ymin: Math.floor(Math.min(...ys) * 10) / 10, ymax: Math.ceil(Math.max(...ys) * 10) / 10,
    series: [{ name: 'best', color: '#5ee6a8', pts: res.history.map((h) => [h.gen, h.best, 0]) }, { name: 'population mean', color: '#8b9ab8', pts: res.history.map((h) => [h.gen, h.mean, 0]) }] }));
  console.log(`wrote ${d}/tuned.json, ${d}/tune.svg`);
}

function cmdBench(args) {
  const n = intArg(args, 'n', 2000, 2);
  const f = new Flock({ n, width: 1200, height: 800, ...engineOpts(args) });
  f.rebuildIndex();
  const out = [], d2 = [];
  let t = process.hrtime.bigint();
  for (let i = 0; i < n; i++) f.queryRadius(i, f.p.radius, out, d2);
  const tg = Number(process.hrtime.bigint() - t) / 1e6;
  t = process.hrtime.bigint();
  const sample = Math.min(n, 300);
  for (let i = 0; i < sample; i++) f.bruteRadius(i, f.p.radius);
  const tb = Number(process.hrtime.bigint() - t) / 1e6 * (n / sample);
  t = process.hrtime.bigint();
  for (let i = 0; i < n; i++) f.queryKNN(i, 7, out, d2);
  const tk = Number(process.hrtime.bigint() - t) / 1e6;
  let bad = 0;
  for (let i = 0; i < Math.min(n, 200); i++) {
    f.queryKNN(i, 7, out, d2); const b = f.bruteKNN(i, 7);
    if (b.length !== out.length || b.some((e, q) => e[0] !== out[q])) bad++;
  }
  console.log(`n=${n}  radius queries: grid ${tg.toFixed(1)} ms vs brute ~${tb.toFixed(1)} ms (x${(tb / tg).toFixed(1)});  7-NN all agents: ${tk.toFixed(1)} ms;  kNN mismatches vs brute: ${bad}`);
  if (bad) process.exitCode = 1;
}

function cmdReplay(args) {
  if (!args.snapshot || args.snapshot === true) throw new Error('replay needs --snapshot FILE');
  let snap;
  try { snap = JSON.parse(fs.readFileSync(args.snapshot, 'utf8')); } catch (e) { throw new Error(`cannot read snapshot ${args.snapshot}: ${e.message}`); }
  const f = Flock.restore(snap);
  console.log(`restored step ${f.step_n}, hash ${f.hash()}`);
  f.run(intArg(args, 'steps', 100));
  console.log(`after +${intArg(args, 'steps', 100)} steps: step ${f.step_n}, hash ${f.hash()}`);
  if (args.expect) {
    if (f.hash() === args.expect) console.log('hash matches expected ✔');
    else { console.error(`HASH MISMATCH: expected ${args.expect}`); process.exitCode = 2; }
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args._[0];
  const table = { run: cmdRun, sweep: cmdSweep, compare: cmdCompare, hunt: cmdHunt, tune: cmdTune, bench: cmdBench, replay: cmdReplay };
  if (!cmd || cmd === 'help' || args.help) { console.log(USAGE); return; }
  if (!table[cmd]) { console.error(`unknown command "${cmd}"\n\n${USAGE}`); process.exitCode = 64; return; }
  try { checkFlags(args); table[cmd](args); } catch (e) { console.error('error: ' + e.message); process.exitCode = 1; }
}
if (require.main === module) main();
module.exports = { parseArgs, engineOpts };
