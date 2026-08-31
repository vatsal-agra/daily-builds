'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { RNG } = require('../src/rng.js');
const { TILE, generateDungeon, bfsDistances, isWalkable } = require('../src/dungeon.js');

function genOne(seed, w = 60, h = 32) {
  return generateDungeon(w, h, new RNG(seed));
}

test('same seed produces byte-identical dungeon', () => {
  const a = genOne(1);
  const b = genOne(1);
  assert.deepEqual(a.grid, b.grid);
  assert.deepEqual(a.start, b.start);
  assert.deepEqual(a.stairs, b.stairs);
});

test('different seeds produce different dungeons', () => {
  const a = genOne(1);
  const b = genOne(2);
  assert.notDeepEqual(a.grid, b.grid);
});

test('every room is reachable from the start tile (fully connected floor)', () => {
  for (const seed of [1, 2, 3, 4, 5, 100, 999]) {
    const d = genOne(seed);
    const dist = bfsDistances(d.grid, d.start.x, d.start.y);
    for (const room of d.rooms) {
      const reach = dist[room.centerY][room.centerX];
      assert.ok(reach >= 0, `seed ${seed}: room at (${room.centerX},${room.centerY}) unreachable`);
    }
  }
});

test('stairs tile is reachable and is not the start tile', () => {
  for (const seed of [1, 2, 3, 42, 777]) {
    const d = genOne(seed);
    const dist = bfsDistances(d.grid, d.start.x, d.start.y);
    assert.ok(dist[d.stairs.y][d.stairs.x] > 0, `seed ${seed}: stairs unreachable or equal to start`);
    assert.equal(d.grid[d.stairs.y][d.stairs.x], TILE.STAIRS_DOWN);
    assert.notEqual(`${d.start.x},${d.start.y}`, `${d.stairs.x},${d.stairs.y}`);
  }
});

test('start tile is walkable floor', () => {
  const d = genOne(1);
  assert.ok(isWalkable(d.grid, d.start.x, d.start.y));
});

test('grid dimensions match requested width/height', () => {
  const d = genOne(1, 50, 24);
  assert.equal(d.grid.length, 24);
  assert.equal(d.grid[0].length, 50);
});

test('every generated room lies fully within grid bounds', () => {
  const d = genOne(3, 60, 32);
  for (const room of d.rooms) {
    assert.ok(room.x >= 0 && room.y >= 0);
    assert.ok(room.x2 < 60 && room.y2 < 32);
  }
});

test('at least two rooms are generated on a normal-sized floor', () => {
  const d = genOne(1);
  assert.ok(d.rooms.length >= 2);
});

test('too-small dimensions raise a clear error instead of a broken dungeon', () => {
  assert.throws(() => generateDungeon(10, 10, new RNG(1)), RangeError);
});

test('every wall-adjacent floor tile borders at least one wall or is boundary-safe (no index-out-of-range)', () => {
  // Regression guard: rooms/corridors carved right at the grid edge would
  // make FOV/A* read out of bounds. Confirm a 1-tile margin is preserved.
  const d = genOne(9, 60, 32);
  for (let y = 0; y < d.height; y++) {
    for (let x = 0; x < d.width; x++) {
      if (d.grid[y][x] !== TILE.WALL) {
        assert.ok(x > 0 && y > 0 && x < d.width - 1 && y < d.height - 1, `floor tile touches grid edge at (${x},${y})`);
      }
    }
  }
});
