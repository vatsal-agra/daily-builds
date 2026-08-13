// regression.test.js — one test per real bug found during the Phase 3
// adversarial review (see REVIEW.md for the full writeup), pinned here so
// none of them can silently come back.

import test from 'node:test';
import assert from 'node:assert/strict';
import { Doc } from '../src/rga.js';
import { Peer } from '../src/peer.js';
import { NameAllocator, NAME_POOL } from '../src/names.js';

test('REGRESSION: a reused site id must not silently swallow the new peer\'s edits', () => {
  // This is the bug: two DIFFERENT Peer instances sharing the same siteId
  // both start their id-counter at 0, so their local ops collide.
  const oldAlice = new Peer('Alice');
  oldAlice.setText('hello');

  const newAlice = new Peer('Alice'); // deliberately reusing the id
  for (const op of oldAlice.myOps) newAlice.receive(op);

  const carolDoc = new Doc('Carol');
  for (const op of oldAlice.myOps) carolDoc.applyOp(op);

  const ops = newAlice.setText(newAlice.text + 'X');
  for (const op of ops) carolDoc.applyOp(op);

  // Document the failure mode precisely: with a reused id, the edit is lost.
  assert.equal(carolDoc.getText(), 'hello', 'demonstrates the bug: reused-id edit vanishes');

  // The actual fix lives in src/names.js — verify it can never hand out a
  // name twice, which is what prevents this scenario in the app.
  const allocator = new NameAllocator();
  const seen = new Set();
  for (let i = 0; i < NAME_POOL.length + 15; i++) {
    const name = allocator.next();
    assert.equal(seen.has(name), false, `NameAllocator reused "${name}"`);
    seen.add(name);
  }
});

test('REGRESSION: concurrent inserts must not tear an astral character (emoji) apart', () => {
  const a = new Peer('A');
  const b = new Peer('B');

  for (const op of a.setText('hi 👍 there')) b.receive(op);
  assert.equal(a.text, b.text);

  const idx = a.text.indexOf('👍');
  const opsA = a.setText(a.text.slice(0, idx) + '🎉' + a.text.slice(idx));
  const opsB = b.setText(b.text.slice(0, idx) + 'Z' + b.text.slice(idx));
  for (const op of opsB) a.receive(op);
  for (const op of opsA) b.receive(op);

  assert.equal(a.text, b.text, 'must still converge');
  assert.equal(hasLoneSurrogate(a.text), false, 'emoji must not be torn into a lone surrogate');
  assert.equal(hasLoneSurrogate(b.text), false);
  assert.ok(a.text.includes('👍') && a.text.includes('🎉'), 'both emoji must render intact');
});

test('REGRESSION: RGA insert must skip an entire sibling subtree, not just the sibling node (3-way convergence)', () => {
  // The exact shape that exposed the bug: three sites each insert one
  // character concurrently at the document head, THEN each inserts a
  // second character as a child of their own first — so the tree has
  // three top-level siblings, each with one child. A correct RGA
  // linearizes this as a full pre-order traversal (parent, its child,
  // then next sibling by id); the buggy version, which only compared a
  // direct sibling instead of skipping that sibling's whole subtree,
  // produced a DIFFERENT order depending on delivery order.
  // three independent local histories (as if built by sites A, B, C)
  const opC = { type: 'insert', id: { site: 'A', seq: 0 }, char: 'c', origin: null };
  const opE = { type: 'insert', id: { site: 'A', seq: 1 }, char: 'e', origin: { site: 'A', seq: 0 } };
  const opZ = { type: 'insert', id: { site: 'B', seq: 0 }, char: 'z', origin: null };
  const opX = { type: 'insert', id: { site: 'B', seq: 1 }, char: 'x', origin: { site: 'B', seq: 0 } };
  const opU = { type: 'insert', id: { site: 'C', seq: 0 }, char: 'u', origin: null };
  const opS = { type: 'insert', id: { site: 'C', seq: 1 }, char: 's', origin: { site: 'C', seq: 0 } };

  const allOps = [opC, opE, opZ, opX, opU, opS];

  function applyInOrder(order) {
    const doc = new Doc('replica-' + order.join(''));
    for (const i of order) doc.applyOp(allOps[i]);
    return doc.getText();
  }

  // canonical result: children sorted by id descending at each level,
  // pre-order — u,s (C's subtree) then z,x (B's) then c,e (A's)
  const canonical = 'uszxce';

  // try several different delivery orders, including the one that
  // originally exposed the bug (a partial prefix delivered, then the rest
  // out of order — here approximated with distinct permutations)
  const orders = [
    [0, 1, 2, 3, 4, 5],
    [5, 4, 3, 2, 1, 0],
    [2, 3, 0, 1, 4, 5], // B's pair, then A's pair, then C's pair
    [4, 0, 2, 5, 1, 3], // interleaved — this permutation reproduced the bug
    [0, 2, 4, 1, 3, 5],
  ];
  for (const order of orders) {
    assert.equal(applyInOrder(order), canonical, `order ${JSON.stringify(order)} must match the canonical linearization`);
  }
});

function hasLoneSurrogate(s) {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const next = s.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return true;
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      const prev = s.charCodeAt(i - 1);
      if (!(prev >= 0xd800 && prev <= 0xdbff)) return true;
    }
  }
  return false;
}
