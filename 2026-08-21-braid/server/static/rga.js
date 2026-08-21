// A faithful JavaScript port of crdt/rga.py's integrate algorithm — the
// browser applies its own local edits optimistically and must therefore
// run the exact same CRDT logic as the Python server/verification code,
// not a simplified stand-in. Ids are [counter, peerId] pairs; comparison
// mirrors Python tuple comparison (counter first, then peerId string).
"use strict";

function idGreater(a, b) {
  if (a === null || b === null) throw new Error("idGreater: null id");
  if (a[0] !== b[0]) return a[0] > b[0];
  return a[1] > b[1];
}

function idEqual(a, b) {
  if (a === null && b === null) return true;
  if (a === null || b === null) return false;
  return a[0] === b[0] && a[1] === b[1];
}

function idKey(id) {
  return id === null ? "HEAD" : `${id[0]}:${id[1]}`;
}

class LamportClock {
  constructor(peerId) {
    this.peerId = peerId;
    this.counter = 0;
  }
  tick() {
    this.counter += 1;
    return this.counter;
  }
  observe(remoteCounter) {
    this.counter = Math.max(this.counter, remoteCounter);
    return this.counter;
  }
}

class RGA {
  constructor(peerId) {
    this.peerId = peerId;
    this.clock = new LamportClock(peerId);
    this.nodes = new Map(); // idKey -> {id, value, parent, tombstone, tombstoneOpId}
    this.order = []; // array of idKey, left-to-right
    this.pos = new Map(); // idKey -> index
    this.pendingTombstones = new Map(); // idKey -> [opId, value]
    this.opLog = [];
    this._logged = new Set();
  }

  localInsert(index, value) {
    const afterId = this._visibleIdBefore(index);
    const counter = this.clock.tick();
    const nodeId = [counter, this.peerId];
    const node = { id: nodeId, value, parent: afterId, tombstone: false };
    this._integrate(node);
    const op = {
      type: "insert",
      id: nodeId,
      parent: afterId,
      value,
      deps: afterId === null ? [] : [afterId],
    };
    this._log(op);
    return op;
  }

  localDelete(index) {
    const targetId = this._visibleIdAt(index);
    if (targetId === null) throw new RangeError("delete index out of range");
    return this.localDeleteById(targetId);
  }

  localDeleteById(targetId) {
    if (!this.nodes.has(idKey(targetId))) throw new Error("unknown node id");
    return this._localTombstoneOp(targetId, true);
  }

  localUndeleteById(targetId) {
    if (!this.nodes.has(idKey(targetId))) throw new Error("unknown node id");
    return this._localTombstoneOp(targetId, false);
  }

  _localTombstoneOp(targetId, value) {
    const opId = [this.clock.tick(), this.peerId];
    this._applyTombstone(targetId, opId, value);
    const op = { type: value ? "delete" : "undelete", id: targetId, op_id: opId, deps: [targetId] };
    this._log(op);
    return op;
  }

  _applyTombstone(targetId, opId, value) {
    const k = idKey(targetId);
    const node = this.nodes.get(k);
    if (!node) {
      const current = this.pendingTombstones.get(k);
      if (!current || idGreater(opId, current[0])) this.pendingTombstones.set(k, [opId, value]);
      return;
    }
    if (!node.tombstoneOpId || idGreater(opId, node.tombstoneOpId)) {
      node.tombstoneOpId = opId;
      node.tombstone = value;
    }
  }

  text() {
    let out = "";
    for (const k of this.order) {
      const n = this.nodes.get(k);
      if (!n.tombstone) out += n.value;
    }
    return out;
  }

  length() {
    let c = 0;
    for (const k of this.order) if (!this.nodes.get(k).tombstone) c++;
    return c;
  }

  hasId(nodeId) {
    return nodeId === null || this.nodes.has(idKey(nodeId));
  }

  applyRemote(op) {
    if (op.type === "insert") {
      const nodeId = op.id;
      this.clock.observe(nodeId[0]);
      if (this.nodes.has(idKey(nodeId))) return; // idempotent duplicate
      const node = { id: nodeId, value: op.value, parent: op.parent, tombstone: false, tombstoneOpId: null };
      this._integrate(node);
      this._log(op);
      const pending = this.pendingTombstones.get(idKey(nodeId));
      if (pending) {
        node.tombstoneOpId = pending[0];
        node.tombstone = pending[1];
        this.pendingTombstones.delete(idKey(nodeId));
      }
    } else if (op.type === "delete" || op.type === "undelete") {
      this.clock.observe(op.op_id[0]);
      this._applyTombstone(op.id, op.op_id, op.type === "delete");
      this._log(op);
    } else {
      throw new Error("unknown op type " + op.type);
    }
  }

  _log(op) {
    const key = "op_id" in op ? op.type + ":" + idKey(op.op_id) : op.type + ":" + idKey(op.id);
    if (this._logged.has(key)) return false;
    this._logged.add(key);
    this.opLog.push(op);
    return true;
  }

  _visibleIds() {
    const out = [];
    for (const k of this.order) {
      const n = this.nodes.get(k);
      if (!n.tombstone) out.push(n.id);
    }
    return out;
  }

  _visibleIdBefore(index) {
    const vis = this._visibleIds();
    if (index <= 0 || vis.length === 0) return null;
    return vis[Math.min(index, vis.length) - 1];
  }

  _visibleIdAt(index) {
    const vis = this._visibleIds();
    if (index >= 0 && index < vis.length) return vis[index];
    return null;
  }

  _idx(nodeId) {
    return nodeId === null ? -1 : this.pos.get(idKey(nodeId));
  }

  _subtreeEnd(rootIdx) {
    let j = rootIdx + 1;
    const n = this.order.length;
    while (j < n) {
      const parent = this.nodes.get(this.order[j]).parent;
      if (this._idx(parent) < rootIdx) break;
      j += 1;
    }
    return j;
  }

  _integrate(node) {
    const parentIdx = this._idx(node.parent);
    let i = parentIdx + 1;
    const n = this.order.length;
    while (i < n) {
      const other = this.nodes.get(this.order[i]);
      const otherParentIdx = this._idx(other.parent);
      if (otherParentIdx < parentIdx) break;
      if (otherParentIdx === parentIdx) {
        if (idGreater(other.id, node.id)) {
          i = this._subtreeEnd(i);
          continue;
        }
        break;
      }
      i += 1;
    }
    this.order.splice(i, 0, idKey(node.id));
    this.nodes.set(idKey(node.id), node);
    for (let j = i; j < this.order.length; j++) this.pos.set(this.order[j], j);
  }
}

class CausalDeliveryBuffer {
  constructor(hasIdFn) {
    this._has = hasIdFn;
    this._pending = [];
  }
  submit(op, applyFn) {
    this._pending.push(op);
    let progressed = true;
    let applied = 0;
    while (progressed) {
      progressed = false;
      const still = [];
      for (const pendingOp of this._pending) {
        const deps = pendingOp.deps || [];
        if (deps.every((d) => this._has(d))) {
          applyFn(pendingOp);
          applied += 1;
          progressed = true;
        } else {
          still.push(pendingOp);
        }
      }
      this._pending = still;
    }
    return applied;
  }
  get size() {
    return this._pending.length;
  }
}

// CRDT-aware undo/redo -- a faithful port of crdt/undo.py. "insert" and
// "undelete" are both make-visible actions (inverse hides); "delete" is
// the one make-hidden action (inverse shows). Every step is skipped as a
// no-op if the doc has already concurrently reached that state, rather
// than forcing it and clobbering someone else's concurrent edit.
class UndoManager {
  constructor(doc) {
    this.doc = doc;
    this._undoStack = [];
    this._redoStack = [];
  }

  recordLocalOp(op) {
    if (op.type === "insert") this._undoStack.push({ kind: "insert", target: op.id });
    else if (op.type === "delete" || op.type === "undelete") this._undoStack.push({ kind: op.type, target: op.id });
    else return;
    this._redoStack = [];
  }

  canUndo() {
    return this._undoStack.length > 0;
  }
  canRedo() {
    return this._redoStack.length > 0;
  }

  undo() {
    if (!this._undoStack.length) return null;
    const entry = this._undoStack.pop();
    const op = this._applyInverse(entry);
    this._redoStack.push(entry);
    return op;
  }

  redo() {
    if (!this._redoStack.length) return null;
    const entry = this._redoStack.pop();
    const op = this._applyForward(entry);
    this._undoStack.push(entry);
    return op;
  }

  _show(target) {
    const node = this.doc.nodes.get(idKey(target));
    if (!node || !node.tombstone) return null;
    return this.doc.localUndeleteById(target);
  }
  _hide(target) {
    const node = this.doc.nodes.get(idKey(target));
    if (!node || node.tombstone) return null;
    return this.doc.localDeleteById(target);
  }
  _applyInverse(entry) {
    const makesVisible = entry.kind === "insert" || entry.kind === "undelete";
    return makesVisible ? this._hide(entry.target) : this._show(entry.target);
  }
  _applyForward(entry) {
    const makesVisible = entry.kind === "insert" || entry.kind === "undelete";
    return makesVisible ? this._show(entry.target) : this._hide(entry.target);
  }
}

// exposed for both <script> global use and, if ever needed, module use
if (typeof module !== "undefined") {
  module.exports = { RGA, CausalDeliveryBuffer, UndoManager, idGreater, idEqual, idKey };
}
