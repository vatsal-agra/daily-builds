// attribution.js — small helpers shared by the UI and the test suite:
// a deterministic per-site color, and a cheap content hash used to
// detect convergence (two peers agree iff their hashes agree).
//
// Character-level attribution itself needs no extra bookkeeping in the
// CRDT: every node's id already carries the site that created it
// (`id.site`), so "who wrote this character" is just `node.id.site`.

/** FNV-1a, good enough to catch divergence in a demo/test, not cryptography. */
export function hashText(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}

const PALETTE = [
  '#e07a5f', '#3d8bfd', '#81b29a', '#f2cc8f', '#9b5de5', '#00bbf9', '#f15bb5', '#43aa8b',
];

/** Deterministic color for a site id, stable across the whole run. */
export function colorForSite(siteId, siteOrder) {
  const idx = siteOrder ? siteOrder.indexOf(siteId) : hashCode(siteId) % PALETTE.length;
  return PALETTE[((idx % PALETTE.length) + PALETTE.length) % PALETTE.length];
}

function hashCode(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}
