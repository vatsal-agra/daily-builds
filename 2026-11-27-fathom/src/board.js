// Minesweeper game engine.
import { makeRng, shuffle } from './rng.js';

export const HIDDEN = 0, REVEALED = 1, FLAGGED = 2;

export const DIFFICULTIES = {
  beginner: { w: 9, h: 9, mines: 10 },
  intermediate: { w: 16, h: 16, mines: 40 },
  expert: { w: 30, h: 16, mines: 99 },
};

export function validateConfig({ w, h, mines }) {
  if (!Number.isInteger(w) || !Number.isInteger(h) || w < 2 || h < 2 || w > 100 || h > 100)
    throw new RangeError('width/height must be integers in 2..100');
  if (!Number.isInteger(mines) || mines < 1) throw new RangeError('mines must be a positive integer');
  if (mines > w * h - 1) throw new RangeError(`too many mines: max ${w * h - 1} for ${w}x${h}`);
}

export function neighborTable(w, h) {
  const nb = new Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const list = [];
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      if (!dx && !dy) continue;
      const nx = x + dx, ny = y + dy;
      if (nx >= 0 && ny >= 0 && nx < w && ny < h) list.push(ny * w + nx);
    }
    nb[y * w + x] = list;
  }
  return nb;
}

/**
 * Choose mine positions with a safe zone around `first` (the cell and, when the
 * board is roomy enough, all its neighbours). Returns a sorted array of indices.
 */
export function placeMines(w, h, mines, first, rng) {
  validateConfig({ w, h, mines });
  const nb = neighborTable(w, h);
  let banned = new Set([first, ...nb[first]]);
  if (w * h - banned.size < mines) banned = new Set([first]);
  const pool = [];
  for (let i = 0; i < w * h; i++) if (!banned.has(i)) pool.push(i);
  if (pool.length < mines) throw new RangeError('not enough room for mines');
  shuffle(pool, rng);
  return pool.slice(0, mines).sort((a, b) => a - b);
}

export class Game {
  /**
   * @param {{w:number,h:number,mines:number,seed?:string|number,layout?:number[]}} cfg
   * If `layout` (array of mine indices) is given the board is fixed from the start;
   * otherwise mines are placed on the first reveal so the first click is always safe.
   */
  constructor(cfg) {
    const { w, h, mines } = cfg;
    validateConfig({ w, h, mines });
    this.w = w; this.h = h; this.mines = mines; this.n = w * h;
    this.seed = cfg.seed ?? 'fathom';
    this.nb = neighborTable(w, h);
    this.state = new Uint8Array(this.n);
    this.mine = new Uint8Array(this.n);
    this.adj = new Uint8Array(this.n);
    this.placed = false;
    this.status = 'ready'; // ready | playing | won | lost
    this.revealedCount = 0;
    this.flagCount = 0;
    this.exploded = -1;
    this.layoutProvider = cfg.layoutProvider || null; // (first)=>number[]
    if (cfg.layout) this.#applyLayout(cfg.layout);
  }

  static fromLayout(w, h, layout, seed) {
    return new Game({ w, h, mines: layout.length, layout, seed });
  }

  #applyLayout(layout) {
    const set = new Set(layout);
    if (set.size !== this.mines) throw new RangeError('layout must contain exactly `mines` distinct cells');
    for (const i of set) {
      if (!Number.isInteger(i) || i < 0 || i >= this.n) throw new RangeError('layout cell out of range');
      this.mine[i] = 1;
    }
    for (let i = 0; i < this.n; i++) {
      let c = 0;
      for (const j of this.nb[i]) c += this.mine[j];
      this.adj[i] = c;
    }
    this.placed = true;
  }

  idx(x, y) { return y * this.w + x; }

  /** Reveal a cell. Returns {opened:number[], boom:boolean}. */
  reveal(i) {
    if (!Number.isInteger(i) || i < 0 || i >= this.n) throw new RangeError('cell out of range');
    if (this.status === 'won' || this.status === 'lost') return { opened: [], boom: false };
    if (this.state[i] !== HIDDEN) return { opened: [], boom: false };
    if (!this.placed) {
      const layout = this.layoutProvider
        ? this.layoutProvider(i)
        : placeMines(this.w, this.h, this.mines, i, makeRng(`${this.seed}|${this.w}x${this.h}x${this.mines}`));
      this.#applyLayout(layout);
    }
    this.status = 'playing';
    if (this.mine[i]) {
      this.state[i] = REVEALED; this.exploded = i; this.status = 'lost';
      return { opened: [i], boom: true };
    }
    const opened = this.#flood(i);
    this.#checkWin();
    return { opened, boom: false };
  }

  #flood(start) {
    const opened = [];
    const stack = [start];
    while (stack.length) {
      const c = stack.pop();
      if (this.state[c] === REVEALED) continue;
      if (this.state[c] === FLAGGED && c !== start) continue; // flood never opens a flagged cell
      this.state[c] = REVEALED; this.revealedCount++; opened.push(c);
      if (this.adj[c] === 0) for (const j of this.nb[c]) if (this.state[j] !== REVEALED) stack.push(j);
    }
    return opened;
  }

  #checkWin() {
    if (this.revealedCount === this.n - this.mines && this.status === 'playing') {
      this.status = 'won';
      for (let i = 0; i < this.n; i++) if (this.mine[i] && this.state[i] !== FLAGGED) { this.state[i] = FLAGGED; this.flagCount++; }
    }
  }

  toggleFlag(i) {
    if (!Number.isInteger(i) || i < 0 || i >= this.n) throw new RangeError('cell out of range');
    if (this.status === 'won' || this.status === 'lost') return false;
    if (this.state[i] === REVEALED) return false;
    if (this.state[i] === FLAGGED) { this.state[i] = HIDDEN; this.flagCount--; }
    else { this.state[i] = FLAGGED; this.flagCount++; }
    return true;
  }

  /** Chord: if a revealed number has exactly that many flags around it, reveal the other neighbours. */
  chord(i) {
    if (this.state[i] !== REVEALED || this.adj[i] === 0) return { opened: [], boom: false };
    let flags = 0;
    for (const j of this.nb[i]) if (this.state[j] === FLAGGED) flags++;
    if (flags !== this.adj[i]) return { opened: [], boom: false };
    const opened = []; let boom = false;
    for (const j of this.nb[i]) {
      if (this.state[j] !== HIDDEN) continue;
      const r = this.reveal(j);
      opened.push(...r.opened); boom = boom || r.boom;
      if (this.status === 'lost') break;
    }
    return { opened, boom };
  }

  /** Solver-facing view: -1 for hidden/flagged (flags are never trusted), else the revealed number. */
  view() {
    const v = new Int8Array(this.n);
    for (let i = 0; i < this.n; i++) v[i] = this.state[i] === REVEALED && !this.mine[i] ? this.adj[i] : -1;
    return v;
  }

  /** ASCII rendering for the CLI. */
  render(revealAll = false) {
    const rows = [];
    for (let y = 0; y < this.h; y++) {
      let r = '';
      for (let x = 0; x < this.w; x++) {
        const i = this.idx(x, y), s = this.state[i];
        let ch;
        if (revealAll || this.status === 'lost' && this.mine[i] && s !== FLAGGED) ch = this.mine[i] ? '*' : (this.adj[i] || '.');
        else if (s === FLAGGED) ch = 'F';
        else if (s === HIDDEN) ch = '#';
        else ch = this.mine[i] ? 'X' : (this.adj[i] || '.');
        r += ch + ' ';
      }
      rows.push(r.trimEnd());
    }
    return rows.join('\n');
  }
}
