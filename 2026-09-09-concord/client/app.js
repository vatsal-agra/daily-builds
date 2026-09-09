/**
 * app.js — wires the DOM to the RGA replica (crdt.js) and the relay
 * connection (net.js). This file owns: local-edit diffing (turning a raw
 * textarea input event into CRDT ops), caret preservation across remote
 * edits, presence-cursor rendering, the offline toggle, and the CRDT
 * internals inspector. It contains zero CRDT logic of its own — every
 * decision about ordering, tombstoning, or convergence happens in
 * crdt.js; this file only ever calls into it.
 */
(function () {
  'use strict';

  // ---- identity -----------------------------------------------------
  // Each *tab* is an independent replica/site, deliberately — that's what
  // makes opening the same doc URL in two tabs a faithful two-person demo.
  // sessionStorage (not localStorage) scopes identity to this tab only.
  var PALETTE = ['#e0554f', '#3a86ff', '#2fb380', '#c77dff', '#ff9f1c', '#118ab2'];

  function randomSiteId() {
    var bytes = new Uint8Array(9);
    crypto.getRandomValues(bytes);
    return Array.prototype.map.call(bytes, function (b) { return b.toString(36); }).join('').slice(0, 10);
  }

  function loadIdentity() {
    // Deliberately NOT persisted in sessionStorage (unlike name/color
    // below): a browser's "Duplicate Tab" — a completely ordinary, common
    // action — clones sessionStorage verbatim into the new tab. If siteId
    // were persisted, both tabs would generate ops under the *same*
    // (counter, siteId) identity and could mint genuinely colliding ids
    // for two different concurrently-typed characters, which the CRDT's
    // dedup logic would then treat as a real duplicate and silently drop
    // one of them — actual data loss, not just a cosmetic glitch. A fresh
    // random siteId every page load closes that off entirely, and costs
    // nothing: net.js no longer special-cases "my own" ops (see its
    // comment), so a reload's fresh, empty replica still correctly
    // rebuilds full history from the relay's backlog under its new
    // identity. Caught during adversarial review, not by normal use —
    // see REVIEW.md.
    var siteId = randomSiteId();
    var name = sessionStorage.getItem('concord-name');
    if (!name) {
      name = 'Guest-' + siteId.slice(0, 4);
      sessionStorage.setItem('concord-name', name);
    }
    var color = sessionStorage.getItem('concord-color');
    if (!color) {
      // Deterministic-ish from siteId so a reload keeps the same color.
      var sum = 0;
      for (var i = 0; i < siteId.length; i++) sum += siteId.charCodeAt(i);
      color = PALETTE[sum % PALETTE.length];
      sessionStorage.setItem('concord-color', color);
    }
    return { siteId: siteId, name: name, color: color };
  }

  function docIdFromUrl() {
    var params = new URLSearchParams(location.search);
    var doc = params.get('doc');
    return doc && /^[A-Za-z0-9_-]{1,64}$/.test(doc) ? doc : 'lobby';
  }

  // ---- boot -----------------------------------------------------------
  var identity = loadIdentity();
  var docId = docIdFromUrl();
  var rga = new Concord.RGA(identity.siteId);
  var net = new window.ConcordNet(docId, rga, {
    onRemoteOp: handleRemoteOp,
    onCursor: handleRemoteCursor,
    onStatus: handleStatus,
  });
  net.displayName = identity.name;
  net.displayColor = identity.color;

  var editor = document.getElementById('editor');
  var mirror = document.getElementById('mirror');
  var cursorLayer = document.getElementById('cursor-layer');
  var docInput = document.getElementById('doc-input');
  var docGo = document.getElementById('doc-go');
  var statusDot = document.getElementById('status-dot');
  var statusLabel = document.getElementById('status-label');
  var offlineToggle = document.getElementById('offline-toggle');
  var offlineBanner = document.getElementById('offline-banner');
  var charCount = document.getElementById('char-count');
  var pendingCountEl = document.getElementById('pending-count');
  var inspectorToggle = document.getElementById('inspector-toggle');
  var inspectorPane = document.getElementById('inspector-pane');
  var inspectorList = document.getElementById('inspector-list');
  var inspectorStats = document.getElementById('inspector-stats');
  var peersEl = document.getElementById('peers');

  docInput.value = docId;

  // remote presence state: siteId -> {name, color, index, lastSeen}
  var peers = new Map();

  // ---- local edit diffing --------------------------------------------
  // The textarea is the source of truth for what the user sees typing;
  // every 'input' event is diffed against our own last-known value to
  // recover the minimal insert/delete that explains the change, which we
  // then replay against the RGA replica (and broadcast). This handles
  // typing, backspace/delete, cut, paste, and IME composition uniformly —
  // there's no special-casing per key.
  var lastValue = '';

  function commonPrefixLen(a, b) {
    var n = Math.min(a.length, b.length);
    var i = 0;
    while (i < n && a[i] === b[i]) i++;
    return i;
  }
  function commonSuffixLen(a, b, maxLen) {
    var n = Math.min(a.length, b.length, maxLen);
    var i = 0;
    while (i < n && a[a.length - 1 - i] === b[b.length - 1 - i]) i++;
    return i;
  }

  function onLocalInput() {
    var newValue = editor.value;
    var oldValue = lastValue;
    if (newValue === oldValue) return;

    var prefix = commonPrefixLen(oldValue, newValue);
    var maxSuffix = Math.min(oldValue.length - prefix, newValue.length - prefix);
    var suffix = commonSuffixLen(oldValue, newValue, maxSuffix);

    var deleteCount = oldValue.length - prefix - suffix;
    var insertText = newValue.slice(prefix, newValue.length - suffix);

    var ops = [];
    if (deleteCount > 0) {
      ops = ops.concat(rga.localDelete(prefix, deleteCount));
    }
    if (insertText.length > 0) {
      ops = ops.concat(rga.localInsert(prefix, insertText));
    }
    lastValue = editor.value;
    net.sendOps(ops);
    refreshChrome();
  }

  editor.addEventListener('input', onLocalInput);

  // Local cursor/selection change -> broadcast presence.
  var cursorSendTimer = null;
  function onLocalSelectionChange() {
    if (document.activeElement !== editor) return;
    if (cursorSendTimer) clearTimeout(cursorSendTimer);
    cursorSendTimer = setTimeout(function () {
      net.sendCursor(editor.selectionStart);
    }, 80);
  }
  editor.addEventListener('keyup', onLocalSelectionChange);
  editor.addEventListener('click', onLocalSelectionChange);
  editor.addEventListener('select', onLocalSelectionChange);

  // ---- remote ops -------------------------------------------------------
  function handleRemoteOp(op, result) {
    if (!result || !result.applied) return; // buffered — nothing to render yet
    var caret = editor.selectionStart;
    var caretEnd = editor.selectionEnd;
    if (result.kind === 'insert') {
      // A char landed at result.visibleIndex. If it landed at or before
      // our caret, the caret needs to shift right by one so it stays next
      // to the same character it was next to before — otherwise a remote
      // insertion earlier in the document would visibly yank the local
      // user's typing position out from under them.
      if (result.visibleIndex <= caret) caret += 1;
      if (result.visibleIndex <= caretEnd) caretEnd += 1;
    } else if (result.kind === 'delete') {
      if (result.visibleIndex < caret) caret -= 1;
      if (result.visibleIndex < caretEnd) caretEnd -= 1;
    }
    editor.value = rga.text();
    lastValue = editor.value;
    caret = Math.max(0, Math.min(caret, editor.value.length));
    caretEnd = Math.max(caret, Math.min(caretEnd, editor.value.length));
    if (document.activeElement === editor) {
      editor.setSelectionRange(caret, caretEnd);
    }
    refreshChrome();
  }

  function handleRemoteCursor(payload) {
    peers.set(payload.siteId, {
      name: payload.name || 'Guest',
      color: payload.color || '#888',
      index: payload.index,
      lastSeen: Date.now(),
    });
    renderCursors();
    renderPeerList();
  }

  // ---- connection status ------------------------------------------------
  function handleStatus(status) {
    statusDot.setAttribute('data-status', status);
    var labels = {
      connecting: 'connecting…',
      online: 'live',
      reconnecting: 'reconnecting…',
      offline: 'offline',
    };
    statusLabel.textContent = labels[status] || status;
    offlineBanner.hidden = status !== 'offline';
    offlineToggle.textContent = status === 'offline' ? 'Go online' : 'Go offline';
    if (status !== 'online') {
      peers.clear();
      renderPeerList();
      renderCursors();
    }
  }

  offlineToggle.addEventListener('click', function () {
    if (net.online) {
      net.disconnect();
    } else {
      net.connect();
    }
  });

  // ---- doc switching ------------------------------------------------
  docGo.addEventListener('click', function () {
    var v = docInput.value.trim();
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(v)) {
      docInput.classList.add('invalid');
      setTimeout(function () { docInput.classList.remove('invalid'); }, 900);
      return;
    }
    var url = new URL(location.href);
    url.searchParams.set('doc', v);
    location.href = url.toString();
  });
  docInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') docGo.click();
  });

  // ---- inspector ------------------------------------------------------
  var inspectorOpen = false;
  inspectorToggle.addEventListener('click', function () {
    inspectorOpen = !inspectorOpen;
    inspectorPane.hidden = !inspectorOpen;
    inspectorToggle.textContent = inspectorOpen ? 'Hide CRDT internals' : 'Show CRDT internals';
    if (inspectorOpen) renderInspector();
  });

  function renderInspector() {
    if (!inspectorOpen) return;
    var nodes = rga.inspect();
    var visible = 0, tomb = 0;
    var rows = nodes.map(function (n) {
      if (n.deleted) tomb++; else visible++;
      var cls = n.deleted ? 'node tombstone' : 'node';
      var displayVal = n.value === '\n' ? '\\n' : n.value === ' ' ? '·' : escapeHtml(n.value);
      // n.id[0]/n.leftId[0] are server-validated integers (safe to
      // concatenate raw), but the siteId half of an id is an arbitrary
      // string the relay only checks is non-empty — NOT that it's free of
      // HTML-breaking characters. A hostile/misbehaving peer could craft
      // an op whose siteId is itself markup, which every other client's
      // inspector then renders. escapeHtml() here isn't decorative: this
      // exact author/leftId metadata was going in as raw string
      // concatenation into innerHTML with no escaping — found during
      // adversarial review, not by any test using this build's own
      // (harmless, [a-z0-9]-only) generated siteIds. See REVIEW.md.
      return (
        '<div class="' + cls + '" style="--author:' + colorForSite(n.author) + '">' +
        '<span class="node-val">' + displayVal + '</span>' +
        '<span class="node-meta">id ' + n.id[0] + ':' + escapeHtml(shortSite(n.author)) +
        ' &middot; after ' + (n.leftId ? n.leftId[0] + ':' + escapeHtml(shortSite(n.leftId[1])) : '∅') +
        (n.deleted ? ' &middot; tombstoned' : '') + '</span>' +
        '</div>'
      );
    });
    inspectorList.innerHTML = rows.join('');
    inspectorStats.textContent = visible + ' visible node' + (visible === 1 ? '' : 's') + ', ' + tomb + ' tombstone' + (tomb === 1 ? '' : 's') + ', ' + rga.pendingCount() + ' buffered';
  }

  function shortSite(s) { return (s || '').slice(0, 6); }
  function siteColorCache() { return {}; }
  var _siteColors = {};
  function colorForSite(site) {
    if (site === identity.siteId) return identity.color;
    var peer = peers.get(site);
    if (peer) return peer.color;
    if (!_siteColors[site]) {
      var sum = 0;
      for (var i = 0; i < site.length; i++) sum += site.charCodeAt(i);
      _siteColors[site] = PALETTE[sum % PALETTE.length];
    }
    return _siteColors[site];
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ---- cursor overlay (mirror-div caret coordinates) -------------------
  // Renders every remote peer's cursor as a labeled colored caret over the
  // textarea. Textareas have no API for "pixel position of character N",
  // so we keep an invisible <div> styled identically to the textarea
  // (same font/padding/wrapping), fill it with the text up to that
  // character plus a marker <span>, and read the marker's offset — the
  // standard technique for textarea caret coordinates.
  var mirroredStyleProps = [
    'boxSizing', 'width', 'height', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
    'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
    'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'whiteSpace', 'wordWrap', 'wordBreak', 'tabSize',
  ];
  function syncMirrorStyle() {
    var cs = getComputedStyle(editor);
    mirroredStyleProps.forEach(function (p) { mirror.style[p] = cs[p]; });
    mirror.style.whiteSpace = 'pre-wrap';
    mirror.style.wordWrap = 'break-word';
    mirror.style.overflowWrap = 'break-word';
  }

  function caretPixelPosition(index) {
    syncMirrorStyle();
    var text = editor.value;
    var before = text.slice(0, index);
    mirror.textContent = '';
    mirror.appendChild(document.createTextNode(before));
    var marker = document.createElement('span');
    marker.textContent = '​';
    mirror.appendChild(marker);
    mirror.appendChild(document.createTextNode(text.slice(index) || ' '));
    return {
      top: marker.offsetTop - editor.scrollTop,
      left: marker.offsetLeft - editor.scrollLeft,
      height: marker.offsetHeight,
    };
  }

  function renderCursors() {
    var now = Date.now();
    var html = [];
    peers.forEach(function (peer, siteId) {
      if (now - peer.lastSeen > 12000) return; // stale, don't render a ghost
      if (peer.index == null) return;
      var pos = caretPixelPosition(Math.max(0, Math.min(peer.index, editor.value.length)));
      html.push(
        '<div class="remote-caret" style="top:' + pos.top + 'px; left:' + pos.left + 'px; height:' + pos.height + 'px; --peer-color:' + peer.color + '">' +
        '<span class="caret-flag">' + escapeHtml(peer.name) + '</span></div>'
      );
    });
    cursorLayer.innerHTML = html.join('');
  }

  function renderPeerList() {
    var now = Date.now();
    var html = [];
    peers.forEach(function (peer) {
      if (now - peer.lastSeen > 12000) return;
      html.push('<span class="peer-chip" style="--peer-color:' + peer.color + '" title="' + escapeHtml(peer.name) + '">' + escapeHtml(peer.name.slice(0, 1).toUpperCase()) + '</span>');
    });
    peersEl.innerHTML = html.join('');
  }

  // Reloading or closing the tab wipes the in-memory RGA replica entirely
  // — this build keeps no localStorage snapshot of the document (see
  // README's "known limits"). That's fine while online (a reload just
  // re-syncs from the relay's backlog), but while OFFLINE it would
  // silently throw away any edits net.js's outbox hasn't sent yet, with
  // zero warning to the user. Standard browser guard, same pattern any
  // "you have unsaved changes" app uses: block the unload and let the
  // browser's native confirmation dialog do the asking. Found and fixed
  // during adversarial review by actually reloading mid-offline-edit —
  // see REVIEW.md.
  window.addEventListener('beforeunload', function (e) {
    if (net.hasUnsyncedChanges()) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  // Sweep stale peers periodically so a closed tab's cursor eventually
  // disappears even without an explicit "goodbye" message.
  setInterval(function () {
    var now = Date.now();
    var changed = false;
    peers.forEach(function (peer, id) {
      if (now - peer.lastSeen > 12000) { peers.delete(id); changed = true; }
    });
    if (changed) { renderCursors(); renderPeerList(); }
  }, 4000);

  window.addEventListener('resize', renderCursors);
  editor.addEventListener('scroll', renderCursors);

  // ---- chrome (char count, pending count) --------------------------
  function refreshChrome() {
    var n = rga.length();
    charCount.textContent = n + ' character' + (n === 1 ? '' : 's');
    var pending = rga.pendingCount();
    pendingCountEl.textContent = pending > 0 ? pending + ' op' + (pending === 1 ? '' : 's') + ' buffered (waiting on a dependency)' : '';
    if (inspectorOpen) renderInspector();
  }

  // ---- go ---------------------------------------------------------------
  editor.focus();
  refreshChrome();
  net.connect();

  // Exposed for tests (headless-browser smoke test drives the real app
  // through this handle rather than poking at private closures).
  window.__concord = { rga: rga, net: net, identity: identity, docId: docId };
})();
