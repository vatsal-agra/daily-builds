// game.js — the Game class: turn loop, floor generation/descent, combat
// dispatch, inventory actions, and save/load serialization. This is the
// one module that ties every other from-scratch system (dungeon, fov,
// astar, entities, combat, items) into an actual playable turn loop. It
// touches no DOM and no localStorage — render.js/main.js own the browser,
// this module owns the rules — which is exactly what lets it run
// unmodified under `node:test`.

'use strict';

(function () {

let Mod;
if (typeof module !== 'undefined' && module.exports) {
  Mod = {
    ...require('./rng'),
    ...require('./dungeon'),
    ...require('./fov'),
    ...require('./astar'),
    ...require('./entities'),
    ...require('./combat'),
    ...require('./items'),
  };
} else {
  Mod = window.Ashenkeep;
}
const { RNG, TILE, generateDungeon, isWalkable, computeFOV, blockingFromGrid, findPath, Player, Monster, spawnMonster, resolveAttack, generateLootDrop, addToInventory, removeFromInventory, equipItem, unequipSlot } = Mod;

const VISION_RADIUS = 8;
const MONSTER_SIGHT_RADIUS = 6;
const MAX_FLOOR = 10;
const MAX_MESSAGES = 80;

function floorDimensions(floorNumber) {
  return {
    width: Math.min(74, 40 + floorNumber * 3),
    height: Math.min(38, 22 + floorNumber * 2),
  };
}

function monsterCountForFloor(floorNumber) {
  return Math.min(18, 3 + floorNumber);
}

function itemCountForFloor(floorNumber) {
  return Math.min(12, 2 + Math.floor(floorNumber / 2) + 2);
}

class Game {
  constructor(seed, opts = {}) {
    if (opts.deferInit) return; // used by Game.fromSaved()
    this.seed = seed >>> 0;
    this.rng = new RNG(this.seed);
    this.player = new Player();
    this.floorNumber = 0;
    this.turnCount = 0;
    this.messages = [];
    this.gameOver = false;
    this.won = false;
    this.dungeon = null;
    this.monsters = [];
    this.groundItems = new Map(); // "x,y" -> Item[]
    this.explored = null; // boolean[][]
    this.visible = new Set();
    this._nextFloor();
    this._log('You descend into Ashenkeep.');
  }

  _log(message) {
    this.messages.push(message);
    if (this.messages.length > MAX_MESSAGES) this.messages.shift();
  }

  _key(x, y) {
    return `${x},${y}`;
  }

  isWalkableTile(x, y) {
    if (!this.dungeon) return false;
    return isWalkable(this.dungeon.grid, x, y);
  }

  monsterAt(x, y) {
    return this.monsters.find((m) => m.isAlive() && m.x === x && m.y === y) || null;
  }

  itemsAt(x, y) {
    return this.groundItems.get(this._key(x, y)) || [];
  }

  // ---- floor generation -------------------------------------------------

  _nextFloor() {
    this.floorNumber += 1;
    this.player.floor = this.floorNumber;
    const { width, height } = floorDimensions(this.floorNumber);
    const maxDepth = Math.min(7, 5 + Math.floor(this.floorNumber / 4));
    this.dungeon = generateDungeon(width, height, this.rng, { minLeafSize: 7, maxDepth });

    this.player.x = this.dungeon.start.x;
    this.player.y = this.dungeon.start.y;

    this.explored = new Array(height);
    for (let y = 0; y < height; y++) this.explored[y] = new Array(width).fill(false);

    this.monsters = [];
    this.groundItems = new Map();

    const occupied = new Set([this._key(this.player.x, this.player.y)]);
    const spawnRooms = this.dungeon.rooms.slice(1); // never spawn in the start room
    if (spawnRooms.length === 0) spawnRooms.push(this.dungeon.rooms[0]);

    const monsterCount = monsterCountForFloor(this.floorNumber);
    for (let i = 0; i < monsterCount; i++) {
      const spot = this._randomFloorTile(spawnRooms, occupied);
      if (!spot) break;
      occupied.add(this._key(spot.x, spot.y));
      this.monsters.push(spawnMonster(this.floorNumber, spot.x, spot.y, this.rng));
    }

    const itemCount = itemCountForFloor(this.floorNumber);
    for (let i = 0; i < itemCount; i++) {
      const spot = this._randomFloorTile(spawnRooms, occupied);
      if (!spot) break;
      // Items may share a tile with each other (not with monsters/player),
      // so don't add item tiles to `occupied`.
      const item = generateLootDrop(this.floorNumber, this.rng);
      const k = this._key(spot.x, spot.y);
      const stack = this.groundItems.get(k) || [];
      stack.push(item);
      this.groundItems.set(k, stack);
    }

    this._recomputeFOV();
  }

  _randomFloorTile(rooms, occupied) {
    for (let attempt = 0; attempt < 200; attempt++) {
      const room = this.rng.pick(rooms);
      const x = this.rng.int(room.x, room.x2);
      const y = this.rng.int(room.y, room.y2);
      if (this.dungeon.grid[y][x] === TILE.WALL) continue;
      if (this.dungeon.grid[y][x] === TILE.STAIRS_DOWN) continue;
      if (occupied.has(this._key(x, y))) continue;
      return { x, y };
    }
    return null;
  }

  _recomputeFOV() {
    const blocking = blockingFromGrid(this.dungeon.grid, TILE);
    this.visible = computeFOV(this.player.x, this.player.y, VISION_RADIUS, blocking);
    for (const key of this.visible) {
      const [x, y] = key.split(',').map(Number);
      if (this.explored[y]) this.explored[y][x] = true;
    }
  }

  // ---- player actions (each returns {ok, message?}) ----------------------

  movePlayer(dx, dy) {
    if (this.gameOver) return { ok: false, message: 'The run has ended.' };
    const nx = this.player.x + dx;
    const ny = this.player.y + dy;
    const target = this.monsterAt(nx, ny);

    if (target) {
      this._playerAttack(target);
      this._endTurn();
      return { ok: true };
    }
    if (!this.isWalkableTile(nx, ny)) {
      return { ok: false, message: 'You bump into a wall.' };
    }
    this.player.x = nx;
    this.player.y = ny;
    this._autoPickup();
    this._endTurn();
    return { ok: true };
  }

  _autoPickup() {
    const k = this._key(this.player.x, this.player.y);
    const stack = this.groundItems.get(k);
    if (!stack || stack.length === 0) return;
    const remaining = [];
    for (const item of stack) {
      const result = addToInventory(this.player, item);
      this._log(result.message);
      if (!result.ok) remaining.push(item);
    }
    if (remaining.length > 0) this.groundItems.set(k, remaining);
    else this.groundItems.delete(k);
  }

  _playerAttack(monster) {
    const result = resolveAttack(this.player, monster, this.rng);
    this._log(result.message);
    monster.aggro = true;
    if (result.defenderDied) {
      this._log(`${monster.name} dies.`);
      this.player.kills += 1;
      const levelUps = this.player.gainXp(monster.xpReward);
      if (levelUps > 0) this._log(`You feel stronger! You reached level ${this.player.level}.`);
      this.monsters = this.monsters.filter((m) => m.id !== monster.id);
    }
  }

  waitTurn() {
    if (this.gameOver) return { ok: false, message: 'The run has ended.' };
    this._log('You wait.');
    this._endTurn();
    return { ok: true };
  }

  useItem(itemId) {
    if (this.gameOver) return { ok: false, message: 'The run has ended.' };
    const item = this.player.inventory.find((i) => i.id === itemId);
    if (!item) return { ok: false, message: 'You do not have that item.' };

    if (item.type === 'potion') {
      const healed = this.player.heal(item.heal);
      this._log(`You drink the ${item.name} and recover ${healed} HP.`);
      removeFromInventory(this.player, itemId);
      this._endTurn();
      return { ok: true };
    }
    if (item.type === 'scroll') {
      if (item.effect === 'teleport') {
        const spot = this._randomFloorTile(this.dungeon.rooms, new Set());
        if (spot) {
          this.player.x = spot.x;
          this.player.y = spot.y;
          this._log(`You read the ${item.name} and are wrenched elsewhere.`);
        } else {
          this._log(`You read the ${item.name} but nothing happens.`);
        }
      } else if (item.effect === 'reveal') {
        for (let y = 0; y < this.explored.length; y++) {
          for (let x = 0; x < this.explored[y].length; x++) {
            if (this.dungeon.grid[y][x] !== TILE.WALL) this.explored[y][x] = true;
          }
        }
        this._log(`You read the ${item.name} and the floor's layout is revealed.`);
      }
      removeFromInventory(this.player, itemId);
      this._recomputeFOV();
      this._endTurn();
      return { ok: true };
    }
    return { ok: false, message: `You cannot use ${item.name} directly — try equipping it.` };
  }

  equip(itemId) {
    if (this.gameOver) return { ok: false, message: 'The run has ended.' };
    const result = equipItem(this.player, itemId);
    this._log(result.message);
    if (result.ok) this._endTurn();
    return result;
  }

  unequip(slot) {
    if (this.gameOver) return { ok: false, message: 'The run has ended.' };
    const result = unequipSlot(this.player, slot);
    this._log(result.message);
    if (result.ok) this._endTurn();
    return result;
  }

  dropItem(itemId) {
    if (this.gameOver) return { ok: false, message: 'The run has ended.' };
    const item = removeFromInventory(this.player, itemId);
    if (!item) return { ok: false, message: 'You do not have that item.' };
    const k = this._key(this.player.x, this.player.y);
    const stack = this.groundItems.get(k) || [];
    stack.push({ ...item, count: 1 });
    this.groundItems.set(k, stack);
    this._log(`You drop the ${item.name}.`);
    this._endTurn();
    return { ok: true };
  }

  descend() {
    if (this.gameOver) return { ok: false, message: 'The run has ended.' };
    const tile = this.dungeon.grid[this.player.y][this.player.x];
    if (tile !== TILE.STAIRS_DOWN) {
      return { ok: false, message: 'There are no stairs down here.' };
    }
    if (this.floorNumber >= MAX_FLOOR) {
      this.gameOver = true;
      this.won = true;
      this._log(`You escape Ashenkeep alive, having conquered all ${MAX_FLOOR} floors! Final score: level ${this.player.level}, ${this.player.kills} kills.`);
      return { ok: true, won: true };
    }
    this._nextFloor();
    this._log(`You descend to floor ${this.floorNumber}.`);
    return { ok: true };
  }

  // ---- monster turn -------------------------------------------------------

  _endTurn() {
    this.turnCount += 1;
    this._recomputeFOV();
    this._processMonsterTurns();
  }

  _processMonsterTurns() {
    const blocking = blockingFromGrid(this.dungeon.grid, TILE);
    for (const monster of this.monsters.slice()) {
      if (!monster.isAlive()) continue;
      if (!this.player.isAlive()) break;

      if (!monster.aggro) {
        const sight = computeFOV(monster.x, monster.y, MONSTER_SIGHT_RADIUS, blocking);
        if (sight.has(this._key(this.player.x, this.player.y))) {
          monster.aggro = true;
          this._log(`${monster.name} notices you!`);
        }
      }

      if (monster.aggro) {
        const dist = Math.abs(monster.x - this.player.x) + Math.abs(monster.y - this.player.y);
        if (dist === 1) {
          const result = resolveAttack(monster, this.player, this.rng);
          this._log(result.message);
          if (result.defenderDied) {
            this.gameOver = true;
            this.won = false;
            this._log(`You have fallen on floor ${this.floorNumber}. Final score: level ${this.player.level}, ${this.player.kills} kills.`);
            return;
          }
          continue;
        }
        const extraBlocked = new Set(
          this.monsters.filter((m) => m.id !== monster.id && m.isAlive()).map((m) => this._key(m.x, m.y))
        );
        const path = findPath(
          (x, y) => isWalkable(this.dungeon.grid, x, y),
          { x: monster.x, y: monster.y },
          { x: this.player.x, y: this.player.y },
          { extraBlocked }
        );
        if (path && path.length > 0) {
          const next = path[0];
          if (!(next.x === this.player.x && next.y === this.player.y) && !this.monsterAt(next.x, next.y)) {
            monster.x = next.x;
            monster.y = next.y;
          }
        }
      } else if (this.rng.chance(0.5)) {
        const dirs = [
          [1, 0],
          [-1, 0],
          [0, 1],
          [0, -1],
        ];
        const [dx, dy] = this.rng.pick(dirs);
        const nx = monster.x + dx;
        const ny = monster.y + dy;
        if (isWalkable(this.dungeon.grid, nx, ny) && !this.monsterAt(nx, ny) && !(nx === this.player.x && ny === this.player.y)) {
          monster.x = nx;
          monster.y = ny;
        }
      }
    }
  }

  // ---- save / load ---------------------------------------------------------

  serialize() {
    return {
      version: 1,
      seed: this.seed,
      rngState: this.rng.getState(),
      floorNumber: this.floorNumber,
      turnCount: this.turnCount,
      messages: this.messages.slice(),
      gameOver: this.gameOver,
      won: this.won,
      dungeon: {
        grid: this.dungeon.grid,
        width: this.dungeon.width,
        height: this.dungeon.height,
        start: this.dungeon.start,
        stairs: this.dungeon.stairs,
      },
      explored: this.explored,
      player: { ...this.player, inventory: this.player.inventory.map((i) => ({ ...i })), equipment: { ...this.player.equipment } },
      monsters: this.monsters.map((m) => ({ ...m, path: undefined })),
      groundItems: Array.from(this.groundItems.entries()).map(([k, items]) => [k, items.map((i) => ({ ...i }))]),
    };
  }

  static fromSaved(data) {
    const game = new Game(0, { deferInit: true });
    game.seed = data.seed >>> 0;
    game.rng = new RNG(game.seed);
    game.rng.setState(data.rngState);
    game.floorNumber = data.floorNumber;
    game.turnCount = data.turnCount;
    game.messages = data.messages.slice();
    game.gameOver = data.gameOver;
    game.won = data.won;
    game.dungeon = {
      grid: data.dungeon.grid,
      width: data.dungeon.width,
      height: data.dungeon.height,
      start: data.dungeon.start,
      stairs: data.dungeon.stairs,
      rooms: [],
    };
    game.explored = data.explored;

    const player = Object.create(Player.prototype);
    Object.assign(player, data.player);
    game.player = player;

    game.monsters = data.monsters.map((m) => {
      const monster = Object.create(Monster.prototype);
      Object.assign(monster, m);
      monster.path = [];
      return monster;
    });

    game.groundItems = new Map(data.groundItems.map(([k, items]) => [k, items]));
    game._recomputeFOV();
    return game;
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { Game, VISION_RADIUS, MONSTER_SIGHT_RADIUS, MAX_FLOOR, floorDimensions };
}
if (typeof window !== 'undefined') {
  window.Ashenkeep = window.Ashenkeep || {};
  Object.assign(window.Ashenkeep, { Game, VISION_RADIUS, MONSTER_SIGHT_RADIUS, MAX_FLOOR, floorDimensions });
}

})();
