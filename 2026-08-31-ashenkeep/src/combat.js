// combat.js — a real stat resolver shared by both player-attacks-monster
// and monster-attacks-player, so there is exactly one place that decides
// whether an attack lands and for how much. Both `Player` and `Monster`
// (entities.js) expose the same {atk, def, accuracy, evasion, critChance,
// takeDamage, isAlive} surface, so this function doesn't care which is
// which.

'use strict';

(function () {

const MIN_HIT_CHANCE = 0.05;
const MAX_HIT_CHANCE = 0.99;
const CRIT_MULTIPLIER = 1.75;
const DAMAGE_VARIANCE = 0.3; // +/-15% around the base roll

/**
 * Resolve one attack from `attacker` against `defender`, mutating
 * `defender.hp` via takeDamage() when the attack lands.
 * @returns {{hit: boolean, crit: boolean, damage: number, defenderDied: boolean, message: string}}
 */
function resolveAttack(attacker, defender, rng) {
  const hitChance = Math.max(MIN_HIT_CHANCE, Math.min(MAX_HIT_CHANCE, attacker.accuracy - defender.evasion));
  const hit = rng.chance(hitChance);

  if (!hit) {
    return {
      hit: false,
      crit: false,
      damage: 0,
      defenderDied: false,
      message: `${attacker.name} attacks ${defender.name} but misses.`,
    };
  }

  const rawDamage = Math.max(1, attacker.atk - defender.def);
  const variance = 1 - DAMAGE_VARIANCE / 2 + rng.next() * DAMAGE_VARIANCE;
  let damage = Math.max(1, Math.round(rawDamage * variance));
  const crit = rng.chance(attacker.critChance);
  if (crit) damage = Math.round(damage * CRIT_MULTIPLIER);

  defender.takeDamage(damage);
  const defenderDied = !defender.isAlive();

  const message = crit
    ? `${attacker.name} lands a CRITICAL hit on ${defender.name} for ${damage} damage!`
    : `${attacker.name} hits ${defender.name} for ${damage} damage.`;

  return { hit: true, crit, damage, defenderDied, message };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { resolveAttack, MIN_HIT_CHANCE, MAX_HIT_CHANCE, CRIT_MULTIPLIER };
}
if (typeof window !== 'undefined') {
  window.Ashenkeep = window.Ashenkeep || {};
  Object.assign(window.Ashenkeep, { resolveAttack, MIN_HIT_CHANCE, MAX_HIT_CHANCE, CRIT_MULTIPLIER });
}

})();
