'use strict';
/* Experiments, genetic tuner and SVG plotting built on engine.js */
const { Flock, Rng, DEFAULTS } = require('./engine');

const mean = (a) => (a.length ? a.reduce((s, v) => s + v, 0) / a.length : 0);
const std = (a) => { if (a.length < 2) return 0; const m = mean(a); return Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / (a.length - 1)); };

/** run a flock `burn` steps then average metrics over `window` further steps, sampled every `every` steps */
function measure(opts, { burn = 300, window = 150, every = 10, linkR } = {}) {
  const f = new Flock(opts);
  f.run(burn);
  const acc = { polarization: [], angularMomentum: [], largestFrac: [], clusters: [], nnDist: [], collisions: [] };
  for (let s = 0; s < window; s++) {
    f.step();
    if (s % every === 0) {
      const m = f.metrics(linkR);
      for (const k of Object.keys(acc)) acc[k].push(m[k]);
    }
  }
  const out = {}; for (const k of Object.keys(acc)) out[k] = mean(acc[k]);
  out.caught = f.caught; out.hash = f.hash();
  return out;
}

/** order parameter vs noise: the order→disorder transition */
function noiseSweep({ noises, reps = 3, base = {}, burn = 300, window = 150, constSpeed = true } = {}) {
  if (!noises || !noises.length) throw new RangeError('noiseSweep: noises must be non-empty');
  return noises.map((noise) => {
    const pols = [], fr = [];
    for (let r = 0; r < reps; r++) {
      const m = measure({ ...base, noise, constSpeed, seed: (base.seed || 1) * 1000 + r }, { burn, window });
      pols.push(m.polarization); fr.push(m.largestFrac);
    }
    return { noise, polarization: mean(pols), polStd: std(pols), largestFrac: mean(fr), reps };
  });
}

/** same world, varying density: does the neighbourhood rule keep the flock together? */
function densitySweep({ ns, modes = ['metric', 'topological'], reps = 3, base = {}, burn = 300, window = 150 } = {}) {
  const rows = [];
  for (const n of ns) for (const mode of modes) {
    const pol = [], fr = [], cl = [], nn = [];
    for (let r = 0; r < reps; r++) {
      // the same seed per rep for both modes → paired comparison
      const m = measure({ ...base, n, mode, seed: 7000 + r }, { burn, window });
      pol.push(m.polarization); fr.push(m.largestFrac); cl.push(m.clusters); nn.push(m.nnDist);
    }
    rows.push({ n, mode, polarization: mean(pol), largestFrac: mean(fr), largestStd: std(fr), clusters: mean(cl), nnDist: mean(nn), reps });
  }
  return rows;
}

/** predator experiment: catches per 1000 steps */
function predatorTrial({ base = {}, steps = 1500, predators = 1, obstacles = [] } = {}) {
  const f = new Flock(base);
  for (const o of obstacles) f.addObstacle(o.x, o.y, o.r);
  for (let i = 0; i < predators; i++) f.addPredator(f.p.width * (0.2 + 0.6 * f.rng.next()), f.p.height * (0.2 + 0.6 * f.rng.next()));
  f.run(200); const c0 = f.caught;
  f.run(steps);
  return { catches: f.caught - c0, per1000: (f.caught - c0) / steps * 1000, finalPolarization: f.polarization(), hash: f.hash() };
}

// -------------------------------------------------------------------- genetic tuner
const GENES = [
  { key: 'wSep', lo: 0.2, hi: 4 }, { key: 'wAli', lo: 0, hi: 3 }, { key: 'wCoh', lo: 0, hi: 3 },
  { key: 'sepR', lo: 6, hi: 30 }, { key: 'radius', lo: 25, hi: 90 }, { key: 'k', lo: 2, hi: 14, int: true },
  { key: 'wFlee', lo: 0, hi: 8 },
];

/** fitness of a parameter set: ordered, cohesive, not colliding, and hard for a predator to catch */
function fitness(genes, { base = {}, seeds = [11, 12], steps = 400 } = {}) {
  let tot = 0;
  for (const seed of seeds) {
    const f = new Flock({ ...base, ...genes, seed });
    f.addPredator(f.p.width / 2, f.p.height / 2);
    f.run(150); const c0 = f.caught;
    let pol = 0, frac = 0, col = 0, ns = 0;
    for (let s = 0; s < steps; s++) {
      f.step();
      if (s % 20 === 0) { const m = f.metrics(); pol += m.polarization; frac += m.largestFrac; col += m.collisions / f.n; ns++; }
    }
    const caught = f.caught - c0;
    tot += 0.8 * (pol / ns) + 1.0 * (frac / ns) - 4 * (col / ns) - 0.02 * caught;
  }
  return tot / seeds.length;
}

function randomGenome(rng) {
  const g = {};
  for (const d of GENES) { const v = rng.range(d.lo, d.hi); g[d.key] = d.int ? Math.round(v) : v; }
  return g;
}

/** (μ+λ) genetic algorithm with tournament selection, blend crossover and gaussian mutation. */
function tune({ generations = 8, popSize = 14, seed = 5, base = {}, evalOpts = {}, onGen } = {}) {
  if (popSize < 4) throw new RangeError('tune: popSize must be >= 4');
  const rng = new Rng(seed);
  const evalg = (g) => fitness(g, { base, ...evalOpts });
  let pop = [];
  // seed one individual from the engine defaults so we can report improvement over them
  const dflt = {}; for (const d of GENES) dflt[d.key] = DEFAULTS[d.key];
  pop.push({ genes: dflt, fit: evalg(dflt) });
  while (pop.length < popSize) { const g = randomGenome(rng); pop.push({ genes: g, fit: evalg(g) }); }
  const baseline = pop[0].fit;
  const history = [];
  const tourney = () => { let best = null; for (let i = 0; i < 3; i++) { const c = pop[Math.floor(rng.next() * pop.length)]; if (!best || c.fit > best.fit) best = c; } return best; };
  for (let gen = 0; gen < generations; gen++) {
    pop.sort((a, b) => b.fit - a.fit);
    history.push({ gen, best: pop[0].fit, mean: mean(pop.map((p) => p.fit)) });
    if (onGen) onGen(history[history.length - 1], pop[0]);
    const kids = [];
    while (kids.length < popSize) {
      const a = tourney(), b = tourney(), g = {};
      for (const d of GENES) {
        const t = rng.range(-0.25, 1.25);
        let v = a.genes[d.key] * (1 - t) + b.genes[d.key] * t;
        if (rng.next() < 0.3) v += rng.gauss() * (d.hi - d.lo) * 0.1;
        v = Math.min(d.hi, Math.max(d.lo, v));
        g[d.key] = d.int ? Math.round(v) : v;
      }
      kids.push({ genes: g, fit: evalg(g) });
    }
    pop = pop.concat(kids).sort((a, b) => b.fit - a.fit).slice(0, popSize); // elitist survivor selection
  }
  pop.sort((a, b) => b.fit - a.fit);
  history.push({ gen: generations, best: pop[0].fit, mean: mean(pop.map((p) => p.fit)) });
  return { best: pop[0].genes, bestFitness: pop[0].fit, baselineFitness: baseline, history };
}

// -------------------------------------------------------------------- SVG
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/** series: [{name, color, pts:[[x,y,err?]]}] */
function svgChart({ title, xlabel, ylabel, series, ymin = 0, ymax = 1, width = 640, height = 380 }) {
  const L = 64, R = 24, T = 44, B = 56, W = width - L - R, H = height - T - B;
  const xs = series.flatMap((s) => s.pts.map((p) => p[0]));
  if (!xs.length) throw new RangeError('svgChart: no data');
  let x0 = Math.min(...xs), x1 = Math.max(...xs); if (x0 === x1) { x0 -= 1; x1 += 1; }
  const X = (v) => L + (v - x0) / (x1 - x0) * W, Y = (v) => T + H - (v - ymin) / (ymax - ymin) * H;
  let g = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" font-family="system-ui,sans-serif" font-size="12">`;
  g += `<rect width="${width}" height="${height}" fill="#0f1420"/>`;
  g += `<text x="${L}" y="26" fill="#e6edf7" font-size="15" font-weight="600">${esc(title)}</text>`;
  for (let i = 0; i <= 5; i++) {
    const v = ymin + (ymax - ymin) * i / 5, y = Y(v);
    g += `<line x1="${L}" x2="${L + W}" y1="${y}" y2="${y}" stroke="#26304a"/><text x="${L - 8}" y="${y + 4}" fill="#8b9ab8" text-anchor="end">${+v.toFixed(2)}</text>`;
  }
  for (let i = 0; i <= 5; i++) {
    const v = x0 + (x1 - x0) * i / 5, x = X(v);
    g += `<line y1="${T}" y2="${T + H}" x1="${x}" x2="${x}" stroke="#1b2438"/><text x="${x}" y="${T + H + 18}" fill="#8b9ab8" text-anchor="middle">${+v.toFixed(3)}</text>`;
  }
  g += `<text x="${L + W / 2}" y="${height - 12}" fill="#b6c3dc" text-anchor="middle">${esc(xlabel)}</text>`;
  g += `<text transform="translate(16 ${T + H / 2}) rotate(-90)" fill="#b6c3dc" text-anchor="middle">${esc(ylabel)}</text>`;
  series.forEach((s, si) => {
    const pts = s.pts.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ');
    for (const p of s.pts) if (p[2] > 0) g += `<line x1="${X(p[0])}" x2="${X(p[0])}" y1="${Y(p[1] - p[2])}" y2="${Y(p[1] + p[2])}" stroke="${s.color}" stroke-opacity=".5"/>`;
    g += `<polyline fill="none" stroke="${s.color}" stroke-width="2.5" points="${pts}"/>`;
    for (const p of s.pts) g += `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="3.5" fill="${s.color}"/>`;
    g += `<rect x="${L + 10 + si * 150}" y="${T + 8}" width="10" height="10" fill="${s.color}"/><text x="${L + 26 + si * 150}" y="${T + 17}" fill="#e6edf7">${esc(s.name)}</text>`;
  });
  return g + '</svg>';
}

function toCSV(rows) {
  if (!rows.length) return '';
  const keys = Object.keys(rows[0]);
  return [keys.join(','), ...rows.map((r) => keys.map((k) => (typeof r[k] === 'number' ? +r[k].toFixed(6) : r[k])).join(','))].join('\n') + '\n';
}

module.exports = { measure, noiseSweep, densitySweep, predatorTrial, fitness, tune, GENES, svgChart, toCSV, mean, std };
