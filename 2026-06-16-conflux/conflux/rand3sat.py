"""Uniform random k-SAT generation and the satisfiability phase transition.

For random 3-SAT, the probability that a formula is satisfiable drops sharply
from ~1 to ~0 as the clause-to-variable ratio α = m/n crosses a threshold near
α ≈ 4.26, and solve cost peaks right at the threshold. This module generates the
instances and sweeps α to reveal that famous curve empirically.
"""
from __future__ import annotations

import random
from typing import List, Tuple

from .cnf import CNF
from .solver import Solver, SAT, UNSAT, UNKNOWN


def random_ksat(num_vars: int, num_clauses: int, k: int = 3,
                rng: random.Random = None) -> CNF:
    rng = rng or random.Random()
    if num_vars < k:
        raise ValueError("need at least k variables for distinct literals")
    cnf = CNF()
    cnf.num_vars = num_vars
    cnf.comments.append(f"random {k}-SAT n={num_vars} m={num_clauses}")
    for _ in range(num_clauses):
        vs = rng.sample(range(1, num_vars + 1), k)
        clause = [v if rng.random() < 0.5 else -v for v in vs]
        cnf.add_clause(clause)
    return cnf


def phase_transition(num_vars: int = 60, k: int = 3,
                     alpha_min: float = 2.0, alpha_max: float = 7.0,
                     steps: int = 26, samples: int = 40,
                     seed: int = 0, max_conflicts: int = 200000):
    """Sweep α = m/n and measure P(SAT) and median conflicts at each point.

    Returns a list of dicts: {alpha, p_sat, median_conflicts, samples}.
    """
    rng = random.Random(seed)
    results = []
    for s in range(steps):
        alpha = alpha_min + (alpha_max - alpha_min) * s / (steps - 1)
        m = max(1, round(alpha * num_vars))
        sat_count = 0
        conflicts = []
        valid = 0
        for _ in range(samples):
            cnf = random_ksat(num_vars, m, k, rng)
            solver = Solver(num_vars=cnf.num_vars)
            for cl in cnf.clauses:
                if not solver.add_clause(cl):
                    break
            res = solver.solve(max_conflicts=max_conflicts)
            if res == UNKNOWN:
                continue
            valid += 1
            if res == SAT:
                sat_count += 1
            conflicts.append(solver.stats.conflicts)
        conflicts.sort()
        median = conflicts[len(conflicts) // 2] if conflicts else 0
        results.append({
            "alpha": round(alpha, 3),
            "p_sat": round(sat_count / valid, 3) if valid else None,
            "median_conflicts": median,
            "samples": valid,
        })
    return results


def render_sweep_ascii(results) -> str:
    """A compact terminal chart of P(SAT) and solve cost vs α."""
    lines = []
    lines.append("  α     P(SAT)  median   |0" + " " * 23 + "P(SAT)" + " " * 16 + "1|")
    lines.append("  " + "-" * 70)
    for r in results:
        p = r["p_sat"]
        if p is None:
            bar = "?" * 0
            cell = " " * 50
        else:
            fill = int(round(p * 50))
            cell = "█" * fill + "·" * (50 - fill)
        mc = r["median_conflicts"]
        pv = f"{p:.2f}" if p is not None else " n/a"
        lines.append(f"  {r['alpha']:>4.2f}   {pv}   {mc:>6}   |{cell}|")
    # find crossing of 0.5
    cross = None
    prev = None
    for r in results:
        if r["p_sat"] is None:
            continue
        if prev is not None and prev[1] >= 0.5 > r["p_sat"]:
            # linear interpolate
            a0, p0 = prev
            a1, p1 = r["alpha"], r["p_sat"]
            cross = a0 + (a1 - a0) * (p0 - 0.5) / (p0 - p1)
            break
        prev = (r["alpha"], r["p_sat"])
    if cross is not None:
        lines.append("")
        lines.append(f"  P(SAT)=0.5 crossing at α ≈ {cross:.2f}   "
                     f"(known random-3-SAT threshold ≈ 4.26)")
    return "\n".join(lines)
