package ir

import (
	"fmt"
)

// Verify checks structural and SSA invariants, returning the first problem found.
func (m *Module) Verify() error {
	for _, f := range m.Funcs {
		if err := f.VerifyIn(m); err != nil {
			return err
		}
	}
	return nil
}

// Verify checks a function standalone (calls are not arity-checked).
func (f *Func) Verify() error { return f.VerifyIn(nil) }

func (f *Func) VerifyIn(m *Module) error {
	fail := func(format string, a ...any) error {
		return fmt.Errorf("verify @%s: %s", f.Name, fmt.Sprintf(format, a...))
	}
	if len(f.Blocks) == 0 {
		return fail("no blocks")
	}
	if len(f.Entry().Preds) != 0 {
		return fail("entry block %s has predecessors", f.Entry().Name)
	}
	inFn := map[*Block]bool{}
	names := map[string]bool{}
	for _, b := range f.Blocks {
		if inFn[b] {
			return fail("block %s listed twice", b.Name)
		}
		inFn[b] = true
		if names[b.Name] {
			return fail("duplicate block name %s", b.Name)
		}
		names[b.Name] = true
	}
	// CFG consistency
	predCount := map[[2]*Block]int{}
	for _, b := range f.Blocks {
		switch b.Term {
		case TermBr:
			if len(b.Succs) != 1 || b.Ctrl != nil {
				return fail("block %s: malformed br", b.Name)
			}
		case TermCondBr:
			if len(b.Succs) != 2 || b.Ctrl == nil {
				return fail("block %s: malformed condbr", b.Name)
			}
			if b.Succs[0] == b.Succs[1] {
				return fail("block %s: condbr with identical targets", b.Name)
			}
		case TermRet:
			if len(b.Succs) != 0 || b.Ctrl == nil {
				return fail("block %s: malformed ret", b.Name)
			}
		default:
			return fail("block %s has no terminator", b.Name)
		}
		for _, s := range b.Succs {
			if !inFn[s] {
				return fail("block %s branches to a block outside the function", b.Name)
			}
			predCount[[2]*Block{b, s}]++
		}
	}
	for _, b := range f.Blocks {
		cnt := map[*Block]int{}
		for _, p := range b.Preds {
			if !inFn[p] {
				return fail("block %s has a stale predecessor %s", b.Name, p.Name)
			}
			cnt[p]++
		}
		for p, n := range cnt {
			if predCount[[2]*Block{p, b}] != n {
				return fail("pred list of %s disagrees with successors of %s", b.Name, p.Name)
			}
		}
		for k, n := range predCount {
			if k[1] == b && cnt[k[0]] != n {
				return fail("block %s missing predecessor %s", b.Name, k[0].Name)
			}
		}
	}
	// per-value checks
	defBlock := map[*Value]*Block{}
	defIdx := map[*Value]int{}
	for _, b := range f.Blocks {
		for i, v := range b.Phis {
			if v.Op != OpPhi || v.Block != b {
				return fail("block %s: bad phi list entry", b.Name)
			}
			defBlock[v], defIdx[v] = b, -1
			_ = i
		}
		for i, v := range b.Instrs {
			if v.Op == OpPhi || v.Op == OpConst || v.Op == OpParam || v.Op == OpInvalid {
				return fail("block %s: %s in instruction list", b.Name, v.Op)
			}
			if v.Block != b {
				return fail("block %s: instruction %%%d has wrong Block pointer", b.Name, v.ID)
			}
			if _, dup := defBlock[v]; dup {
				return fail("instruction %%%d appears twice", v.ID)
			}
			defBlock[v], defIdx[v] = b, i
		}
	}
	dom := ComputeDom(f)
	isParam := map[*Value]bool{}
	for _, p := range f.Params {
		isParam[p] = true
	}
	checkUse := func(user *Value, useBlk *Block, usePos int, a *Value) error {
		if a == nil {
			return fail("nil operand in %s", describe(user, useBlk))
		}
		if a.Op == OpConst || isParam[a] {
			return nil
		}
		db, ok := defBlock[a]
		if !ok {
			return fail("operand %%%d of %s is not defined in this function", a.ID, describe(user, useBlk))
		}
		if !a.HasResult() {
			return fail("operand of %s refers to a value-less instruction", describe(user, useBlk))
		}
		if !dom.Reachable(useBlk) {
			return nil
		}
		if db == useBlk {
			if defIdx[a] >= usePos {
				return fail("use of %%%d before its definition in block %s", a.ID, useBlk.Name)
			}
			return nil
		}
		if !dom.Dominates(db, useBlk) {
			return fail("definition of %%%d in %s does not dominate its use in %s", a.ID, db.Name, useBlk.Name)
		}
		return nil
	}
	for _, b := range f.Blocks {
		for _, v := range b.Phis {
			if len(v.Args) != len(b.Preds) {
				return fail("phi in %s has %d args for %d preds", b.Name, len(v.Args), len(b.Preds))
			}
			for i, a := range v.Args {
				// a phi argument is "used" at the end of the corresponding predecessor
				if err := checkUse(v, b.Preds[i], 1<<30, a); err != nil {
					return err
				}
			}
		}
		for i, v := range b.Instrs {
			if n := v.Op.NumArgs(); n >= 0 && len(v.Args) != n {
				return fail("%s takes %d operands, has %d", v.Op, n, len(v.Args))
			}
			switch v.Op {
			case OpAlloca:
				if v.Const < 1 || b != f.Entry() {
					return fail("alloca must be in entry block with positive size")
				}
			case OpLoad, OpStore:
				if v.Args[0].Op != OpAlloca {
					return fail("%s slot operand must be an alloca", v.Op)
				}
			case OpCall:
				if m != nil {
					c := m.Func(v.Callee)
					if c == nil {
						return fail("call to undefined function @%s", v.Callee)
					}
					if len(c.Params) != len(v.Args) {
						return fail("call @%s with %d args, want %d", v.Callee, len(v.Args), len(c.Params))
					}
				}
			}
			for ai, a := range v.Args {
				if a.Op == OpAlloca && !((v.Op == OpLoad || v.Op == OpStore) && ai == 0) {
					return fail("alloca %%%d used as a value in %s (slots may only be load/store targets)", a.ID, describe(v, b))
				}
				if err := checkUse(v, b, i, a); err != nil {
					return err
				}
			}
		}
		if b.Ctrl != nil {
			if err := checkUse(nil, b, 1<<30, b.Ctrl); err != nil {
				return err
			}
		}
	}
	return nil
}

func describe(v *Value, b *Block) string {
	if v == nil {
		return "terminator of " + b.Name
	}
	return fmt.Sprintf("%s (%%%d) in %s", v.Op, v.ID, b.Name)
}
