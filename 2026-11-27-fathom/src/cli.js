#!/usr/bin/env node
// Fathom command line: bench | solve | generate | play
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { DIFFICULTIES, Game, HIDDEN, REVEALED, FLAGGED } from './board.js';
import { solve, chooseMove, InconsistentBoard } from './solver.js';
import { generateNoGuess, newGame } from './generator.js';
import { runBench } from './bench.js';
import { analyzeGame } from './analysis.js';

const HELP = `fathom — minesweeper with exact odds

  fathom bench    [--level expert] [--games 50] [--seed s] [--no-guess]
  fathom solve    <file|-> --mines N        solve an ASCII board (# or F = hidden, . = 0, 1-8 = numbers)
  fathom generate [--level L | --size WxHxM] [--seed s] [--first x,y] [--no-guess] [--json]
  fathom play     [--level L | --size WxHxM] [--seed s] [--no-guess]

Coordinates are 1-based "x y" (column row).`;

export function parseArgs(argv) {
  const pos = [], opt = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      if (['no-guess', 'json'].includes(k)) opt[k] = true;
      else { if (i + 1 >= argv.length) throw new Error(`--${k} needs a value`); opt[k] = argv[++i]; }
    } else pos.push(a);
  }
  return { pos, opt };
}

function intOpt(opt, k, def) {
  if (opt[k] === undefined) return def;
  const v = Number(opt[k]);
  if (!Number.isInteger(v)) throw new Error(`--${k} must be an integer, got "${opt[k]}"`);
  return v;
}

export function configFrom(opt) {
  if (opt.size) {
    const m = /^(\d+)x(\d+)x(\d+)$/.exec(opt.size);
    if (!m) throw new Error('--size must look like 16x16x40');
    return { w: +m[1], h: +m[2], mines: +m[3] };
  }
  const level = opt.level || 'beginner';
  if (!DIFFICULTIES[level]) throw new Error(`unknown level "${level}" (beginner|intermediate|expert)`);
  return { ...DIFFICULTIES[level] };
}

/** Parse an ASCII board into a solver view. Returns {view,w,h}. */
export function parseBoard(text) {
  const rows = text.split('\n').map(r => r.trim()).filter(r => r.length);
  if (!rows.length) throw new Error('empty board');
  const grid = rows.map(r => r.split(/\s+/).join('').split(''));
  const w = grid[0].length;
  if (w < 2 || grid.length < 2) throw new Error('board must be at least 2x2');
  const view = new Int8Array(w * grid.length);
  grid.forEach((r, y) => {
    if (r.length !== w) throw new Error(`row ${y + 1} has ${r.length} cells, expected ${w}`);
    r.forEach((ch, x) => {
      let v;
      if (ch === '#' || ch === 'F' || ch === 'f' || ch === '?') v = -1;
      else if (ch === '.' || ch === '0') v = 0;
      else if (/[1-8]/.test(ch)) v = +ch;
      else throw new Error(`row ${y + 1} col ${x + 1}: unexpected character "${ch}"`);
      view[y * w + x] = v;
    });
  });
  return { view, w, h: grid.length };
}

export function renderProbabilities(view, w, h, res) {
  const lines = [];
  for (let y = 0; y < h; y++) {
    const cols = [];
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (view[i] >= 0) cols.push(view[i] === 0 ? '  .' : `  ${view[i]}`);
      else if (res.certainSafe.includes(i)) cols.push('  ✓');
      else if (res.certainMine.includes(i)) cols.push('  ■');
      else cols.push(String(Math.min(99, Math.round(res.prob[i] * 100)) || '<1').padStart(3));
    }
    lines.push(cols.join(' '));
  }
  return lines.join('\n');
}

function cmdBench(opt) {
  const level = opt.level || 'beginner';
  const games = intOpt(opt, 'games', 50);
  process.stderr.write(`benchmarking ${games} ${level} games…\n`);
  const r = runBench({ level, games, seed: opt.seed || 'bench', noGuess: !!opt['no-guess'] });
  console.log(`level ${r.level}: ${r.wins}/${r.games} won (${(r.winRate * 100).toFixed(1)}%), ` +
    `${r.avgGuesses.toFixed(2)} guesses/game, ${r.zeroGuessWins} guess-free wins, ${r.msPerGame.toFixed(1)} ms/game`);
  return r;
}

function cmdSolve(pos, opt) {
  const src = pos[0];
  if (!src) throw new Error('solve needs a file path or "-" for stdin');
  const text = readFileSync(src === '-' ? 0 : src, 'utf8');
  if (opt.mines === undefined) throw new Error('solve needs --mines N (total mines on the board)');
  const mines = intOpt(opt, 'mines');
  const { view, w, h } = parseBoard(text);
  const res = solve(view, w, h, mines);
  console.log(renderProbabilities(view, w, h, res));
  const xy = i => `(${(i % w) + 1},${Math.floor(i / w) + 1})`;
  console.log(`\ncertain safe : ${res.certainSafe.map(xy).join(' ') || '—'}`);
  console.log(`certain mines: ${res.certainMine.map(xy).join(' ') || '—'}`);
  const mv = chooseMove(res, view, w, h);
  if (mv.kind === 'guess') console.log(`best guess   : ${xy(mv.cells[0])} at ${(mv.p * 100).toFixed(1)}% risk`);
  console.log(`layouts      : ${res.stats.solutions}${res.exact ? '' : '  (approximate: frontier too large)'}`);
  return res;
}

function cmdGenerate(opt) {
  const cfg = configFrom(opt);
  const seed = opt.seed || 'fathom';
  let fx = Math.floor(cfg.w / 2), fy = Math.floor(cfg.h / 2);
  if (opt.first) {
    const m = /^(\d+),(\d+)$/.exec(opt.first);
    if (!m) throw new Error('--first must look like 5,5');
    fx = +m[1] - 1; fy = +m[2] - 1;
    if (fx < 0 || fy < 0 || fx >= cfg.w || fy >= cfg.h) throw new Error('--first is outside the board');
  }
  const first = fy * cfg.w + fx;
  const g = newGame({ ...cfg, seed, noGuess: !!opt['no-guess'] });
  g.reveal(first);
  if (opt.json) console.log(JSON.stringify({ ...cfg, seed, first: [fx + 1, fy + 1], noGuess: !!opt['no-guess'], noGuessFailed: !!g.noGuessFailed, mines: [...g.mine].flatMap((m, i) => m ? [i] : []) }));
  else {
    console.log(g.render(true));
    console.log(`\n${cfg.w}x${cfg.h}, ${cfg.mines} mines, seed "${seed}"${opt['no-guess'] ? (g.noGuessFailed ? ' — no-guess search timed out, plain board' : ` — no-guess verified (${g.attempts} candidate${g.attempts > 1 ? 's' : ''})`) : ''}`);
  }
  return g;
}

async function cmdPlay(opt) {
  const cfg = configFrom(opt);
  const seed = opt.seed || Math.random().toString(36).slice(2, 8);
  const g = newGame({ ...cfg, seed, noGuess: !!opt['no-guess'] });
  const moves = [];
  const xyOf = i => `(${(i % g.w) + 1},${Math.floor(i / g.w) + 1})`;
  console.log(`Fathom — ${cfg.w}x${cfg.h}, ${cfg.mines} mines, seed ${seed}. Commands: r x y | f x y | hint | odds | step | q`);
  const rl = createInterface({ input: process.stdin, output: process.stdout, prompt: '> ' });
  const show = () => { console.log('\n' + g.render() + `\nmines left: ${g.mines - g.flagCount}`); };
  const cur = () => g.status === 'ready' ? null : (() => { const v = g.view(); const r = solve(v, g.w, g.h, g.mines); return { v, r, m: chooseMove(r, v, g.w, g.h) }; })();
  const doReveal = i => {
    const c = cur();
    moves.push({ cell: i, p: c ? c.r.prob[i] : null, bestP: c ? Math.min(...[...c.r.prob].filter(x => !Number.isNaN(x))) : null, hadSafe: c ? c.r.certainSafe.length > 0 : false, first: !c, boom: false });
    const r = g.reveal(i); moves[moves.length - 1].boom = r.boom;
  };
  show(); rl.prompt();
  for await (const line of rl) {
    const t = line.trim().split(/\s+/);
    try {
      if (t[0] === 'q') break;
      else if (t[0] === 'r' || t[0] === 'f') {
        const x = Number(t[1]), y = Number(t[2]);
        if (!Number.isInteger(x) || !Number.isInteger(y) || x < 1 || y < 1 || x > g.w || y > g.h) throw new Error(`coordinates must be integers in 1..${g.w} × 1..${g.h}`);
        const i = (y - 1) * g.w + (x - 1);
        if (t[0] === 'f') g.toggleFlag(i);
        else if (g.state[i] === REVEALED) { for (const j of g.nb[i]) if (g.state[j] === HIDDEN && g.state[i] === REVEALED) { let f = 0; for (const k of g.nb[i]) if (g.state[k] === FLAGGED) f++; if (f === g.adj[i]) doReveal(j); } }
        else if (g.state[i] === FLAGGED) throw new Error('that cell is flagged; unflag it first');
        else doReveal(i);
      } else if (t[0] === 'hint' || t[0] === 'odds' || t[0] === 'step') {
        const c = cur();
        if (!c) throw new Error('make a first move first');
        if (t[0] === 'odds') console.log(renderProbabilities(c.v, g.w, g.h, c.r));
        else if (c.m.kind === 'safe') { if (t[0] === 'step') for (const i of c.m.cells) { if (g.state[i] === HIDDEN) doReveal(i); if (g.status !== 'playing') break; } else console.log('certainly safe: ' + c.m.cells.map(xyOf).join(' ')); }
        else if (c.m.kind === 'guess') { console.log(`no certain move; best guess ${xyOf(c.m.cells[0])} at ${(c.m.p * 100).toFixed(1)}% risk`); if (t[0] === 'step') doReveal(c.m.cells[0]); }
      } else if (t[0]) throw new Error('unknown command (r x y | f x y | hint | odds | step | q)');
    } catch (e) { console.log('! ' + e.message); }
    if (t[0] !== 'odds') show();
    if (g.status === 'won' || g.status === 'lost') {
      console.log(g.status === 'won' ? 'You cleared the board.' : 'Boom.');
      const a = analyzeGame(moves, g.status);
      console.log(`Luck report: ${a.risks} risk${a.risks === 1 ? '' : 's'} taken, ${(a.survival * 100).toFixed(1)}% chance of surviving them all. ${a.verdict}`);
      break;
    }
    rl.prompt();
  }
  rl.close();
}

export async function main(argv) {
  const { pos, opt } = parseArgs(argv);
  const cmd = pos.shift();
  switch (cmd) {
    case 'bench': return cmdBench(opt);
    case 'solve': return cmdSolve(pos, opt);
    case 'generate': return cmdGenerate(opt);
    case 'play': return cmdPlay(opt);
    case undefined: case 'help': case '--help': console.log(HELP); return;
    default: throw new Error(`unknown command "${cmd}"\n\n${HELP}`);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main(process.argv.slice(2)).catch(e => {
    console.error(e instanceof InconsistentBoard ? `inconsistent board: ${e.message}` : `error: ${e.message}`);
    process.exit(e instanceof InconsistentBoard ? 3 : 2);
  });
}
