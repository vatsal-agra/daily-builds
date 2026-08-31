// items.js — item templates, procedural rarity/affix rolls, and inventory
// management. All effects here are *data*; applying a consumable's effect
// to live game state happens in game.js so this module stays a pure
// generator + a small set of inventory list operations.

'use strict';

(function () {

const INVENTORY_CAPACITY = 16;

const RARITIES = [
  { key: 'common', label: 'Common', color: '#c9c9c9', affixCount: 0, mult: 1.0, weight: 58 },
  { key: 'magic', label: 'Magic', color: '#4f8fdc', affixCount: 1, mult: 1.35, weight: 28 },
  { key: 'rare', label: 'Rare', color: '#d6c94f', affixCount: 2, mult: 1.75, weight: 12 },
  { key: 'epic', label: 'Epic', color: '#c04fd6', affixCount: 3, mult: 2.3, weight: 2 },
];

const WEAPON_BASES = [
  { name: 'Dagger', minTier: 1, range: [2, 4] },
  { name: 'Short Sword', minTier: 1, range: [4, 7] },
  { name: 'Long Sword', minTier: 2, range: [6, 10] },
  { name: 'War Axe', minTier: 3, range: [9, 14] },
];

const ARMOR_BASES = [
  { name: 'Leather Vest', minTier: 1, range: [1, 2] },
  { name: 'Chainmail', minTier: 2, range: [2, 4] },
  { name: 'Plate Armor', minTier: 3, range: [4, 6] },
];

// Secondary affixes rollable on any equippable item (weapon/armor/ring),
// each keyed to a stat Player reads directly off `equipment.*.affixes`.
const AFFIX_POOL = [
  { key: 'atk', suffix: 'of Might', range: [1, 3] },
  { key: 'def', suffix: 'of Warding', range: [1, 2] },
  { key: 'accuracy', suffix: 'of Precision', range: [0.03, 0.07] },
  { key: 'evasion', suffix: 'of Shadows', range: [0.03, 0.07] },
  { key: 'critChance', suffix: 'of the Viper', range: [0.03, 0.06] },
  { key: 'maxHp', suffix: 'of the Bear', range: [4, 10] },
];

const POTION_TEMPLATES = [
  { key: 'potion_minor', name: 'Minor Healing Potion', glyph: '!', color: '#e05c5c', heal: 12 },
  { key: 'potion_major', name: 'Major Healing Potion', glyph: '!', color: '#ff2e2e', heal: 28 },
];

const SCROLL_TEMPLATES = [
  { key: 'scroll_teleport', name: 'Scroll of Teleportation', glyph: '?', color: '#5ce0c6', effect: 'teleport' },
  { key: 'scroll_mapping', name: 'Scroll of Magic Mapping', glyph: '?', color: '#e0d15c', effect: 'reveal' },
];

let itemIdCounter = 0;

function rollFloat(rng, [lo, hi]) {
  return lo + rng.next() * (hi - lo);
}

function pickRarity(rng) {
  return rng.weighted(RARITIES.map((r) => ({ weight: r.weight, value: r })));
}

function rollEquippable(type, bases, statKey, floor, rng) {
  const tier = Math.min(bases.length, 1 + Math.floor((floor - 1) / 3));
  const eligible = bases.filter((b) => b.minTier <= tier);
  const base = rng.pick(eligible);
  const rarity = pickRarity(rng);
  const floorScale = 1 + (floor - 1) * 0.08;
  const primary = Math.max(1, Math.round(rollFloat(rng, base.range) * rarity.mult * floorScale));

  const affixes = { [statKey]: primary };
  const usedKeys = new Set([statKey]);
  const suffixes = [];
  const pool = AFFIX_POOL.filter((a) => a.key !== statKey);
  for (let i = 0; i < rarity.affixCount && pool.length > 0; i++) {
    const idx = rng.int(0, pool.length - 1);
    const affix = pool.splice(idx, 1)[0];
    if (usedKeys.has(affix.key)) continue;
    usedKeys.add(affix.key);
    const isFraction = affix.range[1] <= 1;
    const value = isFraction ? Number(rollFloat(rng, affix.range).toFixed(2)) : Math.max(1, Math.round(rollFloat(rng, affix.range)));
    affixes[affix.key] = (affixes[affix.key] || 0) + value;
    suffixes.push(affix.suffix);
  }

  const namePrefix = rarity.key === 'common' ? '' : `${rarity.label} `;
  const nameSuffix = suffixes.length > 0 ? ` ${suffixes[0]}` : '';
  const name = `${namePrefix}${base.name}${nameSuffix}`;

  return { base, rarity, affixes, name };
}

function makeItem(fields) {
  return { id: ++itemIdCounter, count: 1, ...fields };
}

function rollWeapon(floor, rng) {
  const { rarity, affixes, name } = rollEquippable('weapon', WEAPON_BASES, 'atk', floor, rng);
  return makeItem({ type: 'weapon', slot: 'weapon', name, glyph: '/', color: rarity.color, rarity: rarity.key, affixes, stackable: false });
}

function rollArmor(floor, rng) {
  const { rarity, affixes, name } = rollEquippable('armor', ARMOR_BASES, 'def', floor, rng);
  return makeItem({ type: 'armor', slot: 'armor', name, glyph: '[', color: rarity.color, rarity: rarity.key, affixes, stackable: false });
}

function rollRing(floor, rng) {
  // Rings have no fixed primary stat — every affix comes from the pool, so
  // a ring always does *something* interesting rather than "+atk again".
  const rarity = pickRarity(rng);
  const affixCount = Math.max(1, rarity.affixCount); // rings always roll at least 1
  const pool = AFFIX_POOL.slice();
  const affixes = {};
  const suffixes = [];
  const floorScale = 1 + (floor - 1) * 0.08;
  for (let i = 0; i < affixCount && pool.length > 0; i++) {
    const idx = rng.int(0, pool.length - 1);
    const affix = pool.splice(idx, 1)[0];
    const isFraction = affix.range[1] <= 1;
    const raw = rollFloat(rng, affix.range) * rarity.mult * floorScale;
    const value = isFraction ? Number(Math.min(0.3, raw).toFixed(2)) : Math.max(1, Math.round(raw));
    affixes[affix.key] = value;
    suffixes.push(affix.suffix);
  }
  const namePrefix = rarity.key === 'common' ? '' : `${rarity.label} `;
  const name = `${namePrefix}Ring${suffixes.length ? ' ' + suffixes[0] : ''}`;
  return makeItem({ type: 'ring', slot: 'ring', name, glyph: '=', color: rarity.color, rarity: rarity.key, affixes, stackable: false });
}

function rollPotion(floor, rng) {
  const pool = floor >= 4 ? POTION_TEMPLATES : POTION_TEMPLATES.slice(0, 1);
  const t = rng.pick(pool);
  return makeItem({ type: 'potion', name: t.name, glyph: t.glyph, color: t.color, rarity: 'common', heal: t.heal, stackable: true, key: t.key });
}

function rollScroll(floor, rng) {
  const t = rng.pick(SCROLL_TEMPLATES);
  return makeItem({ type: 'scroll', name: t.name, glyph: t.glyph, color: t.color, rarity: 'common', effect: t.effect, stackable: true, key: t.key });
}

/**
 * Roll one random loot item appropriate for `floor`. Category weights
 * favor consumables early and gear later, but every category is always
 * possible so a lucky floor-1 drop can still hand over a real weapon.
 */
function generateLootDrop(floor, rng) {
  const category = rng.weighted([
    { weight: 30, value: 'potion' },
    { weight: 15, value: 'scroll' },
    { weight: 25, value: 'weapon' },
    { weight: 20, value: 'armor' },
    { weight: 10, value: 'ring' },
  ]);
  switch (category) {
    case 'weapon':
      return rollWeapon(floor, rng);
    case 'armor':
      return rollArmor(floor, rng);
    case 'ring':
      return rollRing(floor, rng);
    case 'scroll':
      return rollScroll(floor, rng);
    default:
      return rollPotion(floor, rng);
  }
}

/**
 * Add an item to a player's inventory, respecting capacity and stacking.
 * Mutates `player.inventory` in place.
 * @returns {{ok: boolean, message: string}}
 */
function addToInventory(player, item) {
  if (item.stackable) {
    const existing = player.inventory.find((i) => i.stackable && i.key === item.key);
    if (existing) {
      existing.count += item.count;
      return { ok: true, message: `Picked up ${item.name} (x${existing.count}).` };
    }
  }
  if (player.inventory.length >= INVENTORY_CAPACITY) {
    return { ok: false, message: `Inventory full — cannot pick up ${item.name}.` };
  }
  player.inventory.push(item);
  return { ok: true, message: `Picked up ${item.name}.` };
}

// Remove one unit of the stack (or the whole item, if not stackable/last unit).
function removeFromInventory(player, itemId) {
  const idx = player.inventory.findIndex((i) => i.id === itemId);
  if (idx === -1) return null;
  const item = player.inventory[idx];
  if (item.stackable && item.count > 1) {
    item.count -= 1;
    return item;
  }
  player.inventory.splice(idx, 1);
  return item;
}

/**
 * Equip an item from inventory into its slot. Whatever was previously
 * equipped there is returned to the inventory (swapped, never destroyed).
 * @returns {{ok: boolean, message: string}}
 */
function equipItem(player, itemId) {
  const item = player.inventory.find((i) => i.id === itemId);
  if (!item) return { ok: false, message: 'Item not found.' };
  if (!item.slot) return { ok: false, message: `${item.name} cannot be equipped.` };

  const previous = player.equipment[item.slot];
  player.equipment[item.slot] = item;
  player.inventory = player.inventory.filter((i) => i.id !== itemId);
  if (previous) player.inventory.push(previous);
  return { ok: true, message: previous ? `Equipped ${item.name} (unequipped ${previous.name}).` : `Equipped ${item.name}.` };
}

function unequipSlot(player, slotName) {
  const item = player.equipment[slotName];
  if (!item) return { ok: false, message: `Nothing equipped in ${slotName}.` };
  if (player.inventory.length >= INVENTORY_CAPACITY) {
    return { ok: false, message: 'Inventory full — cannot unequip.' };
  }
  player.equipment[slotName] = null;
  player.inventory.push(item);
  return { ok: true, message: `Unequipped ${item.name}.` };
}

function describeAffixes(affixes) {
  const labels = { atk: 'Atk', def: 'Def', accuracy: 'Accuracy', evasion: 'Evasion', critChance: 'Crit', maxHp: 'Max HP' };
  const fractionKeys = new Set(['accuracy', 'evasion', 'critChance']);
  return Object.entries(affixes)
    .map(([k, v]) => `+${fractionKeys.has(k) ? Math.round(v * 100) + '%' : v} ${labels[k] || k}`)
    .join(', ');
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    INVENTORY_CAPACITY,
    RARITIES,
    generateLootDrop,
    rollWeapon,
    rollArmor,
    rollRing,
    rollPotion,
    rollScroll,
    addToInventory,
    removeFromInventory,
    equipItem,
    unequipSlot,
    describeAffixes,
  };
}
if (typeof window !== 'undefined') {
  window.Ashenkeep = window.Ashenkeep || {};
  Object.assign(window.Ashenkeep, {
    INVENTORY_CAPACITY,
    RARITIES,
    generateLootDrop,
    rollWeapon,
    rollArmor,
    rollRing,
    rollPotion,
    rollScroll,
    addToInventory,
    removeFromInventory,
    equipItem,
    unequipSlot,
    describeAffixes,
  });
}

})();
