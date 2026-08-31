'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { RNG } = require('../src/rng.js');
const { resolveAttack } = require('../src/combat.js');

function makeActor(overrides) {
  return {
    name: 'Test',
    atk: 5,
    def: 0,
    accuracy: 0.8,
    evasion: 0.1,
    critChance: 0.1,
    hp: 20,
    isAlive() {
      return this.hp > 0;
    },
    takeDamage(amount) {
      this.hp = Math.max(0, this.hp - amount);
    },
    ...overrides,
  };
}

test('a near-guaranteed-hit attacker (accuracy 1, defender evasion 0) hits almost every time and always deals damage on a hit', () => {
  // Hit chance is intentionally clamped below 100% (see MAX_HIT_CHANCE in
  // combat.js) so no build ever becomes literally unmissable — so this
  // checks "hits the overwhelming majority of the time", not "always".
  const rng = new RNG(1);
  const attacker = makeActor({ accuracy: 1, critChance: 0 });
  let hits = 0;
  for (let i = 0; i < 200; i++) {
    const defender = makeActor({ evasion: 0, hp: 9999 });
    const result = resolveAttack(attacker, defender, rng);
    if (result.hit) {
      hits += 1;
      assert.ok(result.damage > 0);
    }
  }
  assert.ok(hits >= 180, `expected at least 90% hit rate at max accuracy, got ${hits}/200`);
});

test('damage is never negative or zero on a hit, even when defense exceeds attack', () => {
  const rng = new RNG(2);
  const attacker = makeActor({ atk: 1, accuracy: 1, critChance: 0 });
  const defender = makeActor({ def: 999, evasion: 0, hp: 9999 });
  for (let i = 0; i < 50; i++) {
    const result = resolveAttack(attacker, defender, rng);
    assert.ok(result.hit);
    assert.ok(result.damage >= 1, 'minimum damage floor of 1 should always apply');
  }
});

test('a miss deals zero damage and does not call takeDamage', () => {
  const rng = new RNG(3);
  const attacker = makeActor({ accuracy: 0.0 });
  let damageCalls = 0;
  const defender = makeActor({
    evasion: 0,
    takeDamage(amount) {
      damageCalls += 1;
      this.hp -= amount;
    },
  });
  const result = resolveAttack(attacker, defender, rng);
  assert.equal(result.hit, false);
  assert.equal(result.damage, 0);
  assert.equal(damageCalls, 0);
});

test('hit chance is clamped so a defender can never be literally unhittable or an attacker never-miss', () => {
  const rng = new RNG(4);
  const attacker = makeActor({ accuracy: 0.0 });
  const defender = makeActor({ evasion: 5, hp: 9999 }); // absurd evasion
  let anyHit = false;
  for (let i = 0; i < 3000; i++) {
    if (resolveAttack(attacker, defender, rng).hit) anyHit = true;
  }
  assert.ok(anyHit, 'a minimum hit chance floor should guarantee occasional hits over enough trials');
});

test('defenderDied is true exactly when hp reaches 0 from this attack', () => {
  const rng = new RNG(5);
  const attacker = makeActor({ atk: 50, accuracy: 1, critChance: 0 });
  const defender = makeActor({ def: 0, evasion: 0, hp: 5 });
  const result = resolveAttack(attacker, defender, rng);
  assert.ok(result.hit);
  assert.equal(defender.hp, 0);
  assert.equal(result.defenderDied, true);
});

test('critical hits deal strictly more damage than the same roll without a crit', () => {
  const rng1 = new RNG(6);
  const rng2 = new RNG(6);
  const attackerCrit = makeActor({ accuracy: 1, critChance: 1 });
  const attackerNoCrit = makeActor({ accuracy: 1, critChance: 0 });
  const defenderA = makeActor({ evasion: 0, hp: 9999 });
  const defenderB = makeActor({ evasion: 0, hp: 9999 });
  const critResult = resolveAttack(attackerCrit, defenderA, rng1);
  const normalResult = resolveAttack(attackerNoCrit, defenderB, rng2);
  assert.ok(critResult.crit);
  assert.ok(!normalResult.crit);
  assert.ok(critResult.damage > normalResult.damage);
});

test('resolveAttack is a pure function of (attacker, defender, rng) — no hidden mutation of the attacker', () => {
  const rng = new RNG(7);
  const attacker = makeActor({});
  const before = { ...attacker };
  const defender = makeActor({});
  resolveAttack(attacker, defender, rng);
  assert.equal(attacker.hp, before.hp);
  assert.equal(attacker.atk, before.atk);
});
