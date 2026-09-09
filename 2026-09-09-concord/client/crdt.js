/**
 * crdt.js — Concord's RGA (Replicated Growable Array) sequence CRDT.
 *
 * This is the ONE file where the actual conflict-free-replication logic
 * lives. Everything else (the relay server, net.js, app.js) is plumbing
 * around it. It is written as plain CommonJS-compatible JS with no
 * dependencies so it can be `<script src="crdt.js">`'d unmodified in a
 * browser AND `require()`'d unmodified in Node for the property-fuzz test
 * harness in tests/ — one file, one behavior, no reimplementation to drift.
 *
 * Algorithm: RGA (Roh, Jeong, Kim & Lee, "Replicated abstract data types:
 * Building blocks for collaborative applications", JPDC 2011).
 *
 *   - Every character ever inserted gets a globally unique id
 *     `[lamportCounter, siteId]`, generated once by whichever site typed it
 *     and never reused, never mutated.
 *   - An insert is always relative: "insert this new node immediately after
 *     the node with id `leftId`" (or at the very start if `leftId` is null).
 *   - Two sites can concurrently insert after the *same* left neighbor
 *     (e.g. two people type at the same cursor position at the same
 *     instant). RGA resolves this deterministically: among all nodes that
 *     share a left neighbor, the one with the higher id sorts first. Every
 *     replica that eventually sees both inserts computes the exact same
 *     ordering, regardless of which one it received first — that's the
 *     "conflict-free" guarantee.
 *   - Delete never removes a node from the list — it tombstones it
 *     (`deleted = true`). This means a delete can never race an insert
 *     into corrupting the list structure (the insert's `leftId` reference
 *     stays valid forever, even if the referenced node is later deleted),
 *     at the cost of tombstones accumulating in the sequence. That's the
 *     standard RGA trade-off and is exactly why `crdt-internals` inspector
 *     (app.js) is worth having: the tombstones are real and visible.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.Concord = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** Total order on ids: higher lamport counter wins; ties broken by siteId
   *  string compare. Returns <0, 0, >0 like a normal comparator. Never
   *  returns 0 for two distinct real ids because (counter, siteId) is
   *  always unique per site (each site's counter is strictly increasing
   *  and siteIds are unique per replica). */
  function compareId(a, b) {
    if (a[0] !== b[0]) return a[0] - b[0];
    if (a[1] < b[1]) return -1;
    if (a[1] > b[1]) return 1;
    return 0;
  }

  function idKey(id) {
    return id === null ? 'ROOT' : id[0] + ':' + id[1];
  }

  function idsEqual(a, b) {
    if (a === null || b === null) return a === b;
    return a[0] === b[0] && a[1] === b[1];
  }

  /** Thrown internally when integrating a remote op whose reference isn't
   *  present yet. Callers (applyRemote) catch this and buffer the op —
   *  it is never allowed to escape to library-external callers. */
  function MissingDependency(key) {
    this.key = key;
  }

  function RGA(siteId) {
    if (!siteId) throw new Error('RGA requires a non-empty siteId');
    this.siteId = siteId;
    this.counter = 0;
    this.seq = []; // ordered array of nodes, INCLUDING tombstones
    this.byId = new Map(); // idKey -> node
    this.posById = new Map(); // idKey -> current index in this.seq (kept in
    // sync on every structural change so integration scans are O(1)-lookup
    // per step instead of re-scanning the array to find an index)
    // dependency key -> array of buffered ops waiting on that key to exist
    this.pending = new Map();
  }

  RGA.prototype.nextId = function () {
    this.counter += 1;
    return [this.counter, this.siteId];
  };

  /** Observing a remote id must keep our own counter strictly ahead of
   *  everything we've seen, so ids we generate next never collide with
   *  (nor sort ambiguously against) ids from any other site — a real
   *  Lamport-clock rule, not just cosmetic. */
  RGA.prototype._observe = function (id) {
    if (id[0] > this.counter) this.counter = id[0];
  };

  /** Rebuild the id->index cache from scratch. Called after every
   *  structural insert (O(n), same order as the array splice itself, so
   *  this doesn't change the asymptotics — it just turns the O(n) *lookups*
   *  inside _integrateInsert's scan into O(1) instead of an O(n) indexOf
   *  each, which would make a single insert O(n^2)). */
  RGA.prototype._reindex = function () {
    this.posById.clear();
    for (var i = 0; i < this.seq.length; i++) {
      this.posById.set(idKey(this.seq[i].id), i);
    }
  };

  RGA.prototype._indexOfId = function (id) {
    if (id === null) return -1;
    var idx = this.posById.get(idKey(id));
    return idx === undefined ? -1 : idx;
  };

  /** Core RGA insertion procedure. `node` = {id, value, leftId, deleted}.
   *  Throws MissingDependency if leftId is non-null and not yet known
   *  locally — callers integrating *local* edits never hit this (they only
   *  ever reference nodes they already have); callers integrating *remote*
   *  ops must catch it and buffer.
   *
   *  The scan below is the one part of this file that's easy to get subtly
   *  wrong (an earlier version of it shipped with exactly this bug, caught
   *  by hand before the fuzz harness even existed — see REVIEW.md): it is
   *  NOT enough to compare `other.leftId` against `node.leftId` for exact
   *  equality and stop at the first mismatch. A node further along the
   *  array can have a *different* leftId that still belongs entirely
   *  "inside" the span we're scanning past — e.g. a third character typed
   *  right after a second character that itself was our sibling. The
   *  correct rule compares *positions*, not raw id equality: keep
   *  advancing past `other` as long as `other`'s own left-neighbor sits at
   *  or after our insertion point (that makes `other` — and everything
   *  chained after it — a "descendant" of a node we're scanning past, so
   *  it stays exactly where it is relative to us); stop the instant we hit
   *  a node whose left-neighbor sits strictly *before* our insertion
   *  point, because that means we've walked past the entire run that was
   *  ever contesting this position. */
  RGA.prototype._integrateInsert = function (node, skipReindex) {
    var startIndex;
    if (node.leftId === null) {
      startIndex = 0;
    } else {
      if (!this.byId.has(idKey(node.leftId))) {
        throw new MissingDependency(idKey(node.leftId));
      }
      startIndex = this._indexOfId(node.leftId) + 1;
    }
    var i = startIndex;
    while (i < this.seq.length) {
      var other = this.seq[i];
      var otherOriginIdx = this._indexOfId(other.leftId);
      var leftIdx = startIndex - 1; // index of our own left-neighbor, or -1
      if (otherOriginIdx > leftIdx) {
        // `other` is chained off something strictly after our own
        // reference point (a descendant of a winning sibling, or a
        // descendant of THAT node, transitively) — skip straight past it.
        i += 1;
        continue;
      }
      if (otherOriginIdx === leftIdx) {
        // `other` is a direct concurrent sibling: also inserted
        // immediately after our exact left neighbor. Higher id wins the
        // position closer to the left neighbor — an arbitrary but total,
        // universally-agreed tie-break every replica computes identically.
        if (compareId(other.id, node.id) > 0) {
          i += 1;
          continue;
        }
        break;
      }
      // otherOriginIdx < leftIdx: we've walked past the entire contested
      // run for this insertion point. Insert here.
      break;
    }
    this.seq.splice(i, 0, node);
    this.byId.set(idKey(node.id), node);
    // `skipReindex` lets a caller that's about to do several splices in a
    // row (localInsert's same-run fast path, below) defer the O(n)
    // posById rebuild to a single pass at the end instead of paying for
    // it after every single character — see localInsert's comment for why
    // that's still correct.
    if (!skipReindex) this._reindex();
    return i;
  };

  /** Re-attempt every op that was buffered waiting on `key` to exist,
   *  now that it does. Recursive by construction: applyRemote calls this
   *  again for each op it successfully integrates, so a whole chain of
   *  causally-dependent ops that arrived out of order unwinds correctly
   *  once its root dependency shows up. */
  RGA.prototype._resolvePending = function (key) {
    var waiting = this.pending.get(key);
    if (!waiting) return;
    this.pending.delete(key);
    for (var i = 0; i < waiting.length; i++) {
      this.applyRemote(waiting[i]);
    }
  };

  RGA.prototype._buffer = function (key, op) {
    var list = this.pending.get(key);
    if (!list) {
      list = [];
      this.pending.set(key, list);
    }
    list.push(op);
  };

  /** Apply an op received from another site (or replayed from the relay's
   *  log on reconnect). Idempotent: applying the same insert op twice, or
   *  deleting an already-deleted node, is a safe no-op — required for a
   *  broadcast relay that may redeliver, and exercised directly by
   *  tests/fuzz_convergence.js. */
  RGA.prototype.applyRemote = function (op) {
    if (op.type === 'insert') {
      this._observe(op.id);
      var key = idKey(op.id);
      if (this.byId.has(key)) return { applied: false, reason: 'duplicate' };
      if (op.leftId !== null && !this.byId.has(idKey(op.leftId))) {
        this._buffer(idKey(op.leftId), op);
        return { applied: false, reason: 'buffered' };
      }
      this._integrateInsert({
        id: op.id,
        value: op.value,
        leftId: op.leftId,
        deleted: false,
      });
      this._resolvePending(key);
      // Computed AFTER integration (the node is visible at this point) so
      // callers (app.js) can shift a local caret/cursor without having to
      // reach into engine internals themselves.
      return { applied: true, kind: 'insert', visibleIndex: this.visibleIndexOf(op.id) };
    }
    if (op.type === 'delete') {
      this._observe(op.id);
      var node = this.byId.get(idKey(op.id));
      if (!node) {
        this._buffer(idKey(op.id), op);
        return { applied: false, reason: 'buffered' };
      }
      if (node.deleted) return { applied: false, reason: 'duplicate' };
      // Idempotence guard, symmetric with the insert branch's `byId.has`
      // check above. Without it, a redelivered delete (its own author's
      // op echoing back over the relay's SSE stream, or the same op
      // arriving twice on a reconnect) would fall through, and because
      // an already-tombstoned node makes `visibleIndexOf` return -1,
      // app.js's caret-shift logic (`visibleIndex < caret`) would read
      // that -1 as "something to the left of the caret was deleted" and
      // shift the caret again for a delete that didn't actually change
      // any text. Repeated over several redelivered echoes this walks
      // the real caret away from where the user is actually typing,
      // so *subsequent* keystrokes land on and corrupt the wrong
      // characters — a real, user-visible bug, not just an internal
      // bookkeeping nit. Caught by typing+backspacing through a live
      // browser tab during adversarial review (a single tab echoes its
      // own ops back to itself once net.js stopped special-casing "my
      // own siteId" — see net.js's comment); no engine-only test caught
      // it because the *data* was always correct, only the caller-facing
      // position bookkeeping drifted. See REVIEW.md.
      // Computed BEFORE tombstoning — this is the last instant the node's
      // visible position is still meaningful.
      var visIdx = this.visibleIndexOf(op.id);
      node.deleted = true;
      return { applied: true, kind: 'delete', visibleIndex: visIdx };
    }
    throw new Error('unknown op type: ' + op.type);
  };

  /** Number of ops still waiting on a dependency that hasn't arrived yet.
   *  Used by tests (and the internals inspector) to prove buffering
   *  actually drains rather than silently leaking ops forever. */
  RGA.prototype.pendingCount = function () {
    var n = 0;
    this.pending.forEach(function (list) {
      n += list.length;
    });
    return n;
  };

  /** Returns the pos-th (0-based) *visible* (non-tombstoned) node, or null
   *  if pos is out of range. */
  RGA.prototype._visibleNodeAt = function (pos) {
    var count = 0;
    for (var i = 0; i < this.seq.length; i++) {
      if (this.seq[i].deleted) continue;
      if (count === pos) return this.seq[i];
      count += 1;
    }
    return null;
  };

  /** Insert `text` (may be empty or multi-character) so that it becomes
   *  visible characters [pos, pos+text.length) of the document. Generates
   *  and integrates one op per character locally, returning the ops so the
   *  caller (net.js) can broadcast them. Chains each new char's leftId to
   *  the previous one just inserted, so a multi-char paste is itself a
   *  sequence of RGA nodes, not a special "block" primitive. */
  RGA.prototype.localInsert = function (pos, text) {
    // Clamp rather than trust the caller: a stale caret/position computed
    // against a document that has since shrunk (or any out-of-range value
    // from a caller) must not crash the whole replica — it should behave
    // like a real text editor and insert at the nearest valid spot. An
    // earlier version of this method did `this._visibleNodeAt(pos - 1).id`
    // unguarded and threw on any pos <= 0 or pos > length(); caught by
    // adversarial testing, not by any normal typing flow — see REVIEW.md.
    pos = Math.max(0, Math.min(pos, this.length()));
    if (text.length === 0) return [];
    var ops = [];

    // The first character goes through the full general-purpose
    // integration scan (it may have to contest position against nodes
    // some other site already inserted at this exact spot).
    var leftId = pos === 0 ? null : this._visibleNodeAt(pos - 1).id;
    var firstId = this.nextId();
    var firstNode = { id: firstId, value: text[0], leftId: leftId, deleted: false };
    var idx = this._integrateInsert(firstNode, /* skipReindex */ true);
    ops.push({ type: 'insert', id: firstId, value: text[0], leftId: leftId });

    // Every subsequent character in this SAME local call is chained to
    // the one immediately before it — an id that didn't exist until this
    // exact synchronous call created it a moment ago, so by construction
    // nothing else can possibly claim to be its concurrent sibling. That
    // means the general scan's whole job (find where we rank among
    // contesting siblings) is moot for these — they always land exactly
    // one slot past the previous character, no scan required. Without
    // this fast path, pasting a large block of text was O(n^2) (an O(n)
    // tie-break scan *and* an O(n) posById rebuild per character) and
    // visibly froze the UI for seconds on a few-thousand-character paste
    // — caught by timing a large paste during adversarial review, not by
    // any functional test (small inputs never revealed it). See REVIEW.md.
    var prevId = firstId;
    for (var i = 1; i < text.length; i++) {
      var id = this.nextId();
      var node = { id: id, value: text[i], leftId: prevId, deleted: false };
      idx += 1;
      this.seq.splice(idx, 0, node);
      this.byId.set(idKey(id), node);
      ops.push({ type: 'insert', id: id, value: text[i], leftId: prevId });
      prevId = id;
    }
    this._reindex(); // one O(n) rebuild for the whole batch, not one per char
    return ops;
  };

  /** Tombstone `count` visible characters starting at visible position
   *  `pos`. Returns the delete ops for broadcast. */
  RGA.prototype.localDelete = function (pos, count) {
    pos = Math.max(0, pos);
    var ops = [];
    for (var k = 0; k < count; k++) {
      var node = this._visibleNodeAt(pos);
      if (!node) break; // deleting past end of document: stop, don't throw
      node.deleted = true;
      ops.push({ type: 'delete', id: node.id });
    }
    return ops;
  };

  /** The 0-based visible-text index of the node with `id`, or -1 if that
   *  id doesn't exist locally yet or is currently tombstoned (not visible).
   *  This is the id-based analogue of a numeric caret position: stable
   *  across concurrent edits happening elsewhere in the document, because
   *  it's recomputed from the id, not cached as a number that would drift. */
  RGA.prototype.visibleIndexOf = function (id) {
    if (id === null) return -1;
    var node = this.byId.get(idKey(id));
    if (!node || node.deleted) return -1;
    var count = 0;
    for (var i = 0; i < this.seq.length; i++) {
      if (this.seq[i] === node) return count;
      if (!this.seq[i].deleted) count += 1;
    }
    return -1;
  };

  /** The id a cursor at visible position `pos` should be anchored to: the
   *  id of the visible node immediately to its left, or null at the very
   *  start of the document. Same convention as an insert's `leftId`, which
   *  is exactly why it's the right representation for a cursor position
   *  that has to stay meaningful while everyone else keeps editing: peers
   *  recompute the current pixel/index position from the id via
   *  visibleIndexOf, instead of trusting a raw number that silently goes
   *  stale the moment someone inserts text before it. */
  RGA.prototype.anchorAt = function (pos) {
    pos = Math.max(0, Math.min(pos, this.length()));
    if (pos === 0) return null;
    var n = this._visibleNodeAt(pos - 1);
    return n ? n.id : null;
  };

  RGA.prototype.text = function () {
    var out = [];
    for (var i = 0; i < this.seq.length; i++) {
      if (!this.seq[i].deleted) out.push(this.seq[i].value);
    }
    return out.join('');
  };

  RGA.prototype.length = function () {
    var n = 0;
    for (var i = 0; i < this.seq.length; i++) {
      if (!this.seq[i].deleted) n += 1;
    }
    return n;
  };

  /** Snapshot of the full internal structure (including tombstones) for
   *  the CRDT-internals inspector: every node's id, value, author site,
   *  left-neighbor pointer, and tombstone state, in actual sequence order. */
  RGA.prototype.inspect = function () {
    return this.seq.map(function (n) {
      return {
        id: n.id,
        value: n.value,
        author: n.id[1],
        leftId: n.leftId,
        deleted: n.deleted,
      };
    });
  };

  return {
    RGA: RGA,
    compareId: compareId,
    idKey: idKey,
    idsEqual: idsEqual,
  };
});
