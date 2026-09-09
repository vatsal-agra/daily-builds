/**
 * net.js — browser-side networking glue between an RGA replica and the
 * relay server. Browser-only (EventSource/fetch), loaded via <script> after
 * crdt.js. Deliberately separate from crdt.js: the CRDT engine has zero
 * knowledge of HTTP, offline state, or reconnection — it only knows how to
 * integrate ops. Everything network-shaped lives here.
 *
 * Responsibilities:
 *   - subscribe to the relay's SSE stream for this document and apply
 *     every remote op to the local RGA replica (skipping ops that
 *     originated from this exact site — they were already applied locally
 *     the instant they were typed, so re-applying them is a redundant but
 *     harmless idempotent no-op if we didn't skip them; we skip purely to
 *     avoid needless work, not because applying them would be wrong)
 *   - track `lastSeq`, the highest server-assigned sequence number this
 *     site has durably applied, so a reconnect can ask for `?since=lastSeq`
 *     instead of replaying the whole document history
 *   - queue locally-generated ops in an outbox while offline, and flush
 *     them (in order) the moment the connection comes back — this, plus
 *     the relay's own backlog replay, is the entire "offline editing +
 *     merge on reconnect" feature: there is no separate merge algorithm,
 *     because the CRDT itself guarantees convergence once every op has
 *     been seen by every replica, in whatever order that happens.
 *   - relay ephemeral cursor/presence events (never queued, never
 *     replayed — a stale cursor position from an offline period is not
 *     worth resurrecting)
 */
(function (global) {
  'use strict';

  function Net(docId, rga, opts) {
    opts = opts || {};
    this.docId = docId;
    this.rga = rga;
    this.siteId = rga.siteId;
    this.baseUrl = opts.baseUrl || '';
    this.online = false;
    this.everConnected = false;
    this.lastSeq = 0;
    this.outbox = [];
    this.eventSource = null;
    this.onRemoteOp = opts.onRemoteOp || function () {};
    this.onCursor = opts.onCursor || function () {};
    this.onStatus = opts.onStatus || function () {};
  }

  Net.prototype._setStatus = function (status) {
    this.online = status === 'online';
    this.onStatus(status);
  };

  Net.prototype.connect = function () {
    if (this.eventSource) this.eventSource.close();
    this._setStatus('connecting');
    var url =
      this.baseUrl +
      '/doc/' +
      encodeURIComponent(this.docId) +
      '/events?since=' +
      this.lastSeq +
      '&site=' +
      encodeURIComponent(this.siteId);
    var es = new EventSource(url);
    var self = this;

    es.addEventListener('op', function (ev) {
      var entry = JSON.parse(ev.data); // {seq, op: {siteId, op}}
      if (entry.seq <= self.lastSeq) return; // already-applied redelivery
      self.lastSeq = entry.seq;
      // Deliberately NOT skipped just because entry.op.siteId === our own
      // siteId: that would be correct only within a single unbroken JS
      // session (where our own ops are already integrated in memory the
      // instant we generate them). It's wrong the moment identity persists
      // across a page reload — sessionStorage keeps the same siteId, but a
      // fresh page load starts with an EMPTY in-memory replica, so this
      // exact site's own *earlier* ops must still be replayed from the
      // relay's backlog like anyone else's. applyRemote() is idempotent
      // (it no-ops on an id it already has), so there's no correctness
      // reason to special-case "our own" ops here at all — only a
      // negligible, not-worth-it micro-optimization we're deliberately not
      // taking. (Caught by tests/test_browser.js's dark-mode reload check;
      // see REVIEW.md.)
      var result = self.rga.applyRemote(entry.op.op);
      self.onRemoteOp(entry.op.op, result);
    });

    es.addEventListener('cursor', function (ev) {
      var payload = JSON.parse(ev.data);
      if (payload.siteId === self.siteId) return;
      self.onCursor(payload);
    });

    es.addEventListener('ready', function () {
      self.everConnected = true;
      self._setStatus('online');
      self._flushOutbox();
    });

    es.onerror = function () {
      // The browser's EventSource keeps retrying the connection on its
      // own; we just reflect "not currently reliable" to the app. When it
      // reconnects, the server sends 'ready' again and we re-flush.
      self._setStatus(self.everConnected ? 'reconnecting' : 'connecting');
    };

    this.eventSource = es;
  };

  /** Go offline deliberately (the "Go offline" UI toggle, or a real
   *  network failure the app detected). Stops the SSE stream entirely —
   *  no reconnection attempts happen until connect() is called again. */
  Net.prototype.disconnect = function () {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    this._setStatus('offline');
  };

  /** A failed POST doesn't necessarily mean the SSE stream itself has
   *  noticed anything wrong — a transient hiccup can fail one fetch
   *  without EventSource ever firing its own onerror, which would
   *  otherwise be the only thing that re-triggers `_flushOutbox` (it only
   *  runs again on the next 'ready' event). Without forcing a fresh
   *  connect here, ops that fail to send while nominally "online" could
   *  sit in the outbox indefinitely with nothing left to retry them —
   *  found by reasoning through the failure path during adversarial
   *  review, not by a flaky test (reproducing a real transient-network
   *  blip deterministically isn't practical to test directly, so this is
   *  documented instead of test-gated — see REVIEW.md). Forcing a
   *  reconnect is cheap and always safe here: this only runs from a path
   *  that already checked `this.online`, so it can never fight a
   *  deliberate disconnect(). */
  Net.prototype._retryConnection = function () {
    this._setStatus('reconnecting');
    this.connect();
  };

  Net.prototype._flushOutbox = function () {
    if (!this.online || this.outbox.length === 0) return;
    var toSend = this.outbox;
    this.outbox = [];
    this._post('/doc/' + encodeURIComponent(this.docId) + '/ops', {
      siteId: this.siteId,
      ops: toSend,
    }).catch(
      function () {
        // Couldn't reach the relay: put the ops back at the FRONT of the
        // outbox (preserve order) and force a fresh connection attempt.
        this.outbox = toSend.concat(this.outbox);
        this._retryConnection();
      }.bind(this)
    );
  };

  /** Called by app.js immediately after generating ops from a local edit.
   *  If online, sends them now; if offline, queues them — either way the
   *  local RGA replica already has them applied (localInsert/localDelete
   *  mutate synchronously), so the editor never waits on the network. */
  Net.prototype.sendOps = function (ops) {
    if (!ops || ops.length === 0) return;
    if (!this.online) {
      this.outbox.push.apply(this.outbox, ops);
      return;
    }
    this._post('/doc/' + encodeURIComponent(this.docId) + '/ops', {
      siteId: this.siteId,
      ops: ops,
    }).catch(
      function () {
        this.outbox.push.apply(this.outbox, ops);
        this._retryConnection();
      }.bind(this)
    );
  };

  /** True while there are locally-generated ops this replica has not yet
   *  confirmed reaching the relay (queued while offline, or a send that
   *  failed and fell back to the outbox). Used by app.js to warn before
   *  an accidental reload/close silently discards them — see its
   *  `beforeunload` handler. Deliberately NOT "is the outbox non-empty
   *  OR are we offline": being offline with an empty outbox (nothing
   *  typed yet) has nothing to lose. */
  Net.prototype.hasUnsyncedChanges = function () {
    return this.outbox.length > 0;
  };

  Net.prototype.sendCursor = function (index) {
    if (!this.online) return; // presence is inherently best-effort/live-only
    this._post('/doc/' + encodeURIComponent(this.docId) + '/cursor', {
      siteId: this.siteId,
      name: this.displayName,
      color: this.displayColor,
      index: index,
    }).catch(function () {
      /* presence pings are fire-and-forget; a dropped one is harmless */
    });
  };

  Net.prototype._post = function (path, body) {
    return fetch(this.baseUrl + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (resp) {
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return resp.json();
    });
  };

  global.ConcordNet = Net;
})(typeof window !== 'undefined' ? window : this);
