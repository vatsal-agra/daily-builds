// Board generation and solver self-play.
import { Game, placeMines } from './board.js';
import { makeRng } from './rng.js';
import { solve, chooseMove } from './solver.js';

/**
 * Let the solver play `game` to the end (or until stuck when guessing is disallowed).
 * The first click must already have been made (game.status === 'playing') or `first` provided.
 * Returns {won, guesses, steps, log} where log lists each decision: {kind, cell, p}.
 */
export function autoPlay(game, { allowGuess = true, first = null, maxSteps = 100000 } = {}) {
  const log = [];
  let guesses = 0, steps = 0, stuck = false;
  if (game.status === 'ready') {
    const f = first ?? Math.floor(game.n / 2);
    game.reveal(f); log.push({ kind: 'first', cell: f, p: (game.mines) / game.n });
  }
  while (game.status === 'playing' && steps++ < maxSteps) {
    const view = game.view();
    const res = solve(view, game.w, game.h, game.mines);
    const mv = chooseMove(res, view, game.w, game.h);
    if (mv.kind === 'none') { stuck = true; break; }
    if (mv.kind === 'safe') {
      for (const c of mv.cells) { game.reveal(c); log.push({ kind: 'safe', cell: c, p: 0 }); if (game.status !== 'playing') break; }
    } else {
      if (!allowGuess) { stuck = true; break; }
      guesses++;
      game.reveal(mv.cells[0]); log.push({ kind: 'guess', cell: mv.cells[0], p: mv.p });
    }
  }
  return { won: game.status === 'won', guesses, steps, stuck, log };
}

/**
 * Generate a layout for which the first click at `first` opens a region and the whole board is then
 * solvable by *certain* deductions alone (including the global mine-count). Rejection sampling driven by
 * the seeded RNG, so the result is a pure function of (w,h,mines,first,seed).
 */
export function generateNoGuess(w, h, mines, first, seed, { maxAttempts = 5000, timeBudgetMs = 3000 } = {}) {
  const t0 = Date.now();
  const rng = makeRng(`${seed}|ng|${w}x${h}x${mines}|${first}`);
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    if (attempt > 1 && Date.now() - t0 > timeBudgetMs) break;
    const layout = placeMines(w, h, mines, first, rng);
    const g = Game.fromLayout(w, h, layout, seed);
    // Require that the first click opens something bigger than itself, to avoid dull "1-cell" starts.
    g.reveal(first);
    if (g.status !== 'playing' && g.status !== 'won') continue;
    if (g.status === 'playing' && g.revealedCount < 2 && g.n > 25) continue;
    const r = autoPlay(g, { allowGuess: false, first });
    if (r.won) return { layout, attempts: attempt };
  }
  return null;
}

/** A Game whose layout is produced on the first click (so the first click is always safe, and optionally no-guess). */
export function newGame({ w, h, mines, seed = 'fathom', noGuess = false, maxAttempts, timeBudgetMs }) {
  const game = new Game({ w, h, mines, seed });
  if (noGuess) {
    game.layoutProvider = first => {
      const r = generateNoGuess(w, h, mines, first, seed, { maxAttempts, timeBudgetMs });
      if (!r) {
        game.noGuessFailed = true; // surfaced to UI/CLI: we fell back to a plain safe-first-click board
        return placeMines(w, h, mines, first, makeRng(`${seed}|fallback|${first}`));
      }
      game.attempts = r.attempts;
      return r.layout;
    };
  }
  return game;
}
