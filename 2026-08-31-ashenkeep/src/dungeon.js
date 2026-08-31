// dungeon.js — procedural dungeon generation via binary space partitioning.
//
// The grid is recursively split into two until each region is small enough
// to become a leaf; every leaf carves one room inside itself; then, walking
// back UP the same split tree, every internal node connects one room from
// its left subtree to one room from its right subtree with an L-shaped
// corridor. Because every split node performs exactly one such connection,
// the resulting floor is provably a single connected component — there is
// no separate "make sure it's connected" pass bolted on afterward.

'use strict';

(function () {

const TILE = Object.freeze({
  WALL: 0,
  FLOOR: 1,
  STAIRS_DOWN: 2,
});

class Room {
  constructor(x, y, w, h) {
    this.x = x;
    this.y = y;
    this.w = w;
    this.h = h;
  }
  get x2() {
    return this.x + this.w - 1;
  }
  get y2() {
    return this.y + this.h - 1;
  }
  get centerX() {
    return Math.floor(this.x + this.w / 2);
  }
  get centerY() {
    return Math.floor(this.y + this.h / 2);
  }
  contains(x, y) {
    return x >= this.x && x <= this.x2 && y >= this.y && y <= this.y2;
  }
}

class BSPNode {
  constructor(x, y, w, h) {
    this.x = x;
    this.y = y;
    this.w = w;
    this.h = h;
    this.left = null;
    this.right = null;
    this.room = null; // set only on leaves
    this.rooms = []; // all rooms reachable under this node, populated bottom-up
  }
  isLeaf() {
    return this.left === null && this.right === null;
  }
}

function trySplit(node, rng, minLeafSize) {
  let splitHorizontal = rng.chance(0.5);
  if (node.w > node.h && node.w / node.h >= 1.25) splitHorizontal = false;
  else if (node.h > node.w && node.h / node.w >= 1.25) splitHorizontal = true;

  const dim = splitHorizontal ? node.h : node.w;
  const max = dim - minLeafSize;
  if (max <= minLeafSize) return false; // too small to split into two valid leaves

  const splitPoint = rng.int(minLeafSize, max);
  if (splitHorizontal) {
    node.left = new BSPNode(node.x, node.y, node.w, splitPoint);
    node.right = new BSPNode(node.x, node.y + splitPoint, node.w, node.h - splitPoint);
  } else {
    node.left = new BSPNode(node.x, node.y, splitPoint, node.h);
    node.right = new BSPNode(node.x + splitPoint, node.y, node.w - splitPoint, node.h);
  }
  return true;
}

function buildTree(node, rng, minLeafSize, maxDepth, depth) {
  if (depth < maxDepth && trySplit(node, rng, minLeafSize)) {
    buildTree(node.left, rng, minLeafSize, maxDepth, depth + 1);
    buildTree(node.right, rng, minLeafSize, maxDepth, depth + 1);
  }
}

function carveRoomInLeaf(node, rng) {
  const minRoomSize = 4;
  const maxW = Math.max(minRoomSize, node.w - 2);
  const maxH = Math.max(minRoomSize, node.h - 2);
  const w = rng.int(minRoomSize, maxW);
  const h = rng.int(minRoomSize, maxH);
  const x = node.x + rng.int(1, Math.max(1, node.w - w - 1));
  const y = node.y + rng.int(1, Math.max(1, node.h - h - 1));
  node.room = new Room(x, y, w, h);
  node.rooms = [node.room];
}

function carveRect(grid, room) {
  for (let y = room.y; y <= room.y2; y++) {
    for (let x = room.x; x <= room.x2; x++) {
      grid[y][x] = TILE.FLOOR;
    }
  }
}

function carveCorridor(grid, x1, y1, x2, y2, rng) {
  const horizontalFirst = rng.chance(0.5);
  if (horizontalFirst) {
    carveHLine(grid, x1, x2, y1);
    carveVLine(grid, y1, y2, x2);
  } else {
    carveVLine(grid, y1, y2, x1);
    carveHLine(grid, x1, x2, y2);
  }
}

function carveHLine(grid, x1, x2, y) {
  const [lo, hi] = x1 <= x2 ? [x1, x2] : [x2, x1];
  for (let x = lo; x <= hi; x++) grid[y][x] = TILE.FLOOR;
}

function carveVLine(grid, y1, y2, x) {
  const [lo, hi] = y1 <= y2 ? [y1, y2] : [y2, y1];
  for (let y = lo; y <= hi; y++) grid[y][x] = TILE.FLOOR;
}

function connect(node, grid, rng) {
  if (node.isLeaf()) {
    carveRoomInLeaf(node, rng);
    return node.rooms;
  }
  const leftRooms = connect(node.left, grid, rng);
  const rightRooms = connect(node.right, grid, rng);
  const a = rng.pick(leftRooms);
  const b = rng.pick(rightRooms);
  carveCorridor(grid, a.centerX, a.centerY, b.centerX, b.centerY, rng);
  node.rooms = leftRooms.concat(rightRooms);
  return node.rooms;
}

function makeGrid(width, height) {
  const grid = new Array(height);
  for (let y = 0; y < height; y++) grid[y] = new Array(width).fill(TILE.WALL);
  return grid;
}

function inBounds(width, height, x, y) {
  return x >= 0 && y >= 0 && x < width && y < height;
}

function isWalkable(grid, x, y) {
  const width = grid[0].length;
  const height = grid.length;
  if (!inBounds(width, height, x, y)) return false;
  return grid[y][x] !== TILE.WALL;
}

// Breadth-first distance map from (sx, sy) over walkable tiles (4-directional).
function bfsDistances(grid, sx, sy) {
  const width = grid[0].length;
  const height = grid.length;
  const dist = makeGrid(width, height).map((row) => row.map(() => -1));
  if (!isWalkable(grid, sx, sy)) return dist;
  dist[sy][sx] = 0;
  const queue = [[sx, sy]];
  let head = 0;
  const dirs = [
    [1, 0],
    [-1, 0],
    [0, 1],
    [0, -1],
  ];
  while (head < queue.length) {
    const [cx, cy] = queue[head++];
    for (const [dx, dy] of dirs) {
      const nx = cx + dx;
      const ny = cy + dy;
      if (isWalkable(grid, nx, ny) && dist[ny][nx] === -1) {
        dist[ny][nx] = dist[cy][cx] + 1;
        queue.push([nx, ny]);
      }
    }
  }
  return dist;
}

/**
 * Generate one fully-connected dungeon floor.
 * @param {number} width
 * @param {number} height
 * @param {RNG} rng
 * @param {{minLeafSize?: number, maxDepth?: number}} [options]
 * @returns {{grid: number[][], width, height, rooms: Room[], start: {x,y}, stairs: {x,y}}}
 */
function generateDungeon(width, height, rng, options = {}) {
  if (width < 20 || height < 15) {
    throw new RangeError(`generateDungeon: floor too small (${width}x${height}), minimum is 20x15`);
  }
  const minLeafSize = options.minLeafSize || 8;
  const maxDepth = options.maxDepth || 6;

  const grid = makeGrid(width, height);
  const root = new BSPNode(0, 0, width, height);
  buildTree(root, rng, minLeafSize, maxDepth, 0);
  const rooms = connect(root, grid, rng);

  if (rooms.length < 2) {
    throw new Error('generateDungeon: BSP produced fewer than 2 rooms; increase floor size or lower minLeafSize');
  }

  const start = { x: rooms[0].centerX, y: rooms[0].centerY };
  const dist = bfsDistances(grid, start.x, start.y);

  // Stairs go in the room whose center is farthest (by real walking
  // distance, not straight-line) from the start — never the start room
  // itself, and never an unreachable tile (which BSP-by-construction never
  // produces, but we guard rather than trust).
  let bestRoom = null;
  let bestDist = -1;
  for (const room of rooms) {
    if (room === rooms[0]) continue;
    const d = dist[room.centerY][room.centerX];
    if (d > bestDist) {
      bestDist = d;
      bestRoom = room;
    }
  }
  if (!bestRoom || bestDist < 0) {
    throw new Error('generateDungeon: no room reachable for stairs placement — connectivity invariant violated');
  }
  const stairs = { x: bestRoom.centerX, y: bestRoom.centerY };
  grid[stairs.y][stairs.x] = TILE.STAIRS_DOWN;

  return { grid, width, height, rooms, start, stairs };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { TILE, Room, generateDungeon, isWalkable, bfsDistances, inBounds };
}
if (typeof window !== 'undefined') {
  window.Ashenkeep = window.Ashenkeep || {};
  Object.assign(window.Ashenkeep, { TILE, Room, generateDungeon, isWalkable, bfsDistances, inBounds });
}

})();
