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
    this.nodes = new Map(); // idKey -> {id, value, parent, tombstone}
    this.order = []; // array of idKey, left-to-right
    this.pos = new Map(); // idKey -> index
    this.pendingDeletes = new Set();
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
    this.nodes.get(idKey(targetId)).tombstone = true;
    const op = { type: "delete", id: targetId, deps: [targetId] };
    this._log(op);
    return op;
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
      const node = { id: nodeId, value: op.value, parent: op.parent, tombstone: false };
      this._integrate(node);
      this._log(op);
      if (this.pendingDeletes.has(idKey(nodeId))) {
        node.tombstone = true;
        this.pendingDeletes.delete(idKey(nodeId));
      }
    } else if (op.type === "delete") {
      const k = idKey(op.id);
      const existing = this.nodes.get(k);
      if (existing) {
        existing.tombstone = true;
        this._log(op);
      } else {
        this.pendingDeletes.add(k);
        this._log(op);
      }
    } else {
      throw new Error("unknown op type " + op.type);
    }
  }

  _log(op) {
    const key = op.type + ":" + idKey(op.id);
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

// exposed for both <script> global use and, if ever needed, module use
if (typeof module !== "undefined") {
  module.exports = { RGA, CausalDeliveryBuffer, idGreater, idEqual, idKey };
}
