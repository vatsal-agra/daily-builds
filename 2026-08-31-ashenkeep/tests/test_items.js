'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { RNG } = require('../src/rng.js');
const { Player } = require('../src/entities.js');
const {
  INVENTORY_CAPACITY,
  rollWeapon,
  rollArmor,
  rollRing,
  rollPotion,
  rollScroll,
  generateLootDrop,
  addToInventory,
  removeFromInventory,
  equipItem,
  unequipSlot,
} = require('../src/items.js');

test('rollWeapon always has a positive atk affix and a weapon slot', () => {
  const rng = new RNG(1);
  for (let i = 0; i < 100; i++) {
    const w = rollWeapon(1 + (i % 10), rng);
    assert.equal(w.slot, 'weapon');
    assert.ok(w.affixes.atk > 0);
  }
});

test('rollArmor always has a positive def affix', () => {
  const rng = new RNG(2);
  for (let i = 0; i < 100; i++) {
    const a = rollArmor(1 + (i % 10), rng);
    assert.equal(a.slot, 'armor');
    assert.ok(a.affixes.def > 0);
  }
});

test('rollRing always has at least one affix', () => {
  const rng = new RNG(3);
  for (let i = 0; i < 100; i++) {
    const r = rollRing(1 + (i % 10), rng);
    assert.equal(r.slot, 'ring');
    assert.ok(Object.keys(r.affixes).length >= 1);
  }
});

test('higher rarity items appear at nonzero rate and are named accordingly', () => {
  const rng = new RNG(4);
  const rarities = new Set();
  for (let i = 0; i < 500; i++) rarities.add(rollWeapon(5, rng).rarity);
  assert.ok(rarities.has('common'));
  assert.ok(['magic', 'rare', 'epic'].some((r) => rarities.has(r)), 'expected some non-common rolls over 500 samples');
});

test('rollPotion heals a positive amount; rollScroll has a known effect', () => {
  const rng = new RNG(5);
  const p = rollPotion(1, rng);
  assert.ok(p.heal > 0);
  const s = rollScroll(1, rng);
  assert.ok(['teleport', 'reveal'].includes(s.effect));
});

test('generateLootDrop always returns a well-formed item across many rolls', () => {
  const rng = new RNG(6);
  for (let i = 0; i < 300; i++) {
    const item = generateLootDrop(1 + (i % 10), rng);
    assert.ok(item.name);
    assert.ok(['weapon', 'armor', 'ring', 'potion', 'scroll'].includes(item.type));
  }
});

test('addToInventory stacks matching consumables instead of using a new slot', () => {
  const p = new Player();
  const rng = new RNG(1);
  const potionA = rollPotion(1, rng);
  const before = potionA.key;
  const potionB = { ...rollPotion(1, rng), key: before }; // force same key
  addToInventory(p, potionA);
  const result = addToInventory(p, potionB);
  assert.equal(p.inventory.length, 1, 'stackable items should share one inventory slot');
  assert.equal(p.inventory[0].count, 2);
  assert.ok(result.ok);
});

test('addToInventory rejects a new item once capacity is full', () => {
  const p = new Player();
  const rng = new RNG(2);
  for (let i = 0; i < INVENTORY_CAPACITY; i++) {
    const w = rollWeapon(1, rng);
    const r = addToInventory(p, w);
    assert.ok(r.ok);
  }
  const overflow = rollArmor(1, rng);
  const result = addToInventory(p, overflow);
  assert.equal(result.ok, false);
  assert.equal(p.inventory.length, INVENTORY_CAPACITY);
});

test('removeFromInventory decrements a stack and fully removes at count 1', () => {
  const p = new Player();
  const rng = new RNG(3);
  const potion = rollPotion(1, rng);
  potion.count = 3;
  p.inventory.push(potion);
  removeFromInventory(p, potion.id);
  assert.equal(p.inventory[0].count, 2);
  removeFromInventory(p, potion.id);
  removeFromInventory(p, potion.id);
  assert.equal(p.inventory.length, 0);
});

test('equipItem moves item into the slot and swaps out the previous occupant', () => {
  const p = new Player();
  const rng = new RNG(4);
  const sword = rollWeapon(1, rng);
  p.inventory.push(sword);
  const r1 = equipItem(p, sword.id);
  assert.ok(r1.ok);
  assert.equal(p.equipment.weapon.id, sword.id);
  assert.equal(p.inventory.length, 0);

  const axe = rollWeapon(3, rng);
  p.inventory.push(axe);
  const r2 = equipItem(p, axe.id);
  assert.ok(r2.ok);
  assert.equal(p.equipment.weapon.id, axe.id);
  assert.equal(p.inventory.length, 1);
  assert.equal(p.inventory[0].id, sword.id, 'previously equipped item should return to inventory');
});

test('equipItem rejects a non-equippable item', () => {
  const p = new Player();
  const rng = new RNG(5);
  const potion = rollPotion(1, rng);
  p.inventory.push(potion);
  const result = equipItem(p, potion.id);
  assert.equal(result.ok, false);
});

test('unequipSlot moves the item back to inventory, and refuses when inventory is full', () => {
  const p = new Player();
  const rng = new RNG(6);
  const sword = rollWeapon(1, rng);
  p.inventory.push(sword);
  equipItem(p, sword.id);
  assert.equal(p.inventory.length, 0);

  const r1 = unequipSlot(p, 'weapon');
  assert.ok(r1.ok);
  assert.equal(p.inventory.length, 1);

  // Fill inventory to capacity, re-equip, then try to unequip into a full pack.
  equipItem(p, sword.id);
  for (let i = 0; i < INVENTORY_CAPACITY; i++) p.inventory.push(rollArmor(1, rng));
  const r2 = unequipSlot(p, 'weapon');
  assert.equal(r2.ok, false);
  assert.ok(p.equipment.weapon, 'item must stay equipped when the unequip is refused');
});
