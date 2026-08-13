// rga.js — a from-scratch Replicated Growable Array (RGA) CRDT.
//
// This is the entire conflict-free replication algorithm: no library, no
// framework. A Doc is one replica's view of a shared plain-text document.
// Every character ever inserted gets a globally unique id `{site, seq}`.
// Deletes never remove structure — they add a "vote" to a per-character
// vote set, which is what makes undo/redo of deletes and out-of-order
// delivery both safe (see peer.js for how undo uses this).
//
// Concurrent inserts made after the *same* anchor character are ordered
// deterministically by comparing ids (this is the classic RGA rule,
// Roh et al. 2011 / Attiya et al. 2016): every replica, regardless of the
// order operations physically arrive in, computes the exact same total
// order. That's the whole trick that makes this "conflict-free".

/** Compare two ids. Returns <0, 0, or >0. Higher id sorts EARLIER among
 * siblings inserted after the same anchor (see insertNode). */
export function compareId(a, b) {
  if (a.seq !== b.seq) return a.seq - b.seq;
  if (a.site < b.site) return -1;
  if (a.site > b.site) return 1;
  return 0;
}

export function idEq(a, b) {
  return a === b || (a !== null && b !== null && a.site === b.site && a.seq === b.seq);
}

export function idStr(id) {
  return id === null ? 'HEAD' : `${id.site}:${id.seq}`;
}

const HEAD = null; // virtual sentinel representing "start of document"

class Node {
  constructor(id, char, origin) {
    this.id = id;
    this.char = char;
    this.origin = origin; // id this was inserted after (or null = HEAD)
    this.next = null; // linked-list pointer maintained by the Doc
    this.deletedBy = new Set(); // set of vote-id strings; tombstone iff non-empty
  }
  get tombstone() {
    return this.deletedBy.size > 0;
  }
}

export class Doc {
  constructor(siteId) {
    this.siteId = siteId;
    this.counter = 0;
    this.head = new Node(HEAD, '', null); // dummy head sentinel, never visible
    this.idMap = new Map(); // idStr -> Node, includes head under 'HEAD'
    this.idMap.set('HEAD', this.head);
    // causal buffers: an op can't be applied yet because it depends on
    // structure that hasn't arrived at this replica. Buffer it, keyed by
    // the dependency it's waiting on, and re-check when that dependency
    // shows up.
    this.pendingByOrigin = new Map(); // idStr(origin) -> [insert ops]
    this.pendingByTarget = new Map(); // idStr(target) -> [addVote/removeVote ops waiting for target node]
    this.pendingByVote = new Map(); // `${target}:${vote}` -> [removeVote ops waiting for the vote to exist]
  }

  nextId() {
    return { site: this.siteId, seq: this.counter++ };
  }

  // ---- local edits: produce an op AND apply it locally, so the caller
  // can broadcast the returned op to the network. ----

  /** Insert `char` immediately after the node with id `afterId` (or HEAD). */
  localInsert(afterId, char) {
    const id = this.nextId();
    const op = { type: 'insert', id, char, origin: afterId };
    this._applyInsert(op);
    return op;
  }

  /** Delete the node with id `targetId`. Returns the op (carries a fresh
   * vote id, so undo later can retract exactly this vote). */
  localDelete(targetId) {
    const vote = this.nextId();
    const op = { type: 'addVote', target: targetId, vote };
    this._applyAddVote(op);
    return op;
  }

  /** Retract a previously-cast delete vote (used by undo of a delete). */
  localUndelete(targetId, voteId) {
    const op = { type: 'removeVote', target: targetId, vote: voteId };
    this._applyRemoveVote(op);
    return op;
  }

  // ---- convenience helpers keyed by *visible* character index, for the UI ----

  visibleNodes() {
    const out = [];
    for (let n = this.head.next; n; n = n.next) {
      if (!n.tombstone) out.push(n);
    }
    return out;
  }

  getText() {
    let s = '';
    for (let n = this.head.next; n; n = n.next) if (!n.tombstone) s += n.char;
    return s;
  }

  /** id of the visible character currently at `index`, or null (HEAD) if index===0. */
  idAtVisibleIndex(index) {
    if (index <= 0) return null;
    const vis = this.visibleNodes();
    return vis[index - 1].id;
  }

  /** Insert `char` so it becomes visible at position `index` (0-based). */
  localInsertAt(index, char) {
    return this.localInsert(this.idAtVisibleIndex(index), char);
  }

  /** Delete the visible character currently at position `index`. */
  localDeleteAt(index) {
    const vis = this.visibleNodes();
    const node = vis[index];
    return this.localDelete(node.id);
  }

  // ---- applying ops (local or remote) ----

  applyOp(op) {
    if (op.type === 'insert') this._applyInsert(op);
    else if (op.type === 'addVote') this._applyAddVote(op);
    else if (op.type === 'removeVote') this._applyRemoveVote(op);
    else throw new Error(`unknown op type: ${op.type}`);
  }

  _applyInsert(op) {
    const originKey = idStr(op.origin);
    const anchor = this.idMap.get(originKey);
    if (!anchor) {
      // causal dependency missing: buffer until the anchor arrives
      this._buffer(this.pendingByOrigin, originKey, op);
      return;
    }
    if (this.idMap.has(idStr(op.id))) return; // already applied (idempotent)

    const node = new Node(op.id, op.char, op.origin);
    // RGA insert rule: the sequence is always a valid pre-order traversal
    // of the "who was inserted after whom" tree — anchor's direct children
    // sorted by id descending, each one immediately followed by its own
    // (recursively ordered) subtree. To place `node` we walk forward from
    // the anchor comparing against each DIRECT sibling (same origin); a
    // sibling with a greater id keeps priority, so we step past it — but
    // we must then also step past that whole sibling's subtree (every
    // descendant of a node we've committed to skip), not just the sibling
    // itself, or a later direct sibling would get spliced in the middle of
    // someone else's subtree depending on delivery order. `skipped` tracks
    // exactly that: ids we've passed over, so we can recognize their
    // descendants and pass over those too.
    let prev = anchor;
    let curr = anchor.next;
    const skipped = new Set();
    while (curr) {
      if (idEq(curr.origin, op.origin)) {
        if (compareId(curr.id, op.id) > 0) {
          skipped.add(idStr(curr.id));
          prev = curr;
          curr = curr.next;
          continue;
        }
        break; // curr has lower priority: node belongs right before it
      }
      if (skipped.has(idStr(curr.origin))) {
        // curr is a descendant of a sibling we already skipped — still part
        // of that subtree, keep going
        skipped.add(idStr(curr.id));
        prev = curr;
        curr = curr.next;
        continue;
      }
      break; // walked past the anchor's entire run of children
    }
    node.next = curr;
    prev.next = node;
    this.idMap.set(idStr(op.id), node);

    this._resolvePending(op.id);
  }

  _applyAddVote(op) {
    const key = idStr(op.target);
    const node = this.idMap.get(key);
    if (!node) {
      this._buffer(this.pendingByTarget, key, op);
      return;
    }
    node.deletedBy.add(idStr(op.vote));
    this._resolvePendingVotes(op.target, op.vote);
  }

  _applyRemoveVote(op) {
    const key = idStr(op.target);
    const node = this.idMap.get(key);
    if (!node) {
      this._buffer(this.pendingByTarget, key, op);
      return;
    }
    const voteKey = idStr(op.vote);
    if (!node.deletedBy.has(voteKey)) {
      // the vote we're retracting hasn't arrived yet (reordering) — wait for it
      this._buffer(this.pendingByVote, `${key}:${voteKey}`, op);
      return;
    }
    node.deletedBy.delete(voteKey);
  }

  _buffer(map, key, op) {
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(op);
  }

  /** Called after a node with `id` becomes known — replay anything waiting on it. */
  _resolvePending(id) {
    const key = idStr(id);
    const waitingInserts = this.pendingByOrigin.get(key);
    if (waitingInserts) {
      this.pendingByOrigin.delete(key);
      for (const op of waitingInserts) this._applyInsert(op);
    }
    const waitingVotes = this.pendingByTarget.get(key);
    if (waitingVotes) {
      this.pendingByTarget.delete(key);
      for (const op of waitingVotes) this.applyOp(op);
    }
  }

  /** Called after a vote is added to a node — replay any removeVote waiting on it. */
  _resolvePendingVotes(target, vote) {
    const k = `${idStr(target)}:${idStr(vote)}`;
    const waiting = this.pendingByVote.get(k);
    if (waiting) {
      this.pendingByVote.delete(k);
      for (const op of waiting) this._applyRemoveVote(op);
    }
  }

  /** True if there are no ops still waiting on a causal dependency. */
  isFullyDelivered() {
    return this.pendingByOrigin.size === 0 && this.pendingByTarget.size === 0 && this.pendingByVote.size === 0;
  }
}
