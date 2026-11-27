// Solver self-play benchmark.
import { DIFFICULTIES } from './board.js';
import { newGame, autoPlay } from './generator.js';

/**
 * Play `games` games with the solver (certain moves first, then the lowest-risk guess).
 * Returns aggregate stats. Deterministic for a given (level, games, seed).
 */
export function runBench({ level = 'expert', games = 50, seed = 'bench', noGuess = false, onProgress } = {}) {
  const cfg = typeof level === 'string' ? DIFFICULTIES[level] : level;
  if (!cfg) throw new RangeError(`unknown level "${level}" (beginner|intermediate|expert)`);
  if (!Number.isInteger(games) || games < 1) throw new RangeError('games must be a positive integer');
  const t0 = performance.now();
  let wins = 0, guessTotal = 0, noGuessWins = 0, zeroGuess = 0, losses = 0, inexact = 0;
  const lossGuessIdx = [];
  for (let g = 0; g < games; g++) {
    const game = newGame({ ...cfg, seed: `${seed}-${g}`, noGuess });
    const first = Math.floor(cfg.h / 2) * cfg.w + Math.floor(cfg.w / 2);
    const r = autoPlay(game, { first });
    guessTotal += r.guesses;
    if (r.won) { wins++; if (r.guesses === 0) zeroGuess++; } else { losses++; lossGuessIdx.push(r.guesses); }
    if (noGuess && r.won && r.guesses === 0) noGuessWins++;
    if (game.noGuessFailed) inexact++;
    onProgress?.(g + 1, games, wins);
  }
  const ms = performance.now() - t0;
  return {
    level: typeof level === 'string' ? level : `${cfg.w}x${cfg.h}x${cfg.mines}`, games, wins, losses,
    winRate: wins / games, avgGuesses: guessTotal / games, zeroGuessWins: zeroGuess,
    generatorFallbacks: inexact, ms, msPerGame: ms / games,
  };
}
