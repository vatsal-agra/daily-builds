"""Mutation testing of Argus itself: inject one plausible bug at a time, run the unit/fuzz suite and
demo.sh, and report whether anything noticed.  Edits sources in place and always restores them.

    python3 tools/mutate.py            (takes ~10 minutes; run from the project directory)

Recorded result (see README): 9/9 non-equivalent mutants killed by the unit + fuzz suite; the
within-level BFS reordering survives because it is an *equivalent* mutant (BFS levels still give
shortest traces).
"""
import subprocess, sys
MUTANTS = [
 ("weak fairness ignored", "argus/live.py", "                if all_en & ~taken:\n                    continue\n                return C", "                return C"),
 ("strong refinement dropped", "argus/live.py", "            refined = {u for u in C if not (en[u] & bad)}\n            if refined:\n                work.append(refined)", "            return C"),
 ("validator skips state compare", "argus/trace.py", "            if hit[0] != claimed:\n                raise ValidationError(f\"step {i}: recorded state differs from re-executed state\")\n", ""),
 ("lasso fairness unchecked in validator", "argus/trace.py", "    if fairness != \"none\":\n        cls_enabled", "    if False:\n        cls_enabled"),
 ("until acceptance dropped", "argus/ltl.py", "acc.append({i for i, n in enumerate(order) if u not in n.old or u[2] in n.old})", "acc.append(set(range(len(order))))"),
 ("end-label deadlock rule", "argus/model.py", "            if lab.startswith(\"end\"):", "            if False:"),
 ("POR cycle proviso removed", "argus/safety.py", "        if all(t not in visited for _, _, t in mine):\n            return mine, True", "        return mine, True"),
 ("POR ignores observed procs", "argus/safety.py", "        if p.id in observed:\n            continue\n", ""),
 ("state limit silently ignored", "argus/safety.py", "                res.limited = True\n                break", "                pass"),
 ("level order scrambled (equivalent mutant)", "argus/safety.py", "        level = nxt\n", "        level = nxt[::-1]\n"),
]
res = []
for name, f, old, new in MUTANTS:
    src = open(f).read()
    assert old in src, (name, f)
    open(f, "w").write(src.replace(old, new, 1))
    try:
        p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], capture_output=True, text=True, timeout=300)
        tail = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ""
        killed = p.returncode != 0
        d = subprocess.run(["bash", "-c", "SKIP_TESTS=1 ./demo.sh >/dev/null 2>&1"], timeout=300).returncode != 0
    except subprocess.TimeoutExpired:
        killed, d, tail = True, True, "timeout"
    finally:
        open(f, "w").write(src)
    res.append((name, killed, d, tail))
    print(f"{'KILLED ' if killed else 'SURVIVED'} unit={killed!s:5} demo={d!s:5} {name}   [{tail}]", flush=True)
