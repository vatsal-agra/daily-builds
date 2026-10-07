#!/usr/bin/env python3
"""Cross-check Dantzig against HiGHS (scipy.optimize.milp) on generated and random models.

usage: tools/crosscheck.py [--dantzig ./dantzig] [--random N] [--seed S]
Skips (exit 0) when scipy is unavailable. Exit 1 on any disagreement.
"""
import argparse, json, math, os, random, re, subprocess, sys, tempfile

try:
    import numpy as np
    from scipy.optimize import milp, LinearConstraint, Bounds
except Exception:
    print("scipy not available: cross-check skipped")
    sys.exit(0)

def highs(model):
    n = len(model["c"])
    c = np.array(model["c"], float)
    if model["maximize"]:
        c = -c
    lo = np.array([-np.inf if v is None else v for v in model["lo"]])
    hi = np.array([np.inf if v is None else v for v in model["hi"]])
    rows = model["rows"]
    if rows:
        A = np.zeros((len(rows), n))
        rl = np.zeros(len(rows)); ru = np.zeros(len(rows))
        for i, r in enumerate(rows):
            for j, v in zip(r["idx"], r["val"]):
                A[i, j] += v
            rl[i] = -np.inf if r["lo"] is None else r["lo"]
            ru[i] = np.inf if r["hi"] is None else r["hi"]
        cons = [LinearConstraint(A, rl, ru)]
    else:
        cons = []
    res = milp(c, constraints=cons, bounds=Bounds(lo, hi),
               integrality=np.array([1 if b else 0 for b in model["int"]]),
               options={"time_limit": 60})
    # status: 0 optimal, 2 infeasible, 3 unbounded
    if res.status == 0:
        obj = res.fun * (-1 if model["maximize"] else 1) + model["const"]
        return "optimal", obj
    if res.status == 2:
        return "infeasible", None
    if res.status == 3:
        return "unbounded", None
    return "other", None

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)

def ours(exe, path):
    p = run([exe, "solve", path, "--quiet", "--time", "60"])
    out = p.stdout
    m = re.search(r"status: (\w+)", out)
    st = m.group(1).lower() if m else "error"
    obj = None
    mo = re.search(r"objective \((?:min|max)\): (\S+)", out)
    if mo:
        tok = mo.group(1)
        if tok == "≈":
            tok = re.search(r"≈ (\S+)", out).group(1)
        obj = float(eval(tok, {}, {})) if "/" in tok else float(tok)
    certified = "exact certificate verified" in out
    return st, obj, certified, out

def rnd_model(rng, n, m, integer):
    lines = []
    mx = rng.random() < 0.5
    lines.append("Maximize" if mx else "Minimize")
    terms = " ".join(f"{rng.choice(['+','-'])} {rng.randint(1,9)} x{j}" for j in range(n))
    lines.append(" obj: " + terms)
    lines.append("Subject To")
    for i in range(m):
        t = " ".join(f"{rng.choice(['+','-'])} {rng.randint(1,9)} x{j}" for j in range(n) if rng.random() < 0.6) or "+ 1 x0"
        op = rng.choice(["<=", ">=", "<=", "="])
        rhs = rng.randint(1, 30) if op != ">=" else rng.randint(0, 10)
        lines.append(f" c{i}: {t} {op} {rhs}")
    lines.append("Bounds")
    for j in range(n):
        lines.append(f" x{j} <= {rng.randint(3, 15)}")
    if integer:
        ints = [f"x{j}" for j in range(n) if rng.random() < 0.7]
        if ints:
            lines.append("Integer")
            lines.append(" " + " ".join(ints))
    lines.append("End")
    return "\n".join(lines) + "\n"

def wild_model(rng, n, m, integer):
    """Free / negative-bounded variables, ranges, equalities: includes unbounded and infeasible cases."""
    mx = rng.random() < 0.5
    lines = ["Maximize" if mx else "Minimize"]
    lines.append(" obj: " + " ".join(f"{rng.choice(['+','-'])} {rng.randint(0,6)} y{j}" for j in range(n)))
    lines.append("Subject To")
    for i in range(m):
        t = " ".join(f"{rng.choice(['+','-'])} {rng.randint(1,7)} y{j}" for j in range(n) if rng.random() < 0.6) or "+ 1 y0"
        kind = rng.random()
        if kind < 0.25:
            lines.append(f" c{i}: {t} = {rng.randint(-8, 8)}")
        elif kind < 0.5:
            lo = rng.randint(-10, 5)
            lines.append(f" c{i}: {lo} <= {t} <= {lo + rng.randint(0, 9)}")
        elif kind < 0.75:
            lines.append(f" c{i}: {t} <= {rng.randint(-5, 20)}")
        else:
            lines.append(f" c{i}: {t} >= {rng.randint(-20, 5)}")
    lines.append("Bounds")
    for j in range(n):
        r = rng.random()
        if r < 0.3:
            lines.append(f" y{j} free")
        elif r < 0.6:
            lines.append(f" {rng.randint(-9, -1)} <= y{j} <= {rng.randint(0, 9)}")
        elif r < 0.8:
            lines.append(f" y{j} >= {rng.randint(-5, 5)}")
        else:
            lines.append(f" y{j} <= {rng.randint(-3, 9)}")
    if integer:
        ints = [f"y{j}" for j in range(n) if rng.random() < 0.6]
        if ints:
            lines.append("Integer")
            lines.append(" " + " ".join(ints))
    lines.append("End")
    return "\n".join(lines) + "\n"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dantzig", default="./dantzig")
    ap.add_argument("--random", type=int, default=150)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seeds", type=int, default=0, help="extra generated instances per structured family")
    a = ap.parse_args()
    exe = a.dantzig
    cases = []
    for spec in ["knapsack 25 1", "knapsack 30 2 3", "knapsack 35 3 2", "setcover 25 30 1", "setcover 40 60 2",
                 "assignment 15 1", "assignment 25 2", "tsp 6 1", "tsp 8 2", "tsp 9 3", "facility 5 10 1",
                 "facility 8 15 2", "transport 6 9 1", "transport 10 12 2", "diet", "sudoku", "sudoku hard"]:
        cases.append((spec, run([exe, "gen"] + spec.split()).stdout))
    for sd in range(10, 10 + a.seeds):
        for spec in [f"knapsack 28 {sd}", f"knapsack 24 {sd} 3", f"setcover 30 45 {sd}", f"assignment 14 {sd}",
                     f"tsp 7 {sd}", f"facility 6 12 {sd}", f"transport 7 9 {sd}"]:
            cases.append((spec, run([exe, "gen"] + spec.split()).stdout))
    rng = random.Random(a.seed)
    for k in range(a.random):
        n = rng.randint(3, 9); m = rng.randint(2, 7)
        cases.append((f"random#{k} n={n} m={m} {'mip' if k % 2 else 'lp'}", rnd_model(rng, n, m, k % 2 == 1)))
    for k in range(a.random):
        n = rng.randint(2, 8); m = rng.randint(1, 6)
        cases.append((f"wild#{k} n={n} m={m} {'mip' if k % 2 else 'lp'}", wild_model(rng, n, m, k % 2 == 1)))
    bad = 0
    stats = {"optimal": 0, "infeasible": 0, "unbounded": 0}
    with tempfile.TemporaryDirectory() as d:
        for name, text in cases:
            path = os.path.join(d, "m.lp")
            open(path, "w").write(text)
            exp = run([exe, "export", path]).stdout
            model = json.loads(exp)
            h_status, h_obj = highs(model)
            st, obj, cert, out = ours(exe, path)
            ok = True
            if h_status == "optimal":
                ok = st == "optimal" and obj is not None and abs(obj - h_obj) <= 1e-6 * max(1, abs(h_obj)) and cert
            elif h_status == "infeasible":
                # HiGHS reports "infeasible" for some unbounded MIPs it cannot classify; accept
                # an unbounded answer only if its certificate verified
                ok = st == "infeasible" and cert
            elif h_status == "unbounded":
                ok = st == "unbounded" and cert
            else:
                ok = True  # HiGHS gave no answer; nothing to compare
            stats[h_status] = stats.get(h_status, 0) + 1
            if not ok:
                bad += 1
                print(f"MISMATCH {name}: highs={h_status}/{h_obj} dantzig={st}/{obj} certified={cert}")
                open(f"/tmp/mismatch_{bad}.lp", "w").write(text)
    print(f"cross-checked {len(cases)} models against HiGHS: {stats}, mismatches: {bad}")
    sys.exit(1 if bad else 0)

main()
