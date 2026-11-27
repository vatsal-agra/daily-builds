import { DIFFICULTIES, HIDDEN, REVEALED, FLAGGED } from '../src/board.js';
import { newGame } from '../src/generator.js';
import { solve, chooseMove } from '../src/solver.js';

const $ = id => document.getElementById(id);
const els = {
  level: $('level'), customBox: $('customBox'), cw: $('cw'), ch: $('ch'), cm: $('cm'), seed: $('seed'), noguess: $('noguess'),
  newgame: $('newgame'), board: $('board'), minesLeft: $('minesLeft'), timer: $('timer'), state: $('state'), hintLine: $('hintLine'),
  hint: $('hint'), step: $('step'), auto: $('auto'), flagmines: $('flagmines'), flagmode: $('flagmode'), heat: $('heat'),
  autoguess: $('autoguess'), advice: $('advice'), inspect: $('inspect'), stats: $('stats'), reportCard: $('reportCard'), report: $('report'),
};

let game = null, cfg = null, cells = [], ver = 0, cache = null, hintCells = new Set(), moves = [];
let timerId = null, startedAt = 0, autoId = null, hovered = -1, flagMode = false;

// ---------- helpers ----------
function randomSeed() { return Math.random().toString(36).slice(2, 8); }
function fmtBig(b) {
  const s = b.toString();
  if (s.length <= 9) return s;
  return s[0] + '.' + s.slice(1, 3) + 'e+' + (s.length - 1);
}
function fmtPct(p) {
  if (p === 0) return '0%';
  if (p === 1) return '100%';
  const v = p * 100;
  if (v < 0.1) return '<0.1%';
  if (v > 99.9) return '>99.9%';
  return (v < 10 ? v.toFixed(1) : Math.round(v)) + '%';
}
function xy(i) { return `(${(i % game.w) + 1}, ${Math.floor(i / game.w) + 1})`; }
function heatColor(p) { const hue = Math.round(150 * (1 - Math.sqrt(p))); return `hsl(${hue} 68% ${p > 0.5 ? 36 : 30}%)`; }

function readConfig() {
  let base;
  if (els.level.value === 'custom') {
    base = { w: +els.cw.value, h: +els.ch.value, mines: +els.cm.value };
  } else base = { ...DIFFICULTIES[els.level.value] };
  return base;
}

// ---------- solver cache ----------
function currentSolve() {
  if (!game || game.status === 'ready') return null;
  if (cache && cache.ver === ver) return cache;
  try {
    const view = game.view();
    const res = solve(view, game.w, game.h, game.mines);
    const move = chooseMove(res, view, game.w, game.h);
    res.frontierSet = new Set();
    for (let i = 0; i < game.n; i++) if (view[i] < 0 && game.nb[i].some(j => view[j] >= 0)) res.frontierSet.add(i);
    cache = { ver, view, res, move };
  } catch (e) {
    cache = { ver, error: e.message };
  }
  return cache;
}

// ---------- game lifecycle ----------
function newRound(seedOverride) {
  stopAuto(); clearInterval(timerId); timerId = null;
  const c = readConfig();
  let seed = (seedOverride ?? els.seed.value.trim()) || randomSeed();
  try {
    game = newGame({ ...c, seed, noGuess: els.noguess.checked, maxAttempts: 4000 });
  } catch (e) {
    els.advice.innerHTML = `<b>Invalid setup:</b> ${e.message}`;
    return;
  }
  cfg = { ...c, seed, noGuess: els.noguess.checked };
  els.seed.value = seed;
  history.replaceState(null, '', `#d=${els.level.value === 'custom' ? `${c.w}x${c.h}x${c.mines}` : els.level.value}&seed=${encodeURIComponent(seed)}${cfg.noGuess ? '&ng=1' : ''}`);
  ver++; cache = null; hintCells = new Set(); moves = []; startedAt = 0; els.timer.textContent = '0';
  els.reportCard.hidden = true;
  buildBoard();
  els.advice.textContent = 'Make a first move to wake the solver. The first click is always safe.';
  els.hintLine.textContent = 'Left-click reveals · right-click (or long-press) flags · click a number to chord';
  paint();
}

function buildBoard() {
  const b = els.board;
  b.textContent = '';
  const avail = Math.max(280, b.parentElement.clientWidth - 30);
  const size = Math.max(22, Math.min(38, Math.floor((avail - 16 - game.w * 2) / game.w)));
  b.style.setProperty('--cell', size + 'px');
  b.style.gridTemplateColumns = `repeat(${game.w}, var(--cell))`;
  cells = [];
  for (let i = 0; i < game.n; i++) {
    const d = document.createElement('div');
    d.className = 'c h'; d.dataset.i = i; d.setAttribute('role', 'gridcell');
    b.appendChild(d); cells.push(d);
  }
}

function paint() {
  const c = currentSolve();
  const showHeat = els.heat.checked && c && c.res && game.status === 'playing';
  const safe = c && c.res ? new Set(c.res.certainSafe) : new Set();
  const mineSet = c && c.res ? new Set(c.res.certainMine) : new Set();
  for (let i = 0; i < game.n; i++) {
    const d = cells[i], s = game.state[i];
    let cls = 'c', html = '', style = '';
    if (s === REVEALED) {
      if (game.mine[i]) { cls += ' o ' + (i === game.exploded ? 'boom' : 'mine'); html = '✹'; }
      else { cls += ' o'; if (game.adj[i]) { cls += ` num n${game.adj[i]}`; html = game.adj[i]; } }
    } else if (s === FLAGGED) {
      cls += ' h flag';
      if (game.status === 'lost' && !game.mine[i]) cls += ' wrongflag';
    } else {
      cls += ' h';
      if (game.status === 'lost' && game.mine[i]) { cls += ' mine'; html = '✹'; }
      else if (showHeat && c.res) {
        const p = c.res.prob[i];
        if (!Number.isNaN(p)) {
          style = `background:${heatColor(p)}`;
          if (safe.has(i)) { cls += ' sure-safe'; html = '<span class="pct">✓</span>'; }
          else if (mineSet.has(i)) { cls += ' sure-mine'; html = '<span class="pct">!</span>'; }
          else if (!c.res.frontierSet.has(i)) cls += ' int';
          else if (parseInt(getComputedStyle(els.board).getPropertyValue('--cell')) >= 26) html = `<span class="pct">${Math.min(99, Math.round(p * 100)) || '<1'}</span>`;
        }
      }
    }
    if (hintCells.has(i)) cls += ' hint';
    d.className = cls; d.innerHTML = html; d.style.cssText = style;
    d.setAttribute('aria-label', `row ${Math.floor(i / game.w) + 1} column ${(i % game.w) + 1}, ${s === FLAGGED ? 'flagged' : s === HIDDEN ? 'hidden' : game.adj[i] ? game.adj[i] + ' adjacent' : 'empty'}`);
  }
  els.minesLeft.textContent = game.mines - game.flagCount;
  const st = { ready: 'Ready', playing: 'Playing', won: 'Cleared!', lost: 'Detonated' }[game.status];
  els.state.textContent = st; els.state.className = 'state ' + game.status;
  els.hint.disabled = els.step.disabled = els.flagmines.disabled = game.status !== 'playing';
  els.auto.textContent = autoId ? 'Stop' : 'Auto';
  els.auto.disabled = game.status !== 'playing' && !autoId;
  renderStats(c);
  if (hovered >= 0) inspectCell(hovered);
}

function renderStats(c) {
  if (!c || !c.res) {
    els.stats.innerHTML = c && c.error ? `<dt>Solver</dt><dd>${c.error}</dd>` : '';
    return;
  }
  const s = c.res.stats;
  els.stats.innerHTML = [
    ['Hidden cells', s.hidden], ['Frontier', s.frontier], ['Interior', s.interior], ['Components', s.components],
    ['Consistent layouts', fmtBig(s.solutions)], ['Search nodes', s.nodes.toLocaleString()],
    ['Sure safe / mines', `${c.res.certainSafe.length} / ${c.res.certainMine.length}`],
    ['Exact', c.res.exact ? 'yes' : 'approximate'],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
}

function inspectCell(i) {
  const c = currentSolve();
  if (!game || game.state[i] === REVEALED) { els.inspect.textContent = 'Hover a hidden cell.'; return; }
  if (!c || !c.res) { els.inspect.innerHTML = `Cell ${xy(i)} — prior chance <span class="big">${fmtPct(game.mines / game.n)}</span>`; return; }
  const p = c.res.prob[i];
  const kind = c.res.certainSafe.includes(i) ? 'certainly safe' : c.res.certainMine.includes(i) ? 'certainly a mine'
    : (c.res.stats.interior && !isFrontierCell(c, i) ? 'unconstrained region' : 'on the frontier');
  els.inspect.innerHTML = `Cell ${xy(i)} — <span class="big">${fmtPct(p)}</span> mine<br><small>${kind}</small>`;
}
function isFrontierCell(c, i) { return game.nb[i].some(j => c.view[j] >= 0); }

// ---------- actions ----------
function afterMove(note) {
  ver++; cache = null; hintCells = new Set();
  if (game.status === 'playing' && !timerId) {
    startedAt = Date.now();
    timerId = setInterval(() => { els.timer.textContent = Math.min(999, Math.floor((Date.now() - startedAt) / 1000)); }, 250);
  }
  if (game.status === 'won' || game.status === 'lost') {
    clearInterval(timerId); timerId = null; stopAuto();
    if (startedAt) els.timer.textContent = Math.min(999, Math.floor((Date.now() - startedAt) / 1000));
  }
  paint();
  if (game.status === 'playing') adviseFromCache(note);
  else if (game.status === 'won') els.advice.innerHTML = '<b>Cleared.</b> ' + (note || '');
  else els.advice.innerHTML = '<b>Boom.</b> ' + (note || '');
  if (game.status === 'won' || game.status === 'lost') onGameEnd();
}

function adviseFromCache(prefix = '') {
  const c = currentSolve();
  if (!c) return;
  if (c.error) { els.advice.innerHTML = `${prefix} <b>Solver:</b> ${c.error}`; return; }
  const m = c.move;
  const pre = (prefix ? prefix + ' ' : '') + (c.res.exact ? '' : '<b>Huge frontier:</b> odds are approximate in places, certain moves remain sound. ');
  if (m.kind === 'safe') els.advice.innerHTML = `${pre}<b>${m.cells.length}</b> cell${m.cells.length > 1 ? 's are' : ' is'} certainly safe. Press Hint to see them.`;
  else if (m.kind === 'guess') els.advice.innerHTML = `${pre}<b>No certain move.</b> Best guess is ${xy(m.cells[0])} at <b>${fmtPct(m.p)}</b> mine risk.`;
  else els.advice.textContent = pre;
}

/** Reveal one cell, recording the exact risk the player took. */
function doReveal(i, via = 'click') {
  if (game.state[i] !== HIDDEN) return;
  const c = game.status === 'ready' ? null : currentSolve();
  const p = c && c.res ? c.res.prob[i] : null;
  const bestP = c && c.res ? Math.min(...[...c.res.prob].filter(x => !Number.isNaN(x))) : null;
  const hadSafe = c && c.res ? c.res.certainSafe.length > 0 : false;
  const r = game.reveal(i);
  moves.push({ cell: i, p: p ?? (game.status === 'lost' ? 1 : 0), bestP, hadSafe, via, first: p === null, boom: r.boom });
  return r;
}

function onCell(i, how) {
  if (!game || game.status === 'won' || game.status === 'lost') return;
  stopAuto();
  if (how === 'flag') { if (game.toggleFlag(i)) { ver++; cache = null; paint(); adviseFromCache(); } return; }
  if (game.state[i] === REVEALED) {
    // chord one cell at a time so every reveal is scored against the position it was actually taken in
    let flags = 0; for (const j of game.nb[i]) if (game.state[j] === FLAGGED) flags++;
    if (!game.adj[i] || flags !== game.adj[i]) return;
    for (const j of game.nb[i]) {
      if (game.state[j] !== HIDDEN) continue;
      doReveal(j, 'chord');
      if (game.status === 'lost') break;
      ver++; cache = null;
    }
    afterMove(); return;
  }
  if (game.state[i] === FLAGGED) return;
  if (flagMode) { game.toggleFlag(i); ver++; cache = null; paint(); return; }
  doReveal(i);
  afterMove(game.noGuessFailed && game.status === 'playing' && moves.length === 1 ? 'No-guess board not found for this setup in time — this one may need guesses.' : '');
}

function hint() {
  const c = currentSolve();
  if (!c || !c.move) return;
  hintCells = new Set(c.move.cells);
  paint(); adviseFromCache();
}

function step() {
  const c = currentSolve();
  if (!c || !c.move || c.move.kind === 'none') return false;
  const m = c.move;
  const note = m.kind === 'guess' ? `Solver guessed ${xy(m.cells[0])} at ${fmtPct(m.p)} risk.` : '';
  for (const i of m.cells) { if (game.state[i] === HIDDEN) doReveal(i, 'solver'); if (game.status !== 'playing') break; ver++; cache = null; }
  afterMove(note);
  return true;
}

function flagSureMines() {
  const c = currentSolve();
  if (!c || !c.res) return;
  let n = 0;
  for (const i of c.res.certainMine) if (game.state[i] === HIDDEN) { game.toggleFlag(i); n++; }
  ver++; cache = null; paint();
  els.advice.innerHTML = n ? `Flagged <b>${n}</b> certain mine${n > 1 ? 's' : ''}.` : 'No new certain mines to flag.';
}

function stopAuto() { if (autoId) { clearInterval(autoId); autoId = null; } }
function toggleAuto() {
  if (autoId) { stopAuto(); paint(); return; }
  if (game.status === 'ready') return;
  autoId = setInterval(() => {
    if (game.status !== 'playing') { stopAuto(); paint(); return; }
    const c = currentSolve();
    if (c && c.move && c.move.kind === 'guess' && !els.autoguess.checked) {
      stopAuto(); paint(); adviseFromCache('Auto paused: it would have to guess.'); return;
    }
    if (!step()) stopAuto();
  }, 140);
  paint();
}

window.addEventListener('resize', () => { if (game) { const size = Math.max(22, Math.min(38, Math.floor((Math.max(280, els.board.parentElement.clientWidth - 30) - 16 - game.w * 2) / game.w))); els.board.style.setProperty('--cell', size + 'px'); } });

function onGameEnd() { /* luck report is attached in phase 4 */ }

// ---------- wiring ----------
let pressTimer = null, pressed = false;
els.board.addEventListener('contextmenu', e => { e.preventDefault(); const t = e.target.closest('.c'); if (t) onCell(+t.dataset.i, 'flag'); });
els.board.addEventListener('pointerdown', e => {
  const t = e.target.closest('.c'); if (!t) return;
  pressed = false;
  if (e.pointerType === 'touch') pressTimer = setTimeout(() => { pressed = true; onCell(+t.dataset.i, 'flag'); }, 420);
});
['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => els.board.addEventListener(ev, () => clearTimeout(pressTimer)));
els.board.addEventListener('click', e => {
  const t = e.target.closest('.c'); if (!t) return;
  if (pressed) { pressed = false; return; }
  onCell(+t.dataset.i, 'reveal');
});
els.board.addEventListener('auxclick', e => { if (e.button === 1) { e.preventDefault(); const t = e.target.closest('.c'); if (t) onCell(+t.dataset.i, 'reveal'); } });
els.board.addEventListener('mouseover', e => { const t = e.target.closest('.c'); if (t) { hovered = +t.dataset.i; if (game) inspectCell(hovered); } });
els.board.addEventListener('mouseleave', () => { hovered = -1; els.inspect.textContent = 'Hover a hidden cell.'; });

els.newgame.addEventListener('click', () => newRound());
els.level.addEventListener('change', () => { els.customBox.hidden = els.level.value !== 'custom'; newRound(); });
els.noguess.addEventListener('change', () => newRound());
els.seed.addEventListener('keydown', e => { if (e.key === 'Enter') newRound(); });
[els.cw, els.ch, els.cm].forEach(x => x.addEventListener('change', () => newRound()));
els.heat.addEventListener('change', () => paint());
els.hint.addEventListener('click', hint);
els.step.addEventListener('click', () => { stopAuto(); step(); });
els.auto.addEventListener('click', toggleAuto);
els.flagmines.addEventListener('click', flagSureMines);
els.flagmode.addEventListener('click', () => { flagMode = !flagMode; els.flagmode.setAttribute('aria-pressed', flagMode); });
window.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.ctrlKey || e.metaKey) return;
  const k = e.key.toLowerCase();
  if (k === 'h' && game.status === 'playing') hint();
  else if (k === 's' && game.status === 'playing') { stopAuto(); step(); }
  else if (k === 'p') { els.heat.checked = !els.heat.checked; paint(); }
  else if (k === 'n') newRound();
  else if (k === 'f' && hovered >= 0) onCell(hovered, 'flag');
  else if (k === ' ' && hovered >= 0) { e.preventDefault(); onCell(hovered, 'reveal'); }
});

// initial state from URL hash
(function init() {
  const p = new URLSearchParams(location.hash.slice(1));
  const d = p.get('d');
  if (d && DIFFICULTIES[d]) els.level.value = d;
  else if (d && /^\d+x\d+x\d+$/.test(d)) { const [w, h, m] = d.split('x').map(Number); els.level.value = 'custom'; els.cw.value = w; els.ch.value = h; els.cm.value = m; els.customBox.hidden = false; }
  if (p.get('ng') === '1') els.noguess.checked = true;
  newRound(p.get('seed') || undefined);
})();
