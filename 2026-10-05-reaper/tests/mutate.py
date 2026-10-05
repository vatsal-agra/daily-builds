#!/usr/bin/env python3
"""Mutation testing for the test harness itself.

Each mutant plants one realistic GC bug in a scratch copy of the sources, rebuilds, and runs the
differential fuzzer. A mutant that the fuzzer does NOT kill is a hole in the test suite, so the
script exits non-zero if any survive.
"""
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MUTANTS = [
    ("generational", "src/generational.cpp", "if (obj < nurStart && val >= nurStart) {", "if (false) {",
     "write barrier never fires"),
    ("generational", "src/generational.cpp", "for (Ref o : remembered) {", "for (Ref o : std::vector<Ref>{}) {",
     "minor GC ignores the remembered set"),
    ("generational", "src/generational.cpp", "for (Ref& r : roots) r = evacuate(r);", "",
     "minor GC does not update roots"),
    ("incremental", "src/incremental.cpp", "if (st == MARK && val != NIL", "if (false && st == MARK && val != NIL",
     "Dijkstra insertion barrier removed"),
    ("incremental", "src/incremental.cpp", "  for (Ref r : roots) markObject(r, gray);\n  drainMarks(gray, &cycleLive);\n  touchLive",
     "  drainMarks(gray, &cycleLive);\n  touchLive", "root rescan at mark termination removed"),
    ("incremental", "src/incremental.cpp", "if (!isFree && !dead) { mem[pos] &= ~MARK_BIT; flushPending(); continue; }",
     "if (!isFree && !dead) { flushPending(); continue; }", "sweep forgets to clear mark bits"),
    ("marksweep", "src/marksweep.cpp", "bool dead = !isFree && !(mem[pos] & MARK_BIT);",
     "bool dead = !isFree && !(mem[pos] & MARK_BIT) && tag((Ref)pos) != 3;", "leaks every object with tag 3"),
    ("marksweep", "src/marksweep.cpp", "if (!isFree && !dead) { mem[pos] &= ~MARK_BIT; lastFree = NIL; pos += sz; continue; }",
     "if (!isFree && !dead) { lastFree = NIL; pos += sz; continue; }", "sweep forgets to clear mark bits"),
    ("marksweep", "src/marksweep.cpp", "if (lastFree != NIL && lastFree + size(lastFree) == pos) {",
     "if (lastFree != NIL && lastFree + size(lastFree) == pos + 1) {", "coalescing condition off by one (never coalesces)"),
    ("markcompact", "src/heap.cpp", "if (f != NIL) f = mem[f + 1];", "", "compaction does not rewrite heap pointers"),
    ("markcompact", "src/heap.cpp", "for (Ref& r : roots) if (r != NIL) r = (Ref)mem[r + 1];", "",
     "compaction does not rewrite roots"),
    ("markcompact", "src/heap.cpp", "std::memmove(&mem[to], &mem[pos], sz * sizeof(Word));",
     "std::memmove(&mem[to], &mem[pos], (sz - 1) * sizeof(Word));", "slide copies one word too few"),
    ("copying", "src/copying.cpp", "for (Ref& r : roots) r = evacuate(r, free);", "", "roots not evacuated"),
    ("copying", "src/copying.cpp", "mem[o + HDR + i] = evacuate((Ref)mem[o + HDR + i], free);",
     "evacuate((Ref)mem[o + HDR + i], free);", "Cheney scan does not rewrite fields"),
    ("copying", "src/copying.cpp", "if (mem[r] & FWD_BIT) return (Ref)mem[r + 1];", "",
     "no forwarding check (shared objects get duplicated)"),
    ("marksweep", "src/marksweep.cpp", "freeW -= w;", "", "free-word accounting broken"),
]

WORKLOADS = "graph-fuzz,pointer-shuffle,lru-cache"

def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    survivors, killed = [], 0
    for gc, path, old, new, why in MUTANTS:
        if only and only != gc:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            for d in ("src",):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(tmp, d))
            shutil.copy(os.path.join(ROOT, "Makefile"), tmp)
            f = os.path.join(tmp, path)
            text = open(f).read()
            if old not in text:
                print(f"BROKEN MUTANT (pattern not found): {why}")
                survivors.append(why)
                continue
            open(f, "w").write(text.replace(old, new, 1))
            b = run(["make", "-j8", "reaper"], tmp)
            if b.returncode != 0:
                print(f"BROKEN MUTANT (does not compile): {why}\n{b.stderr[-400:]}")
                survivors.append(why)
                continue
            verdict = None
            # the incremental collector needs long mark phases (small heap, tiny slice) to expose barrier bugs
            extra = ["--heap", "12000", "--param", "4", "--steps", "15000", "--seeds", "6"] if gc == "incremental" else \
                    ["--heap", "32768", "--steps", "6000", "--seeds", "4"]
            for w in WORKLOADS.split(","):
                r = run(["timeout", "120", "./reaper", "fuzz", "--gc", gc, "--workload", w] + extra, tmp)
                if r.returncode != 0:
                    lines = (r.stdout + r.stderr).strip().splitlines()
                    verdict = (w, lines[0][:110] if lines else f"crashed (exit {r.returncode})")
                    break
            if verdict:
                killed += 1
                print(f"killed   [{gc:12}] {why:58} <- {verdict[0]}: {verdict[1]}")
            else:
                survivors.append(why)
                print(f"SURVIVED [{gc:12}] {why}")
    print(f"\n{killed} mutants killed, {len(survivors)} survived")
    return 1 if survivors else 0

if __name__ == "__main__":
    sys.exit(main())
