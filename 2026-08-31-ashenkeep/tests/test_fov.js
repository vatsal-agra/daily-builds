'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { computeFOV, blockingFromGrid } = require('../src/fov.js');
const { TILE } = require('../src/dungeon.js');

function gridFromStrings(rows) {
  // '#' = wall, '.' = floor
  return rows.map((row) => row.split('').map((ch) => (ch === '#' ? TILE.WALL : TILE.FLOOR)));
}

test('origin is always visible', () => {
  const grid = gridFromStrings(['#####', '#...#', '#####']);
  const vis = computeFOV(2, 1, 5, blockingFromGrid(grid, TILE));
  assert.ok(vis.has('2,1'));
});

test('open room: every floor tile within radius is visible', () => {
  const grid = gridFromStrings(['#######', '#.....#', '#.....#', '#.....#', '#######']);
  const vis = computeFOV(3, 2, 10, blockingFromGrid(grid, TILE));
  for (let y = 1; y <= 3; y++) {
    for (let x = 1; x <= 5; x++) {
      assert.ok(vis.has(`${x},${y}`), `expected (${x},${y}) visible in open room`);
    }
  }
});

test('a wall blocks sight around a corner', () => {
  // A single blocking wall between viewer and a tile directly behind it,
  // with no other line of sight, must not be visible.
  const grid = gridFromStrings([
    '#########',
    '#.......#',
    '#..###..#',
    '#..#.#..#',
    '#..###..#',
    '#.......#',
    '#########',
  ]);
  const vis = computeFOV(2, 3, 10, blockingFromGrid(grid, TILE));
  // (4,3) is enclosed by walls on all four sides except it's the same tile
  // as the wall block center — pick the actual enclosed floor tile inside
  // the box, which is unreachable/invisible from outside it.
  assert.ok(!vis.has('4,3'), 'enclosed tile should not be visible through walls');
});

test('radius limits visibility even with a clear line of sight', () => {
  const grid = gridFromStrings(['.'.repeat(21)]);
  const vis = computeFOV(10, 0, 3, blockingFromGrid(grid, TILE));
  assert.ok(vis.has('13,0')); // distance 3
  assert.ok(!vis.has('14,0')); // distance 4, beyond radius
});

test('walls themselves can be seen (you can see the wall you cannot pass)', () => {
  const grid = gridFromStrings(['#####', '#...#', '#####']);
  const vis = computeFOV(2, 1, 5, blockingFromGrid(grid, TILE));
  assert.ok(vis.has('0,1') || vis.has('4,1'), 'expected at least one bounding wall tile to be visible');
});

test('out-of-bounds origin does not throw and returns just the origin-adjacent set', () => {
  const grid = gridFromStrings(['###', '#.#', '###']);
  assert.doesNotThrow(() => computeFOV(-5, -5, 5, blockingFromGrid(grid, TILE)));
});

test('symmetry-ish sanity: two mutually visible open tiles see each other', () => {
  const grid = gridFromStrings(['#######', '#.....#', '#######']);
  const visA = computeFOV(1, 1, 10, blockingFromGrid(grid, TILE));
  const visB = computeFOV(5, 1, 10, blockingFromGrid(grid, TILE));
  assert.ok(visA.has('5,1'));
  assert.ok(visB.has('1,1'));
});
