#!/usr/bin/env python3
"""Mutation analysis of Dominion's own test-suite.

Each mutant is a one-line, plausible compiler bug (wrong sign, swapped operand, off-by-one, missing
restore ...). The suite (`go test -short ./...`, which includes the differential fuzzers) must fail for
every mutant; survivors are printed and make the script exit non-zero.

usage: scripts/mutants.py [name-substring ...]
"""
import os, subprocess, sys, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
os.chdir(ROOT)

M = [
 # name, file, original text, mutated text
 ("instcombine: x-c -> x+c",            "opt/instcombine.go", "v.Op, v.Args[1] = ir.OpAdd, c(-y.Const)", "v.Op, v.Args[1] = ir.OpAdd, c(y.Const)"),
 ("instcombine: mul 2^k -> shl k+1",    "opt/instcombine.go", "c(int64(bits.TrailingZeros64(uint64(y.Const))))\n\t\t\t\t*changed", "c(int64(bits.TrailingZeros64(uint64(y.Const)))+1)\n\t\t\t\t*changed"),
 ("instcombine: x/2^k without bias",    "opt/instcombine.go", "bias := emit(ir.OpAnd, neg, c(y.Const-1))\n\t\t\t\treturn emit(ir.OpShr, emit(ir.OpAdd, x, bias), c(k))", "_ = neg\n\t\t\t\treturn emit(ir.OpShr, x, c(k))"),
 ("instcombine: x%2^k wrong mask",      "opt/instcombine.go", "c(-y.Const)))", "c(y.Const)))"),
 ("instcombine: x*-1 -> x",             "opt/instcombine.go", "v.Op, v.Args = ir.OpNeg, []*ir.Value{x}", "return x"),
 ("instcombine: eq cmp,0 not inverted", "opt/instcombine.go", "v.Op, v.Args = invertCmp(x.Op), []*ir.Value{x.Args[0], x.Args[1]}", "v.Op, v.Args = x.Op, []*ir.Value{x.Args[0], x.Args[1]}"),
 ("sccp: select arm inverted",          "opt/sccp.go", "if ls[0].c == 0 {\n\t\t\t\tarm = ls[2]", "if ls[0].c != 0 {\n\t\t\t\tarm = ls[2]"),
 ("sccp: mul absorbs on 1",             "opt/sccp.go", "if ls[i].k == latConst && ls[i].c == 0 {", "if ls[i].k == latConst && ls[i].c == 1 {"),
 ("sccp: ignores executable edges",     "opt/sccp.go", "if execEdge[[2]*ir.Block{ph.Block.Preds[i], ph.Block}] {", "if i >= 0 {"),
 ("ir: trapping div treated as pure",   "ir/ir.go", "return !(d.IsConst() && d.Const != 0)", "_ = d\n\t\treturn false"),
 ("gvn: key ignores opcode",            "opt/gvn.go", "k := v.Op.String()", "k := \"\""),
 ("memopt: store never kills aliases",  "opt/gvn.go", "if idx != nil && idx.IsConst() && k.idx.IsConst() && idx.Const != k.idx.Const {", "if true {"),
 ("memopt: loads keep stores pending",  "opt/gvn.go", "for pk := range pendingStore { // a load may observe any store to this slot", "for pk := range map[key]*ir.Value{} {"),
 ("dce: stores live without loads",     "opt/dce.go", "if v.Op == ir.OpLoad && !slotNeeded[v.Args[0]] {", "if false {"),
 ("licm: hoists loads of stored slots", "opt/licm.go", "stored[v.Args[0]] || !idx.IsConst()", "!idx.IsConst()"),
 ("licm: preheader phi order",          "opt/licm.go", "np.Args = append(np.Args, phi.Args[i])", "np.Args = append([]*ir.Value{phi.Args[i]}, np.Args...)"),
 ("mem2reg: wrong successor value",     "opt/mem2reg.go", "ph.Args[k] = cur[i][len(cur[i])-1]", "ph.Args[k] = cur[i][0]"),
 ("simplifycfg: merge with 2 preds",    "opt/cfg.go", "if s == b || s == f.Entry() || len(s.Preds) != 1 {", "if s == b || s == f.Entry() || len(s.Preds) > 2 {"),
 ("simplifycfg: forward drops phi arg", "opt/cfg.go", "ph.Args = append(ph.Args, ph.Args[idx])", "ph.Args = append(ph.Args, ph.Args[0+idx*0])"),
 ("inline: no re-zeroing of allocas",   "opt/inline.go", "zeroing = append(zeroing, f.NewValue(ir.OpStore, v, f.Const(k), f.Const(0)))", "_ = k"),
 ("inline: return phi order reversed",  "opt/inline.go", "ph := f.NewValue(ir.OpPhi, retVals...)", "ph := f.NewValue(ir.OpPhi, append([]*ir.Value{retVals[len(retVals)-1]}, retVals[:len(retVals)-1]...)...)"),
 ("tre: tail-call args permuted",       "opt/tre.go", "phis[i].Args = append(phis[i].Args, c.Args[i])", "phis[i].Args = append(phis[i].Args, c.Args[(i+1)%len(c.Args)])"),
 ("unroll: trip count off by one",      "opt/unroll.go", "return k, true", "return k + 1, true"),
 ("unroll: live-outs not remapped",     "opt/unroll.go", "repl.Add(v, m)", "_ = m"),
 ("unroll: previous iteration value",   "opt/unroll.go", "a := ph.Args[li]\n\t\tif m, ok := prev.vmap[a]; ok {", "a := ph.Args[li]\n\t\tif m, ok := prev.vmap[ph]; ok {"),
 ("ifconv: select arms swapped",        "opt/ifconv.go", "sel := f.NewValue(ir.OpSelect, h.Ctrl, ph.Args[ti], ph.Args[ei])", "sel := f.NewValue(ir.OpSelect, h.Ctrl, ph.Args[ei], ph.Args[ti])"),
 ("ifconv: speculates anything",        "opt/ifconv.go", "return cost <= ifconvBudget", "return true"),
 ("ifconv: speculates loads",           "opt/ifconv.go", "if !v.IsPure() { // loads, calls, stores, trapping division stay put\n\t\t\treturn false\n\t\t}", "if v.Op == ir.OpStore || v.Op == ir.OpCall || v.Op == ir.OpPrint {\n\t\t\treturn false\n\t\t}"),
 ("regalloc: ignores call crossing",    "backend/regalloc.go", "iv.crosses = i < len(lv.calls) && lv.calls[i] < iv.end", "_ = i\n\t\tiv.crosses = false"),
 ("regalloc: expires too early",        "backend/regalloc.go", "if a.end < iv.start {", "if a.end <= iv.start+1 {"),
 ("emit: callee-saved not restored",    "backend/emit.go", "e.put(vm.Instr{Op: vm.Ld, Rd: r, Off: e.saveOff[i], Comment: \"restore callee-saved\"})", "_, _ = r, i"),
 ("emit: parallel copy w/o cycle break","backend/emit.go", "d := ms[0].dst\n\t\te.move(tmp, srcv{l: d})", "d := ms[0].dst\n\t\te.move(d, ms[0].src)\n\t\tms = ms[1:]\n\t\tcontinue\n\t\te.move(tmp, srcv{l: d})"),
 ("emit: spilled param gets fresh slot","backend/emit.go", "if pi, ok := paramVreg[iv.v]; ok {\n\t\t\t\tiv.off = pi", "if pi, ok := paramVreg[iv.v]; ok && false {\n\t\t\t\tiv.off = pi"),
 ("emit: select operand c unspilled",   "backend/emit.go", "b, c = e.src(mi.b, 1), e.src(mi.c, 2)", "b, c = e.src(mi.b, 1), e.src(mi.c, 1)"),
 ("backend: no critical edge split",    "backend/mir.go", "if len(s.Phis) == 0 {\n\t\t\t\tcontinue\n\t\t\t}", "if true {\n\t\t\t\tcontinue\n\t\t\t}"),
 ("vm: caller-saved not poisoned",      "vm/vm.go", "regs[r] = poison\n\t\t\t\t}\n\t\t\t}\n\t\t\tfor r := p.NumRegs", "_ = r\n\t\t\t\t}\n\t\t\t}\n\t\t\tfor r := p.NumRegs"),
 ("ir: dominance frontier off",         "ir/dom.go", "for r := p; r != nil && r != d.Idom[b]; r = d.Idom[r] {", "for r := p; r != nil && r != b; r = d.Idom[r] {"),
 ("ir: verifier skips dominance",       "ir/verify.go", "if !dom.Dominates(db, useBlk) {", "if false {"),
 ("ir: phis evaluated sequentially",    "ir/interp.go", "tmp[i] = get(ph.Args[k])", "tmp[i] = get(ph.Args[k]); vals[ph.ID] = tmp[i]"),
 ("front: continue skips for-step",     "front/lower.go", "cont = pb", "cont = hdr"),
 ("front: && evaluates rhs eagerly",    "front/lower.go", "if err := l.cond(e.l, mid, fb); err != nil {", "if err := l.cond(e.l, tb, fb); err != nil {"),
]

import concurrent.futures, shutil, tempfile

def run_one(m):
    name, path, old, new = m
    work = tempfile.mkdtemp(prefix="dominion-mut-")
    try:
        shutil.copytree(ROOT, work, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "*.report.html", "*.png"))
        f = os.path.join(work, path)
        src = open(f).read()
        if old not in src:
            return (name, "invalid", f"pattern not found in {path}", 0)
        open(f, "w").write(src.replace(old, new, 1))
        t0 = time.time()
        b = subprocess.run(["go", "build", "./..."], capture_output=True, text=True, cwd=work)
        if b.returncode != 0:
            return (name, "invalid", "mutant does not compile: " + b.stderr.strip().splitlines()[0], 0)
        try:
            r = subprocess.run(["go", "test", "-short", "-count=1", "./..."], capture_output=True, text=True, timeout=300, cwd=work)
        except subprocess.TimeoutExpired:
            return (name, "kill", "test run hung (infinite loop in the mutant)", time.time() - t0)
        dt = time.time() - t0
        if r.returncode != 0:
            first = next((l for l in r.stdout.splitlines() if l.startswith("--- FAIL")), None) or next((l for l in r.stdout.splitlines() if l.startswith("FAIL")), "FAIL")
            return (name, "kill", first[:70], dt)
        return (name, "live", "", dt)
    finally:
        shutil.rmtree(work, ignore_errors=True)

only = sys.argv[1:]
todo = [m for m in M if not only or any(o in m[0] for o in only)]
survived, invalid, killed = [], [], 0
workers = max(1, (os.cpu_count() or 2) // 2)
with concurrent.futures.ThreadPoolExecutor(workers) as ex:
    for name, status, info, dt in ex.map(run_one, todo):
        tag = {"kill": "kill ", "live": "LIVE ", "invalid": "??   "}[status]
        print(f"  {tag} {name}  ({dt:.0f}s)  {info}", flush=True)
        if status == "kill": killed += 1
        elif status == "live": survived.append(name)
        else: invalid.append(name)
print(f"\n{killed} killed, {len(survived)} survived, {len(invalid)} invalid", flush=True)
for s_ in survived:
    print("  survivor:", s_)
sys.exit(1 if survived or invalid else 0)
