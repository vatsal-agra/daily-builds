// Package backend lowers SSA IR to DVM machine code: critical-edge splitting, phi elimination via
// parallel copies, liveness, linear-scan register allocation and emission.
package backend

import (
	"fmt"

	"dominion/ir"
)

type kind int

const (
	kMov kind = iota
	kAlu
	kLdX
	kStX
	kJmp
	kBrnz
	kBrz
	kSetArg
	kCall
	kRet
	kPrint
	kPCopy
	kParam
)

// mopnd is a machine operand over virtual registers.
type mopnd struct {
	imm bool
	v   int64 // immediate
	vr  int   // virtual register
}

type minstr struct {
	k       kind
	alu     ir.Op
	dst     int // vreg, -1 if none
	a, b, c mopnd
	arr     *ir.Value // alloca for kLdX / kStX
	callee  int
	cname   string
	target  *mblock // kJmp / kBrnz
	argIdx  int     // kSetArg index / kParam index
	dsts    []int   // kPCopy
	srcs    []mopnd // kPCopy
}

type mblock struct {
	b       *ir.Block
	instrs  []*minstr
	pos     int // index of the first instruction in the function's linear order
	liveIn  bitset
	liveOut bitset
}

type mfunc struct {
	f      *ir.Func
	blocks []*mblock
	nvreg  int
	vid    map[*ir.Value]int
	params int
}

func (mf *mfunc) vreg(v *ir.Value) int {
	if id, ok := mf.vid[v]; ok {
		return id
	}
	id := mf.nvreg
	mf.nvreg++
	mf.vid[v] = id
	return id
}

func (mf *mfunc) opnd(v *ir.Value) mopnd {
	if v.IsConst() {
		return mopnd{imm: true, v: v.Const}
	}
	return mopnd{vr: mf.vreg(v)}
}

func uses(mi *minstr) []int {
	var u []int
	add := func(o mopnd) {
		if !o.imm {
			u = append(u, o.vr)
		}
	}
	switch mi.k {
	case kMov, kSetArg, kPrint, kBrnz, kBrz, kRet:
		add(mi.a)
	case kAlu:
		add(mi.a)
		add(mi.b)
		if mi.alu == ir.OpSelect {
			add(mi.c)
		}
	case kLdX:
		add(mi.a)
	case kStX:
		add(mi.a)
		add(mi.b)
	case kPCopy:
		for _, s := range mi.srcs {
			add(s)
		}
	}
	return u
}

func defs(mi *minstr) []int {
	switch mi.k {
	case kPCopy:
		return mi.dsts
	case kMov, kAlu, kLdX, kCall, kParam:
		if mi.dst >= 0 {
			return []int{mi.dst}
		}
	}
	return nil
}

// splitCriticalEdges inserts a block on every edge from a multi-successor block to a block with phis.
func splitCriticalEdges(f *ir.Func) {
	for _, b := range append([]*ir.Block(nil), f.Blocks...) {
		if len(b.Succs) < 2 {
			continue
		}
		for i, s := range b.Succs {
			if len(s.Phis) == 0 {
				continue
			}
			nb := f.NewBlock(f.UniqueBlockName(b.Name + ".to." + s.Name))
			nb.Term, nb.Succs, nb.Preds = ir.TermBr, []*ir.Block{s}, []*ir.Block{b}
			b.Succs[i] = nb
			for k, p := range s.Preds {
				if p == b {
					s.Preds[k] = nb
					break
				}
			}
		}
	}
}

// buildMIR translates one function in linear (reverse post) order.
func buildMIR(m *ir.Module, f *ir.Func, fidx map[string]int) (*mfunc, error) {
	if len(f.Params) > 64 {
		return nil, fmt.Errorf("@%s: more than 64 parameters", f.Name)
	}
	splitCriticalEdges(f)
	mf := &mfunc{f: f, vid: map[*ir.Value]int{}, params: len(f.Params)}
	order := ir.ReversePostorder(f)
	byIR := map[*ir.Block]*mblock{}
	for _, b := range order {
		mb := &mblock{b: b}
		byIR[b] = mb
		mf.blocks = append(mf.blocks, mb)
	}
	for bi, b := range order {
		mb := byIR[b]
		emit := func(mi *minstr) *minstr {
			mb.instrs = append(mb.instrs, mi)
			return mi
		}
		if bi == 0 {
			for i, p := range f.Params {
				emit(&minstr{k: kParam, dst: mf.vreg(p), argIdx: i})
			}
		}
		for _, v := range b.Instrs {
			switch {
			case v.Op == ir.OpAlloca:
			case v.Op == ir.OpLoad:
				emit(&minstr{k: kLdX, dst: mf.vreg(v), arr: v.Args[0], a: mf.opnd(v.Args[1])})
			case v.Op == ir.OpStore:
				emit(&minstr{k: kStX, dst: -1, arr: v.Args[0], a: mf.opnd(v.Args[1]), b: mf.opnd(v.Args[2])})
			case v.Op == ir.OpPrint:
				emit(&minstr{k: kPrint, dst: -1, a: mf.opnd(v.Args[0])})
			case v.Op == ir.OpCall:
				for i, a := range v.Args {
					emit(&minstr{k: kSetArg, dst: -1, argIdx: i, a: mf.opnd(a)})
				}
				ci, ok := fidx[v.Callee]
				if !ok {
					return nil, fmt.Errorf("@%s: call to undefined @%s", f.Name, v.Callee)
				}
				emit(&minstr{k: kCall, dst: mf.vreg(v), callee: ci, cname: v.Callee})
			default:
				mi := &minstr{k: kAlu, alu: v.Op, dst: mf.vreg(v), a: mf.opnd(v.Args[0])}
				if len(v.Args) > 1 {
					mi.b = mf.opnd(v.Args[1])
				}
				if len(v.Args) > 2 {
					mi.c = mf.opnd(v.Args[2])
				}
				emit(mi)
			}
		}
		// phi copies for the (unique, post edge-splitting) successor
		if b.Term == ir.TermBr && len(b.Succs[0].Phis) > 0 {
			s := b.Succs[0]
			k := s.PredIndex(b)
			pc := &minstr{k: kPCopy, dst: -1}
			for _, ph := range s.Phis {
				pc.dsts = append(pc.dsts, mf.vreg(ph))
				pc.srcs = append(pc.srcs, mf.opnd(ph.Args[k]))
			}
			emit(pc)
		}
		next := (*mblock)(nil)
		if bi+1 < len(order) {
			next = byIR[order[bi+1]]
		}
		switch b.Term {
		case ir.TermBr:
			if t := byIR[b.Succs[0]]; t != next {
				emit(&minstr{k: kJmp, dst: -1, target: t})
			}
		case ir.TermCondBr:
			t, e := byIR[b.Succs[0]], byIR[b.Succs[1]]
			c := mf.opnd(b.Ctrl)
			switch {
			case c.imm:
				tgt := t
				if c.v == 0 {
					tgt = e
				}
				if tgt != next {
					emit(&minstr{k: kJmp, dst: -1, target: tgt})
				}
			case e == next:
				emit(&minstr{k: kBrnz, dst: -1, a: c, target: t})
			case t == next:
				emit(&minstr{k: kBrz, dst: -1, a: c, target: e})
			default:
				emit(&minstr{k: kBrnz, dst: -1, a: c, target: t})
				emit(&minstr{k: kJmp, dst: -1, target: e})
			}
		case ir.TermRet:
			emit(&minstr{k: kRet, dst: -1, a: mf.opnd(b.Ctrl)})
		}
	}
	return mf, nil
}
