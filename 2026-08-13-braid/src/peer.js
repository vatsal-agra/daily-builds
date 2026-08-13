// peer.js — wraps one RGA replica with the bookkeeping needed to act as a
// "user" in the simulation: turning whole-text edits (what a <textarea>
// gives you) into a sequence of CRDT ops, receiving remote ops, and
// causal undo/redo of this peer's own edits.

import { Doc, idStr } from './rga.js';

export class Peer {
  constructor(siteId) {
    this.siteId = siteId;
    this.doc = new Doc(siteId);
    this.lastText = '';
    // undoStack entries: {type:'insert', id} | {type:'delete', target, vote}
    this.undoStack = [];
    // redoStack entries: {type:'undo-insert', target, vote} | {type:'undo-delete', target, vote}
    this.redoStack = [];
    // every op this peer has ever ORIGINATED locally (not ops relayed in
    // from elsewhere). This is the peer's own anti-entropy log: a real
    // network can genuinely drop a packet, so periodically re-announcing
    // "here is everything I've ever created" (see resyncOps()) is what
    // lets a delivered-but-lost edit still get through eventually, without
    // requiring the transport to be reliable. Applying an already-known op
    // again is a no-op (see Doc._applyInsert's idempotency check), so this
    // is always safe to call.
    this.myOps = [];
  }

  get text() {
    return this.doc.getText();
  }

  /** Diff `newText` against the last known text and turn the difference
   * into a sequence of local CRDT ops (handles typing, backspace, paste,
   * and multi-character selection replace — not just single keystrokes).
   * Returns the ops to broadcast to the network. Also records each op on
   * the undo stack and clears the redo stack (as any real editor would). */
  setText(newText) {
    const oldText = this.lastText;
    if (newText === oldText) return [];

    // Diff by Unicode CODE POINT, not by raw UTF-16 index. Every CRDT node
    // is meant to be one atomic character; splitting on code units would
    // let an astral character (most emoji — two UTF-16 units, one code
    // point) get diffed as two independent "characters" that could then
    // be reordered relative to each other by a concurrent remote op,
    // tearing it into two lone, unrenderable surrogate halves. Iterating
    // the string (its default iterator, and what Array.from uses) walks
    // by code point, so a surrogate pair is always one indivisible entry.
    const oldChars = Array.from(oldText);
    const newChars = Array.from(newText);

    // common prefix / suffix, so we only touch what actually changed
    let start = 0;
    const maxStart = Math.min(oldChars.length, newChars.length);
    while (start < maxStart && oldChars[start] === newChars[start]) start++;

    let endOld = oldChars.length;
    let endNew = newChars.length;
    while (endOld > start && endNew > start && oldChars[endOld - 1] === newChars[endNew - 1]) {
      endOld--;
      endNew--;
    }

    const removed = oldChars.slice(start, endOld);
    const inserted = newChars.slice(start, endNew);

    const ops = [];

    // delete removed characters, from the end so indices stay valid
    for (let i = 0; i < removed.length; i++) {
      const op = this.doc.localDeleteAt(start); // same index each time: they shift left as we delete
      ops.push(op);
      this.myOps.push(op);
      this.undoStack.push({ type: 'delete', target: op.target, vote: op.vote });
    }

    // insert new characters, one at a time so ids/origins chain correctly
    for (let i = 0; i < inserted.length; i++) {
      const op = this.doc.localInsertAt(start + i, inserted[i]);
      ops.push(op);
      this.myOps.push(op);
      this.undoStack.push({ type: 'insert', id: op.id });
    }

    if (ops.length) this.redoStack = [];
    this.lastText = this.doc.getText();
    return ops;
  }

  /** Apply a remote op received from the network. */
  receive(op) {
    this.doc.applyOp(op);
    this.lastText = this.doc.getText();
  }

  canUndo() {
    return this.undoStack.length > 0;
  }
  canRedo() {
    return this.redoStack.length > 0;
  }

  /** Undo this peer's own most recent not-yet-undone edit. Returns the op
   * to broadcast (or null if nothing to undo). Correct even if other
   * peers have edited around the text since — it only ever affects the
   * exact character(s) this peer itself touched. */
  undo() {
    const entry = this.undoStack.pop();
    if (!entry) return null;
    let op;
    if (entry.type === 'insert') {
      // undo an insert = delete that exact character
      op = this.doc.localDelete(entry.id);
      this.redoStack.push({ type: 'undo-insert', target: op.target, vote: op.vote });
    } else {
      // undo a delete = retract that exact delete vote
      op = this.doc.localUndelete(entry.target, entry.vote);
      this.redoStack.push({ type: 'undo-delete', target: entry.target });
    }
    this.myOps.push(op);
    this.lastText = this.doc.getText();
    return op;
  }

  redo() {
    const entry = this.redoStack.pop();
    if (!entry) return null;
    let op;
    if (entry.type === 'undo-insert') {
      // redo = retract the delete vote the undo added, bringing the char back
      op = this.doc.localUndelete(entry.target, entry.vote);
      this.undoStack.push({ type: 'insert', id: entry.target });
    } else {
      // redo = re-delete it with a fresh vote
      op = this.doc.localDelete(entry.target);
      this.undoStack.push({ type: 'delete', target: op.target, vote: op.vote });
    }
    this.myOps.push(op);
    this.lastText = this.doc.getText();
    return op;
  }

  /** Everything this peer has ever originated, for anti-entropy resync
   * over an unreliable transport. Safe to re-broadcast at any time. */
  resyncOps() {
    return this.myOps;
  }
}

export { idStr };
