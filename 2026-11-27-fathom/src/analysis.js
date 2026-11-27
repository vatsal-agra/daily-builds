// Luck analyzer: grades a finished game against the exact odds each move was taken at.
//
// A "move" is {cell, p, bestP, hadSafe, first, boom}: p is the exact probability that the revealed
// cell was a mine in the position where it was clicked; bestP the lowest risk available anywhere;
// hadSafe whether a certainly-safe cell existed.

const EPS = 1e-9;

/**
 * @param {Array} moves
 * @param {'won'|'lost'} outcome
 */
export function analyzeGame(moves, outcome) {
  const scored = moves.filter(m => !m.first && m.p !== null);
  const risks = scored.filter(m => m.p > EPS);
  let survival = 1;
  for (const m of risks) survival *= 1 - m.p;
  // A move that detonated has p of dying on that very click; survival of the *others* is what luck compares.
  const totalRisk = risks.reduce((a, m) => a + m.p, 0);

  // Reckless: took a risk while a certain move existed. Suboptimal: a guess clearly riskier than the best available.
  const reckless = risks.filter(m => m.hadSafe);
  const suboptimal = risks.filter(m => !m.hadSafe && m.bestP !== null && m.p - m.bestP > 0.02);
  const worst = risks.slice().sort((a, b) => b.p - a.p).slice(0, 3);

  let verdict, tone;
  if (outcome === 'lost') {
    const dying = moves.find(m => m.boom);
    const pDie = dying ? dying.p : null;
    if (reckless.length || suboptimal.length) { verdict = 'Avoidable: a better move was available.'; tone = 'bad'; }
    else if (pDie !== null && pDie < 0.2) { verdict = `Unlucky: the fatal click was only a ${(pDie * 100).toFixed(1)}% risk.`; tone = 'good'; }
    else if (pDie !== null && pDie >= 0.2) { verdict = `Forced gamble: the fatal click was a ${(pDie * 100).toFixed(0)}% risk with no better option.`; tone = 'neutral'; }
    else verdict = 'Lost.';
  } else {
    if (survival < 0.35) { verdict = `Lucky: surviving every risk had only a ${(survival * 100).toFixed(0)}% chance.`; tone = 'good'; }
    else if (!risks.length) { verdict = 'Pure logic: no risk taken at all.'; tone = 'good'; }
    else { verdict = 'Solid win.'; tone = 'good'; }
    if (reckless.length || suboptimal.length) verdict += ' (Some risks were avoidable.)';
  }
  return {
    moves: scored.length, risks: risks.length, survival, totalRisk,
    reckless: reckless.length, suboptimal: suboptimal.length, worst, verdict, tone,
  };
}
