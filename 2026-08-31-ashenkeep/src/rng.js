// rng.js — seeded pseudo-random number generator (mulberry32).
//
// Deterministic: the same seed always produces the same stream of numbers,
// which is what lets a whole dungeon floor (layout, monsters, loot) be
// reproduced exactly from one 32-bit integer, and lets a save file resume
// a run bit-for-bit by persisting the generator's internal state.

'use strict';

(function () {

class RNG {
  constructor(seed) {
    // Normalize to an unsigned 32-bit integer seed.
    this.state = (seed >>> 0) || 0xdeadbeef;
  }

  // Returns a float in [0, 1).
  next() {
    let t = (this.state += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  // Integer in [min, max] inclusive.
  int(min, max) {
    if (max < min) throw new RangeError(`int(${min}, ${max}): max < min`);
    return min + Math.floor(this.next() * (max - min + 1));
  }

  // True with probability p (0..1).
  chance(p) {
    return this.next() < p;
  }

  // Pick a uniformly random element of a non-empty array.
  pick(arr) {
    if (!arr || arr.length === 0) {
      throw new RangeError('pick() called on an empty array');
    }
    return arr[this.int(0, arr.length - 1)];
  }

  // Weighted pick: items = [{weight, value}, ...]. Weights must sum > 0.
  weighted(items) {
    const total = items.reduce((s, it) => s + it.weight, 0);
    if (!(total > 0)) throw new RangeError('weighted(): total weight must be > 0');
    let r = this.next() * total;
    for (const it of items) {
      if (r < it.weight) return it.value;
      r -= it.weight;
    }
    return items[items.length - 1].value; // floating-point fallback
  }

  // Serializable snapshot so a save file can resume the exact stream.
  getState() {
    return this.state >>> 0;
  }

  setState(state) {
    this.state = state >>> 0;
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { RNG };
}
if (typeof window !== 'undefined') {
  window.Ashenkeep = window.Ashenkeep || {};
  window.Ashenkeep.RNG = RNG;
}

})();
