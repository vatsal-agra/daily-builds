// Formulate frontend. No formula evaluation happens here — every edit is
// sent to the real Python engine and the DOM is patched with its response.
(() => {
  "use strict";

  const gridEl = document.getElementById("grid");
  const gridWrap = document.getElementById("grid-wrap");
  const cellNameEl = document.getElementById("cell-name");
  const formulaInput = document.getElementById("formula-input");
  const statusMsg = document.getElementById("status-msg");
  const statusSelection = document.getElementById("status-selection");
  const sheetTabs = document.getElementById("sheet-tabs");
  const btnUndo = document.getElementById("btn-undo");
  const btnRedo = document.getElementById("btn-redo");

  let state = { sheets: [], active: null, rows: 0, cols: 0, cells: {} };
  let sel = { row: 0, col: 0 };       // active cell
  let anchor = { row: 0, col: 0 };    // range-selection anchor
  let editing = null;                 // {row, col, initial}
  let dragMode = null;                // 'select' | 'fill'

  function colLetters(col) {
    col += 1;
    let s = "";
    while (col > 0) {
      const rem = (col - 1) % 26;
      s = String.fromCharCode(65 + rem) + s;
      col = Math.floor((col - 1) / 26);
    }
    return s;
  }

  function a1(row, col) {
    return colLetters(col) + (row + 1);
  }

  function td(row, col) {
    return gridEl.querySelector(`td[data-row="${row}"][data-col="${col}"]`);
  }

  // -- networking ----------------------------------------------------------

  async function api(path, method, body) {
    const opts = { method };
    if (body !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    const data = await res.json();
    if (!res.ok || data.error) {
      setStatus(data.error || `request failed (${res.status})`, true);
    }
    return data;
  }

  // Mutating requests (edit/undo/redo/autofill/import) must reach the server
  // in the order the user triggered them. Callers don't await commitEdit()
  // before moving on (so typing stays snappy), so without this a fast
  // Tab-then-type sequence could race two POSTs over the network and land
  // out of order, corrupting the edit history / dependency graph.
  let mutationChain = Promise.resolve();
  function mutate(path, body) {
    const result = mutationChain.then(() => api(path, "POST", body));
    mutationChain = result.catch(() => {}); // one failed edit must not jam the queue
    return result;
  }

  async function loadState(sheetName) {
    const qs = sheetName ? `?sheet=${encodeURIComponent(sheetName)}` : "";
    state = await api("/api/state" + qs, "GET");
    renderAll();
  }

  // `resp.changed` is always keyed by sheet name -> { ref: cellInfo|null }
  function applyChangedForActiveSheet(resp) {
    if (!resp) return;
    if ("can_undo" in resp) updateUndoRedo(resp.can_undo, resp.can_redo);
    const changed = (resp.changed || {})[state.active] || {};
    for (const [ref, value] of Object.entries(changed)) {
      if (value === null) {
        delete state.cells[ref];
      } else {
        state.cells[ref] = value;
      }
      renderCell(ref);
    }
    refreshChartIfOpen();
  }

  function updateUndoRedo(canUndo, canRedo) {
    btnUndo.disabled = !canUndo;
    btnRedo.disabled = !canRedo;
  }

  function setStatus(text, isError) {
    statusMsg.textContent = text;
    statusMsg.classList.toggle("err", !!isError);
    if (!isError) {
      clearTimeout(setStatus._t);
      setStatus._t = setTimeout(() => { statusMsg.textContent = "Ready."; statusMsg.classList.remove("err"); }, 2500);
    }
  }

  // -- rendering -------------------------------------------------------------

  function renderAll() {
    renderTabs();
    renderGrid();
    updateUndoRedo(state.can_undo, state.can_redo);
    updateFormulaBar();
  }

  function renderTabs() {
    sheetTabs.innerHTML = "";
    for (const name of state.sheets) {
      const tab = document.createElement("div");
      tab.className = "tab" + (name === state.active ? " active" : "");
      tab.textContent = name;
      tab.onclick = () => switchSheet(name);
      sheetTabs.appendChild(tab);
    }
    const add = document.createElement("div");
    add.id = "add-sheet";
    add.textContent = "+";
    add.title = "Add sheet";
    add.onclick = addSheet;
    sheetTabs.appendChild(add);
  }

  async function switchSheet(name) {
    if (name === state.active) return;
    await api("/api/sheet", "POST", { action: "switch", name });
    sel = { row: 0, col: 0 };
    anchor = { row: 0, col: 0 };
    await loadState(name);
  }

  async function addSheet() {
    const name = prompt("New sheet name:", `Sheet${state.sheets.length + 1}`);
    if (!name) return;
    const resp = await api("/api/sheet", "POST", { action: "add", name });
    if (resp.error) return;
    await switchSheet(name);
  }

  function renderGrid() {
    gridEl.innerHTML = "";
    const thead = document.createElement("tr");
    const corner = document.createElement("th");
    corner.className = "corner";
    thead.appendChild(corner);
    for (let c = 0; c < state.cols; c++) {
      const th = document.createElement("th");
      th.className = "colhead";
      th.textContent = colLetters(c);
      thead.appendChild(th);
    }
    gridEl.appendChild(thead);

    for (let r = 0; r < state.rows; r++) {
      const tr = document.createElement("tr");
      const rh = document.createElement("th");
      rh.className = "rowhead";
      rh.textContent = r + 1;
      tr.appendChild(rh);
      for (let c = 0; c < state.cols; c++) {
        const cell = document.createElement("td");
        cell.className = "cell";
        cell.dataset.row = r;
        cell.dataset.col = c;
        cell.onmousedown = (e) => onCellMouseDown(r, c, e);
        cell.onmouseenter = () => onCellMouseEnter(r, c);
        cell.ondblclick = () => startEditing(r, c, null);
        tr.appendChild(cell);
      }
      gridEl.appendChild(tr);
    }
    for (let r = 0; r < state.rows; r++) {
      for (let c = 0; c < state.cols; c++) {
        paintCellContent(r, c);
      }
    }
    paintSelection();
  }

  function renderCell(ref) {
    const [row, col] = refToRowCol(ref);
    if (row === null) return;
    if (row >= state.rows || col >= state.cols) return; // outside current viewport, harmless
    paintCellContent(row, col);
    if (sel.row === row && sel.col === col) updateFormulaBar();
  }

  function refToRowCol(ref) {
    const m = /^([A-Z]+)([0-9]+)$/.exec(ref);
    if (!m) return [null, null];
    let col = 0;
    for (const ch of m[1]) col = col * 26 + (ch.charCodeAt(0) - 64);
    return [parseInt(m[2], 10) - 1, col - 1];
  }

  function paintCellContent(row, col) {
    const cell = td(row, col);
    if (!cell || cell.classList.contains("editing")) return;
    const info = state.cells[a1(row, col)];
    cell.classList.toggle("error", !!(info && info.error));
    if (!info) {
      cell.textContent = "";
      cell.classList.remove("text-align-left");
      return;
    }
    cell.textContent = info.display;
    const isText = typeof info.value === "string" && !info.error;
    cell.classList.toggle("text-align-left", isText);
  }

  // -- selection -------------------------------------------------------------

  function onCellMouseDown(row, col, e) {
    if (editing) commitEdit(true);
    if (e.shiftKey) {
      sel = { row, col };
    } else {
      anchor = { row, col };
      sel = { row, col };
    }
    dragMode = "select";
    paintSelection();
    updateFormulaBar();
  }

  function onCellMouseEnter(row, col) {
    if (dragMode === "select") {
      sel = { row, col };
      paintSelection();
    } else if (dragMode === "fill") {
      fillPreview = { row, col };
      paintSelection();
    }
  }

  let fillPreview = null;

  window.addEventListener("mouseup", () => {
    if (dragMode === "fill" && fillPreview) {
      performFill();
    }
    dragMode = null;
    fillPreview = null;
  });

  function rangeBounds() {
    const target = fillPreview || sel;
    return {
      r1: Math.min(anchor.row, target.row), r2: Math.max(anchor.row, target.row),
      c1: Math.min(anchor.col, target.col), c2: Math.max(anchor.col, target.col),
    };
  }

  function paintSelection() {
    gridEl.querySelectorAll("td.cell").forEach((el) => {
      el.classList.remove("selected", "in-range");
      const h = el.querySelector(".fill-handle");
      if (h) h.remove();
    });
    const { r1, r2, c1, c2 } = rangeBounds();
    for (let r = r1; r <= r2; r++) {
      for (let c = c1; c <= c2; c++) {
        const el = td(r, c);
        if (el) el.classList.add("in-range");
      }
    }
    const activeEl = td(sel.row, sel.col);
    if (activeEl) activeEl.classList.add("selected");
    const cornerEl = td(r2, c2);
    if (cornerEl && !editing) {
      const handle = document.createElement("div");
      handle.className = "fill-handle";
      handle.onmousedown = (e) => { e.stopPropagation(); dragMode = "fill"; anchor = { ...sel }; };
      cornerEl.appendChild(handle);
    }
    statusSelection.textContent = (r1 === r2 && c1 === c2) ? a1(r1, c1) : `${a1(r1, c1)}:${a1(r2, c2)}`;
  }

  function updateFormulaBar() {
    cellNameEl.textContent = a1(sel.row, sel.col);
    const info = state.cells[a1(sel.row, sel.col)];
    formulaInput.value = info ? info.raw : "";
  }

  // -- editing -----------------------------------------------------------

  function startEditing(row, col, initialChar) {
    sel = { row, col };
    anchor = { row, col };
    const cell = td(row, col);
    if (!cell) return;
    const info = state.cells[a1(row, col)];
    const initial = initialChar !== null ? initialChar : (info ? info.raw : "");
    editing = { row, col };
    cell.classList.add("editing");
    cell.textContent = "";
    const input = document.createElement("input");
    input.value = initial;
    cell.appendChild(input);
    input.focus();
    if (initialChar === null) input.select();
    else input.setSelectionRange(initial.length, initial.length);
    input.addEventListener("keydown", onEditKeydown);
    formulaInput.value = initial;
    paintSelection();
  }

  function onEditKeydown(e) {
    // stopPropagation matters here: commitEdit()/cancelEdit() clear `editing`
    // synchronously, and this handler runs before the document-level one
    // during bubbling -- without this, the same keystroke would be handled
    // twice (once here, once by the global nav handler that no longer sees
    // `editing` set).
    if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); commitEdit(true); moveSelection(1, 0); }
    else if (e.key === "Tab") { e.preventDefault(); e.stopPropagation(); commitEdit(true); moveSelection(0, e.shiftKey ? -1 : 1); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancelEdit(); }
  }

  async function commitEdit(rerenderNow) {
    if (!editing) return;
    const { row, col } = editing;
    const cell = td(row, col);
    const input = cell ? cell.querySelector("input") : null;
    const raw = input ? input.value : "";
    editing = null;
    if (cell) cell.classList.remove("editing");
    const resp = await mutate("/api/edit", { sheet: state.active, ref: a1(row, col), raw });
    applyChangedForActiveSheet(resp);
    if (rerenderNow) paintSelection();
  }

  function cancelEdit() {
    if (!editing) return;
    const { row, col } = editing;
    editing = null;
    paintCellContent(row, col);
    paintSelection();
    updateFormulaBar();
  }

  function moveSelection(dr, dc) {
    sel = { row: clamp(sel.row + dr, 0, state.rows - 1), col: clamp(sel.col + dc, 0, state.cols - 1) };
    anchor = { ...sel };
    paintSelection();
    updateFormulaBar();
    scrollIntoView();
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function scrollIntoView() {
    const el = td(sel.row, sel.col);
    if (el) el.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  // -- fill handle ------------------------------------------------------------

  async function performFill() {
    const { r1, r2, c1, c2 } = rangeBounds();
    const targets = [];
    for (let r = r1; r <= r2; r++) {
      for (let c = c1; c <= c2; c++) {
        if (r === sel.row && c === sel.col) continue;
        targets.push(a1(r, c));
      }
    }
    if (!targets.length) return;
    const resp = await mutate("/api/autofill", { sheet: state.active, src: a1(sel.row, sel.col), targets });
    applyChangedForActiveSheet(resp);
    anchor = { row: r1, col: c1 };
    sel = { row: r2, col: c2 };
    paintSelection();
  }

  // -- global keyboard ---------------------------------------------------

  document.addEventListener("keydown", (e) => {
    if (editing) return;
    if (document.activeElement === formulaInput) {
      if (e.key === "Enter") { e.preventDefault(); commitFormulaBar(); moveSelection(1, 0); }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      if (e.shiftKey) doRedo(); else doUndo();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); doRedo(); return; }

    const map = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (map[e.key]) { e.preventDefault(); moveSelection(map[e.key][0], map[e.key][1]); return; }
    if (e.key === "Tab") { e.preventDefault(); moveSelection(0, e.shiftKey ? -1 : 1); return; }
    if (e.key === "Enter") { e.preventDefault(); moveSelection(1, 0); return; }
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      clearSelection();
      return;
    }
    if (e.key === "F2") { e.preventDefault(); startEditing(sel.row, sel.col, null); return; }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      startEditing(sel.row, sel.col, e.key);
    }
  });

  async function clearSelection() {
    const { r1, r2, c1, c2 } = rangeBounds();
    const edits = [];
    for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) edits.push({ ref: a1(r, c), raw: "" });
    const resp = await mutate("/api/edit", { sheet: state.active, edits });
    applyChangedForActiveSheet(resp);
    updateFormulaBar();
  }

  formulaInput.addEventListener("focus", () => { if (!editing) { anchor = { ...sel }; } });
  async function commitFormulaBar() {
    const raw = formulaInput.value;
    const resp = await mutate("/api/edit", { sheet: state.active, ref: a1(sel.row, sel.col), raw });
    applyChangedForActiveSheet(resp);
  }
  formulaInput.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { updateFormulaBar(); formulaInput.blur(); }
  });

  // -- undo/redo -----------------------------------------------------------

  async function doUndo() {
    const resp = await mutate("/api/undo", {});
    applyChangedForActiveSheet({ changed: { [state.active]: flattenChanged(resp.changed) }, can_undo: resp.can_undo, can_redo: resp.can_redo });
  }
  async function doRedo() {
    const resp = await mutate("/api/redo", {});
    applyChangedForActiveSheet({ changed: { [state.active]: flattenChanged(resp.changed) }, can_undo: resp.can_undo, can_redo: resp.can_redo });
  }
  function flattenChanged(changed) {
    if (!changed) return {};
    return changed[state.active] || changed;
  }
  btnUndo.onclick = doUndo;
  btnRedo.onclick = doRedo;

  // -- toolbar: save/load/csv/chart ----------------------------------------

  document.getElementById("btn-save").onclick = async () => {
    const name = document.getElementById("save-name").value.trim() || "workbook";
    const resp = await api("/api/save", "POST", { name });
    if (!resp.error) setStatus(`Saved as "${resp.name}.json".`);
  };
  document.getElementById("btn-load").onclick = async () => {
    const name = document.getElementById("save-name").value.trim() || "workbook";
    const resp = await api("/api/load", "POST", { name });
    if (resp.error) return;
    state = resp.state;
    renderAll();
    setStatus(`Loaded "${name}.json".`);
  };
  document.getElementById("btn-export-csv").onclick = () => {
    window.location = `/api/export_csv?sheet=${encodeURIComponent(state.active)}`;
  };
  document.getElementById("csv-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    const resp = await mutate("/api/import_csv", { sheet: state.active, text, start: a1(sel.row, sel.col) });
    applyChangedForActiveSheet(resp);
    e.target.value = "";
    setStatus(`Imported ${file.name}.`);
  });

  // -- chart ---------------------------------------------------------------

  const chartPanel = document.getElementById("chart-panel");
  const chartCanvas = document.getElementById("chart-canvas");
  const chartType = document.getElementById("chart-type");
  let currentChartRange = null;

  document.getElementById("btn-chart").onclick = () => {
    const { r1, r2, c1, c2 } = rangeBounds();
    currentChartRange = `${a1(r1, c1)}:${a1(r2, c2)}`;
    document.getElementById("chart-title").textContent = `Chart — ${currentChartRange}`;
    chartPanel.classList.add("open");
    refreshChart();
  };
  document.getElementById("chart-close").onclick = () => { chartPanel.classList.remove("open"); currentChartRange = null; };
  chartType.onchange = refreshChart;

  async function refreshChart() {
    if (!currentChartRange) return;
    const data = await api(`/api/chart?sheet=${encodeURIComponent(state.active)}&range=${encodeURIComponent(currentChartRange)}`, "GET");
    drawChart(data);
  }
  function refreshChartIfOpen() { if (chartPanel.classList.contains("open")) refreshChart(); }

  function drawChart(data) {
    const ctx = chartCanvas.getContext("2d");
    const W = chartCanvas.width, H = chartCanvas.height;
    ctx.clearRect(0, 0, W, H);
    const isDark = matchMedia("(prefers-color-scheme: dark)").matches ||
      document.documentElement.getAttribute("data-theme") === "dark";
    const fg = isDark ? "#e6e9ec" : "#1c2126";
    const gridColor = isDark ? "#2c3138" : "#d7dbe0";
    const colors = ["#2563eb", "#e08e0b", "#16a34a", "#dc2626", "#7c3aed"];
    const padding = { top: 16, right: 12, bottom: 28, left: 40 };
    const plotW = W - padding.left - padding.right;
    const plotH = H - padding.top - padding.bottom;
    const labels = data.labels || [];
    const series = data.series || [];
    const allVals = series.flatMap((s) => s.values);
    const maxV = Math.max(1, ...allVals, 0);
    const minV = Math.min(0, ...allVals);
    const range = maxV - minV || 1;

    ctx.strokeStyle = gridColor;
    ctx.fillStyle = fg;
    ctx.font = "10px sans-serif";
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top);
    ctx.lineTo(padding.left, padding.top + plotH);
    ctx.lineTo(padding.left + plotW, padding.top + plotH);
    ctx.stroke();

    const n = labels.length || 1;
    const yOf = (v) => padding.top + plotH - ((v - minV) / range) * plotH;

    if (chartType.value === "bar") {
      const groupW = plotW / n;
      const barW = groupW / (series.length + 1);
      series.forEach((s, si) => {
        ctx.fillStyle = colors[si % colors.length];
        s.values.forEach((v, i) => {
          const x = padding.left + i * groupW + (si + 0.5) * barW;
          const y0 = yOf(0), y1 = yOf(v);
          ctx.fillRect(x, Math.min(y0, y1), barW * 0.9, Math.abs(y1 - y0));
        });
      });
    } else {
      series.forEach((s, si) => {
        ctx.strokeStyle = colors[si % colors.length];
        ctx.lineWidth = 2;
        ctx.beginPath();
        s.values.forEach((v, i) => {
          const x = padding.left + (n === 1 ? 0.5 : i / (n - 1)) * plotW;
          const y = yOf(v);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
      });
    }
    ctx.fillStyle = fg;
    labels.forEach((label, i) => {
      const x = padding.left + (n === 1 ? 0.5 : (i + 0.5) / n) * plotW;
      ctx.textAlign = "center";
      ctx.fillText(String(label).slice(0, 8), chartType.value === "bar" ? padding.left + (i + 0.5) * (plotW / n) : x, H - 10);
    });
  }

  // -- init -----------------------------------------------------------------

  loadState(null).then(() => {
    sel = { row: 0, col: 0 };
    anchor = { row: 0, col: 0 };
    paintSelection();
    updateFormulaBar();
  });
})();
