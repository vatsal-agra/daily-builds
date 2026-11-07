package sable

import "math/bits"

// isBool reports whether v is known to be 0 or 1.
func isBool(v *Value, depth int) bool {
	switch {
	case v.Op == OpConst:
		return v.Imm == 0 || v.Imm == 1
	case v.Op.IsCompare() || v.Op == OpNot:
		return true
	case (v.Op == OpAnd || v.Op == OpOr || v.Op == OpXor) && depth < 4:
		return isBool(v.Args[0], depth+1) && isBool(v.Args[1], depth+1)
	case v.Op == OpPhi && depth < 3:
		for _, a := range v.Args {
			if a != v && !isBool(a, depth+1) {
				return false
			}
		}
		return true
	}
	return false
}

var invertCmp = map[Op]Op{OpLt: OpGe, OpGe: OpLt, OpLe: OpGt, OpGt: OpLe, OpEq: OpNe, OpNe: OpEq}
var swapCmp = map[Op]Op{OpLt: OpGt, OpGt: OpLt, OpLe: OpGe, OpGe: OpLe, OpEq: OpEq, OpNe: OpNe}

// InstCombine does local algebraic simplification and strength reduction.
func InstCombine(f *Func) bool {
	changed := false
	for round := 0; round < 8; round++ {
		repl := map[*Value]*Value{}
		any := false
		for _, b := range f.Blocks {
			for i := 0; i < len(b.Instrs); i++ {
				v := b.Instrs[i]
				if v.Op == OpPhi || v.Op == OpConst {
					continue
				}
				// resolve operands replaced earlier in this round
				for j, a := range v.Args {
					for {
						w, ok := repl[a]
						if !ok {
							break
						}
						a = w
					}
					v.Args[j] = a
				}
				r, ins := combine(f, b, i, v)
				i += ins
				if r != nil && r != v {
					repl[v] = r
					any = true
				} else if r == v {
					any = true // mutated in place
				}
			}
			if b.Ctrl != nil {
				for {
					w, ok := repl[b.Ctrl]
					if !ok {
						break
					}
					b.Ctrl = w
				}
			}
		}
		if len(repl) > 0 {
			f.replaceAllUses(repl)
		}
		if !any {
			break
		}
		changed = true
	}
	return changed
}

func constBefore(f *Func, b *Block, i int, c int64) (*Value, int) {
	k := f.newValue(OpConst)
	k.Imm = c
	b.insertAt(i, k)
	return k, 1
}

// combine returns a replacement for v (nil = none, v itself = mutated in place)
// and how many instructions it inserted before position i.
func combine(f *Func, b *Block, i int, v *Value) (*Value, int) {
	isC := func(x *Value) bool { return x.Op == OpConst }
	switch {
	case v.Op.IsUnary():
		x := v.Args[0]
		switch v.Op {
		case OpNeg:
			if x.Op == OpNeg {
				return x.Args[0], 0
			}
		case OpBNot:
			if x.Op == OpBNot {
				return x.Args[0], 0
			}
		case OpNot:
			if x.Op == OpNot && isBool(x.Args[0], 0) {
				return x.Args[0], 0
			}
			if inv, ok := invertCmp[x.Op]; ok {
				v.Op, v.Args = inv, []*Value{x.Args[0], x.Args[1]}
				return v, 0
			}
		}
		return nil, 0
	case !v.Op.IsBinary():
		return nil, 0
	}
	a, c := v.Args[0], v.Args[1]
	// canonical form: constant on the right
	if isC(a) && !isC(c) {
		if v.Op.Commutative() {
			v.Args[0], v.Args[1] = c, a
			a, c = c, a
		} else if sw, ok := swapCmp[v.Op]; ok {
			v.Op = sw
			v.Args[0], v.Args[1] = c, a
			a, c = c, a
		}
	}
	zero := func() (*Value, int) { return constBefore(f, b, i, 0) }
	one := func() (*Value, int) { return constBefore(f, b, i, 1) }
	if isC(a) && isC(c) {
		if (v.Op == OpDiv || v.Op == OpMod) && c.Imm == 0 {
			return nil, 0
		}
		k, n := constBefore(f, b, i, EvalBin(opSym[v.Op], a.Imm, c.Imm))
		return k, n
	}
	if a == c { // same operand twice
		switch v.Op {
		case OpSub, OpXor:
			return zero()
		case OpAnd, OpOr:
			return a, 0
		case OpEq, OpLe, OpGe:
			return one()
		case OpNe, OpLt, OpGt:
			return zero()
		}
	}
	if isC(c) {
		k := c.Imm
		switch v.Op {
		case OpAdd, OpSub, OpOr, OpXor:
			if k == 0 {
				return a, 0
			}
		case OpMul:
			switch {
			case k == 0:
				return c, 0
			case k == 1:
				return a, 0
			case k == -1:
				v.Op, v.Args = OpNeg, []*Value{a}
				return v, 0
			case k > 0 && k&(k-1) == 0:
				sh, n := constBefore(f, b, i, int64(bits.TrailingZeros64(uint64(k))))
				v.Op, v.Args = OpShl, []*Value{a, sh}
				return v, n
			}
		case OpAnd:
			if k == 0 {
				return c, 0
			}
			if k == -1 {
				return a, 0
			}
		case OpShl, OpShr:
			if k&63 == 0 {
				return a, 0
			}
		case OpDiv:
			if k == 1 {
				return a, 0
			}
			if k == -1 {
				v.Op, v.Args = OpNeg, []*Value{a}
				return v, 0
			}
		case OpMod:
			if k == 1 || k == -1 {
				return zero()
			}
		case OpNe:
			if k == 0 && isBool(a, 0) {
				return a, 0
			}
		case OpEq:
			if k == 0 && isBool(a, 0) {
				v.Op, v.Args = OpNot, []*Value{a}
				return v, 0
			}
			if k == 1 && isBool(a, 0) {
				return a, 0
			}
		}
		if k == -1 && v.Op == OpOr {
			return c, 0
		}
		// sub x,c  ==>  add x,-c  (canonical, enables constant reassociation)
		if v.Op == OpSub && k != -1<<63 {
			nk, n := constBefore(f, b, i, -k)
			v.Op, v.Args = OpAdd, []*Value{a, nk}
			return v, n
		}
		// (x op c1) op c2 ==> x op (c1 op c2) for add/mul/and/or/xor
		if (v.Op == OpAdd || v.Op == OpMul || v.Op == OpAnd || v.Op == OpOr || v.Op == OpXor) && a.Op == v.Op && isC(a.Args[1]) {
			nk, n := constBefore(f, b, i, EvalBin(opSym[v.Op], a.Args[1].Imm, k))
			v.Args = []*Value{a.Args[0], nk}
			return v, n
		}
	}
	return nil, 0
}
