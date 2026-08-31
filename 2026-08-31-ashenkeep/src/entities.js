// entities.js — actor stat blocks (player + monsters) and the leveling
// curve. Pure data + pure functions; no rendering, no I/O.

'use strict';

(function () {

// XP required to go from `level` to `level + 1`.
function xpForLevel(level) {
  return Math.round(20 * Math.pow(1.45, level - 1));
}

class Player {
  constructor(name = 'Wanderer') {
    this.name = name;
    this.level = 1;
    this.xp = 0;
    this.baseMaxHp = 32;
    this.hp = this.baseMaxHp;
    this.baseAtk = 5; // base damage before equipment
    this.baseDef = 2; // base damage reduction before equipment
    this.baseAccuracy = 0.85; // base chance to hit
    this.baseEvasion = 0.05; // base chance to dodge an incoming hit
    this.baseCritChance = 0.05;
    this.kills = 0;
    this.floor = 1;
    this.x = 0;
    this.y = 0;
    this.inventory = []; // Item[]
    this.equipment = { weapon: null, armor: null, ring: null };
  }

  isAlive() {
    return this.hp > 0;
  }

  get maxHp() {
    let bonus = 0;
    for (const slot of Object.values(this.equipment)) {
      if (slot) bonus += slot.affixes.maxHp || 0;
    }
    return this.baseMaxHp + bonus;
  }

  get atk() {
    let bonus = 0;
    for (const slot of Object.values(this.equipment)) {
      if (slot) bonus += slot.affixes.atk || 0;
    }
    return this.baseAtk + bonus;
  }

  get def() {
    let bonus = 0;
    for (const slot of Object.values(this.equipment)) {
      if (slot) bonus += slot.affixes.def || 0;
    }
    return this.baseDef + bonus;
  }

  get accuracy() {
    let bonus = 0;
    for (const slot of Object.values(this.equipment)) {
      if (slot) bonus += slot.affixes.accuracy || 0;
    }
    return Math.min(0.99, this.baseAccuracy + bonus);
  }

  get evasion() {
    let bonus = 0;
    for (const slot of Object.values(this.equipment)) {
      if (slot) bonus += slot.affixes.evasion || 0;
    }
    return Math.min(0.5, this.baseEvasion + bonus);
  }

  get critChance() {
    let bonus = 0;
    for (const slot of Object.values(this.equipment)) {
      if (slot) bonus += slot.affixes.critChance || 0;
    }
    return Math.min(0.75, this.baseCritChance + bonus);
  }

  get xpToNext() {
    return xpForLevel(this.level);
  }

  // Returns the number of level-ups triggered (0 if none).
  gainXp(amount) {
    if (amount <= 0) return 0;
    this.xp += amount;
    let levelUps = 0;
    while (this.xp >= this.xpToNext) {
      this.xp -= this.xpToNext;
      this.level += 1;
      levelUps += 1;
      const hpGain = 8 + this.level * 3;
      this.baseMaxHp += hpGain;
      this.hp = Math.min(this.maxHp, this.hp + hpGain);
      this.baseAtk += 1;
      if (this.level % 2 === 0) this.baseDef += 1;
    }
    return levelUps;
  }

  heal(amount) {
    const before = this.hp;
    this.hp = Math.min(this.maxHp, this.hp + amount);
    return this.hp - before;
  }

  takeDamage(amount) {
    this.hp = Math.max(0, this.hp - amount);
  }
}

// Monster templates scale with the floor they're spawned on (see
// `spawnMonster`). `tier` is used to gate which monsters can appear on
// which floor so early floors stay survivable.
const MONSTER_TEMPLATES = [
  { key: 'rat', name: 'Giant Rat', glyph: 'r', color: '#a5895a', tier: 1, hp: 6, atk: 2, def: 0, accuracy: 0.7, evasion: 0.1, xp: 4 },
  { key: 'jackal', name: 'Cave Jackal', glyph: 'j', color: '#c98a4b', tier: 1, hp: 9, atk: 3, def: 0, accuracy: 0.75, evasion: 0.15, xp: 6 },
  { key: 'goblin', name: 'Goblin', glyph: 'g', color: '#6fae4c', tier: 2, hp: 14, atk: 4, def: 1, accuracy: 0.75, evasion: 0.08, xp: 10 },
  { key: 'skeleton', name: 'Skeleton', glyph: 's', color: '#d8d8d8', tier: 2, hp: 16, atk: 5, def: 2, accuracy: 0.7, evasion: 0.02, xp: 13 },
  { key: 'orc', name: 'Orc Brute', glyph: 'o', color: '#4f8f4f', tier: 3, hp: 26, atk: 7, def: 3, accuracy: 0.72, evasion: 0.03, xp: 22 },
  { key: 'wraith', name: 'Wraith', glyph: 'w', color: '#8f7fd6', tier: 3, hp: 20, atk: 8, def: 1, accuracy: 0.8, evasion: 0.2, xp: 26 },
  { key: 'troll', name: 'Cave Troll', glyph: 'T', color: '#3f6b3f', tier: 4, hp: 42, atk: 10, def: 4, accuracy: 0.7, evasion: 0.0, xp: 40 },
  { key: 'lich', name: 'Lesser Lich', glyph: 'L', color: '#b23fd6', tier: 4, hp: 34, atk: 12, def: 3, accuracy: 0.78, evasion: 0.08, xp: 48 },
];

// The final-floor guardian. Not part of MONSTER_TEMPLATES's random pool —
// it is spawned exactly once, deliberately, standing on the floor-10
// stairs tile (see spawnBoss/game.js), so the player must defeat it to
// ever physically stand on that tile and descend to win.
const BOSS_TEMPLATE = {
  key: 'keeper',
  name: 'The Keeper of Ashenkeep',
  glyph: 'K',
  color: '#ff4d4d',
  tier: 5,
  hp: 150,
  atk: 19,
  def: 8,
  accuracy: 0.8,
  evasion: 0.08,
  xp: 200,
};

let monsterIdCounter = 0;

class Monster {
  constructor(template, x, y) {
    this.id = ++monsterIdCounter;
    this.key = template.key;
    this.name = template.name;
    this.glyph = template.glyph;
    this.color = template.color;
    this.hp = template.hp;
    this.maxHp = template.hp;
    this.atk = template.atk;
    this.def = template.def;
    this.accuracy = template.accuracy;
    this.evasion = template.evasion;
    this.critChance = 0.04;
    this.xpReward = template.xp;
    this.x = x;
    this.y = y;
    this.aggro = false;
    this.isBoss = false;
  }

  isAlive() {
    return this.hp > 0;
  }

  takeDamage(amount) {
    this.hp = Math.max(0, this.hp - amount);
  }
}

// Which templates are allowed to spawn on a given floor number (1-based),
// and a mild stat-scaling multiplier so floor 10 monsters of the same
// species genuinely hit harder than floor 1 ones.
function templatesForFloor(floor) {
  const maxTier = Math.min(4, 1 + Math.floor((floor - 1) / 2));
  return MONSTER_TEMPLATES.filter((t) => t.tier <= maxTier);
}

function spawnMonster(floor, x, y, rng) {
  const pool = templatesForFloor(floor);
  const template = rng.pick(pool);
  const scale = 1 + (floor - 1) * 0.08;
  const scaled = {
    ...template,
    hp: Math.round(template.hp * scale),
    atk: Math.round(template.atk * scale),
  };
  return new Monster(scaled, x, y);
}

function spawnBoss(x, y) {
  const boss = new Monster(BOSS_TEMPLATE, x, y);
  boss.isBoss = true;
  return boss;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { Player, Monster, MONSTER_TEMPLATES, BOSS_TEMPLATE, spawnMonster, spawnBoss, templatesForFloor, xpForLevel };
}
if (typeof window !== 'undefined') {
  window.Ashenkeep = window.Ashenkeep || {};
  Object.assign(window.Ashenkeep, { Player, Monster, MONSTER_TEMPLATES, BOSS_TEMPLATE, spawnMonster, spawnBoss, templatesForFloor, xpForLevel });
}

})();
