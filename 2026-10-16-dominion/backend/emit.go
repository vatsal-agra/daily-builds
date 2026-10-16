package backend

import (
	"fmt"
	"strings"

	"dominion/ir"
	"dominion/vm"
)

// Config selects the register file.
type Config struct {
	NumRegs int // allocatable registers (>= 4); half are caller-saved, half callee-saved
}

// FuncReport summarises allocation for one function.
type FuncReport struct {
	Name        string
	Instrs      int
	Vregs       int
	Spilled     int
	CalleeSaved int // callee-saved registers used (saved in prologue)
	FrameWords  int
}

// Output of Compile.
type Output struct {
	Prog   *vm.Program
	Report []FuncReport
}

func (o *Output) ReportString() string {
	var sb strings.Builder
	fmt.Fprintf(&sb, "%-14s %7s %6s %8s %12s %6s\n", "function", "instrs", "vregs", "spilled", "callee-saved", "frame")
	for _, r := range o.Report {
		fmt.Fprintf(&sb, "%-14s %7d %6d %8d %12d %6d\n", r.Name, r.Instrs, r.Vregs, r.Spilled, r.CalleeSaved, r.FrameWords)
	}
	return sb.String()
}

type loc struct {
	reg bool
	n   int // register number or frame offset
}

type srcv struct {
	imm bool
	v   int64
	l   loc
}

type emitter struct {
	cfg      Config
	cs       int
	code     []vm.Instr
	lv       *liveness
	mf       *mfunc
	loc      []loc
	arrOff   map[*ir.Value]int
	fix      []fixup
	blockPC  map[*mblock]int
	saveRegs []int
	saveOff  []int
}

type fixup struct {
	at int
	to *mblock
}

func (e *emitter) scratch(i int) int { return e.cfg.NumRegs + i }

func (e *emitter) put(in vm.Instr) { e.code = append(e.code, in) }

// src returns an operand for a vreg operand, loading spilled values into scratch register si.
func (e *emitter) src(o mopnd, si int) vm.Operand {
	if o.imm {
		return vm.I(o.v)
	}
	l := e.loc[o.vr]
	if l.reg {
		return vm.R(l.n)
	}
	e.put(vm.Instr{Op: vm.Ld, Rd: e.scratch(si), Off: l.n})
	return vm.R(e.scratch(si))
}

// dstReg returns the register to compute into and a finisher that stores it if the vreg is spilled.
func (e *emitter) dstReg(v int) (int, func()) {
	l := e.loc[v]
	if l.reg {
		return l.n, func() {}
	}
	s := e.scratch(0)
	return s, func() { e.put(vm.Instr{Op: vm.St, Off: l.n, A: vm.R(s)}) }
}

func (e *emitter) move(dst loc, s srcv) {
	switch {
	case dst.reg && s.imm:
		e.put(vm.Instr{Op: vm.Mov, Rd: dst.n, A: vm.I(s.v)})
	case dst.reg && s.l.reg:
		e.put(vm.Instr{Op: vm.Mov, Rd: dst.n, A: vm.R(s.l.n)})
	case dst.reg:
		e.put(vm.Instr{Op: vm.Ld, Rd: dst.n, Off: s.l.n})
	case s.imm:
		e.put(vm.Instr{Op: vm.St, Off: dst.n, A: vm.I(s.v)})
	case s.l.reg:
		e.put(vm.Instr{Op: vm.St, Off: dst.n, A: vm.R(s.l.n)})
	default:
		t := e.scratch(1)
		e.put(vm.Instr{Op: vm.Ld, Rd: t, Off: s.l.n})
		e.put(vm.Instr{Op: vm.St, Off: dst.n, A: vm.R(t)})
	}
}

type pmove struct {
	dst loc
	src srcv
}

// parallelCopy performs all moves "simultaneously": every source is read before any destination
// is overwritten. Cycles are broken with scratch register #2.
func (e *emitter) parallelCopy(moves []pmove) {
	var ms []pmove
	for _, m := range moves {
		if !m.src.imm && m.src.l == m.dst {
			continue
		}
		ms = append(ms, m)
	}
	tmp := loc{reg: true, n: e.scratch(2)}
	for len(ms) > 0 {
		progressed := false
		for i, m := range ms {
			blocked := false
			for j, o := range ms {
				if j != i && !o.src.imm && o.src.l == m.dst {
					blocked = true
					break
				}
			}
			if !blocked {
				e.move(m.dst, m.src)
				ms = append(ms[:i], ms[i+1:]...)
				progressed = true
				break
			}
		}
		if progressed {
			continue
		}
		d := ms[0].dst
		e.move(tmp, srcv{l: d})
		for i := range ms {
			if !ms[i].src.imm && ms[i].src.l == d {
				ms[i].src.l = tmp
			}
		}
	}
}

func (e *emitter) srcOf(o mopnd) srcv {
	if o.imm {
		return srcv{imm: true, v: o.v}
	}
	return srcv{l: e.loc[o.vr]}
}

func (e *emitter) emitInstr(mi *minstr) {
	switch mi.k {
	case kParam:
		l := e.loc[mi.dst]
		if l.reg {
			e.put(vm.Instr{Op: vm.Ld, Rd: l.n, Off: mi.argIdx, Comment: fmt.Sprintf("param %d", mi.argIdx)})
		}
	case kMov:
		a := e.src(mi.a, 0)
		d, fin := e.dstReg(mi.dst)
		e.put(vm.Instr{Op: vm.Mov, Rd: d, A: a})
		fin()
	case kAlu:
		a := e.src(mi.a, 0)
		var b, c vm.Operand
		switch {
		case mi.alu == ir.OpNeg || mi.alu == ir.OpNot:
		case mi.alu == ir.OpSelect:
			b, c = e.src(mi.b, 1), e.src(mi.c, 2)
		default:
			b = e.src(mi.b, 1)
		}
		d, fin := e.dstReg(mi.dst)
		e.put(vm.Instr{Op: vm.Alu, ALU: mi.alu, Rd: d, A: a, B: b, C: c})
		fin()
	case kLdX:
		a := e.src(mi.a, 1)
		d, fin := e.dstReg(mi.dst)
		e.put(vm.Instr{Op: vm.LdX, Rd: d, A: a, Off: e.arrOff[mi.arr], Size: mi.arr.Const})
		fin()
	case kStX:
		a, b := e.src(mi.a, 0), e.src(mi.b, 1)
		e.put(vm.Instr{Op: vm.StX, A: a, B: b, Off: e.arrOff[mi.arr], Size: mi.arr.Const})
	case kSetArg:
		e.put(vm.Instr{Op: vm.SetArg, Off: mi.argIdx, A: e.src(mi.a, 0)})
	case kPrint:
		e.put(vm.Instr{Op: vm.Print, A: e.src(mi.a, 0)})
	case kCall:
		e.put(vm.Instr{Op: vm.Call, Target: mi.callee, Comment: "@" + mi.cname})
		if mi.dst >= 0 {
			l := e.loc[mi.dst]
			if l.reg {
				if l.n != 0 {
					e.put(vm.Instr{Op: vm.Mov, Rd: l.n, A: vm.R(0)})
				}
			} else {
				e.put(vm.Instr{Op: vm.St, Off: l.n, A: vm.R(0)})
			}
		}
	case kRet:
		if mi.a.imm {
			e.put(vm.Instr{Op: vm.Mov, Rd: 0, A: vm.I(mi.a.v)})
		} else if l := e.loc[mi.a.vr]; l.reg {
			if l.n != 0 {
				e.put(vm.Instr{Op: vm.Mov, Rd: 0, A: vm.R(l.n)})
			}
		} else {
			e.put(vm.Instr{Op: vm.Ld, Rd: 0, Off: l.n})
		}
		for i, r := range e.saveRegs {
			e.put(vm.Instr{Op: vm.Ld, Rd: r, Off: e.saveOff[i], Comment: "restore callee-saved"})
		}
		e.put(vm.Instr{Op: vm.Ret})
	case kPCopy:
		var ms []pmove
		for i, d := range mi.dsts {
			ms = append(ms, pmove{e.loc[d], e.srcOf(mi.srcs[i])})
		}
		e.parallelCopy(ms)
	case kJmp:
		e.fix = append(e.fix, fixup{len(e.code), mi.target})
		e.put(vm.Instr{Op: vm.Jmp})
	case kBrnz, kBrz:
		op := vm.Brnz
		if mi.k == kBrz {
			op = vm.Brz
		}
		a := e.src(mi.a, 0)
		e.fix = append(e.fix, fixup{len(e.code), mi.target})
		e.put(vm.Instr{Op: op, A: a})
	}
}

// Compile translates an optimised (or unoptimised) module to a DVM program. The input module is
// not modified (the backend works on a private copy).
func Compile(src *ir.Module, cfg Config) (*Output, error) {
	if cfg.NumRegs == 0 {
		cfg.NumRegs = 12
	}
	if cfg.NumRegs < 4 || cfg.NumRegs > 64 {
		return nil, fmt.Errorf("backend: register count must be in 4..64, got %d", cfg.NumRegs)
	}
	if err := src.Verify(); err != nil {
		return nil, fmt.Errorf("backend: refusing invalid IR: %w", err)
	}
	m, err := ir.Parse(src.String()) // private copy
	if err != nil {
		return nil, fmt.Errorf("backend: cloning module: %w", err)
	}
	fidx := map[string]int{}
	for i, f := range m.Funcs {
		fidx[f.Name] = i
	}
	cs := (cfg.NumRegs + 1) / 2
	prog := &vm.Program{NumRegs: cfg.NumRegs, CallerSaved: cs, Scratch: 3}
	out := &Output{Prog: prog}
	for _, f := range m.Funcs {
		mf, err := buildMIR(m, f, fidx)
		if err != nil {
			return nil, err
		}
		lv := mf.analyze()
		spills := linearScan(lv.ivals, cfg.NumRegs, cs)
		e := &emitter{cfg: cfg, cs: cs, lv: lv, mf: mf, arrOff: map[*ir.Value]int{}, blockPC: map[*mblock]int{}}
		// frame layout: params | spills | arrays | callee-save area
		off := len(f.Params)
		e.loc = make([]loc, mf.nvreg)
		paramVreg := map[int]int{}
		for _, mb := range mf.blocks {
			for _, mi := range mb.instrs {
				if mi.k == kParam {
					paramVreg[mi.dst] = mi.argIdx
				}
			}
		}
		used := map[int]bool{}
		for _, iv := range lv.ivals {
			if iv.reg >= 0 {
				e.loc[iv.v] = loc{reg: true, n: iv.reg}
				used[iv.reg] = true
				continue
			}
			if pi, ok := paramVreg[iv.v]; ok {
				iv.off = pi
			} else {
				iv.off = off
				off++
			}
			e.loc[iv.v] = loc{n: iv.off}
		}
		for _, v := range f.Entry().Instrs {
			if v.Op == ir.OpAlloca {
				e.arrOff[v] = off
				off += int(v.Const)
			}
		}
		for r := cs; r < cfg.NumRegs; r++ {
			if used[r] {
				e.saveRegs = append(e.saveRegs, r)
				e.saveOff = append(e.saveOff, off)
				off++
			}
		}
		entry := len(prog.Code)
		for i, r := range e.saveRegs {
			e.put(vm.Instr{Op: vm.St, Off: e.saveOff[i], A: vm.R(r), Comment: "save callee-saved"})
		}
		for _, mb := range mf.blocks {
			e.blockPC[mb] = len(e.code)
			for _, mi := range mb.instrs {
				e.emitInstr(mi)
			}
		}
		for _, fx := range e.fix {
			e.code[fx.at].Target = entry + e.blockPC[fx.to]
		}
		prog.Code = append(prog.Code, e.code...)
		prog.Funcs = append(prog.Funcs, vm.FuncInfo{Name: f.Name, Entry: entry, NParams: len(f.Params), FrameSize: off})
		out.Report = append(out.Report, FuncReport{f.Name, len(e.code), mf.nvreg, spills, len(e.saveRegs), off})
	}
	return out, nil
}
