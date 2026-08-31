// fov.js — recursive shadowcasting field-of-view (Björn Bergström's
// algorithm, the same technique used by Brogue/NetHack-style roguelikes).
//
// Casts light out from an origin tile through eight octants; a wall tile
// truncates the slope range of everything behind it, which is what makes
// sight correctly stop at corners instead of just being a plain circle
// with walls ignored. Returns the exact set of currently-visible tiles —
// callers are responsible for merging that into a persistent "explored"
// set for fog-of-war memory.

'use strict';

(function () {

// Octant transform multipliers: [xx, xy, yx, yy] per octant index.
const OCTANTS = [
  [1, 0, 0, 1],
  [0, 1, 1, 0],
  [0, -1, 1, 0],
  [-1, 0, 0, 1],
  [-1, 0, 0, -1],
  [0, -1, -1, 0],
  [0, 1, -1, 0],
  [1, 0, 0, -1],
];

function castLight(originX, originY, row, start, end, radius, xx, xy, yx, yy, isBlocking, markVisible) {
  if (start < end) return;
  let newStart = 0;
  let blocked = false;

  for (let distance = row; distance <= radius && !blocked; distance++) {
    const deltaY = -distance;
    for (let deltaX = -distance; deltaX <= 0; deltaX++) {
      const currentX = originX + deltaX * xx + deltaY * xy;
      const currentY = originY + deltaX * yx + deltaY * yy;
      const leftSlope = (deltaX - 0.5) / (deltaY + 0.5);
      const rightSlope = (deltaX + 0.5) / (deltaY - 0.5);

      if (start < rightSlope) {
        continue;
      } else if (end > leftSlope) {
        break;
      }

      const inRadius = deltaX * deltaX + deltaY * deltaY <= radius * radius;
      if (inRadius) markVisible(currentX, currentY);

      if (blocked) {
        if (isBlocking(currentX, currentY)) {
          newStart = rightSlope;
          continue;
        } else {
          blocked = false;
          start = newStart;
        }
      } else if (isBlocking(currentX, currentY) && distance < radius) {
        blocked = true;
        castLight(originX, originY, distance + 1, start, leftSlope, radius, xx, xy, yx, yy, isBlocking, markVisible);
        newStart = rightSlope;
      }
    }
  }
}

/**
 * Compute the set of tiles visible from (originX, originY) within radius,
 * given a blocking predicate `isBlocking(x, y) -> boolean`.
 * @returns {Set<string>} set of "x,y" keys — always includes the origin.
 */
function computeFOV(originX, originY, radius, isBlocking) {
  const visible = new Set();
  const markVisible = (x, y) => visible.add(`${x},${y}`);
  markVisible(originX, originY);
  for (const [xx, xy, yx, yy] of OCTANTS) {
    castLight(originX, originY, 1, 1.0, 0.0, radius, xx, xy, yx, yy, isBlocking, markVisible);
  }
  return visible;
}

// Convenience: build an isBlocking predicate from a dungeon grid, treating
// out-of-bounds tiles as blocking so shadowcasting never indexes off-grid.
function blockingFromGrid(grid, TILE) {
  const height = grid.length;
  const width = grid[0].length;
  return (x, y) => {
    if (x < 0 || y < 0 || x >= width || y >= height) return true;
    return grid[y][x] === TILE.WALL;
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { computeFOV, blockingFromGrid };
}
if (typeof window !== 'undefined') {
  window.Ashenkeep = window.Ashenkeep || {};
  Object.assign(window.Ashenkeep, { computeFOV, blockingFromGrid });
}

})();
