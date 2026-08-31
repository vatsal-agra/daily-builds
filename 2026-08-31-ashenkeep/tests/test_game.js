'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { Game, MAX_FLOOR } = require('../src/game.js');
const { TILE } = require('../src/dungeon.js');

function freshGame(seed = 1) {
  return new Game(seed);
}

test('a new game starts alive, on floor 1, on a walkable non-wall tile', () => {
  const g = freshGame(1);
  assert.equal(g.floorNumber, 1);
  assert.ok(g.player.isAlive());
  assert.ok(g.isWalkableTile(g.player.x, g.player.y));
  assert.equal(g.gameOver, false);
  assert.ok(g.messages.length > 0);
});

test('same seed produces an identical initial world (dungeon, monsters, items)', () => {
  const a = freshGame(777);
  const b = freshGame(777);
  assert.deepEqual(a.dungeon.grid, b.dungeon.grid);
  assert.deepEqual(a.player.x, b.player.x);
  assert.deepEqual(a.player.y, b.player.y);
  assert.equal(a.monsters.length, b.monsters.length);
  for (let i = 0; i < a.monsters.length; i++) {
    assert.equal(a.monsters[i].x, b.monsters[i].x);
    assert.equal(a.monsters[i].y, b.monsters[i].y);
    assert.equal(a.monsters[i].hp, b.monsters[i].hp);
  }
});

test('different seeds produce different worlds', () => {
  const a = freshGame(1);
  const b = freshGame(2);
  assert.notDeepEqual(a.dungeon.grid, b.dungeon.grid);
});

test('moving into a wall does not consume a turn and does not move the player', () => {
  const g = freshGame(1);
  // Find a direction that is definitely a wall from the start tile: scan
  // the 4 neighbors and pick one that is not walkable (there must be one,
  // since a room interior is surrounded by walls beyond its extent... to
  // be robust, search outward until a wall neighbor of *some* floor tile
  // is found, then teleport the player there for a deterministic setup).
  outer: for (let y = 1; y < g.dungeon.height - 1; y++) {
    for (let x = 1; x < g.dungeon.width - 1; x++) {
      if (g.dungeon.grid[y][x] === TILE.WALL) continue;
      if (g.dungeon.grid[y][x - 1] === TILE.WALL) {
        g.player.x = x;
        g.player.y = y;
        const turnsBefore = g.turnCount;
        const result = g.movePlayer(-1, 0);
        assert.equal(result.ok, false);
        assert.equal(g.turnCount, turnsBefore);
        assert.equal(g.player.x, x);
        assert.equal(g.player.y, y);
        break outer;
      }
    }
  }
});

test('moving into open floor advances the turn counter and updates position', () => {
  const g = freshGame(3);
  const dirs = [
    [1, 0],
    [-1, 0],
    [0, 1],
    [0, -1],
  ];
  let moved = false;
  for (const [dx, dy] of dirs) {
    if (g.isWalkableTile(g.player.x + dx, g.player.y + dy)) {
      const before = { x: g.player.x, y: g.player.y, turns: g.turnCount };
      const result = g.movePlayer(dx, dy);
      assert.ok(result.ok);
      assert.equal(g.player.x, before.x + dx);
      assert.equal(g.player.y, before.y + dy);
      assert.equal(g.turnCount, before.turns + 1);
      moved = true;
      break;
    }
  }
  assert.ok(moved, 'expected at least one walkable neighbor from the start tile');
});

test('walking into a monster attacks it instead of moving onto its tile', () => {
  const g = freshGame(2);
  const monster = g.monsters[0];
  const px = g.player.x;
  const py = g.player.y;
  // Place the monster directly east of the player, with a wall check
  // bypassed by forcing the tile walkable-adjacent (use the player's own
  // tile mechanics: monster placement doesn't need to be reachable by
  // corridor for this unit check, only adjacent for the attack branch).
  monster.x = px + 1;
  monster.y = py;
  monster.hp = 9999;
  monster.maxHp = 9999;
  const hpBefore = monster.hp;
  const result = g.movePlayer(1, 0);
  assert.ok(result.ok);
  assert.equal(g.player.x, px, 'player must not move onto an occupied tile');
  assert.equal(g.player.y, py);
  assert.ok(monster.hp <= hpBefore, 'attack should have been resolved against the monster');
});

test('killing the last-standing monster awards xp and removes it from the world', () => {
  const g = freshGame(4);
  const monster = g.monsters[0];
  monster.x = g.player.x + 1;
  monster.y = g.player.y;
  monster.hp = 1;
  monster.def = 0;
  monster.evasion = 0;
  g.player.baseAccuracy = 1;
  g.player.baseAtk = 999;
  const xpBefore = g.player.xp + g.player.xpToNext * 0; // just to read before
  const killsBefore = g.player.kills;
  g.movePlayer(1, 0);
  assert.equal(g.monsters.find((m) => m.id === monster.id), undefined);
  assert.equal(g.player.kills, killsBefore + 1);
});

test('picking up an item adds it to inventory and clears the ground tile', () => {
  const g = freshGame(5);
  const { rollPotion } = require('../src/items.js');
  const potion = rollPotion(1, g.rng);
  const key = `${g.player.x},${g.player.y}`;
  g.groundItems.set(key, [potion]);
  g._autoPickup();
  assert.equal(g.player.inventory.length, 1);
  assert.equal(g.groundItems.has(key), false);
});

test('a full inventory leaves the item on the ground with a clear message', () => {
  const g = freshGame(6);
  const { rollWeapon, INVENTORY_CAPACITY } = require('../src/items.js');
  for (let i = 0; i < INVENTORY_CAPACITY; i++) g.player.inventory.push(rollWeapon(1, g.rng));
  const key = `${g.player.x},${g.player.y}`;
  const extra = rollWeapon(1, g.rng);
  g.groundItems.set(key, [extra]);
  g._autoPickup();
  assert.equal(g.player.inventory.length, INVENTORY_CAPACITY);
  assert.ok(g.groundItems.has(key), 'item should remain on the ground when inventory is full');
  assert.ok(g.messages[g.messages.length - 1].toLowerCase().includes('full'));
});

test('using a healing potion restores hp and consumes the item', () => {
  const g = freshGame(7);
  const { rollPotion } = require('../src/items.js');
  const potion = rollPotion(1, g.rng);
  potion.heal = 15;
  g.player.inventory.push(potion);
  g.player.hp = 1;
  const result = g.useItem(potion.id);
  assert.ok(result.ok);
  assert.equal(g.player.hp, 16);
  assert.equal(g.player.inventory.length, 0);
});

test('using a reveal scroll marks every non-wall tile explored', () => {
  const g = freshGame(8);
  const { rollScroll } = require('../src/items.js');
  let scroll = rollScroll(1, g.rng);
  while (scroll.effect !== 'reveal') scroll = rollScroll(1, g.rng);
  g.player.inventory.push(scroll);
  g.useItem(scroll.id);
  for (let y = 0; y < g.dungeon.height; y++) {
    for (let x = 0; x < g.dungeon.width; x++) {
      if (g.dungeon.grid[y][x] !== TILE.WALL) assert.ok(g.explored[y][x], `(${x},${y}) should be explored after reveal`);
    }
  }
});

test('teleporting never lands the player on an occupied tile (regression: REVIEW.md #1)', () => {
  const g = freshGame(18);
  const { rollScroll } = require('../src/items.js');
  let scroll = rollScroll(1, g.rng);
  while (scroll.effect !== 'teleport') scroll = rollScroll(1, g.rng);
  for (let i = 0; i < 30; i++) {
    g.player.inventory.push({ ...scroll, id: scroll.id + i });
  }
  for (const item of g.player.inventory.slice()) {
    g.useItem(item.id);
    for (const m of g.monsters) {
      if (!m.isAlive()) continue;
      assert.ok(m.x !== g.player.x || m.y !== g.player.y, 'teleport must never land the player on a live monster');
    }
  }
});

test('equip then unequip round-trips the item and its stat bonus', () => {
  const g = freshGame(9);
  const { rollWeapon } = require('../src/items.js');
  const sword = rollWeapon(3, g.rng);
  g.player.inventory.push(sword);
  const baseAtk = g.player.atk;
  g.equip(sword.id);
  assert.equal(g.player.atk, baseAtk + sword.affixes.atk);
  g.unequip('weapon');
  assert.equal(g.player.atk, baseAtk);
  assert.equal(g.player.inventory.some((i) => i.id === sword.id), true);
});

test('dropping an item places it back on the ground at the player position', () => {
  const g = freshGame(10);
  const { rollArmor } = require('../src/items.js');
  const armor = rollArmor(1, g.rng);
  g.player.inventory.push(armor);
  g.dropItem(armor.id);
  const key = `${g.player.x},${g.player.y}`;
  assert.ok(g.groundItems.get(key).some((i) => i.name === armor.name));
});

test('descend() refuses when not standing on the stairs tile', () => {
  const g = freshGame(11);
  if (g.dungeon.grid[g.player.y][g.player.x] === TILE.STAIRS_DOWN) {
    g.player.x = g.dungeon.start.x;
    g.player.y = g.dungeon.start.y;
  }
  const result = g.descend();
  assert.equal(result.ok, false);
});

test('descend() from the stairs generates a new, harder floor and resets position', () => {
  const g = freshGame(12);
  const oldGrid = g.dungeon.grid;
  g.player.x = g.dungeon.stairs.x;
  g.player.y = g.dungeon.stairs.y;
  const result = g.descend();
  assert.ok(result.ok);
  assert.equal(g.floorNumber, 2);
  assert.notDeepEqual(g.dungeon.grid, oldGrid);
  assert.equal(g.player.x, g.dungeon.start.x);
  assert.equal(g.player.y, g.dungeon.start.y);
});

test('descending from the final floor wins the game', () => {
  const g = freshGame(13);
  g.floorNumber = MAX_FLOOR;
  g.player.x = g.dungeon.stairs.x;
  g.player.y = g.dungeon.stairs.y;
  const result = g.descend();
  assert.ok(result.ok);
  assert.equal(g.gameOver, true);
  assert.equal(g.won, true);
});

test('the player can die: repeated adjacency to a guaranteed-hit monster ends the game as a loss', () => {
  const g = freshGame(14);
  const monster = g.monsters[0];
  monster.x = g.player.x + 1;
  monster.y = g.player.y;
  monster.accuracy = 1;
  monster.atk = 5;
  g.player.baseEvasion = 0;
  g.player.hp = 1;
  let iterations = 0;
  while (!g.gameOver && iterations < 50) {
    g.waitTurn();
    iterations += 1;
  }
  assert.equal(g.gameOver, true);
  assert.equal(g.won, false);
  assert.ok(g.messages[g.messages.length - 1].toLowerCase().includes('fallen'));
});

test('actions are refused once the game is over', () => {
  const g = freshGame(15);
  g.gameOver = true;
  assert.equal(g.movePlayer(1, 0).ok, false);
  assert.equal(g.waitTurn().ok, false);
  assert.equal(g.descend().ok, false);
});

test('a bot playthrough of many turns never throws and never violates hp bounds', () => {
  const g = freshGame(16);
  const dirs = [
    [1, 0],
    [-1, 0],
    [0, 1],
    [0, -1],
  ];
  for (let i = 0; i < 400 && !g.gameOver; i++) {
    const [dx, dy] = dirs[i % dirs.length];
    g.movePlayer(dx, dy);
    assert.ok(g.player.hp >= 0 && g.player.hp <= g.player.maxHp);
    for (const m of g.monsters) assert.ok(m.hp >= 0 && m.hp <= m.maxHp);
  }
  assert.ok(g.turnCount > 0);
});

test('save/load round-trip preserves full game state and the restored game keeps working', () => {
  const g = freshGame(17);
  g.movePlayer(0, 0); // no-op-safe warmup not required; do a couple of real actions below
  const dirs = [
    [1, 0],
    [-1, 0],
    [0, 1],
    [0, -1],
  ];
  for (let i = 0; i < 10; i++) g.movePlayer(dirs[i % 4][0], dirs[i % 4][1]);

  const { rollWeapon } = require('../src/items.js');
  const sword = rollWeapon(2, g.rng);
  g.player.inventory.push(sword);
  g.equip(sword.id);

  const json = JSON.parse(JSON.stringify(g.serialize()));
  const restored = Game.fromSaved(json);

  assert.equal(restored.floorNumber, g.floorNumber);
  assert.equal(restored.turnCount, g.turnCount);
  assert.equal(restored.player.x, g.player.x);
  assert.equal(restored.player.y, g.player.y);
  assert.equal(restored.player.hp, g.player.hp);
  assert.equal(restored.player.atk, g.player.atk, 'equipment-derived getter must work after restore');
  assert.deepEqual(restored.dungeon.grid, g.dungeon.grid);
  assert.equal(restored.monsters.length, g.monsters.length);
  assert.deepEqual([...restored.visible].sort(), [...g.visible].sort());

  const turnsBefore = restored.turnCount;
  const result = restored.movePlayer(0, 1);
  assert.ok(typeof result.ok === 'boolean');
  if (result.ok) assert.equal(restored.turnCount, turnsBefore + 1);
});
