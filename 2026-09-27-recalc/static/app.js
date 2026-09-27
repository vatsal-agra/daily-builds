// Recalc grid UI. This file renders state and forwards every mutation to
// the server; it never computes a formula result itself — every value on
// screen came back from the real Python engine.
(function () {
  "use strict";

  const NUM_COLS = 26;
  const NUM_ROWS = 50;

  function colLetters(n) {
    let s = "";
    while (n > 0) {
      const rem = (n - 1) % 26;
      s = String.fromCharCode(65 + rem) + s;
      n = Math.floor((n - 1) / 26);
    }
    return s;
  }

  function addr(col, row) {
    return colLetters(col) + row;
  }

  // -- DOM refs -------------------------------------------------------------

  const gridEl = document.getElementById("grid");
  const gridScroll = document.getElementById("grid-scroll");
  const gridWrapper = document.getElementById("grid-wrapper");
  const formulaInput = document.getElementById("formula-input");
  const cellAddressEl = document.getElementById("cell-address");
  const cellEditor = document.getElementById("cell-editor");
  const statusEl = document.getElementById("status");

  // -- build the fixed grid once ---------------------------------------------

  const cellEls = {}; // "col,row" -> <td>
  const fillHandle = document.createElement("div");
  fillHandle.id = "fill-handle";
  fillHandle.hidden = true;

  function buildGrid() {
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    const corner = document.createElement("th");
    corner.className = "corner";
    headRow.appendChild(corner);
    for (let c = 1; c <= NUM_COLS; c++) {
      const th = document.createElement("th");
      th.textContent = colLetters(c);
      headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    gridEl.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (let r = 1; r <= NUM_ROWS; r++) {
      const tr = document.createElement("tr");
      const rowHead = document.createElement("th");
      rowHead.className = "row-head";
      rowHead.textContent = String(r);
      tr.appendChild(rowHead);
      for (let c = 1; c <= NUM_COLS; c++) {
        const td = document.createElement("td");
        td.dataset.col = c;
        td.dataset.row = r;
        tr.appendChild(td);
        cellEls[c + "," + r] = td;
      }
      tbody.appendChild(tr);
    }
    gridEl.appendChild(tbody);
    gridWrapper.appendChild(fillHandle);
  }

  buildGrid();

  // -- application state ------------------------------------------------------

  const data = {}; // "A1" -> {raw, display, error}
  let bounds = [0, 0];
  let canUndo = false;
  let canRedo = false;

  let sel = { c1: 1, r1: 1, c2: 1, r2: 1, active: true };
  let editing = null; // {col, row}
  let clipboard = null; // {c1,r1,c2,r2}

  function normSel() {
    return {
      c1: Math.min(sel.c1, sel.c2), r1: Math.min(sel.r1, sel.r2),
      c2: Math.max(sel.c1, sel.c2), r2: Math.max(sel.r1, sel.r2),
    };
  }

  function isSingleCellSelection() {
    return sel.c1 === sel.c2 && sel.r1 === sel.r2;
  }

  // -- rendering --------------------------------------------------------------

  function renderCell(col, row) {
    const td = cellEls[col + "," + row];
    if (!td) return;
    const cell = data[addr(col, row)];
    if (!cell || cell.display === "") {
      td.textContent = "";
      td.classList.remove("error-cell", "text-cell");
      return;
    }
    td.textContent = cell.display;
    td.classList.toggle("error-cell", !!cell.error);
    const looksNumeric = /^-?[\d.]+$/.test(cell.display);
    td.classList.toggle("text-cell", !looksNumeric && !cell.error);
  }

  function renderAllCells() {
    for (let r = 1; r <= NUM_ROWS; r++) {
      for (let c = 1; c <= NUM_COLS; c++) renderCell(c, r);
    }
  }

  const colHeadEls = {};
  const rowHeadEls = {};
  document.querySelectorAll("#grid thead th:not(.corner)").forEach((th, i) => { colHeadEls[i + 1] = th; });
  document.querySelectorAll("#grid tbody th.row-head").forEach((th, i) => { rowHeadEls[i + 1] = th; });

  function updateSelectionVisuals() {
    for (const key in cellEls) cellEls[key].classList.remove("selected", "selected-range");
    for (const key in colHeadEls) colHeadEls[key].classList.remove("head-active");
    for (const key in rowHeadEls) rowHeadEls[key].classList.remove("head-active");
    const n = normSel();
    for (let r = n.r1; r <= n.r2; r++) {
      for (let c = n.c1; c <= n.c2; c++) {
        const td = cellEls[c + "," + r];
        if (!td) continue;
        td.classList.add(c === sel.c2 && r === sel.r2 ? "selected" : "selected-range");
      }
    }
    for (let c = n.c1; c <= n.c2; c++) { if (colHeadEls[c]) colHeadEls[c].classList.add("head-active"); }
    for (let r = n.r1; r <= n.r2; r++) { if (rowHeadEls[r]) rowHeadEls[r].classList.add("head-active"); }
    // formula bar reflects the active (most-recently-touched) cell
    cellAddressEl.textContent = addr(sel.c2, sel.r2);
    const activeCell = data[addr(sel.c2, sel.r2)];
    if (!editing) formulaInput.value = activeCell ? activeCell.raw : "";

    positionFillHandle();
  }

  function positionFillHandle() {
    if (!isSingleCellSelection() || editing) {
      fillHandle.hidden = true;
      return;
    }
    const td = cellEls[sel.c2 + "," + sel.r2];
    if (!td) { fillHandle.hidden = true; return; }
    const wrapRect = gridWrapper.getBoundingClientRect();
    const tdRect = td.getBoundingClientRect();
    fillHandle.hidden = false;
    fillHandle.style.left = (tdRect.right - wrapRect.left + gridScroll.scrollLeft - 4) + "px";
    fillHandle.style.top = (tdRect.bottom - wrapRect.top + gridScroll.scrollTop - 4) + "px";
  }

  function updateClipboardVisuals() {
    for (const key in cellEls) cellEls[key].classList.remove("clip-marching");
    if (!clipboard) return;
    for (let r = clipboard.r1; r <= clipboard.r2; r++) {
      for (let c = clipboard.c1; c <= clipboard.c2; c++) {
        const td = cellEls[c + "," + r];
        if (td) td.classList.add("clip-marching");
      }
    }
  }

  function setStatus(msg, isError) {
    statusEl.textContent = msg || "";
    statusEl.style.color = isError ? "var(--error)" : "var(--text-dim)";
    if (msg) setTimeout(() => { if (statusEl.textContent === msg) statusEl.textContent = ""; }, 4000);
  }

  // -- server I/O ---------------------------------------------------------

  async function api(path, body) {
    const resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || ("request failed: " + resp.status));
    }
    return resp.json();
  }

  function applyResponse(resp) {
    if (resp.full) {
      for (const key in data) delete data[key];
    }
    for (const cell of resp.cells) {
      data[cell.addr] = cell;
    }
    bounds = resp.bounds;
    canUndo = resp.can_undo;
    canRedo = resp.can_redo;
    if (resp.full) {
      renderAllCells();
    } else {
      for (const cell of resp.cells) renderCell(cell.col, cell.row);
    }
    document.getElementById("btn-undo").disabled = !canUndo;
    document.getElementById("btn-redo").disabled = !canRedo;
    updateSelectionVisuals();
  }

  async function loadInitialSheet() {
    const resp = await fetch("/api/sheet");
    const json = await resp.json();
    json.full = true;
    applyResponse(json);
  }

  // -- selection & navigation ------------------------------------------------

  function selectCell(col, row, extend) {
    col = Math.max(1, Math.min(NUM_COLS, col));
    row = Math.max(1, Math.min(NUM_ROWS, row));
    if (extend) {
      sel.c2 = col; sel.r2 = row;
    } else {
      sel.c1 = col; sel.r1 = row; sel.c2 = col; sel.r2 = row;
    }
    updateSelectionVisuals();
  }

  let mouseSelecting = false;
  gridEl.addEventListener("mousedown", (e) => {
    const td = e.target.closest("td");
    if (!td) return;
    if (editing) commitEdit(null);
    const col = Number(td.dataset.col), row = Number(td.dataset.row);
    selectCell(col, row, e.shiftKey);
    mouseSelecting = true;
    e.preventDefault();
  });
  gridEl.addEventListener("mousemove", (e) => {
    if (!mouseSelecting) return;
    const td = e.target.closest("td");
    if (!td) return;
    selectCell(Number(td.dataset.col), Number(td.dataset.row), true);
  });
  window.addEventListener("mouseup", () => { mouseSelecting = false; });

  gridEl.addEventListener("dblclick", (e) => {
    const td = e.target.closest("td");
    if (!td) return;
    startEdit(Number(td.dataset.col), Number(td.dataset.row), null);
  });

  // -- editing ------------------------------------------------------------

  function startEdit(col, row, initialText) {
    editing = { col, row };
    const cell = data[addr(col, row)];
    const text = initialText !== null ? initialText : (cell ? cell.raw : "");
    const td = cellEls[col + "," + row];
    const wrapRect = gridWrapper.getBoundingClientRect();
    const tdRect = td.getBoundingClientRect();
    cellEditor.hidden = false;
    cellEditor.style.left = (tdRect.left - wrapRect.left + gridScroll.scrollLeft) + "px";
    cellEditor.style.top = (tdRect.top - wrapRect.top + gridScroll.scrollTop) + "px";
    cellEditor.style.width = tdRect.width + "px";
    cellEditor.style.height = tdRect.height + "px";
    cellEditor.value = text;
    formulaInput.value = text;
    cellEditor.focus();
    if (initialText !== null) {
      cellEditor.setSelectionRange(text.length, text.length);
    } else {
      cellEditor.select();
    }
    positionFillHandle();
  }

  async function commitEdit(moveDir) {
    if (!editing) return;
    const { col, row } = editing;
    const text = cellEditor.value;
    editing = null;
    cellEditor.hidden = true;
    // Move the selection and restore focus to the grid *before* awaiting
    // the network round-trip, not after: with the move deferred into a
    // `.then()` that only ran once the response came back, focus briefly
    // belonged to no element in the grid at all (the just-hidden editor
    // isn't it, and grid-wrapper hadn't been refocused yet). Typing
    // quickly right after Enter/Tab — the normal way to fill in a row —
    // could then lose its first keystroke(s) to nothing, landing instead
    // whenever the fetch happened to resolve. Real bug, found only by
    // actually typing several cells in a row in a live browser and
    // reading back what actually got stored, not from any test that
    // waits between actions.
    if (moveDir === "down") selectCell(col, row + 1, false);
    else if (moveDir === "right") selectCell(col + 1, row, false);
    else selectCell(col, row, false);
    gridWrapper.focus();
    try {
      const resp = await api("/api/cell", { col, row, raw: text });
      applyResponse(resp);
    } catch (err) {
      setStatus(String(err.message || err), true);
    }
  }

  function cancelEdit() {
    editing = null;
    cellEditor.hidden = true;
    updateSelectionVisuals();
    gridWrapper.focus();
  }

  cellEditor.addEventListener("keydown", (e) => {
    // #cell-editor is a DOM child of #grid-wrapper (so it can be
    // absolutely positioned over the cell it's editing), so without
    // stopPropagation these keydowns bubble up into grid-wrapper's own
    // keydown listener. That listener guards on `if (editing) return`,
    // but `editing` is already cleared by commitEdit's synchronous half
    // before the bubbled event arrives — so it fell through and started
    // a second, phantom edit on the *same* cell with an empty value,
    // later silently committed (clearing the cell!) whenever the next
    // click's mousedown handler saw `editing` truthy and auto-committed
    // it. Caught only by watching real POST bodies in a live browser,
    // not by any engine-level test, since the engine itself never wrote
    // anything wrong.
    if (e.key === "Enter") {
      e.preventDefault();
      e.stopPropagation();
      commitEdit("down");
    } else if (e.key === "Tab") {
      e.preventDefault();
      e.stopPropagation();
      commitEdit("right");
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      cancelEdit();
    }
  });
  cellEditor.addEventListener("input", () => { formulaInput.value = cellEditor.value; });

  formulaInput.addEventListener("focus", () => {
    if (!editing) startEdit(sel.c2, sel.r2, null);
  });
  formulaInput.addEventListener("input", () => {
    if (editing) cellEditor.value = formulaInput.value;
  });
  formulaInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      cellEditor.value = formulaInput.value;
      commitEdit("down");
    } else if (e.key === "Escape") {
      cancelEdit();
    }
  });

  // -- keyboard navigation (grid focused, not editing) ----------------------

  gridWrapper.tabIndex = 0;
  gridWrapper.addEventListener("keydown", (e) => {
    if (editing) return;
    const key = e.key;
    if (key === "ArrowUp") { selectCell(sel.c2, sel.r2 - 1, e.shiftKey); e.preventDefault(); }
    else if (key === "ArrowDown") { selectCell(sel.c2, sel.r2 + 1, e.shiftKey); e.preventDefault(); }
    else if (key === "ArrowLeft") { selectCell(sel.c2 - 1, sel.r2, e.shiftKey); e.preventDefault(); }
    else if (key === "ArrowRight") { selectCell(sel.c2 + 1, sel.r2, e.shiftKey); e.preventDefault(); }
    else if (key === "Enter") { startEdit(sel.c2, sel.r2, null); e.preventDefault(); }
    else if (key === "Tab") { selectCell(sel.c2 + 1, sel.r2, false); e.preventDefault(); }
    else if (key === "Delete" || key === "Backspace") { clearSelection(); e.preventDefault(); }
    else if ((e.ctrlKey || e.metaKey) && key.toLowerCase() === "c") { copySelection(); e.preventDefault(); }
    else if ((e.ctrlKey || e.metaKey) && key.toLowerCase() === "v") { pasteClipboard(); e.preventDefault(); }
    else if ((e.ctrlKey || e.metaKey) && key.toLowerCase() === "z") { doUndo(); e.preventDefault(); }
    else if ((e.ctrlKey || e.metaKey) && (key.toLowerCase() === "y" || (key.toLowerCase() === "z" && e.shiftKey))) { doRedo(); e.preventDefault(); }
    else if (key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // Without preventDefault, the same keydown's default action fires
      // *after* startEdit synchronously moves focus to #cell-editor,
      // inserting this character a second time (e.g. typing "=" produced
      // the raw formula "==A1*3" — a real bug caught only by driving the
      // actual browser, not by any engine-level test).
      e.preventDefault();
      startEdit(sel.c2, sel.r2, key);
    }
  });

  // -- clipboard / clear ----------------------------------------------------

  function copySelection() {
    const n = normSel();
    clipboard = n;
    updateClipboardVisuals();
    setStatus("Copied " + addr(n.c1, n.r1) + (n.c1 !== n.c2 || n.r1 !== n.r2 ? ":" + addr(n.c2, n.r2) : ""));
  }

  async function pasteClipboard() {
    if (!clipboard) { setStatus("Nothing to paste", true); return; }
    const n = normSel();
    try {
      const resp = await api("/api/paste", {
        src: [clipboard.c1, clipboard.r1, clipboard.c2, clipboard.r2],
        dest: [n.c1, n.r1],
      });
      applyResponse(resp);
    } catch (err) {
      setStatus(String(err.message || err), true);
    }
  }

  async function clearSelection() {
    const n = normSel();
    try {
      const resp = await api("/api/clear", { range: [n.c1, n.r1, n.c2, n.r2] });
      applyResponse(resp);
    } catch (err) {
      setStatus(String(err.message || err), true);
    }
  }

  async function doUndo() {
    try { applyResponse(await api("/api/undo")); } catch (err) { setStatus(String(err.message || err), true); }
  }
  async function doRedo() {
    try { applyResponse(await api("/api/redo")); } catch (err) { setStatus(String(err.message || err), true); }
  }

  // -- fill handle drag -------------------------------------------------------

  let fillDragActive = false;
  fillHandle.addEventListener("mousedown", (e) => {
    fillDragActive = true;
    e.preventDefault();
    e.stopPropagation();
  });
  window.addEventListener("mousemove", (e) => {
    if (!fillDragActive) return;
    const td = document.elementFromPoint(e.clientX, e.clientY);
    const cellTd = td && td.closest ? td.closest("td") : null;
    if (!cellTd) return;
    const c = Number(cellTd.dataset.col), r = Number(cellTd.dataset.row);
    for (const key in cellEls) cellEls[key].classList.remove("selected-range");
    const c1 = Math.min(sel.c2, c), c2 = Math.max(sel.c2, c);
    const r1 = Math.min(sel.r2, r), r2 = Math.max(sel.r2, r);
    for (let rr = r1; rr <= r2; rr++) {
      for (let cc = c1; cc <= c2; cc++) {
        const t = cellEls[cc + "," + rr];
        if (t) t.classList.add("selected-range");
      }
    }
  });
  window.addEventListener("mouseup", async (e) => {
    if (!fillDragActive) return;
    fillDragActive = false;
    const td = document.elementFromPoint(e.clientX, e.clientY);
    const cellTd = td && td.closest ? td.closest("td") : null;
    updateSelectionVisuals();
    if (!cellTd) return;
    const c = Number(cellTd.dataset.col), r = Number(cellTd.dataset.row);
    if (c === sel.c2 && r === sel.r2) return;
    const c1 = Math.min(sel.c2, c), c2 = Math.max(sel.c2, c);
    const r1 = Math.min(sel.r2, r), r2 = Math.max(sel.r2, r);
    try {
      const resp = await api("/api/fill", { src: [sel.c2, sel.r2], dest: [c1, r1, c2, r2] });
      applyResponse(resp);
      sel = { c1: sel.c2, r1: sel.r2, c2: c2, r2: r2 };
      updateSelectionVisuals();
    } catch (err) {
      setStatus(String(err.message || err), true);
    }
  });

  // -- toolbar --------------------------------------------------------------

  function forgetClipboard() {
    clipboard = null;
    updateClipboardVisuals();
  }

  document.getElementById("btn-new").addEventListener("click", async () => {
    if (!confirm("Start a new, empty workbook? This clears the current sheet.")) return;
    forgetClipboard();
    try { applyResponse(await api("/api/new")); } catch (err) { setStatus(String(err.message || err), true); }
  });
  document.getElementById("btn-undo").addEventListener("click", doUndo);
  document.getElementById("btn-redo").addEventListener("click", doRedo);
  document.getElementById("btn-copy").addEventListener("click", copySelection);
  document.getElementById("btn-paste").addEventListener("click", pasteClipboard);
  document.getElementById("btn-clear").addEventListener("click", clearSelection);

  document.getElementById("btn-export-csv").addEventListener("click", () => {
    window.location.href = "/api/export_csv";
  });
  document.getElementById("btn-save").addEventListener("click", () => {
    window.location.href = "/api/save";
  });

  document.getElementById("btn-import-csv").addEventListener("click", () => {
    document.getElementById("file-import-csv").click();
  });
  document.getElementById("file-import-csv").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    const n = normSel();
    forgetClipboard();
    try {
      const resp = await api("/api/import_csv", { text, origin: [n.c1, n.r1] });
      applyResponse(resp);
      setStatus("Imported " + file.name);
    } catch (err) {
      setStatus(String(err.message || err), true);
    }
    e.target.value = "";
  });

  document.getElementById("btn-load").addEventListener("click", () => {
    document.getElementById("file-load").click();
  });
  document.getElementById("file-load").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    forgetClipboard();
    try {
      const resp = await api("/api/load", { text });
      applyResponse(resp);
      setStatus("Loaded " + file.name);
    } catch (err) {
      setStatus(String(err.message || err), true);
    }
    e.target.value = "";
  });

  // -- chart ------------------------------------------------------------------

  const chartPanel = document.getElementById("chart-panel");
  const chartCanvas = document.getElementById("chart-canvas");
  const chartTypeSel = document.getElementById("chart-type");

  function drawChart() {
    const n = normSel();
    const labels = [];
    const values = [];
    for (let r = n.r1; r <= n.r2; r++) {
      for (let c = n.c1; c <= n.c2; c++) {
        const cell = data[addr(c, r)];
        const num = cell ? parseFloat(cell.display) : NaN;
        labels.push(addr(c, r));
        values.push(isNaN(num) ? 0 : num);
      }
    }
    const ctx = chartCanvas.getContext("2d");
    const W = chartCanvas.width, H = chartCanvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#8b93a7";
    ctx.font = "11px sans-serif";

    if (values.length === 0) {
      ctx.fillText("Select a range with numeric values first.", 16, H / 2);
      return;
    }
    const padding = 32;
    const maxV = Math.max(0, ...values);
    const minV = Math.min(0, ...values);
    const range = (maxV - minV) || 1;
    const plotW = W - padding * 2;
    const plotH = H - padding * 2;
    const zeroY = padding + plotH * (1 - (0 - minV) / range);

    // axes
    ctx.strokeStyle = "#383e50";
    ctx.beginPath();
    ctx.moveTo(padding, zeroY);
    ctx.lineTo(W - padding, zeroY);
    ctx.stroke();

    const type = chartTypeSel.value;
    const n2 = values.length;
    if (type === "bar") {
      const bw = plotW / n2;
      values.forEach((v, i) => {
        const barH = plotH * (Math.abs(v) / range);
        const x = padding + i * bw + bw * 0.15;
        const y = v >= 0 ? zeroY - barH : zeroY;
        ctx.fillStyle = v >= 0 ? "#5b8cff" : "#ff6b6b";
        ctx.fillRect(x, y, bw * 0.7, barH);
      });
    } else {
      ctx.strokeStyle = "#5b8cff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      values.forEach((v, i) => {
        const x = padding + (n2 === 1 ? plotW / 2 : (i / (n2 - 1)) * plotW);
        const y = padding + plotH * (1 - (v - minV) / range);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = "#5b8cff";
      values.forEach((v, i) => {
        const x = padding + (n2 === 1 ? plotW / 2 : (i / (n2 - 1)) * plotW);
        const y = padding + plotH * (1 - (v - minV) / range);
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    ctx.fillStyle = "#8b93a7";
    labels.forEach((label, i) => {
      const x = padding + (n2 === 1 ? plotW / 2 : (i / Math.max(1, n2 - (type === "bar" ? 0 : 1))) * plotW) + (type === "bar" ? plotW / n2 * 0.15 : -8);
      ctx.fillText(label, Math.min(W - 24, Math.max(0, x)), H - 8);
    });
  }

  document.getElementById("btn-chart").addEventListener("click", () => {
    chartPanel.hidden = !chartPanel.hidden;
    if (!chartPanel.hidden) drawChart();
  });
  document.getElementById("btn-close-chart").addEventListener("click", () => { chartPanel.hidden = true; });
  chartTypeSel.addEventListener("change", drawChart);

  const originalUpdateSelectionVisuals = updateSelectionVisuals;
  updateSelectionVisuals = function () {
    originalUpdateSelectionVisuals();
    if (!chartPanel.hidden) drawChart();
  };

  // -- boot ---------------------------------------------------------------

  loadInitialSheet().then(() => {
    selectCell(1, 1, false);
    gridWrapper.focus();
  }).catch((err) => setStatus("Failed to load sheet: " + err.message, true));
})();
