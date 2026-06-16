/* Tumble engine — JS mirror of tumble/engine.py.
 *
 * Same operations, same order, same IEEE-754 doubles => bit-close parity with
 * the Python reference (verified by tests/test_tumble.py via node_parity.js).
 *
 * UMD: attaches `Tumble` to window in a browser, exports it in Node.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Tumble = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  class Particle {
    constructor(x, y, inv_mass = 1.0, radius = 6.0, vx = 0.0, vy = 0.0) {
      this.x = +x;
      this.y = +y;
      this.px = +x - +vx;
      this.py = +y - +vy;
      this.inv_mass = +inv_mass;
      this.radius = +radius;
    }
    get pinned() { return this.inv_mass === 0.0; }
    toDict() {
      return { x: this.x, y: this.y, px: this.px, py: this.py,
               inv_mass: this.inv_mass, radius: this.radius };
    }
    static fromDict(d) {
      const p = new Particle(d.x, d.y, d.inv_mass, d.radius);
      p.px = +d.px; p.py = +d.py;
      return p;
    }
  }

  class DistanceConstraint {
    constructor(i, j, rest, stiffness = 1.0, tearable = true) {
      this.i = i; this.j = j;
      this.rest = +rest;
      this.stiffness = +stiffness;
      this.tearable = !!tearable;
      this.active = true;
    }
    toDict() {
      return { i: this.i, j: this.j, rest: this.rest, stiffness: this.stiffness,
               tearable: this.tearable, active: this.active };
    }
    static fromDict(d) {
      const c = new DistanceConstraint(d.i, d.j, d.rest,
        d.stiffness === undefined ? 1.0 : d.stiffness,
        d.tearable === undefined ? true : d.tearable);
      c.active = d.active === undefined ? true : !!d.active;
      return c;
    }
  }

  class LineSegment {
    constructor(ax, ay, bx, by, radius = 0.0) {
      this.ax = +ax; this.ay = +ay; this.bx = +bx; this.by = +by;
      this.radius = +radius;
    }
    toDict() { return { ax: this.ax, ay: this.ay, bx: this.bx, by: this.by, radius: this.radius }; }
    static fromDict(d) { return new LineSegment(d.ax, d.ay, d.bx, d.by, d.radius || 0.0); }
  }

  class World {
    constructor(opts) {
      opts = opts || {};
      this.width = opts.width === undefined ? 800.0 : +opts.width;
      this.height = opts.height === undefined ? 600.0 : +opts.height;
      const g = opts.gravity || [0.0, 980.0];
      this.gx = +g[0]; this.gy = +g[1];
      this.dt = opts.dt === undefined ? 1.0 / 60.0 : +opts.dt;
      this.iterations = opts.iterations === undefined ? 8 : (opts.iterations | 0);
      this.damping = opts.damping === undefined ? 0.01 : +opts.damping;
      this.restitution = opts.restitution === undefined ? 0.3 : +opts.restitution;
      this.friction = opts.friction === undefined ? 0.05 : +opts.friction;
      const wnd = opts.wind || [0.0, 0.0];
      this.wx = +wnd[0]; this.wy = +wnd[1];
      this.self_collision = !!opts.self_collision;
      this.tearing = !!opts.tearing;
      this.tear_strain = opts.tear_strain === undefined ? 0.6 : +opts.tear_strain;
      this.cell_size = opts.cell_size === undefined ? 40.0 : +opts.cell_size;
      if (this.cell_size <= 0.0) this.cell_size = 1.0;
      this.particles = [];
      this.constraints = [];
      this.segments = [];
      this.time = 0.0;
    }

    addParticle(p) { this.particles.push(p); return this.particles.length - 1; }

    connect(i, j, rest, stiffness, tearable) {
      if (rest === undefined || rest === null) {
        const a = this.particles[i], b = this.particles[j];
        rest = Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
      }
      const c = new DistanceConstraint(i, j, rest,
        stiffness === undefined ? 1.0 : stiffness,
        tearable === undefined ? true : tearable);
      this.constraints.push(c);
      return c;
    }

    addSegment(s) { this.segments.push(s); return s; }

    step() {
      this._integrate();
      for (let it = 0; it < this.iterations; it++) {
        this._solveDistance();
        if (this.self_collision) this._solveCollisions();
        if (this.segments.length) this._solveSegments();
        this._solveBounds();
      }
      this.time += this.dt;
    }

    _integrate() {
      const dt2 = this.dt * this.dt;
      const keep = 1.0 - this.damping;
      const ax = this.gx + this.wx;
      const ay = this.gy + this.wy;
      const ps = this.particles;
      for (let k = 0; k < ps.length; k++) {
        const p = ps[k];
        if (p.inv_mass === 0.0) continue;
        const vx = (p.x - p.px) * keep;
        const vy = (p.y - p.py) * keep;
        p.px = p.x;
        p.py = p.y;
        p.x += vx + ax * dt2;
        p.y += vy + ay * dt2;
      }
    }

    _solveDistance() {
      const ps = this.particles;
      const tearing = this.tearing;
      const limit_factor = 1.0 + this.tear_strain;
      const cs = this.constraints;
      for (let k = 0; k < cs.length; k++) {
        const c = cs[k];
        if (!c.active) continue;
        const a = ps[c.i], b = ps[c.j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist === 0.0) continue;
        if (tearing && c.tearable && dist > c.rest * limit_factor) {
          c.active = false;
          continue;
        }
        const inv_sum = a.inv_mass + b.inv_mass;
        if (inv_sum === 0.0) continue;
        const diff = (dist - c.rest) / dist * c.stiffness;
        const wa = a.inv_mass / inv_sum;
        const wb = b.inv_mass / inv_sum;
        a.x += dx * diff * wa;
        a.y += dy * diff * wa;
        b.x -= dx * diff * wb;
        b.y -= dy * diff * wb;
      }
    }

    _gridPairs() {
      const cs = this.cell_size;
      const ps = this.particles;
      const grid = new Map();
      for (let idx = 0; idx < ps.length; idx++) {
        const p = ps[idx];
        const key = Math.floor(p.x / cs) + "," + Math.floor(p.y / cs);
        let b = grid.get(key);
        if (!b) { b = []; grid.set(key, b); }
        b.push(idx);
      }
      const offsets = [[-1, -1], [0, -1], [1, -1],
                       [-1, 0], [0, 0], [1, 0],
                       [-1, 1], [0, 1], [1, 1]];
      const pairs = [];
      for (let i = 0; i < ps.length; i++) {
        const p = ps[i];
        const cx = Math.floor(p.x / cs);
        const cy = Math.floor(p.y / cs);
        for (let o = 0; o < offsets.length; o++) {
          const bucket = grid.get((cx + offsets[o][0]) + "," + (cy + offsets[o][1]));
          if (!bucket) continue;
          for (let m = 0; m < bucket.length; m++) {
            const j = bucket[m];
            if (j > i) pairs.push(i, j);
          }
        }
      }
      return pairs;
    }

    _solveCollisions() {
      const ps = this.particles;
      const pairs = this._gridPairs();
      for (let k = 0; k < pairs.length; k += 2) {
        const a = ps[pairs[k]], b = ps[pairs[k + 1]];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const min_d = a.radius + b.radius;
        const d2 = dx * dx + dy * dy;
        if (d2 >= min_d * min_d) continue;
        const inv_sum = a.inv_mass + b.inv_mass;
        if (inv_sum === 0.0) continue;
        let dist = Math.sqrt(d2);
        if (dist === 0.0) { dx = 1.0; dy = 0.0; dist = 1.0; }
        const overlap = (min_d - dist) / dist;
        const wa = a.inv_mass / inv_sum;
        const wb = b.inv_mass / inv_sum;
        a.x -= dx * overlap * wa;
        a.y -= dy * overlap * wa;
        b.x += dx * overlap * wb;
        b.y += dy * overlap * wb;
      }
    }

    _solveSegments() {
      const ps = this.particles;
      const segs = this.segments;
      for (let k = 0; k < ps.length; k++) {
        const p = ps[k];
        if (p.inv_mass === 0.0) continue;
        for (let m = 0; m < segs.length; m++) {
          const s = segs[m];
          const abx = s.bx - s.ax;
          const aby = s.by - s.ay;
          const ab2 = abx * abx + aby * aby;
          let cx, cy;
          if (ab2 === 0.0) { cx = s.ax; cy = s.ay; }
          else {
            let t = ((p.x - s.ax) * abx + (p.y - s.ay) * aby) / ab2;
            if (t < 0.0) t = 0.0; else if (t > 1.0) t = 1.0;
            cx = s.ax + abx * t;
            cy = s.ay + aby * t;
          }
          const dx = p.x - cx;
          const dy = p.y - cy;
          const r = p.radius + s.radius;
          const d2 = dx * dx + dy * dy;
          if (d2 >= r * r || d2 === 0.0) continue;
          const dist = Math.sqrt(d2);
          const push = (r - dist) / dist;
          p.x += dx * push;
          p.y += dy * push;
        }
      }
    }

    _solveBounds() {
      const rest = this.restitution;
      const fric = this.friction;
      const w = this.width;
      const h = this.height;
      const ps = this.particles;
      for (let k = 0; k < ps.length; k++) {
        const p = ps[k];
        if (p.inv_mass === 0.0) continue;
        const r = p.radius;
        let vx = p.x - p.px;
        let vy = p.y - p.py;
        if (p.x < r) {
          p.x = r;
          p.px = p.x + vx * rest;
          p.py = p.y - vy * (1.0 - fric);
        } else if (p.x > w - r) {
          p.x = w - r;
          p.px = p.x + vx * rest;
          p.py = p.y - vy * (1.0 - fric);
        }
        vx = p.x - p.px;
        vy = p.y - p.py;
        if (p.y < r) {
          p.y = r;
          p.py = p.y + vy * rest;
          p.px = p.x - vx * (1.0 - fric);
        } else if (p.y > h - r) {
          p.y = h - r;
          p.py = p.y + vy * rest;
          p.px = p.x - vx * (1.0 - fric);
        }
      }
    }

    kineticEnergy() {
      let ke = 0.0;
      const ps = this.particles;
      for (let k = 0; k < ps.length; k++) {
        const p = ps[k];
        if (p.inv_mass === 0.0) continue;
        const vx = p.x - p.px, vy = p.y - p.py;
        const mass = 1.0 / p.inv_mass;
        ke += 0.5 * mass * (vx * vx + vy * vy);
      }
      return ke;
    }

    activeConstraints() {
      let n = 0;
      for (let k = 0; k < this.constraints.length; k++) if (this.constraints[k].active) n++;
      return n;
    }

    toDict() {
      return {
        width: this.width, height: this.height, gravity: [this.gx, this.gy],
        dt: this.dt, iterations: this.iterations, damping: this.damping,
        restitution: this.restitution, friction: this.friction,
        wind: [this.wx, this.wy], self_collision: this.self_collision,
        tearing: this.tearing, tear_strain: this.tear_strain,
        cell_size: this.cell_size, time: this.time,
        particles: this.particles.map((p) => p.toDict()),
        constraints: this.constraints.map((c) => c.toDict()),
        segments: this.segments.map((s) => s.toDict()),
      };
    }

    static fromDict(d) {
      const w = new World({
        width: d.width, height: d.height, gravity: d.gravity, dt: d.dt,
        iterations: d.iterations, damping: d.damping, restitution: d.restitution,
        friction: d.friction, wind: d.wind, self_collision: d.self_collision,
        tearing: d.tearing, tear_strain: d.tear_strain, cell_size: d.cell_size,
      });
      w.time = d.time || 0.0;
      w.particles = (d.particles || []).map(Particle.fromDict);
      w.constraints = (d.constraints || []).map(DistanceConstraint.fromDict);
      w.segments = (d.segments || []).map(LineSegment.fromDict);
      return w;
    }
  }

  /* ---- builders (mirror of tumble/builders.py) ---------------------------- */
  const builders = {
    rope(world, x0, y0, x1, y1, o) {
      o = o || {};
      const segments = o.segments === undefined ? 12 : o.segments;
      const pin_start = o.pin_start === undefined ? true : o.pin_start;
      const pin_end = o.pin_end === undefined ? false : o.pin_end;
      const radius = o.radius === undefined ? 5.0 : o.radius;
      const stiffness = o.stiffness === undefined ? 1.0 : o.stiffness;
      const mass = o.mass === undefined ? 1.0 : o.mass;
      const tearable = o.tearable === undefined ? true : o.tearable;
      const inv = mass === 0.0 ? 0.0 : 1.0 / mass;
      const idxs = [];
      for (let k = 0; k <= segments; k++) {
        const t = k / segments;
        const x = x0 + (x1 - x0) * t;
        const y = y0 + (y1 - y0) * t;
        let im = inv;
        if ((k === 0 && pin_start) || (k === segments && pin_end)) im = 0.0;
        idxs.push(world.addParticle(new Particle(x, y, im, radius)));
      }
      for (let k = 0; k < segments; k++)
        world.connect(idxs[k], idxs[k + 1], undefined, stiffness, tearable);
      return idxs;
    },

    cloth(world, x0, y0, cols, rows, o) {
      o = o || {};
      const spacing = o.spacing === undefined ? 22.0 : o.spacing;
      const pin_top = o.pin_top === undefined ? true : o.pin_top;
      const pin_corners_only = !!o.pin_corners_only;
      const radius = o.radius === undefined ? 4.0 : o.radius;
      const stiffness = o.stiffness === undefined ? 0.9 : o.stiffness;
      const mass = o.mass === undefined ? 1.0 : o.mass;
      const bend = o.bend === undefined ? true : o.bend;
      const tearable = o.tearable === undefined ? true : o.tearable;
      const inv = mass === 0.0 ? 0.0 : 1.0 / mass;
      const grid = [];
      for (let r = 0; r < rows; r++) {
        grid.push([]);
        for (let c = 0; c < cols; c++) {
          const x = x0 + c * spacing;
          const y = y0 + r * spacing;
          let im = inv;
          if (r === 0 && pin_top) {
            if (pin_corners_only) { if (c === 0 || c === cols - 1) im = 0.0; }
            else im = 0.0;
          }
          grid[r].push(world.addParticle(new Particle(x, y, im, radius)));
        }
      }
      for (let r = 0; r < rows; r++)
        for (let c = 0; c < cols; c++) {
          if (c + 1 < cols) world.connect(grid[r][c], grid[r][c + 1], undefined, stiffness, tearable);
          if (r + 1 < rows) world.connect(grid[r][c], grid[r + 1][c], undefined, stiffness, tearable);
        }
      const sh = stiffness * 0.6;
      for (let r = 0; r < rows - 1; r++)
        for (let c = 0; c < cols - 1; c++) {
          world.connect(grid[r][c], grid[r + 1][c + 1], undefined, sh, tearable);
          world.connect(grid[r + 1][c], grid[r][c + 1], undefined, sh, tearable);
        }
      if (bend) {
        const bd = stiffness * 0.3;
        for (let r = 0; r < rows; r++)
          for (let c = 0; c < cols; c++) {
            if (c + 2 < cols) world.connect(grid[r][c], grid[r][c + 2], undefined, bd, false);
            if (r + 2 < rows) world.connect(grid[r][c], grid[r + 2][c], undefined, bd, false);
          }
      }
      return grid;
    },

    box(world, cx, cy, w, h, o) {
      o = o || {};
      const radius = o.radius === undefined ? 6.0 : o.radius;
      const stiffness = o.stiffness === undefined ? 1.0 : o.stiffness;
      const mass = o.mass === undefined ? 1.0 : o.mass;
      const vx = o.vx || 0.0, vy = o.vy || 0.0;
      const inv = mass === 0.0 ? 0.0 : 1.0 / mass;
      const hw = w / 2.0, hh = h / 2.0;
      const corners = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]];
      const idxs = [];
      for (const cc of corners)
        idxs.push(world.addParticle(new Particle(cx + cc[0], cy + cc[1], inv, radius, vx, vy)));
      const edges = [[0, 1], [1, 2], [2, 3], [3, 0], [0, 2], [1, 3]];
      for (const e of edges) world.connect(idxs[e[0]], idxs[e[1]], undefined, stiffness, false);
      return idxs;
    },

    blob(world, cx, cy, r, o) {
      o = o || {};
      const n = o.n === undefined ? 14 : o.n;
      const radius = o.radius === undefined ? 6.0 : o.radius;
      const stiffness = o.stiffness === undefined ? 0.6 : o.stiffness;
      const mass = o.mass === undefined ? 1.0 : o.mass;
      const vx = o.vx || 0.0, vy = o.vy || 0.0;
      const inv = mass === 0.0 ? 0.0 : 1.0 / mass;
      const hub = world.addParticle(new Particle(cx, cy, inv, radius, vx, vy));
      const ring = [];
      for (let k = 0; k < n; k++) {
        const ang = 2.0 * Math.PI * k / n;
        ring.push(world.addParticle(new Particle(cx + Math.cos(ang) * r, cy + Math.sin(ang) * r, inv, radius, vx, vy)));
      }
      for (let k = 0; k < n; k++) {
        world.connect(ring[k], ring[(k + 1) % n], undefined, stiffness, false);
        world.connect(hub, ring[k], undefined, stiffness * 0.8, false);
        world.connect(ring[k], ring[(k + 2) % n], undefined, stiffness * 0.5, false);
      }
      return [hub].concat(ring);
    },
  };

  /* ---- scenes (mirror of tumble/scenes.py) ------------------------------- */
  const SW = 900.0, SH = 600.0;
  const scenes = {
    rope() {
      const w = new World({ width: SW, height: SH, iterations: 10, damping: 0.02 });
      builders.rope(w, 250, 40, 650, 40, { segments: 18, pin_start: true, pin_end: true, stiffness: 1.0 });
      return w;
    },
    pendulum() {
      const w = new World({ width: SW, height: SH, iterations: 30, damping: 0.0, restitution: 0.0 });
      builders.rope(w, 450, 80, 650, 80, { segments: 1, pin_start: true, pin_end: false, radius: 12.0, stiffness: 1.0, mass: 1.0 });
      return w;
    },
    cloth() {
      const w = new World({ width: SW, height: SH, iterations: 8, damping: 0.02, wind: [60.0, 0.0], tearing: true, tear_strain: 0.8 });
      builders.cloth(w, 230, 50, 22, 15, { spacing: 20.0, pin_top: true, stiffness: 0.9 });
      return w;
    },
    curtain() {
      const w = new World({ width: SW, height: SH, iterations: 10, damping: 0.02, tearing: true, tear_strain: 0.7 });
      builders.cloth(w, 200, 60, 24, 14, { spacing: 22.0, pin_top: true, pin_corners_only: true, stiffness: 0.9 });
      return w;
    },
    ballpit() {
      const w = new World({ width: SW, height: SH, iterations: 6, damping: 0.01, restitution: 0.35, friction: 0.08, self_collision: true, cell_size: 44.0 });
      // BigInt LCG so the multiply stays exact (matches Python's int & 0x7FFFFFFF)
      let seed = 1234567n;
      const A = 1103515245n, C = 12345n, M = 0x7FFFFFFFn;
      const n = 60;
      for (let k = 0; k < n; k++) {
        seed = (A * seed + C) & M;
        const x = 80.0 + Number(seed % 740n);
        seed = (A * seed + C) & M;
        const y = 40.0 + Number(seed % 260n);
        seed = (A * seed + C) & M;
        const r = 10.0 + Number(seed % 12n);
        w.addParticle(new Particle(x, y, 1.0, r));
      }
      return w;
    },
    boxes() {
      const w = new World({ width: SW, height: SH, iterations: 12, damping: 0.01, restitution: 0.1, friction: 0.2 });
      builders.box(w, 300, 120, 90, 70, { vx: 20.0 });
      builders.box(w, 520, 80, 70, 70);
      builders.box(w, 680, 150, 110, 60, { vx: -15.0 });
      return w;
    },
    blobs() {
      const w = new World({ width: SW, height: SH, iterations: 10, damping: 0.02, restitution: 0.2, friction: 0.1, self_collision: true, cell_size: 60.0 });
      builders.blob(w, 350, 120, 55, { n: 16, vx: 10.0 });
      builders.blob(w, 560, 90, 45, { n: 14, vx: -10.0 });
      return w;
    },
    obstacles() {
      const w = new World({ width: SW, height: SH, iterations: 10, damping: 0.02 });
      builders.cloth(w, 280, 40, 16, 10, { spacing: 22.0, pin_top: false, stiffness: 0.9 });
      w.addSegment(new LineSegment(120, 360, 460, 460, 6.0));
      w.addSegment(new LineSegment(780, 360, 460, 520, 6.0));
      w.addSegment(new LineSegment(300, 540, 600, 540, 6.0));
      return w;
    },
  };

  function buildScene(name) {
    if (!scenes[name]) throw new Error("unknown scene: " + name);
    return scenes[name]();
  }

  return {
    Particle, DistanceConstraint, LineSegment, World,
    builders, scenes, buildScene,
    sceneNames: () => Object.keys(scenes),
  };
});
