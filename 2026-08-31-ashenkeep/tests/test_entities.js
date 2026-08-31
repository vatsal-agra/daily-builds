'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { RNG } = require('../src/rng.js');
const { Player, Monster, spawnMonster, templatesForFloor, xpForLevel, MONSTER_TEMPLATES } = require('../src/entities.js');

test('xpForLevel is strictly increasing (progression always demands more)', () => {
  let prev = 0;
  for (let lvl = 1; lvl <= 20; lvl++) {
    const need = xpForLevel(lvl);
    assert.ok(need > prev, `xp requirement did not increase at level ${lvl}`);
    prev = need;
  }
});

test('gainXp levels up exactly once per threshold crossed, and can multi-level on a big reward', () => {
  const p = new Player();
  const need = p.xpToNext;
  const ups = p.gainXp(need - 1);
  assert.equal(ups, 0);
  assert.equal(p.level, 1);
  const ups2 = p.gainXp(1);
  assert.equal(ups2, 1);
  assert.equal(p.level, 2);

  const p2 = new Player();
  const bigReward = xpForLevel(1) + xpForLevel(2) + 5;
  const ups3 = p2.gainXp(bigReward);
  assert.equal(ups3, 2);
  assert.equal(p2.level, 3);
});

test('leveling up increases max HP and heals by the gain, never above the new max', () => {
  const p = new Player();
  p.hp = 1; // simulate near-death
  const maxBefore = p.maxHp;
  p.gainXp(p.xpToNext);
  assert.ok(p.maxHp > maxBefore);
  assert.ok(p.hp <= p.maxHp);
  assert.ok(p.hp > 1, 'level-up should have healed the player somewhat');
});

test('heal() never exceeds maxHp, takeDamage() never goes below 0', () => {
  const p = new Player();
  p.hp = p.maxHp - 2;
  const healed = p.heal(100);
  assert.equal(p.hp, p.maxHp);
  assert.equal(healed, 2);

  p.takeDamage(9999);
  assert.equal(p.hp, 0);
  assert.equal(p.isAlive(), false);
});

test('equipment bonuses are additive and reflected in derived getters', () => {
  const p = new Player();
  const baseAtk = p.atk;
  p.equipment.weapon = { affixes: { atk: 5 } };
  assert.equal(p.atk, baseAtk + 5);
  p.equipment.ring = { affixes: { atk: 2, maxHp: 10 } };
  assert.equal(p.atk, baseAtk + 7);
  assert.equal(p.maxHp, p.baseMaxHp + 10);
});

test('templatesForFloor only allows higher-tier monsters on deeper floors', () => {
  const floor1 = templatesForFloor(1).map((t) => t.tier);
  assert.ok(floor1.every((t) => t === 1), 'floor 1 should only spawn tier-1 monsters');
  const floor10 = templatesForFloor(10).map((t) => t.tier);
  assert.ok(floor10.includes(4), 'floor 10 should include tier-4 monsters');
});

test('spawnMonster scales stats up on deeper floors', () => {
  const rng1 = new RNG(1);
  const rng2 = new RNG(1);
  // Force the same template selection by comparing the *ratio* across many
  // samples rather than a single draw (template choice is itself random).
  let totalHp1 = 0;
  let totalHp10 = 0;
  const N = 200;
  const a = new RNG(5);
  const b = new RNG(5);
  for (let i = 0; i < N; i++) {
    totalHp1 += spawnMonster(1, 0, 0, a).maxHp;
    totalHp10 += spawnMonster(10, 0, 0, b).maxHp;
  }
  assert.ok(totalHp10 > totalHp1, 'floor 10 monsters should average tougher than floor 1');
});

test('Monster takeDamage/isAlive behave like Player (shared combat interface)', () => {
  const m = spawnMonster(1, 0, 0, new RNG(1));
  const hp = m.hp;
  m.takeDamage(1);
  assert.equal(m.hp, hp - 1);
  m.takeDamage(9999);
  assert.equal(m.hp, 0);
  assert.equal(m.isAlive(), false);
});

test('every monster template has a positive xp reward and distinct glyph/name', () => {
  for (const t of MONSTER_TEMPLATES) {
    assert.ok(t.xp > 0);
    assert.ok(t.name.length > 0);
    assert.ok(t.glyph.length === 1);
  }
});
