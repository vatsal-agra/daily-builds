// rga.js — a hand-ported, 1:1 mirror of crdt/rga.py's RGADocument.
//
// This is NOT a thin client that trusts the server: every browser tab
// running this file is a full, independent CRDT replica. It applies its
// own edits instantly (no round trip), and merges remote ops using the
// exact same deterministic placement rule as the Python engine — parity
// between the two is checked by tests/test_parity.py, which feeds the
// same op stream through both and asserts identical output.
//
// See crdt/rga.py for the algorithm's rationale; comments here focus on
// JS-specific translation notes.

function idOf(x) {
  if (x === null || x === undefined) return null;
  return [x[0], x[1]];
}

function idKey(id) {
  // ids are [counter, siteId]; used as Map keys, which need a primitive.
  return id === null ? "root" : `${id[0]}:${id[1]}`;
}

function idGreater(a, b) {
  if (a[0] !== b[0]) return a[0] > b[0];
  return a[1] > b[1]; // string comparison, same as Python's tuple compare
}

class RGADocument {
  constructor(siteId) {
    this.siteId = siteId;
    this.counter = 0;
    this.sequence = [];      // ordered array of node objects, tombstones included
    this.byId = new Map();   // idKey -> node
    this.index = new Map();  // idKey -> current index in `sequence`
  }

  // `counter` is a Lamport clock, not a plain per-site increment — see
  // applyRemoteOp and _integrate's comments for why that distinction is
  // load-bearing (it's what makes the tie-break correctly favor a
  // causally-later, non-concurrent insert over one it already knew about).
  _nextId() {
    this.counter += 1;
    return [this.counter, this.siteId];
  }

  _reindexFrom(start) {
    for (let i = start; i < this.sequence.length; i++) {
      this.index.set(idKey(this.sequence[i].id), i);
    }
  }

  // "higher id wins, stays closer to origin" — correct only because ids
  // are Lamport-clock-ordered (see _nextId / applyRemoteOp), not raw
  // per-site counters; see rga.py's _integrate docstring for the bug
  // that would otherwise cause (a non-concurrent insert losing a tie to
  // an *older* node purely because the other site had typed more first).
  _integrate(node) {
    const origin = node.origin;
    const leftIdx = origin !== null ? this.index.get(idKey(origin)) : -1;
    let i = leftIdx + 1;
    const n = this.sequence.length;
    while (i < n) {
      const other = this.sequence[i];
      const otherOrigin = other.origin;
      const otherOriginIdx = otherOrigin !== null ? this.index.get(idKey(otherOrigin)) : -1;
      if (otherOriginIdx < leftIdx) break;
      if (otherOriginIdx === leftIdx) {
        if (idGreater(other.id, node.id)) {
          i += 1;
          continue;
        }
        break;
      }
      i += 1;
    }
    this.sequence.splice(i, 0, node);
    this.byId.set(idKey(node.id), node);
    this._reindexFrom(i);
  }

  _originForVisibleIndex(index) {
    if (index === 0) return null;
    let count = 0;
    for (const node of this.sequence) {
      if (!node.deleted) {
        count += 1;
        if (count === index) return node.id;
      }
    }
    throw new RangeError(`insert index ${index} out of range (doc length ${this.visibleLength()})`);
  }

  _visibleNodeAt(index) {
    let count = -1;
    for (const node of this.sequence) {
      if (!node.deleted) {
        count += 1;
        if (count === index) return node;
      }
    }
    throw new RangeError(`delete index ${index} out of range (doc length ${this.visibleLength()})`);
  }

  localInsert(index, value) {
    // Count by Unicode CODE POINT, not UTF-16 code unit: most emoji (and
    // everything outside the Basic Multilingual Plane) are two UTF-16
    // units (a surrogate pair) but ONE character. `value.length` counts
    // units — [...value].length counts code points, matching how Python
    // (this engine's other half) already indexes strings, and matching
    // how one CRDT node is meant to represent one character.
    if ([...value].length !== 1) throw new Error("localInsert takes exactly one character");
    const origin = this._originForVisibleIndex(index);
    const nodeId = this._nextId();
    const node = { id: nodeId, origin, value, deleted: false };
    this._integrate(node);
    return { type: "insert", id: nodeId, origin: origin, value };
  }

  localDelete(index) {
    const node = this._visibleNodeAt(index);
    node.deleted = true;
    const opId = this._nextId();
    return { type: "delete", id: opId, target: node.id };
  }

  // delete/restore ops get their OWN fresh id (not the target node's id):
  // the same node can be deleted, undone (restored), and deleted again
  // over its lifetime, and each of those needs to be a distinguishable
  // op — see rga.py's local_delete docstring for the bug this avoids.
  deleteById(nodeId) {
    const node = this.byId.get(idKey(nodeId));
    node.deleted = true;
    const opId = this._nextId();
    return { type: "delete", id: opId, target: node.id };
  }

  restoreById(nodeId) {
    const node = this.byId.get(idKey(nodeId));
    node.deleted = false;
    const opId = this._nextId();
    return { type: "restore", id: opId, target: node.id };
  }

  applyRemoteOp(op) {
    // Lamport clock bump: observing any op (even one we can't integrate
    // yet because its dependency hasn't arrived) advances our clock to
    // at least its counter, so the next id we allocate outranks it.
    const seenCounter = op.id[0];
    if (seenCounter > this.counter) this.counter = seenCounter;
    if (op.type === "insert") {
      const nodeId = idOf(op.id);
      if (this.byId.has(idKey(nodeId))) return true; // duplicate delivery
      const origin = idOf(op.origin);
      if (origin !== null && !this.byId.has(idKey(origin))) return false; // dependency not met
      const node = { id: nodeId, origin, value: op.value, deleted: false };
      this._integrate(node);
      return true;
    } else if (op.type === "delete") {
      const target = idOf(op.target);
      const node = this.byId.get(idKey(target));
      if (!node) return false;
      node.deleted = true;
      return true;
    } else if (op.type === "restore") {
      const target = idOf(op.target);
      const node = this.byId.get(idKey(target));
      if (!node) return false;
      node.deleted = false;
      return true;
    }
    throw new Error(`unknown op type: ${op.type}`);
  }

  toString() {
    return this.sequence.filter((n) => !n.deleted).map((n) => n.value).join("");
  }

  visibleLength() {
    let c = 0;
    for (const n of this.sequence) if (!n.deleted) c += 1;
    return c;
  }

  // Number of visible *characters* (CRDT nodes — one per code point)
  // strictly before the node with this id. Used for indexing into the
  // CRDT itself (typeText/typeDeleteRange take a node index).
  visibleIndexOfId(id) {
    const key = idKey(id);
    let count = 0;
    for (const node of this.sequence) {
      if (idKey(node.id) === key) return count;
      if (!node.deleted) count += 1;
    }
    return -1;
  }

  // Same idea, but counting UTF-16 *code units* instead of nodes — what
  // `textarea.selectionStart` actually measures in. A node's `value` is
  // one code point but can be 1 or 2 UTF-16 units (most emoji are 2), so
  // this is NOT the same number as visibleIndexOfId once any astral
  // character precedes the target — app.js's cursor math needs this one.
  utf16IndexOfId(id) {
    const key = idKey(id);
    let count = 0;
    for (const node of this.sequence) {
      if (idKey(node.id) === key) return count;
      if (!node.deleted) count += node.value.length;
    }
    return -1;
  }

  // UTF-16 unit width (1 or 2) of a node's character — nodes persist as
  // tombstones, so this is available even for a just-deleted id.
  charUnitLength(id) {
    const node = this.byId.get(idKey(id));
    return node ? node.value.length : 1;
  }
}

// ---- Site: causal buffering + op log + undo/redo (mirrors crdt/site.py) --

class Site {
  constructor(siteId) {
    this.siteId = siteId;
    this.doc = new RGADocument(siteId);
    this.pending = [];
    this.opLog = [];
    this.appliedKeys = new Set();
    this.undoStack = [];
    this.redoStack = [];
  }

  static opKey(op) {
    return `${op.type}:${idKey(op.id)}`;
  }

  _recordLocal(op) {
    this.appliedKeys.add(Site.opKey(op));
    this.opLog.push(op);
  }

  typeInsert(index, value) {
    const op = this.doc.localInsert(index, value);
    this._recordLocal(op);
    this.undoStack.push({ kind: "insert", nodeIds: [op.id] });
    this.redoStack = [];
    return op;
  }

  typeDelete(index) {
    const op = this.doc.localDelete(index);
    this._recordLocal(op);
    // op.id is the delete op's own fresh identity, not the node it acts
    // on — the undo stack needs the *target* node id.
    this.undoStack.push({ kind: "delete", nodeIds: [op.target] });
    this.redoStack = [];
    return op;
  }

  // Insert a multi-character string (typing fast, or pasting) as a single
  // grouped undo action — one undo removes the whole run.
  typeText(index, text) {
    const ops = [];
    const nodeIds = [];
    const chars = [...text]; // code-point iteration — keeps surrogate pairs (most emoji) intact as one character
    for (let i = 0; i < chars.length; i++) {
      const op = this.doc.localInsert(index + i, chars[i]);
      this._recordLocal(op);
      ops.push(op);
      nodeIds.push(op.id);
    }
    if (nodeIds.length > 0) {
      this.undoStack.push({ kind: "insert", nodeIds });
      this.redoStack = [];
    }
    return ops;
  }

  // Delete `count` characters starting at `index`, grouped as one undo
  // action. Each deletion targets the same visible index since deleting
  // shifts the rest of the text left.
  typeDeleteRange(index, count) {
    const ops = [];
    const nodeIds = [];
    for (let i = 0; i < count; i++) {
      const op = this.doc.localDelete(index);
      this._recordLocal(op);
      ops.push(op);
      nodeIds.push(op.target);
    }
    if (nodeIds.length > 0) {
      this.undoStack.push({ kind: "delete", nodeIds });
      this.redoStack = [];
    }
    return ops;
  }

  undo() {
    if (this.undoStack.length === 0) return null;
    const entry = this.undoStack.pop();
    const compensate = entry.kind === "insert" ? (id) => this.doc.deleteById(id) : (id) => this.doc.restoreById(id);
    const ops = entry.nodeIds.map(compensate);
    ops.forEach((op) => this._recordLocal(op));
    this.redoStack.push(entry);
    return ops;
  }

  redo() {
    if (this.redoStack.length === 0) return null;
    const entry = this.redoStack.pop();
    const compensate = entry.kind === "insert" ? (id) => this.doc.restoreById(id) : (id) => this.doc.deleteById(id);
    const ops = entry.nodeIds.map(compensate);
    ops.forEach((op) => this._recordLocal(op));
    this.undoStack.push(entry);
    return ops;
  }

  canUndo() { return this.undoStack.length > 0; }
  canRedo() { return this.redoStack.length > 0; }

  receive(op) {
    if (this._tryApply(op)) this._drainPending();
    else this.buffer(op);
  }

  _tryApply(op) {
    const key = Site.opKey(op);
    if (this.appliedKeys.has(key)) return true;
    if (!this.doc.applyRemoteOp(op)) return false;
    this.appliedKeys.add(key);
    this.opLog.push(op);
    return true;
  }

  _drainPending() {
    if (this.pending.length === 0) return;
    let progressed = true;
    while (progressed && this.pending.length > 0) {
      progressed = false;
      const stillPending = [];
      for (const op of this.pending) {
        if (this._tryApply(op)) progressed = true;
        else stillPending.push(op);
      }
      this.pending = stillPending;
    }
  }

  buffer(op) {
    if (this.appliedKeys.has(Site.opKey(op))) return;
    this.pending.push(op);
  }

  text() { return this.doc.toString(); }
  isSettled() { return this.pending.length === 0; }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { RGADocument, Site, idGreater, idKey };
}
if (typeof window !== "undefined") {
  window.BraidRGA = { RGADocument, Site, idGreater, idKey };
}
