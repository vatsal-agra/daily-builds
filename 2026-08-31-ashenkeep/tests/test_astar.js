'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { findPath, manhattan } = require('../src/astar.js');

function walkableFromStrings(rows) {
  const grid = rows.map((r) => r.split(''));
  return (x, y) => {
    if (y < 0 || y >= grid.length || x < 0 || x >= grid[0].length) return false;
    return grid[y][x] !== '#';
  };
}

test('start === goal returns an empty path', () => {
  const isWalkable = walkableFromStrings(['...', '...', '...']);
  const path = findPath(isWalkable, { x: 1, y: 1 }, { x: 1, y: 1 });
  assert.deepEqual(path, []);
});

test('finds the shortest path length in an open grid (Manhattan distance)', () => {
  const isWalkable = walkableFromStrings(['.....', '.....', '.....', '.....', '.....']);
  const start = { x: 0, y: 0 };
  const goal = { x: 4, y: 4 };
  const path = findPath(isWalkable, start, goal);
  assert.ok(path);
  assert.equal(path.length, manhattan(start.x, start.y, goal.x, goal.y));
  assert.deepEqual(path[path.length - 1], goal);
});

test('routes around a wall instead of failing', () => {
  const isWalkable = walkableFromStrings(['.....', '.###.', '.....', '.....', '.....']);
  const path = findPath(isWalkable, { x: 0, y: 0 }, { x: 4, y: 0 });
  assert.ok(path);
  for (const step of path) {
    assert.ok(isWalkable(step.x, step.y), `path stepped onto non-walkable (${step.x},${step.y})`);
  }
});

test('returns null when the goal is fully enclosed', () => {
  const isWalkable = walkableFromStrings(['#####', '#.#.#', '#####']);
  const path = findPath(isWalkable, { x: 1, y: 1 }, { x: 3, y: 1 });
  assert.equal(path, null);
});

test('returns null when the goal tile itself is a wall', () => {
  const isWalkable = walkableFromStrings(['...', '.#.', '...']);
  const path = findPath(isWalkable, { x: 0, y: 0 }, { x: 1, y: 1 });
  assert.equal(path, null);
});

test('extraBlocked tiles (other monsters) are avoided except at the goal itself', () => {
  const isWalkable = walkableFromStrings(['...', '...', '...']);
  const extraBlocked = new Set(['1,0', '1,1', '1,2']); // a solid column blocking x=1
  const path = findPath(isWalkable, { x: 0, y: 1 }, { x: 2, y: 1 }, { extraBlocked });
  assert.equal(path, null, 'a fully blocked column (via extraBlocked) should yield no path');
});

test('extraBlocked never blocks the goal tile itself (you can path onto an occupied target to attack)', () => {
  const isWalkable = walkableFromStrings(['...', '...', '...']);
  const extraBlocked = new Set(['2,1']);
  const path = findPath(isWalkable, { x: 0, y: 1 }, { x: 2, y: 1 }, { extraBlocked });
  assert.ok(path, 'goal tile must remain reachable even if occupied');
  assert.deepEqual(path[path.length - 1], { x: 2, y: 1 });
});

test('does not hang on a large open grid (bounded iteration, real result)', () => {
  const size = 80;
  const rows = Array.from({ length: size }, () => '.'.repeat(size));
  const isWalkable = walkableFromStrings(rows);
  const start = Date.now();
  const path = findPath(isWalkable, { x: 0, y: 0 }, { x: size - 1, y: size - 1 });
  assert.ok(Date.now() - start < 2000);
  assert.ok(path);
  assert.equal(path.length, manhattan(0, 0, size - 1, size - 1));
});
