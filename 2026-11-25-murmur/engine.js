/* Murmur engine — deterministic flocking simulation + instruments.
 * UMD: works as `require('./engine')` in Node and as `window.Murmur` in a browser. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Murmur = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ---------------------------------------------------------------- PRNG
  // mulberry32 — state is a single uint32 so snapshots are trivial and exact.
  class Rng {
    constructor(seed) { this.s = (seed >>> 0) || 0x9e3779b9; }
    next() {
      this.s = (this.s + 0x6d2b79f5) >>> 0;
      let t = this.s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    range(a, b) { return a + (b - a) * this.next(); }
    gauss() { // Box–Muller, one value per call (keeps the state a single integer)
      let u = this.next(); if (u < 1e-12) u = 1e-12;
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * this.next());
    }
  }

  // ---------------------------------------------------------------- params
  const DEFAULTS = {
    n: 150, width: 600, height: 400, seed: 1,
    boundary: 'torus',            // 'torus' | 'wall'
    mode: 'metric',               // 'metric' (radius) | 'topological' (k nearest)
    radius: 50, k: 7,
    sepR: 14,
    wSep: 1.6, wAli: 1.0, wCoh: 0.8,
    maxSpeed: 60, minSpeed: 30, constSpeed: false,
    maxForce: 140,
    noise: 0.05,                  // std-dev of heading perturbation per step (radians)
    dt: 1 / 30,
    fearR: 90, wFlee: 4,
    predSpeed: 66, predTurn: 3.2, catchR: 6, predCooldown: 45,
    obsMargin: 16,
  };
  const BOUNDARIES = ['torus', 'wall'];
  const MODES = ['metric', 'topological'];

  function validateParams(p) {
    const err = (m) => { throw new RangeError('Murmur: ' + m); };
    const num = (k, lo, hi) => {
      const v = p[k];
      if (typeof v !== 'number' || !Number.isFinite(v)) err(`${k} must be a finite number (got ${v})`);
      if (v < lo || v > hi) err(`${k} must be in [${lo}, ${hi}] (got ${v})`);
    };
    if (!Number.isInteger(p.n)) err(`n must be an integer (got ${p.n})`);
    num('n', 0, 200000); num('width', 20, 100000); num('height', 20, 100000);
    num('radius', 1, 100000); num('sepR', 0.1, 100000); num('k', 1, 1000);
    if (!Number.isInteger(p.k)) err(`k must be an integer (got ${p.k})`);
    num('wSep', 0, 100); num('wAli', 0, 100); num('wCoh', 0, 100);
    num('maxSpeed', 0.001, 1e5); num('minSpeed', 0, 1e5); num('maxForce', 0, 1e6);
    if (p.minSpeed > p.maxSpeed) err(`minSpeed (${p.minSpeed}) exceeds maxSpeed (${p.maxSpeed})`);
    num('noise', 0, 6.3); num('dt', 1e-4, 1);
    num('fearR', 0, 1e5); num('wFlee', 0, 100); num('predSpeed', 0, 1e5);
    num('predTurn', 0, 100); num('catchR', 0, 1e4); num('predCooldown', 0, 1e6); num('obsMargin', 0, 1e4);
    if (!BOUNDARIES.includes(p.boundary)) err(`boundary must be one of ${BOUNDARIES} (got ${p.boundary})`);
    if (!MODES.includes(p.mode)) err(`mode must be one of ${MODES} (got ${p.mode})`);
    return p;
  }

  // ---------------------------------------------------------------- spatial hash
  class Grid {
    /** cell >= largest metric query radius so a 3x3 neighbourhood suffices for metric queries */
    constructor(width, height, torus, cell) {
      this.w = width; this.h = height; this.torus = torus;
      this.cols = Math.max(1, Math.floor(width / cell));
      this.rows = Math.max(1, Math.floor(height / cell));
      this.cw = width / this.cols; this.ch = height / this.rows;
      this.start = new Int32Array(this.cols * this.rows + 1);
      this.items = new Int32Array(0);
      this.stamp = new Int32Array(this.cols * this.rows);
      this.gen = 0;
    }
    cellOf(x, y) {
      let cx = Math.floor(x / this.cw), cy = Math.floor(y / this.ch);
      if (cx < 0) cx = 0; else if (cx >= this.cols) cx = this.cols - 1;
      if (cy < 0) cy = 0; else if (cy >= this.rows) cy = this.rows - 1;
      return [cx, cy];
    }
    build(xs, ys, n) {
      const nc = this.cols * this.rows;
      const start = this.start; start.fill(0);
      if (this.items.length < n) this.items = new Int32Array(n);
      const cellIdx = this._ci && this._ci.length >= n ? this._ci : (this._ci = new Int32Array(n));
      for (let i = 0; i < n; i++) {
        const [cx, cy] = this.cellOf(xs[i], ys[i]);
        const c = cy * this.cols + cx; cellIdx[i] = c; start[c + 1]++;
      }
      for (let c = 0; c < nc; c++) start[c + 1] += start[c];
      const fill = this._fill && this._fill.length >= nc ? this._fill : (this._fill = new Int32Array(nc));
      for (let c = 0; c < nc; c++) fill[c] = start[c];
      for (let i = 0; i < n; i++) this.items[fill[cellIdx[i]]++] = i;
    }
    /** wrapped/clipped cell index for offset, or -1 if outside (wall mode) */
    _cell(cx, cy) {
      if (this.torus) {
        cx %= this.cols; if (cx < 0) cx += this.cols;
        cy %= this.rows; if (cy < 0) cy += this.rows;
      } else if (cx < 0 || cy < 0 || cx >= this.cols || cy >= this.rows) return -1;
      return cy * this.cols + cx;
    }
  }

  // ---------------------------------------------------------------- Flock
  class Flock {
    constructor(opts = {}, _restore) {
      const p = Object.assign({}, DEFAULTS, opts);
      validateParams(p);
      this.p = p;
      this.rng = new Rng(p.seed);
      this.step_n = 0;
      this.caught = 0;
      this.obstacles = [];     // {x,y,r}
      this.predators = [];     // {x,y,vx,vy,cool}
      this.n = p.n;
      this.x = new Float64Array(p.n); this.y = new Float64Array(p.n);
      this.vx = new Float64Array(p.n); this.vy = new Float64Array(p.n);
      this._nx = new Float64Array(p.n); this._ny = new Float64Array(p.n);
      this._nvx = new Float64Array(p.n); this._nvy = new Float64Array(p.n);
      this._rebuildGrid();
      this._nb = []; this._nbd = [];
      if (!_restore) {
        for (let i = 0; i < p.n; i++) this._spawn(i);
      }
    }

    _rebuildGrid() {
      const p = this.p;
      // cell size must cover the metric radius and the separation radius
      const cell = Math.max(p.radius, p.sepR, 8);
      this.grid = new Grid(p.width, p.height, p.boundary === 'torus', cell);
    }

    /** change parameters live (UI sliders). Rebuilds the grid when geometry-related values change. */
    setParams(patch) {
      const next = Object.assign({}, this.p, patch);
      validateParams(next);
      if (next.n !== this.p.n) throw new RangeError('Murmur: n cannot change live; use resize(n)');
      const geo = ['radius', 'sepR', 'width', 'height', 'boundary'].some((k) => next[k] !== this.p[k]);
      this.p = next;
      if (geo) { this._rebuildGrid(); this._clampAll(); }
    }

    /** grow/shrink the flock (new agents spawn randomly) */
    resize(n) {
      if (!Number.isInteger(n) || n < 0 || n > 200000) throw new RangeError('Murmur: bad n ' + n);
      const old = this.n; if (n === old) return;
      const cp = (a) => { const b = new Float64Array(n); b.set(a.subarray(0, Math.min(old, n))); return b; };
      this.x = cp(this.x); this.y = cp(this.y); this.vx = cp(this.vx); this.vy = cp(this.vy);
      this._nx = new Float64Array(n); this._ny = new Float64Array(n);
      this._nvx = new Float64Array(n); this._nvy = new Float64Array(n);
      this.n = n; this.p = Object.assign({}, this.p, { n });
      for (let i = old; i < n; i++) this._spawn(i);
    }

    _spawn(i) {
      const p = this.p, r = this.rng;
      this.x[i] = r.range(0, p.width); this.y[i] = r.range(0, p.height);
      const a = r.range(0, 2 * Math.PI);
      const s = p.constSpeed ? p.maxSpeed : r.range(p.minSpeed, p.maxSpeed);
      this.vx[i] = Math.cos(a) * s; this.vy[i] = Math.sin(a) * s;
      this._pushOutOfObstacles(i);
    }

    _clampAll() {
      const p = this.p;
      for (let i = 0; i < this.n; i++) {
        if (p.boundary === 'torus') {
          this.x[i] = wrap(this.x[i], p.width); this.y[i] = wrap(this.y[i], p.height);
        } else {
          this.x[i] = clamp(this.x[i], 0, p.width); this.y[i] = clamp(this.y[i], 0, p.height);
        }
      }
    }

    addObstacle(x, y, r) {
      if (![x, y, r].every(Number.isFinite) || r <= 0) throw new RangeError('Murmur: bad obstacle');
      this.obstacles.push({ x, y, r });
      for (let i = 0; i < this.n; i++) this._pushOutOfObstacles(i);
    }
    removeObstacleAt(x, y) {
      for (let i = this.obstacles.length - 1; i >= 0; i--) {
        const o = this.obstacles[i];
        const [dx, dy] = this.delta(x, y, o.x, o.y);
        if (dx * dx + dy * dy <= o.r * o.r) { this.obstacles.splice(i, 1); return true; }
      }
      return false;
    }
    addPredator(x, y) {
      const p = this.p;
      if (![x, y].every(Number.isFinite)) throw new RangeError('Murmur: bad predator position');
      const a = this.rng.range(0, 2 * Math.PI);
      this.predators.push({ x: wrapOrClamp(x, p.width, p.boundary), y: wrapOrClamp(y, p.height, p.boundary),
        vx: Math.cos(a) * p.predSpeed, vy: Math.sin(a) * p.predSpeed, cool: 0 });
    }
    clearPredators() { this.predators.length = 0; }

    _pushOutOfObstacles(i) {
      for (const o of this.obstacles) {
        const [dx, dy] = this.delta(o.x, o.y, this.x[i], this.y[i]);
        const d = Math.hypot(dx, dy);
        if (d < o.r) {
          const ux = d > 1e-9 ? dx / d : 1, uy = d > 1e-9 ? dy / d : 0;
          this.x[i] = this._wrapX(o.x + ux * (o.r + 0.01)); this.y[i] = this._wrapY(o.y + uy * (o.r + 0.01));
        }
      }
    }
    _wrapX(v) { return this.p.boundary === 'torus' ? wrap(v, this.p.width) : clamp(v, 0, this.p.width); }
    _wrapY(v) { return this.p.boundary === 'torus' ? wrap(v, this.p.height) : clamp(v, 0, this.p.height); }

    /** displacement from (x1,y1) to (x2,y2), minimum-image on a torus */
    delta(x1, y1, x2, y2) {
      let dx = x2 - x1, dy = y2 - y1;
      if (this.p.boundary === 'torus') {
        const w = this.p.width, h = this.p.height;
        if (dx > w / 2) dx -= w; else if (dx < -w / 2) dx += w;
        if (dy > h / 2) dy -= h; else if (dy < -h / 2) dy += h;
      }
      return [dx, dy];
    }

    // ------------------------------------------------------------ neighbour queries
    /** all j != i with distance <= R (unsorted). Writes indices and squared dists to the out arrays. */
    queryRadius(i, R, out, outD2) {
      out.length = 0; outD2.length = 0;
      const g = this.grid, torus = this.p.boundary === 'torus';
      const xi = this.x[i], yi = this.y[i], R2 = R * R;
      const [cx, cy] = g.cellOf(xi, yi);
      const rx = Math.ceil(R / g.cw), ry = Math.ceil(R / g.ch);
      g.gen++;
      for (let dy = -ry; dy <= ry; dy++) {
        for (let dx = -rx; dx <= rx; dx++) {
          const c = g._cell(cx + dx, cy + dy);
          if (c < 0 || g.stamp[c] === g.gen) continue;
          g.stamp[c] = g.gen;
          for (let q = g.start[c]; q < g.start[c + 1]; q++) {
            const j = g.items[q]; if (j === i) continue;
            const [ddx, ddy] = this.delta(xi, yi, this.x[j], this.y[j]);
            const d2 = ddx * ddx + ddy * ddy;
            if (d2 <= R2) { out.push(j); outD2.push(d2); }
          }
        }
      }
    }

    /** exact k nearest neighbours of i, ordered by (distance, index). Ring expansion over the grid. */
    queryKNN(i, k, out, outD2) {
      out.length = 0; outD2.length = 0;
      const g = this.grid, torus = this.p.boundary === 'torus';
      const want = Math.min(k, this.n - 1);
      if (want <= 0) return;
      const xi = this.x[i], yi = this.y[i];
      const [cx, cy] = g.cellOf(xi, yi);
      const totalCells = g.cols * g.rows;
      const cmin = Math.min(g.cw, g.ch);
      g.gen++;
      let visited = 0;
      const maxR = Math.max(g.cols, g.rows);
      const consider = (c) => {
        if (c < 0 || g.stamp[c] === g.gen) return;
        g.stamp[c] = g.gen; visited++;
        for (let q = g.start[c]; q < g.start[c + 1]; q++) {
          const j = g.items[q]; if (j === i) continue;
          const [ddx, ddy] = this.delta(xi, yi, this.x[j], this.y[j]);
          const d2 = ddx * ddx + ddy * ddy;
          if (out.length === want) {
            const last = out.length - 1;
            if (d2 > outD2[last] || (d2 === outD2[last] && j > out[last])) continue;
            out.pop(); outD2.pop();
          }
          let pos = out.length;
          while (pos > 0 && (outD2[pos - 1] > d2 || (outD2[pos - 1] === d2 && out[pos - 1] > j))) pos--;
          out.splice(pos, 0, j); outD2.splice(pos, 0, d2);
        }
      };
      for (let r = 0; r <= maxR; r++) {
        if (r === 0) consider(g._cell(cx, cy));
        else {
          for (let dx = -r; dx <= r; dx++) { consider(g._cell(cx + dx, cy - r)); consider(g._cell(cx + dx, cy + r)); }
          for (let dy = -r + 1; dy <= r - 1; dy++) { consider(g._cell(cx - r, cy + dy)); consider(g._cell(cx + r, cy + dy)); }
        }
        if (visited >= totalCells) break;
        if (out.length === want) {
          const kth = Math.sqrt(outD2[out.length - 1]);
          if (kth <= r * cmin) break;
        }
      }
    }

    /** brute-force reference (O(n)) used by tests and the bench */
    bruteRadius(i, R) {
      const res = [];
      for (let j = 0; j < this.n; j++) {
        if (j === i) continue;
        const [dx, dy] = this.delta(this.x[i], this.y[i], this.x[j], this.y[j]);
        const d2 = dx * dx + dy * dy; if (d2 <= R * R) res.push([j, d2]);
      }
      return res;
    }
    bruteKNN(i, k) {
      const res = [];
      for (let j = 0; j < this.n; j++) {
        if (j === i) continue;
        const [dx, dy] = this.delta(this.x[i], this.y[i], this.x[j], this.y[j]);
        res.push([j, dx * dx + dy * dy]);
      }
      res.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
      return res.slice(0, k);
    }
    rebuildIndex() { this.grid.build(this.x, this.y, this.n); }

    // ------------------------------------------------------------ dynamics
    step() {
      const p = this.p, n = this.n, dt = p.dt;
      this.rebuildIndex();
      const nb = this._nb, nbd = this._nbd;
      const sepScale = p.sepR;
      for (let i = 0; i < n; i++) {
        const xi = this.x[i], yi = this.y[i], vxi = this.vx[i], vyi = this.vy[i];
        if (p.mode === 'metric') this.queryRadius(i, Math.max(p.radius, p.sepR), nb, nbd);
        else this.queryKNN(i, p.k, nb, nbd);
        let sx = 0, sy = 0, ax = 0, ay = 0, cx = 0, cy = 0, cnt = 0;
        const R2 = p.radius * p.radius, S2 = p.sepR * p.sepR;
        for (let q = 0; q < nb.length; q++) {
          const j = nb[q], d2 = nbd[q];
          const [dx, dy] = this.delta(xi, yi, this.x[j], this.y[j]);
          // separation always acts on anyone physically close, in either mode
          if (d2 < S2 && d2 > 1e-12) { sx -= dx / d2; sy -= dy / d2; }
          if (p.mode === 'metric' && d2 > R2) continue;  // alignment/cohesion radius
          ax += this.vx[j]; ay += this.vy[j]; cx += dx; cy += dy; cnt++;
        }
        let fx = 0, fy = 0;
        fx += p.wSep * sx * sepScale; fy += p.wSep * sy * sepScale;
        if (cnt > 0) {
          const mvx = ax / cnt, mvy = ay / cnt;
          fx += p.wAli * (mvx - vxi) / p.maxSpeed; fy += p.wAli * (mvy - vyi) / p.maxSpeed;
          const ox = cx / cnt, oy = cy / cnt, od = Math.hypot(ox, oy);
          if (od > 1e-9) { const m = od / (od + p.sepR); fx += p.wCoh * (ox / od) * m; fy += p.wCoh * (oy / od) * m; }
        }
        // predators
        for (const pr of this.predators) {
          const [dx, dy] = this.delta(pr.x, pr.y, xi, yi);
          const d = Math.hypot(dx, dy);
          if (d < p.fearR && d > 1e-9) { const m = (1 - d / p.fearR); fx += p.wFlee * (dx / d) * m; fy += p.wFlee * (dy / d) * m; }
        }
        // obstacles
        for (const o of this.obstacles) {
          const [dx, dy] = this.delta(o.x, o.y, xi, yi);
          const d = Math.hypot(dx, dy), reach = o.r + p.obsMargin;
          if (d < reach && d > 1e-9) {
            const m = (reach - d) / p.obsMargin;
            // steer away and also deflect sideways so flocks flow around rather than bounce
            const ux = dx / d, uy = dy / d;
            const side = (vxi * uy - vyi * ux) >= 0 ? 1 : -1;
            fx += 4 * m * (ux - side * uy * 0.5); fy += 4 * m * (uy + side * ux * 0.5);
          }
        }
        // walls
        if (p.boundary === 'wall') {
          const mg = Math.max(20, p.radius * 0.5);
          if (xi < mg) fx += (mg - xi) / mg * 3; else if (xi > p.width - mg) fx -= (xi - (p.width - mg)) / mg * 3;
          if (yi < mg) fy += (mg - yi) / mg * 3; else if (yi > p.height - mg) fy -= (yi - (p.height - mg)) / mg * 3;
        }
        // clip steering and integrate velocity
        let fm = Math.hypot(fx, fy);
        const fmax = p.maxForce * 1.0;
        if (fm > 1) { fx /= fm; fy /= fm; fm = 1; }
        let nvx = vxi + fx * fmax * dt, nvy = vyi + fy * fmax * dt;
        if (p.noise > 0) {
          const a = this.rng.gauss() * p.noise, c = Math.cos(a), s = Math.sin(a);
          const tx = nvx * c - nvy * s; nvy = nvx * s + nvy * c; nvx = tx;
        }
        let sp = Math.hypot(nvx, nvy);
        if (p.constSpeed) {
          if (sp < 1e-9) { const a = this.rng.range(0, 2 * Math.PI); nvx = Math.cos(a); nvy = Math.sin(a); sp = 1; }
          nvx = nvx / sp * p.maxSpeed; nvy = nvy / sp * p.maxSpeed;
        } else if (sp > p.maxSpeed) { nvx *= p.maxSpeed / sp; nvy *= p.maxSpeed / sp; }
        else if (sp < p.minSpeed) {
          if (sp < 1e-9) { const a = this.rng.range(0, 2 * Math.PI); nvx = Math.cos(a); nvy = Math.sin(a); sp = 1; }
          nvx *= p.minSpeed / sp; nvy *= p.minSpeed / sp;
        }
        this._nvx[i] = nvx; this._nvy[i] = nvy;
        this._nx[i] = xi + nvx * dt; this._ny[i] = yi + nvy * dt;
      }
      // commit (synchronous update)
      for (let i = 0; i < n; i++) {
        let x = this._nx[i], y = this._ny[i], vx = this._nvx[i], vy = this._nvy[i];
        if (p.boundary === 'torus') { x = wrap(x, p.width); y = wrap(y, p.height); }
        else {
          if (x < 0) { x = 0; vx = Math.abs(vx); } else if (x > p.width) { x = p.width; vx = -Math.abs(vx); }
          if (y < 0) { y = 0; vy = Math.abs(vy); } else if (y > p.height) { y = p.height; vy = -Math.abs(vy); }
        }
        // hard obstacle constraint
        for (const o of this.obstacles) {
          const [dx, dy] = this.delta(o.x, o.y, x, y);
          const d = Math.hypot(dx, dy);
          if (d < o.r) {
            const ux = d > 1e-9 ? dx / d : 1, uy = d > 1e-9 ? dy / d : 0;
            x = this._wrapX(o.x + ux * (o.r + 0.01)); y = this._wrapY(o.y + uy * (o.r + 0.01));
            const vn = vx * ux + vy * uy; if (vn < 0) { vx -= vn * ux; vy -= vn * uy; }
          }
        }
        this.x[i] = x; this.y[i] = y; this.vx[i] = vx; this.vy[i] = vy;
      }
      this._stepPredators();
      this.step_n++;
    }

    _stepPredators() {
      const p = this.p, dt = p.dt;
      for (const pr of this.predators) {
        if (pr.cool > 0) pr.cool--;
        // find target = nearest prey (with lead)
        let best = -1, bd2 = Infinity, bdx = 0, bdy = 0;
        if (pr.cool === 0) {
          for (let j = 0; j < this.n; j++) {
            const [dx, dy] = this.delta(pr.x, pr.y, this.x[j], this.y[j]);
            const d2 = dx * dx + dy * dy;
            if (d2 < bd2) { bd2 = d2; best = j; bdx = dx; bdy = dy; }
          }
        }
        if (best >= 0) {
          const d = Math.sqrt(bd2);
          if (d <= p.catchR) {
            this.caught++; pr.cool = p.predCooldown; this._spawn(best);
          } else {
            const lead = p.predSpeed > 0 ? Math.min(d / p.predSpeed, 1.0) : 0;
            const tx = bdx + this.vx[best] * lead, ty = bdy + this.vy[best] * lead;
            const want = Math.atan2(ty, tx), cur = Math.atan2(pr.vy, pr.vx);
            let da = want - cur; while (da > Math.PI) da -= 2 * Math.PI; while (da < -Math.PI) da += 2 * Math.PI;
            const maxTurn = p.predTurn * dt, turn = clamp(da, -maxTurn, maxTurn), a = cur + turn;
            pr.vx = Math.cos(a) * p.predSpeed; pr.vy = Math.sin(a) * p.predSpeed;
          }
        }
        let x = pr.x + pr.vx * dt, y = pr.y + pr.vy * dt;
        if (p.boundary === 'torus') { x = wrap(x, p.width); y = wrap(y, p.height); }
        else {
          if (x < 0 || x > p.width) { pr.vx = -pr.vx; x = clamp(x, 0, p.width); }
          if (y < 0 || y > p.height) { pr.vy = -pr.vy; y = clamp(y, 0, p.height); }
        }
        for (const o of this.obstacles) {
          const [dx, dy] = this.delta(o.x, o.y, x, y), d = Math.hypot(dx, dy);
          if (d < o.r) { const ux = d > 1e-9 ? dx / d : 1, uy = d > 1e-9 ? dy / d : 0; x = this._wrapX(o.x + ux * (o.r + 0.01)); y = this._wrapY(o.y + uy * (o.r + 0.01)); }
        }
        pr.x = x; pr.y = y;
      }
    }

    run(steps) { for (let s = 0; s < steps; s++) this.step(); return this; }

    // ------------------------------------------------------------ metrics
    /** Vicsek order parameter: |mean unit heading| in [0,1] */
    polarization() {
      let sx = 0, sy = 0, m = 0;
      for (let i = 0; i < this.n; i++) {
        const s = Math.hypot(this.vx[i], this.vy[i]); if (s < 1e-12) continue;
        sx += this.vx[i] / s; sy += this.vy[i] / s; m++;
      }
      return this.n === 0 ? 0 : Math.hypot(sx, sy) / this.n;
    }
    /** centre of mass (circular mean on a torus) */
    centroid() {
      const p = this.p, n = this.n;
      if (n === 0) return [p.width / 2, p.height / 2];
      if (p.boundary === 'wall') {
        let sx = 0, sy = 0; for (let i = 0; i < n; i++) { sx += this.x[i]; sy += this.y[i]; }
        return [sx / n, sy / n];
      }
      let cxs = 0, cxc = 0, cys = 0, cyc = 0;
      for (let i = 0; i < n; i++) {
        const ax = this.x[i] / p.width * 2 * Math.PI, ay = this.y[i] / p.height * 2 * Math.PI;
        cxs += Math.sin(ax); cxc += Math.cos(ax); cys += Math.sin(ay); cyc += Math.cos(ay);
      }
      return [wrap(Math.atan2(cxs, cxc) / (2 * Math.PI) * p.width, p.width), wrap(Math.atan2(cys, cyc) / (2 * Math.PI) * p.height, p.height)];
    }
    /** normalized angular momentum |Σ r̂ × v̂| / N about the centroid (1 = perfect milling) */
    angularMomentum() {
      if (this.n === 0) return 0;
      const [cx, cy] = this.centroid();
      let L = 0;
      for (let i = 0; i < this.n; i++) {
        const [rx, ry] = this.delta(cx, cy, this.x[i], this.y[i]);
        const rm = Math.hypot(rx, ry), vm = Math.hypot(this.vx[i], this.vy[i]);
        if (rm < 1e-9 || vm < 1e-9) continue;
        L += (rx * this.vy[i] - ry * this.vx[i]) / (rm * vm);
      }
      return Math.abs(L) / this.n;
    }
    meanNNDist() {
      if (this.n < 2) return 0;
      this.rebuildIndex();
      const o = [], d = []; let s = 0;
      for (let i = 0; i < this.n; i++) { this.queryKNN(i, 1, o, d); s += Math.sqrt(d[0]); }
      return s / this.n;
    }
    /** single-linkage clusters with link distance R (union-find) */
    clusters(R) {
      const n = this.n;
      if (n === 0) return { count: 0, largest: 0, largestFrac: 0, sizes: [] };
      this.rebuildIndex();
      const parent = new Int32Array(n); for (let i = 0; i < n; i++) parent[i] = i;
      const find = (a) => { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; } return a; };
      const out = [], d2 = [];
      // grid cell only guarantees radius coverage up to the cell size; queryRadius loops over extra cells if R is larger
      for (let i = 0; i < n; i++) {
        this.queryRadius(i, R, out, d2);
        for (const j of out) { const a = find(i), b = find(j); if (a !== b) parent[a] = b; }
      }
      const cnt = new Map(); for (let i = 0; i < n; i++) { const r = find(i); cnt.set(r, (cnt.get(r) || 0) + 1); }
      const sizes = [...cnt.values()].sort((a, b) => b - a);
      return { count: sizes.length, largest: sizes[0], largestFrac: sizes[0] / n, sizes };
    }
    /** number of pairs closer than R (collisions) */
    closePairs(R) {
      this.rebuildIndex();
      const out = [], d2 = []; let c = 0;
      for (let i = 0; i < this.n; i++) { this.queryRadius(i, R, out, d2); for (const j of out) if (j > i) c++; }
      return c;
    }
    metrics(linkR) {
      const p = this.p, R = linkR || Math.max(p.sepR * 2.5, 25);
      const cl = this.clusters(R);
      return { step: this.step_n, polarization: this.polarization(), angularMomentum: this.angularMomentum(),
        nnDist: this.meanNNDist(), clusters: cl.count, largestFrac: cl.largestFrac, caught: this.caught,
        collisions: this.closePairs(Math.max(p.sepR * 0.25, 1)) };
    }

    // ------------------------------------------------------------ snapshot / hash
    snapshot() {
      return { v: 1, p: Object.assign({}, this.p), rng: this.rng.s, step: this.step_n, caught: this.caught,
        x: Array.from(this.x), y: Array.from(this.y), vx: Array.from(this.vx), vy: Array.from(this.vy),
        obstacles: this.obstacles.map((o) => ({ ...o })), predators: this.predators.map((o) => ({ ...o })) };
    }
    static restore(s) {
      if (!s || s.v !== 1 || !s.p || !Array.isArray(s.x)) throw new Error('Murmur: not a valid snapshot');
      const n = s.p.n;
      for (const k of ['x', 'y', 'vx', 'vy']) {
        if (!Array.isArray(s[k]) || s[k].length !== n || !s[k].every(Number.isFinite)) throw new Error('Murmur: corrupt snapshot field ' + k);
      }
      const f = new Flock(s.p, true);
      f.rng.s = s.rng >>> 0; f.step_n = s.step; f.caught = s.caught;
      f.x.set(s.x); f.y.set(s.y); f.vx.set(s.vx); f.vy.set(s.vy);
      f.obstacles = s.obstacles.map((o) => ({ ...o })); f.predators = s.predators.map((o) => ({ ...o }));
      return f;
    }
    /** FNV-1a-64 (as two 32-bit halves) over the exact bit patterns of the full state */
    hash() {
      const buf = new DataView(new ArrayBuffer(8));
      let h1 = 0x811c9dc5, h2 = 0xcbf29ce4;
      const mix = (b) => { h1 = Math.imul(h1 ^ b, 0x01000193) >>> 0; h2 = Math.imul(h2 ^ b ^ (h1 >>> 7), 0x01000193) >>> 0; };
      const f64 = (v) => { buf.setFloat64(0, v); for (let k = 0; k < 8; k++) mix(buf.getUint8(k)); };
      const u32 = (v) => { for (let k = 0; k < 4; k++) mix((v >>> (8 * k)) & 255); };
      u32(this.step_n); u32(this.rng.s); u32(this.caught); u32(this.n);
      for (let i = 0; i < this.n; i++) { f64(this.x[i]); f64(this.y[i]); f64(this.vx[i]); f64(this.vy[i]); }
      for (const o of this.obstacles) { f64(o.x); f64(o.y); f64(o.r); }
      for (const o of this.predators) { f64(o.x); f64(o.y); f64(o.vx); f64(o.vy); u32(o.cool); }
      return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0');
    }
  }

  function wrap(v, m) { v %= m; return v < 0 ? v + m : v; }
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function wrapOrClamp(v, m, b) { return b === 'torus' ? wrap(v, m) : clamp(v, 0, m); }

  return { Rng, Flock, Grid, DEFAULTS, validateParams };
});
