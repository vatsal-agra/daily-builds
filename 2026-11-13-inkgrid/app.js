/* Inkgrid UI — canvas board, input, hints, solver visualiser, import/share. */
(function () {
  'use strict';
  const E = window.Inkgrid;
  const $ = id => document.getElementById(id);
  const canvas = $('board'), ctx = canvas.getContext('2d');
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  const S = {
    p: null, w: 0, h: 0, marks: null, solution: null, unique: true, title: '',
    undo: [], redo: [], t0: 0, elapsed: 0, solved: false, timerId: null,
    tool: 'fill', hl: null, hintCells: [], bad: new Set(), geom: null,
    viz: null, // {steps, idx, board, playing, timer, finalSol}
    drag: null,
  };

  // ---------- puzzle lifecycle ----------
  function loadPuzzle(p, opts) {
    opts = opts || {};
    const dims = E.validatePuzzle(p);
    stopViz(true);
    S.p = { rows: p.rows, cols: p.cols }; S.w = dims.w; S.h = dims.h; S.title = opts.title || '';
    S.marks = new Int8Array(S.w * S.h).fill(-1);
    S.undo = []; S.redo = []; S.solved = false; S.hl = null; S.hintCells = []; S.bad = new Set();
    hideHint(); hideBanner();
    // establish solution + uniqueness (tolerant of hand-imported puzzles)
    let sol = opts.grid || null, unique = true;
    if (!sol) {
      const r = E.solve(S.p, { limit: 2, maxNodes: 100000 });
      if (r.count === 0) throw new Error(r.truncated ? 'This puzzle is too hard to analyse here.' : 'This puzzle has no solution — the clues contradict each other.');
      sol = r.solutions[0]; unique = r.count === 1 && !r.truncated;
    }
    S.solution = sol; S.unique = unique;
    const rt = opts.rating || (unique ? E.rate(S.p) : { label: 'multiple solutions', score: 0 });
    if (!opts.grid && unique === false) S.unique = false;
    $('ratingPill').textContent = !unique ? 'uniqueness unproven' : rt.tier === -2 ? 'unrated (large)' : rt.label + ' · ' + rt.score;
    $('ratingPill').title = unique ? 'Measured difficulty (tier ' + rt.tier + ')' : 'Any grid matching the clues counts as a win';
    resetTimer();
    try { history.replaceState(null, '', '#p=' + E.encodeShare(S.p)); } catch (e) { /* file:// restrictions */ }
    layout(); draw();
    setBoardLabel();
  }
  function setBoardLabel() { canvas.setAttribute('aria-label', 'Nonogram board ' + S.w + ' by ' + S.h); }

  function generate() {
    const note = $('genNote'); note.className = 'note'; note.textContent = 'Generating…';
    $('btnNew').disabled = true;
    setTimeout(() => {
      try {
        const w = +$('optW').value, h = +$('optH').value;
        let seed = $('optSeed').value.trim();
        if (!seed) { seed = Math.random().toString(36).slice(2, 8); $('optSeed').value = seed; }
        const t = performance.now();
        const g = E.generate({ w, h, seed, difficulty: $('optDiff').value, density: +$('optDens').value / 100, attempts: 80 });
        loadPuzzle({ rows: g.rows, cols: g.cols }, { grid: g.grid, rating: g.rating });
        const ms = Math.round(performance.now() - t);
        note.className = 'note ' + (g.relaxed ? '' : 'ok');
        note.textContent = (g.relaxed ? 'No ' + $('optDiff').value + ' puzzle found for this seed — closest unique puzzle (' + g.rating.label + '). ' : 'Unique solution guaranteed. ') + ms + ' ms.';
      } catch (e) { note.className = 'note err'; note.textContent = e.message; }
      $('btnNew').disabled = false;
    }, 20);
  }

  // ---------- timer ----------
  function resetTimer() {
    clearInterval(S.timerId); S.t0 = Date.now(); S.elapsed = 0; renderTimer();
    S.timerId = setInterval(() => { if (!S.solved) { S.elapsed = Math.floor((Date.now() - S.t0) / 1000); renderTimer(); } }, 500);
  }
  function renderTimer() { const s = S.elapsed; $('timer').textContent = Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }

  // ---------- geometry & drawing ----------
  function layout() {
    if (!S.p) return;
    const rowDepth = Math.max(1, ...S.p.rows.map(c => c.length)), colDepth = Math.max(1, ...S.p.cols.map(c => c.length));
    const avail = Math.max(240, $('stage').clientWidth - 8);
    const cell = Math.max(8, Math.min(34, Math.floor((avail - 24) / (S.w + rowDepth * 0.8))));
    const left = Math.ceil(rowDepth * cell * 0.8) + 10, top = Math.ceil(colDepth * cell * 0.8) + 10;
    const W = left + S.w * cell + 12, H = top + S.h * cell + 12;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr; canvas.height = H * dpr; canvas.style.width = W + 'px'; canvas.style.height = 'auto';
    S.geom = { cell, left, top, W, H, dpr };
  }

  function lineDone(t, i) {
    const cells = t === 'r' ? rowCells(i) : colCells(i);
    const f = E.lineClue(cells.map(v => (v === 1 ? 1 : 0)));
    const clue = t === 'r' ? S.p.rows[i] : S.p.cols[i];
    return f.length === clue.length && f.every((v, k) => v === clue[k]);
  }
  const rowCells = y => Array.from(S.marks.subarray(y * S.w, (y + 1) * S.w));
  const colCells = x => { const a = []; for (let y = 0; y < S.h; y++) a.push(S.marks[y * S.w + x]); return a; };
  const shown = () => (S.viz ? S.viz.board.cells : S.marks);

  function draw() {
    if (!S.geom) return;
    const { cell, left, top, W, H, dpr } = S.geom;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const paper = css('--paper'), grid = css('--paper-grid'), major = css('--paper-major'), fill = css('--fill'), cross = css('--cross'),
      hl = css('--hl'), accent = css('--accent'), bad = css('--bad'), ink = css('--fill'), good = css('--good');
    ctx.fillStyle = paper; ctx.fillRect(0, 0, W, H);
    const cells = shown();

    // highlighted line band (hint / solver)
    const band = S.viz ? S.viz.cur : S.hl;
    if (band) {
      ctx.fillStyle = hl;
      if (band.t === 'r') ctx.fillRect(4, top + band.i * cell, W - 8, cell);
      else ctx.fillRect(left + band.i * cell, 4, cell, H - 8);
    }
    // cells
    const pad = Math.max(1.5, cell * 0.1);
    for (let y = 0; y < S.h; y++) for (let x = 0; x < S.w; x++) {
      const v = cells[y * S.w + x], px = left + x * cell, py = top + y * cell;
      const isBad = S.bad.has(y * S.w + x);
      if (v === 1) {
        ctx.fillStyle = isBad ? bad : fill;
        const r = cell * 0.16; roundRect(px + 1, py + 1, cell - 2, cell - 2, r); ctx.fill();
      } else if (v === 0) {
        ctx.strokeStyle = isBad ? bad : cross; ctx.lineWidth = Math.max(1.2, cell * 0.07); ctx.lineCap = 'round';
        ctx.beginPath(); ctx.moveTo(px + pad * 1.8, py + pad * 1.8); ctx.lineTo(px + cell - pad * 1.8, py + cell - pad * 1.8);
        ctx.moveTo(px + cell - pad * 1.8, py + pad * 1.8); ctx.lineTo(px + pad * 1.8, py + cell - pad * 1.8); ctx.stroke();
      }
    }
    // hint cells
    for (const [x, y, v] of S.hintCells) {
      const px = left + x * cell, py = top + y * cell;
      ctx.strokeStyle = accent; ctx.lineWidth = 2.5; ctx.strokeRect(px + 2, py + 2, cell - 4, cell - 4);
      ctx.fillStyle = accent; ctx.font = '700 ' + Math.floor(cell * 0.5) + 'px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(v === 1 ? '■' : '✕', px + cell / 2, py + cell / 2 + 1);
    }
    // grid lines
    for (let i = 0; i <= S.w; i++) { ctx.strokeStyle = i % 5 === 0 || i === S.w ? major : grid; ctx.lineWidth = i % 5 === 0 || i === S.w ? 1.4 : 0.8; line(left + i * cell, top, left + i * cell, top + S.h * cell); }
    for (let i = 0; i <= S.h; i++) { ctx.strokeStyle = i % 5 === 0 || i === S.h ? major : grid; ctx.lineWidth = i % 5 === 0 || i === S.h ? 1.4 : 0.8; line(left, top + i * cell, left + S.w * cell, top + i * cell); }

    // clues
    const fs = Math.max(9, Math.floor(cell * 0.56));
    ctx.font = '600 ' + fs + 'px ui-monospace, Menlo, Consolas, monospace'; ctx.textBaseline = 'middle'; ctx.textAlign = 'center';
    const doneFn = (t, i) => (S.viz ? vizDone(t, i) : lineDone(t, i));
    S.p.cols.forEach((c, x) => {
      const done = doneFn('c', x), arr = c.length ? c : [0];
      ctx.fillStyle = done ? grid : (S.viz && S.viz.cur && S.viz.cur.t === 'c' && S.viz.cur.i === x ? accent : ink);
      arr.forEach((v, k) => ctx.fillText(v, left + x * cell + cell / 2, top - 6 - (arr.length - 1 - k) * cell * 0.8 - cell * 0.35));
    });
    ctx.textAlign = 'right';
    S.p.rows.forEach((c, y) => {
      const done = doneFn('r', y), arr = c.length ? c : [0];
      ctx.fillStyle = done ? grid : (S.viz && S.viz.cur && S.viz.cur.t === 'r' && S.viz.cur.i === y ? accent : ink);
      arr.forEach((v, k) => ctx.fillText(v, left - 8 - (arr.length - 1 - k) * cell * 0.8, top + y * cell + cell / 2 + 1));
    });
    if (S.solved) { ctx.fillStyle = good; ctx.globalAlpha = 0.12; ctx.fillRect(left, top, S.w * cell, S.h * cell); ctx.globalAlpha = 1; }
  }
  function line(a, b, c, d) { ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke(); }
  function roundRect(x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  // ---------- input ----------
  function cellAt(ev) {
    const r = canvas.getBoundingClientRect(), g = S.geom;
    const k = g.W / r.width, ky = g.H / r.height; // canvas may be CSS-shrunk on narrow screens
    const x = Math.floor(((ev.clientX - r.left) * k - g.left) / g.cell), y = Math.floor(((ev.clientY - r.top) * ky - g.top) / g.cell);
    return x >= 0 && y >= 0 && x < S.w && y < S.h ? { x, y } : null;
  }
  function setCell(i, v, entry) {
    const old = S.marks[i]; if (old === v) return;
    S.marks[i] = v; entry.push([i, old, v]);
  }
  canvas.addEventListener('contextmenu', e => e.preventDefault());
  canvas.addEventListener('pointerdown', ev => {
    if (S.viz || S.solved || !S.p) return;
    const c = cellAt(ev); if (!c) return;
    ev.preventDefault(); canvas.setPointerCapture(ev.pointerId);
    clearAnnotations();
    const want = (ev.button === 2 || ev.shiftKey || S.tool === 'cross') ? 0 : 1;
    const i = c.y * S.w + c.x, cur = S.marks[i];
    const paint = cur === want ? -1 : want;
    S.drag = { paint, start: cur, want, entry: [], axis: null, x0: c.x, y0: c.y };
    applyDrag(c);
  });
  canvas.addEventListener('pointermove', ev => {
    if (!S.drag) return;
    const c = cellAt(ev); if (!c) return;
    const d = S.drag;
    if (!d.axis && (c.x !== d.x0 || c.y !== d.y0)) d.axis = Math.abs(c.x - d.x0) >= Math.abs(c.y - d.y0) ? 'h' : 'v';
    applyDrag(d.axis === 'h' ? { x: c.x, y: d.y0 } : d.axis === 'v' ? { x: d.x0, y: c.y } : c);
  });
  function applyDrag(c) {
    const d = S.drag, i = c.y * S.w + c.x, cur = S.marks[i];
    if (d.paint === -1 ? cur === d.want : cur === -1) { setCell(i, d.paint, d.entry); draw(); }
  }
  function endDrag() {
    const d = S.drag; if (!d) return; S.drag = null;
    if (!d.entry.length) return;
    if ($('optAuto').checked) autoCross(d.entry);
    S.undo.push(d.entry); S.redo = [];
    afterChange();
  }
  canvas.addEventListener('pointerup', endDrag); canvas.addEventListener('pointercancel', endDrag);

  function autoCross(entry) {
    for (let y = 0; y < S.h; y++) if (lineDone('r', y)) for (let x = 0; x < S.w; x++) if (S.marks[y * S.w + x] === -1) setCell(y * S.w + x, 0, entry);
    for (let x = 0; x < S.w; x++) if (lineDone('c', x)) for (let y = 0; y < S.h; y++) if (S.marks[y * S.w + x] === -1) setCell(y * S.w + x, 0, entry);
  }
  function checkWin() {
    for (let y = 0; y < S.h; y++) if (!lineDone('r', y)) return false;
    for (let x = 0; x < S.w; x++) if (!lineDone('c', x)) return false;
    return true;
  }
  function afterChange() {
    S.bad = new Set();
    if (checkWin()) {
      S.solved = true; S.elapsed = Math.floor((Date.now() - S.t0) / 1000); renderTimer();
      // tidy: unknown cells become crosses so the picture reads cleanly
      const last = S.undo[S.undo.length - 1];
      for (let i = 0; i < S.marks.length; i++) if (S.marks[i] === -1) setCell(i, 0, last);
      showBanner('Solved in ' + $('timer').textContent + (S.unique ? '' : ' (one of several valid grids)'));
    }
    draw(); updateButtons();
  }
  function clearAnnotations() { S.hl = null; S.hintCells = []; S.bad = new Set(); hideHint(); }

  function undo() {
    if (S.viz || !S.undo.length) return; S.solved = false; hideBanner();
    const e = S.undo.pop(); for (let k = e.length - 1; k >= 0; k--) S.marks[e[k][0]] = e[k][1];
    S.redo.push(e); clearAnnotations(); draw(); updateButtons();
  }
  function redo() {
    if (S.viz || !S.redo.length) return;
    const e = S.redo.pop(); for (const [i, , n] of e) S.marks[i] = n;
    S.undo.push(e); clearAnnotations(); afterChange();
  }
  function updateButtons() { $('btnUndo').disabled = !!S.viz || !S.undo.length; $('btnRedo').disabled = !!S.viz || !S.redo.length; }

  // ---------- hints / check ----------
  function hint() {
    if (S.viz || !S.p) return;
    if (S.solved) return showHint('Already solved!');
    if (S.unique) {
      const wrong = [];
      for (let i = 0; i < S.marks.length; i++) { const v = S.marks[i]; if (v !== -1 && v !== S.solution[(i / S.w) | 0][i % S.w]) wrong.push(i); }
      if (wrong.length) {
        S.bad = new Set(wrong); S.hl = null; S.hintCells = [];
        showHint('Before hinting: ' + wrong.length + ' mark' + (wrong.length === 1 ? ' is' : 's are') + ' wrong (red). Fix ' + (wrong.length === 1 ? 'it' : 'them') + ' and ask again.'); return draw();
      }
    }
    const h = E.findHint(S.p, S.marks);
    S.hintCells = h.cells || []; S.hl = h.t != null ? { t: h.t, i: h.i } : null;
    showHint(h.message); draw();
  }
  function check() {
    if (S.viz || !S.p || S.solved) return;
    S.bad = new Set(); S.hintCells = []; S.hl = null;
    if (S.unique) {
      for (let i = 0; i < S.marks.length; i++) {
        const v = S.marks[i], sol = S.solution[(i / S.w) | 0][i % S.w];
        if (v !== -1 && v !== sol) S.bad.add(i);
      }
      showHint(S.bad.size ? S.bad.size + ' cell' + (S.bad.size === 1 ? ' is' : 's are') + ' wrong (shown in red).' : 'No mistakes so far — keep going.');
    } else {
      const h = E.findHint(S.p, S.marks);
      showHint(h.kind === 'mistake' ? h.message : 'No contradictions found.');
      if (h.kind === 'mistake') S.hl = { t: h.t, i: h.i };
    }
    draw();
  }
  function showHint(t) { const b = $('hintBox'); b.hidden = false; b.textContent = t; }
  function hideHint() { $('hintBox').hidden = true; }
  function showBanner(t, err) { const b = $('banner'); b.hidden = false; b.textContent = t; b.className = 'banner' + (err ? ' err' : ''); }
  function hideBanner() { $('banner').hidden = true; }

  function clearBoard() {
    if (S.viz || !S.p) return;
    const e = []; for (let i = 0; i < S.marks.length; i++) setCell(i, -1, e);
    S.solved = false; hideBanner(); clearAnnotations();
    if (e.length) { S.undo.push(e); S.redo = []; }
    draw(); updateButtons();
  }
  function reveal() {
    if (!S.p) return; stopViz(true);
    const e = [];
    for (let y = 0; y < S.h; y++) for (let x = 0; x < S.w; x++) setCell(y * S.w + x, S.solution[y][x] ? 1 : 0, e);
    if (e.length) { S.undo.push(e); S.redo = []; }
    clearAnnotations(); S.solved = true; showBanner('Solution revealed'); draw(); updateButtons();
  }

  // ---------- solver visualiser ----------
  function vizDone(t, i) {
    const b = S.viz.board, cells = t === 'r' ? E.rowOf(b, i) : E.colOf(b, i);
    return !cells.includes(-1) && (() => { const f = E.lineClue(cells), c = (t === 'r' ? S.p.rows : S.p.cols)[i]; return f.length === c.length && f.every((v, k) => v === c[k]); })();
  }
  function startViz() {
    if (!S.p) return;
    stopViz(true); hideBanner(); clearAnnotations();
    const board = E.makeBoard(S.p), probe = E.makeBoard(S.p);
    const r = E.propagate(probe, { trace: true });
    const steps = (r.steps || []).slice();
    let info = '';
    if (!E.isSolved(probe)) {
      const sol = E.solve(S.p, { limit: 1 });
      if (sol.count) {
        const cells = [];
        for (let y = 0; y < S.h; y++) for (let x = 0; x < S.w; x++) if (probe.cells[y * S.w + x] === -1) cells.push([x, y, sol.solutions[0][y][x]]);
        steps.push({ t: null, i: -1, cells, guess: true });
        info = 'Line logic stalls with ' + cells.length + ' cells open; the last step is the search (' + sol.stats.guesses + ' guesses).';
      }
    }
    S.viz = { board, steps, idx: 0, playing: true, timer: null, total: steps.length, cur: null, info };
    $('vizCtl').hidden = false; $('vizPlay').textContent = 'Pause'; $('btnViz').disabled = true;
    updateVizInfo(); updateButtons(); scheduleViz();
  }
  function scheduleViz() {
    if (!S.viz) return; clearTimeout(S.viz.timer);
    if (S.viz.playing) S.viz.timer = setTimeout(() => { stepViz(); scheduleViz(); }, 1100 - $('vizSpeed').value * 100);
  }
  function stepViz() {
    const v = S.viz; if (!v) return;
    if (v.idx >= v.steps.length) { v.playing = false; $('vizPlay').textContent = 'Replay'; return; }
    const st = v.steps[v.idx++];
    v.cur = st.t ? { t: st.t, i: st.i } : null;
    for (const [x, y, val] of st.cells) v.board.cells[y * S.w + x] = val;
    updateVizInfo(st); draw();
  }
  function updateVizInfo(st) {
    const v = S.viz; if (!v) return;
    let t = 'Step ' + v.idx + ' / ' + v.total;
    if (st) t += st.guess ? ' — search fills the remaining ' + st.cells.length + ' cells.' : ' — ' + (st.t === 'r' ? 'row ' : 'column ') + (st.i + 1) + ' forces ' + st.cells.length + ' cell' + (st.cells.length === 1 ? '' : 's') + '.';
    if (v.idx >= v.total) t += ' Done. ' + v.info;
    $('vizInfo').textContent = t;
  }
  function stopViz(silent) {
    if (!S.viz) return; clearTimeout(S.viz.timer); S.viz = null;
    $('vizCtl').hidden = true; $('btnViz').disabled = false;
    if (!silent) draw(); updateButtons();
  }

  // ---------- import / export ----------
  function io(msg, cls) { const n = $('ioNote'); n.textContent = msg; n.className = 'note ' + (cls || ''); }
  function safeLoad(p, o) { try { loadPuzzle(p, o); return true; } catch (e) { io(e.message, 'err'); return false; } }
  $('btnShare').onclick = async () => {
    if (!S.p) return;
    const url = location.href.split('#')[0] + '#p=' + E.encodeShare(S.p);
    try { await navigator.clipboard.writeText(url); io('Share link copied (' + url.length + ' chars).', 'ok'); }
    catch (e) { history.replaceState(null, '', '#p=' + E.encodeShare(S.p)); io('Clipboard unavailable — copy the address bar URL.', ''); }
  };
  $('btnExport').onclick = () => {
    if (!S.p) return;
    const blob = new Blob([E.toNon(S.p, S.title || 'Inkgrid ' + S.w + 'x' + S.h)], { type: 'text/plain' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'inkgrid-' + S.w + 'x' + S.h + '.non'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000); io('Exported .non file.', 'ok');
  };
  $('btnPaste').onclick = () => { $('pasteBox').hidden = !$('pasteBox').hidden; };
  $('pasteCancel').onclick = () => { $('pasteBox').hidden = true; };
  $('pasteGo').onclick = () => {
    try {
      const p = E.parsePuzzle($('pasteText').value);
      if (safeLoad(p, { title: p.title })) { $('pasteBox').hidden = true; io('Loaded ' + S.w + '×' + S.h + ' puzzle.', 'ok'); }
    } catch (e) { io(e.message, 'err'); }
  };
  $('btnImage').onclick = () => $('fileImg').click();
  $('fileImg').onchange = ev => {
    const f = ev.target.files[0]; ev.target.value = ''; if (!f) return;
    if (!/^image\//.test(f.type)) return io('That file is not an image.', 'err');
    const img = new Image(), url = URL.createObjectURL(f);
    img.onerror = () => { URL.revokeObjectURL(url); io('Could not decode that image.', 'err'); };
    img.onload = () => {
      URL.revokeObjectURL(url);
      try {
        const gw = Math.min(40, Math.max(3, +$('optW').value)), gh = Math.min(40, Math.max(3, +$('optH').value));
        const sc = Math.min(1, 480 / Math.max(img.width, img.height)), cw = Math.max(1, Math.round(img.width * sc)), ch = Math.max(1, Math.round(img.height * sc));
        const cv = document.createElement('canvas'); cv.width = cw; cv.height = ch;
        const c2 = cv.getContext('2d'); c2.fillStyle = '#fff'; c2.fillRect(0, 0, cw, ch); c2.drawImage(img, 0, 0, cw, ch);
        const grid = E.gridFromRGBA(c2.getImageData(0, 0, cw, ch).data, cw, ch, gw, gh);
        const filled = grid.flat().reduce((a, b) => a + b, 0);
        if (filled === 0 || filled === gw * gh) return io('The image is a single tone at this size — nothing to draw. Try a higher-contrast picture.', 'err');
        const uni = E.makeUnique(grid, E.mulberry32(E.hashSeed(f.name)));
        if (!uni) return io('Could not make this picture uniquely solvable; try a different size.', 'err');
        let changed = 0; for (let y = 0; y < gh; y++) for (let x = 0; x < gw; x++) if (uni[y][x] !== grid[y][x]) changed++;
        const p = E.cluesFromGrid(uni);
        if (safeLoad(p, { grid: uni, title: f.name })) io('Built a ' + gw + '×' + gh + ' puzzle from your image; ' + changed + ' pixel' + (changed === 1 ? '' : 's') + ' adjusted to make the solution unique.', 'ok');
      } catch (e) { io(e.message, 'err'); }
    };
    img.src = url;
  };

  // ---------- wiring ----------
  $('btnNew').onclick = generate;
  $('toolFill').onclick = () => setTool('fill'); $('toolCross').onclick = () => setTool('cross');
  function setTool(t) { S.tool = t; $('toolFill').classList.toggle('on', t === 'fill'); $('toolCross').classList.toggle('on', t === 'cross'); }
  $('btnUndo').onclick = undo; $('btnRedo').onclick = redo; $('btnHint').onclick = hint; $('btnCheck').onclick = check; $('btnClear').onclick = clearBoard;
  $('btnViz').onclick = startViz; $('btnReveal').onclick = reveal;
  $('vizPlay').onclick = () => {
    const v = S.viz; if (!v) return;
    if (v.idx >= v.steps.length) { v.board = E.makeBoard(S.p); v.idx = 0; v.cur = null; v.playing = true; }
    else v.playing = !v.playing;
    $('vizPlay').textContent = v.playing ? 'Pause' : 'Play'; scheduleViz(); draw();
  };
  $('vizStep').onclick = () => { if (S.viz) { S.viz.playing = false; clearTimeout(S.viz.timer); $('vizPlay').textContent = 'Play'; stepViz(); } };
  $('vizExit').onclick = () => stopViz();
  $('vizSpeed').oninput = scheduleViz;
  $('optDens').oninput = () => { $('densOut').textContent = $('optDens').value + '%'; };
  document.addEventListener('keydown', e => {
    if (/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); }
    else if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); redo(); }
    else if (k === 'h') hint(); else if (k === 'x') setTool(S.tool === 'fill' ? 'cross' : 'fill');
  });
  let rz; window.addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(() => { layout(); draw(); }, 80); });
  if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', draw);

  // ---------- boot ----------
  function boot() {
    const m = /[#&]p=([^&]*)/.exec(location.hash);
    if (m) {
      try { loadPuzzle(E.decodeShare(m[1])); io('Loaded puzzle from share link.', 'ok'); return; }
      catch (e) { io(e.message, 'err'); }
    }
    $('optSeed').value = 'inkgrid'; generate();
  }
  window.__inkgrid = { S, E, loadPuzzle, hint, check }; // handy for debugging & the browser test
  boot();
})();
