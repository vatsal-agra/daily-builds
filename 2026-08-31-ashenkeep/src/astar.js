// astar.js — grid-based A* pathfinding used by monster AI to chase the
// player. Manhattan-distance heuristic (admissible for 4-directional
// movement, which is what this game uses — roguelike corridors are one
// tile wide, so diagonal cutting across a corner would visually clip
// through a wall corner).

'use strict';

(function () {

class MinHeap {
  constructor() {
    this.items = []; // [priority, value]
  }
  get size() {
    return this.items.length;
  }
  push(priority, value) {
    this.items.push([priority, value]);
    let i = this.items.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (this.items[parent][0] <= this.items[i][0]) break;
      [this.items[parent], this.items[i]] = [this.items[i], this.items[parent]];
      i = parent;
    }
  }
  pop() {
    const top = this.items[0];
    const last = this.items.pop();
    if (this.items.length > 0) {
      this.items[0] = last;
      let i = 0;
      const n = this.items.length;
      for (;;) {
        const l = 2 * i + 1;
        const r = 2 * i + 2;
        let smallest = i;
        if (l < n && this.items[l][0] < this.items[smallest][0]) smallest = l;
        if (r < n && this.items[r][0] < this.items[smallest][0]) smallest = r;
        if (smallest === i) break;
        [this.items[smallest], this.items[i]] = [this.items[i], this.items[smallest]];
        i = smallest;
      }
    }
    return top[1];
  }
}

const DIRS4 = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
];

function manhattan(ax, ay, bx, by) {
  return Math.abs(ax - bx) + Math.abs(ay - by);
}

/**
 * Find a shortest path from start to goal over a walkable grid.
 * @param {(x:number,y:number)=>boolean} isWalkable
 * @param {{x:number,y:number}} start
 * @param {{x:number,y:number}} goal
 * @param {{extraBlocked?: Set<string>}} [options] extraBlocked lets callers
 *   temporarily treat occupied tiles (other monsters) as blocked without
 *   mutating the dungeon grid.
 * @returns {Array<{x:number,y:number}>|null} path *excluding* the start
 *   tile and *including* the goal tile, or null if unreachable. An empty
 *   array means start === goal.
 */
function findPath(isWalkable, start, goal, options = {}) {
  const extraBlocked = options.extraBlocked || new Set();
  const key = (x, y) => `${x},${y}`;

  if (start.x === goal.x && start.y === goal.y) return [];
  if (!isWalkable(goal.x, goal.y)) return null;

  const gScore = new Map([[key(start.x, start.y), 0]]);
  const cameFrom = new Map();
  const open = new MinHeap();
  open.push(manhattan(start.x, start.y, goal.x, goal.y), start);
  const closed = new Set();

  const maxIterations = 20000; // safety bound against any pathological input
  let iterations = 0;

  while (open.size > 0) {
    if (++iterations > maxIterations) return null; // give up rather than hang
    const current = open.pop();
    const ck = key(current.x, current.y);
    if (closed.has(ck)) continue;
    closed.add(ck);

    if (current.x === goal.x && current.y === goal.y) {
      // Reconstruct path.
      const path = [];
      let cur = ck;
      while (cur !== key(start.x, start.y)) {
        const [x, y] = cur.split(',').map(Number);
        path.push({ x, y });
        cur = cameFrom.get(cur);
      }
      path.reverse();
      return path;
    }

    for (const [dx, dy] of DIRS4) {
      const nx = current.x + dx;
      const ny = current.y + dy;
      const nk = key(nx, ny);
      if (closed.has(nk)) continue;
      if (extraBlocked.has(nk) && nk !== key(goal.x, goal.y)) continue;
      if (!isWalkable(nx, ny)) continue;

      const tentativeG = gScore.get(ck) + 1;
      if (!gScore.has(nk) || tentativeG < gScore.get(nk)) {
        gScore.set(nk, tentativeG);
        cameFrom.set(nk, ck);
        const f = tentativeG + manhattan(nx, ny, goal.x, goal.y);
        open.push(f, { x: nx, y: ny });
      }
    }
  }
  return null; // no path exists
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { findPath, MinHeap, manhattan };
}
if (typeof window !== 'undefined') {
  window.Ashenkeep = window.Ashenkeep || {};
  Object.assign(window.Ashenkeep, { findPath, MinHeap, manhattan });
}

})();
