// Unit tests for the RGA CRDT primitives themselves: local edits, remote
// application, causal buffering of out-of-order ops, and undo/redo.

import test from 'node:test';
import assert from 'node:assert/strict';
import { Doc } from '../src/rga.js';

test('local insert builds text left to right', () => {
  const doc = new Doc('A');
  doc.localInsertAt(0, 'h');
  doc.localInsertAt(1, 'i');
  assert.equal(doc.getText(), 'hi');
});

test('local delete removes the right character', () => {
  const doc = new Doc('A');
  for (const ch of 'hello') doc.localInsertAt(doc.getText().length, ch);
  doc.localDeleteAt(0); // remove 'h'
  assert.equal(doc.getText(), 'ello');
  doc.localDeleteAt(3); // remove trailing 'o'
  assert.equal(doc.getText(), 'ell');
});

test('two replicas converge on identical concurrent inserts at the same anchor', () => {
  const a = new Doc('A');
  const b = new Doc('B');
  // both start from "hi", identical history
  for (const ch of 'hi') {
    const op = a.localInsertAt(a.getText().length, ch);
    b.applyOp(op);
  }
  assert.equal(a.getText(), b.getText());

  // now A and B concurrently insert right after the 'i' (index 2)
  const opA = a.localInsertAt(2, 'X');
  const opB = b.localInsertAt(2, 'Y');

  // deliver in OPPOSITE orders to each replica
  b.applyOp(opA); // B applies A's op after its own
  a.applyOp(opB); // A applies B's op after its own

  assert.equal(a.getText(), b.getText(), 'replicas must converge regardless of delivery order');
  assert.equal(a.getText().length, 4);
});

test('remote insert arriving before its causal parent is buffered, not lost', () => {
  const a = new Doc('A');
  const opBase = a.localInsertAt(0, 'x'); // id for 'x'
  const opChild = a.localInsertAt(1, 'y'); // inserted after 'x'

  const b = new Doc('B');
  // deliver OUT OF ORDER: child before its parent
  b.applyOp(opChild);
  assert.equal(b.getText(), '', 'child insert must not be visible before its anchor arrives');
  assert.equal(b.isFullyDelivered(), false);

  b.applyOp(opBase);
  assert.equal(b.getText(), 'xy', 'once the anchor arrives, the buffered child must apply');
  assert.equal(b.isFullyDelivered(), true);
});

test('remote delete arriving before the node it targets is buffered', () => {
  const a = new Doc('A');
  const opIns = a.localInsertAt(0, 'z');
  const opDel = a.localDelete(opIns.id);

  const b = new Doc('B');
  b.applyOp(opDel); // delete arrives first
  assert.equal(b.getText(), '');
  b.applyOp(opIns); // then the insert
  assert.equal(b.getText(), '', 'the character must arrive already-deleted, never flash visible');
});

test('applying the same op twice is a no-op (idempotent)', () => {
  const a = new Doc('A');
  const op = a.localInsertAt(0, 'q');
  const b = new Doc('B');
  b.applyOp(op);
  b.applyOp(op);
  b.applyOp(op);
  assert.equal(b.getText(), 'q');
});

test('undo of a local insert removes exactly that character', () => {
  const doc = new Doc('A');
  const op1 = doc.localInsertAt(0, 'a');
  doc.localInsertAt(1, 'b');
  assert.equal(doc.getText(), 'ab');
  doc.localDelete(op1.id); // simulate undo directly on the doc
  assert.equal(doc.getText(), 'b');
});

test('un-deleting (removeVote) brings a character back', () => {
  const doc = new Doc('A');
  const op = doc.localInsertAt(0, 'z');
  const del = doc.localDelete(op.id);
  assert.equal(doc.getText(), '');
  doc.localUndelete(del.target, del.vote);
  assert.equal(doc.getText(), 'z');
});

test('a character deleted by two independent votes needs both retracted to reappear', () => {
  const a = new Doc('A');
  const opIns = a.localInsertAt(0, 'w');
  const b = new Doc('B');
  b.applyOp(opIns);

  const delA = a.localDelete(opIns.id);
  const delB = b.localDelete(opIns.id);
  a.applyOp(delB);
  b.applyOp(delA);
  assert.equal(a.getText(), '');
  assert.equal(b.getText(), '');

  // retract only A's vote on both replicas — still deleted, B's vote stands
  const undoA = { type: 'removeVote', target: delA.target, vote: delA.vote };
  a.applyOp(undoA);
  b.applyOp(undoA);
  assert.equal(a.getText(), '', 'still deleted: a second vote is still active');
  assert.equal(b.getText(), '');

  const undoB = { type: 'removeVote', target: delB.target, vote: delB.vote };
  a.applyOp(undoB);
  b.applyOp(undoB);
  assert.equal(a.getText(), 'w', 'both votes retracted: character is visible again');
  assert.equal(b.getText(), 'w');
});
