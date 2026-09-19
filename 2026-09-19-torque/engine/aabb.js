// aabb.js -- broad-phase pair culling via sort-and-sweep on the x axis.
// O(n log n) sort + O(n + k) sweep instead of the naive O(n^2) all-pairs
// check; k is the number of overlapping-AABB pairs actually found.
(function (root) {
  'use strict';

  const MARGIN = 0.05; // small AABB fattening so bodies don't flicker in/out

  function aabbOverlap(a, b) {
    return a.minX <= b.maxX && b.minX <= a.maxX && a.minY <= b.maxY && b.minY <= a.maxY;
  }

  function fatten(box) {
    return {
      minX: box.minX - MARGIN,
      minY: box.minY - MARGIN,
      maxX: box.maxX + MARGIN,
      maxY: box.maxY + MARGIN,
    };
  }

  // Returns an array of [bodyA, bodyB] candidate pairs whose fattened AABBs
  // overlap. Skips pairs that can never need a physics response: two static
  // bodies, or two bodies that are both asleep.
  function computeBroadPhasePairs(bodies) {
    const entries = [];
    for (let i = 0; i < bodies.length; i++) {
      const b = bodies[i];
      entries.push({ body: b, box: fatten(b.worldAABB()) });
    }
    entries.sort((a, b) => a.box.minX - b.box.minX);

    const pairs = [];
    for (let i = 0; i < entries.length; i++) {
      const ei = entries[i];
      for (let j = i + 1; j < entries.length; j++) {
        const ej = entries[j];
        if (ej.box.minX > ei.box.maxX) break; // sorted by minX -> no more can overlap
        if (ei.body.isStatic && ej.body.isStatic) continue;
        if (ei.body.isSleeping && ej.body.isSleeping) continue;
        if (aabbOverlap(ei.box, ej.box)) {
          pairs.push([ei.body, ej.body]);
        }
      }
    }
    return pairs;
  }

  const api = { computeBroadPhasePairs: computeBroadPhasePairs, aabbOverlap: aabbOverlap };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.Torque = root.Torque || {};
    root.Torque.computeBroadPhasePairs = computeBroadPhasePairs;
  }
})(typeof window !== 'undefined' ? window : globalThis);
