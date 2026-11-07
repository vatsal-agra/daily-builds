package sable

import "fmt"

// Verify checks the structural and SSA invariants of f. ssa=false skips
// dominance/phi checks (pre-mem2reg IR).
func Verify(f *Func, ssa bool) error {
	bad := func(format string, a ...any) error {
		return fmt.Errorf("verify %s: %s", f.Name, fmt.Sprintf(format, a...))
	}
	inFn := map[*Block]bool{}
	for _, b := range f.Blocks {
		if inFn[b] {
			return bad("block %s listed twice", b)
		}
		inFn[b] = true
	}
	if !inFn[f.Entry] {
		return bad("entry not in function")
	}
	if len(f.Entry.Preds) != 0 {
		return bad("entry block has predecessors")
	}
	defBlock := map[*Value]*Block{}
	defIdx := map[*Value]int{}
	for _, b := range f.Blocks {
		if b.Fn != f {
			return bad("%s has wrong Fn", b)
		}
		for i, v := range b.Instrs {
			if _, dup := defBlock[v]; dup {
				return bad("%s defined twice", v)
			}
			if v.Block != b {
				return bad("%s has wrong Block pointer", v)
			}
			defBlock[v], defIdx[v] = b, i
		}
		switch b.Kind {
		case KJump:
			if len(b.Succs) != 1 {
				return bad("%s: jump needs 1 successor, has %d", b, len(b.Succs))
			}
		case KBr:
			if len(b.Succs) != 2 || b.Ctrl == nil {
				return bad("%s: malformed branch", b)
			}
		case KRet:
			if len(b.Succs) != 0 || b.Ctrl == nil {
				return bad("%s: malformed return", b)
			}
		}
		for i, s := range b.Succs {
			if !inFn[s] {
				return bad("%s branches to block outside function", b)
			}
			for _, t := range b.Succs[:i] {
				if t == s {
					return bad("%s has duplicate edge to %s", b, s)
				}
			}
		}
	}
	// pred/succ symmetry (multiset)
	for _, b := range f.Blocks {
		for _, s := range b.Succs {
			cs, cp := 0, 0
			for _, x := range b.Succs {
				if x == s {
					cs++
				}
			}
			for _, x := range s.Preds {
				if x == b {
					cp++
				}
			}
			if cs != cp {
				return bad("edge %s->%s: %d succ entries vs %d pred entries", b, s, cs, cp)
			}
		}
		for _, p := range b.Preds {
			if !inFn[p] {
				return bad("%s has pred outside function", b)
			}
			found := false
			for _, s := range p.Succs {
				if s == b {
					found = true
				}
			}
			if !found {
				return bad("%s lists pred %s which does not branch to it", b, p)
			}
		}
	}
	// operand shapes
	arity := func(v *Value) int {
		switch {
		case v.Op == OpConst || v.Op == OpParam || v.Op == OpLoad:
			return 0
		case v.Op == OpStore || v.Op == OpPrint || v.Op.IsUnary():
			return 1
		case v.Op.IsBinary():
			return 2
		}
		return -1
	}
	for _, b := range f.Blocks {
		seenNonPhi := false
		for _, v := range b.Instrs {
			if v.Op == OpPhi {
				if seenNonPhi {
					return bad("%s: phi %s after non-phi", b, v)
				}
				if len(v.Args) != len(b.Preds) {
					return bad("%s: phi %s has %d args for %d preds", b, v, len(v.Args), len(b.Preds))
				}
			} else {
				seenNonPhi = true
			}
			if ar := arity(v); ar >= 0 && len(v.Args) != ar {
				return bad("%s: %s has %d args, want %d", b, v.Format(), len(v.Args), ar)
			}
			if ssa && (v.Op == OpLoad || v.Op == OpStore) {
				return bad("%s: %s remains after mem2reg", b, v.Format())
			}
			if v.Op == OpCall && v.Callee == "" {
				return bad("call without callee")
			}
			for _, a := range v.Args {
				if a == nil {
					return bad("%s: nil operand in %s", b, v.Format())
				}
				if _, ok := defBlock[a]; !ok {
					return bad("%s: %s uses %s which is not defined in the function", b, v.Format(), a)
				}
			}
		}
		if b.Ctrl != nil {
			if _, ok := defBlock[b.Ctrl]; !ok {
				return bad("%s: terminator uses undefined %s", b, b.Ctrl)
			}
		}
	}
	if !ssa {
		return nil
	}
	// dominance: every use must be dominated by its definition
	for _, b := range f.Blocks {
		if len(b.Preds) == 0 && b != f.Entry {
			return bad("unreachable block %s", b)
		}
	}
	an := Analyze(f)
	dominatesUse := func(def *Value, useBlock *Block, useIdx int) bool {
		db := defBlock[def]
		if db == useBlock {
			return defIdx[def] < useIdx
		}
		return an.Dominates(db, useBlock)
	}
	for _, b := range f.Blocks {
		for i, v := range b.Instrs {
			for j, a := range v.Args {
				if v.Op == OpPhi {
					p := b.Preds[j]
					if !dominatesUse(a, p, len(p.Instrs)+1) {
						return bad("%s: phi operand %s (from %s) does not dominate the edge", b, a, p)
					}
				} else if !dominatesUse(a, b, i) {
					return bad("%s: %s uses %s before it is defined / not dominated", b, v.Format(), a)
				}
			}
		}
		if b.Ctrl != nil && !dominatesUse(b.Ctrl, b, len(b.Instrs)+1) {
			return bad("%s: terminator operand %s not dominated", b, b.Ctrl)
		}
	}
	return nil
}

func VerifyModule(m *Module, ssa bool) error {
	for _, f := range m.Funcs {
		if err := Verify(f, ssa); err != nil {
			return err
		}
	}
	return nil
}
