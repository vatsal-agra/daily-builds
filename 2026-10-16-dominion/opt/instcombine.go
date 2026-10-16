package opt

import (
	"math/bits"

	"dominion/ir"
)

func isPow2(c int64) bool { return c > 0 && c&(c-1) == 0 }

func invertCmp(op ir.Op) ir.Op {
	switch op {
	case ir.OpEq:
		return ir.OpNe
	case ir.OpNe:
		return ir.OpEq
	case ir.OpLt:
		return ir.OpGe
	case ir.OpLe:
		return ir.OpGt
	case ir.OpGt:
		return ir.OpLe
	case ir.OpGe:
		return ir.OpLt
	}
	return ir.OpInvalid
}

// isBool: result is known to be 0 or 1.
func isBool(v *ir.Value) bool {
	if v.IsConst() {
		return v.Const == 0 || v.Const == 1
	}
	if v.Op.IsCompare() {
		return true
	}
	if v.Op == ir.OpAnd || v.Op == ir.OpOr || v.Op == ir.OpXor {
		return isBool(v.Args[0]) && isBool(v.Args[1])
	}
	if v.Op == ir.OpSelect {
		return isBool(v.Args[1]) && isBool(v.Args[2])
	}
	return false
}

// simplify returns an existing value equal to v, or nil. It may rewrite v in place
// (canonicalisation, strength reduction) and reports that through changed.
func simplify(f *ir.Func, b *ir.Block, idx int, v *ir.Value, changed *bool) *ir.Value {
	c := f.Const
	switch {
	case v.Op.IsBinary():
		x, y := v.Args[0], v.Args[1]
		// canonicalise: constant on the right of commutative ops; swap compares accordingly
		if x.IsConst() && !y.IsConst() {
			switch {
			case v.Op.IsCommutative():
				v.Args[0], v.Args[1] = y, x
				x, y = y, x
				*changed = true
			case v.Op.IsCompare():
				v.Op = swapCmp(v.Op)
				v.Args[0], v.Args[1] = y, x
				x, y = y, x
				*changed = true
			}
		}
		if x.IsConst() && y.IsConst() {
			if r, ok := ir.Eval(v.Op, x.Const, y.Const, 0); ok {
				return c(r)
			}
			return nil
		}
		same := x == y
		yc := y.IsConst()
		switch v.Op {
		case ir.OpAdd:
			if yc && y.Const == 0 {
				return x
			}
			if yc && x.Op == ir.OpAdd && x.Args[1].IsConst() { // (a + c1) + c2
				v.Args[0], v.Args[1] = x.Args[0], c(x.Args[1].Const+y.Const)
				*changed = true
			}
		case ir.OpSub:
			if same {
				return c(0)
			}
			if yc && y.Const == 0 {
				return x
			}
			if yc && y.Const != -1<<63 { // x - c  ->  x + (-c) enables reassociation
				v.Op, v.Args[1] = ir.OpAdd, c(-y.Const)
				*changed = true
			}
		case ir.OpMul:
			if yc && y.Const == 0 {
				return c(0)
			}
			if yc && y.Const == 1 {
				return x
			}
			if yc && y.Const == -1 {
				v.Op, v.Args = ir.OpNeg, []*ir.Value{x}
				*changed = true
			} else if yc && isPow2(y.Const) {
				v.Op, v.Args[1] = ir.OpShl, c(int64(bits.TrailingZeros64(uint64(y.Const))))
				*changed = true
			} else if yc && x.Op == ir.OpMul && x.Args[1].IsConst() {
				v.Args[0], v.Args[1] = x.Args[0], c(x.Args[1].Const*y.Const)
				*changed = true
			}
		case ir.OpDiv:
			if yc && y.Const == 1 {
				return x
			}
		case ir.OpRem:
			if yc && (y.Const == 1 || y.Const == -1) {
				return c(0)
			}
		case ir.OpAnd:
			if same {
				return x
			}
			if yc && y.Const == 0 {
				return c(0)
			}
			if yc && y.Const == -1 {
				return x
			}
		case ir.OpOr:
			if same {
				return x
			}
			if yc && y.Const == 0 {
				return x
			}
			if yc && y.Const == -1 {
				return c(-1)
			}
		case ir.OpXor:
			if same {
				return c(0)
			}
			if yc && y.Const == 0 {
				return x
			}
		case ir.OpShl, ir.OpShr:
			if yc && y.Const&63 == 0 {
				return x
			}
		case ir.OpEq:
			if same {
				return c(1)
			}
			if yc && y.Const == 0 && x.Op.IsCompare() { // !(cmp)
				v.Op, v.Args = invertCmp(x.Op), []*ir.Value{x.Args[0], x.Args[1]}
				*changed = true
			} else if yc && y.Const == 1 && isBool(x) {
				return x
			}
		case ir.OpNe:
			if same {
				return c(0)
			}
			if yc && y.Const == 0 && isBool(x) {
				return x
			}
		case ir.OpLt, ir.OpGt:
			if same {
				return c(0)
			}
		case ir.OpLe, ir.OpGe:
			if same {
				return c(1)
			}
		}
	case v.Op == ir.OpNeg:
		x := v.Args[0]
		if x.IsConst() {
			return c(-x.Const)
		}
		if x.Op == ir.OpNeg {
			return x.Args[0]
		}
	case v.Op == ir.OpNot:
		x := v.Args[0]
		if x.IsConst() {
			return c(^x.Const)
		}
		if x.Op == ir.OpNot {
			return x.Args[0]
		}
	case v.Op == ir.OpSelect:
		cnd, x, y := v.Args[0], v.Args[1], v.Args[2]
		if cnd.IsConst() {
			if cnd.Const != 0 {
				return x
			}
			return y
		}
		if x == y {
			return x
		}
		if x.IsConst() && y.IsConst() && x.Const == 1 && y.Const == 0 && isBool(cnd) {
			return cnd
		}
	}
	return nil
}

func swapCmp(op ir.Op) ir.Op {
	switch op {
	case ir.OpLt:
		return ir.OpGt
	case ir.OpLe:
		return ir.OpGe
	case ir.OpGt:
		return ir.OpLt
	case ir.OpGe:
		return ir.OpLe
	}
	return op
}

// InstCombine performs algebraic simplification, constant folding and strength reduction.
func InstCombine(f *ir.Func) int {
	total := 0
	for round := 0; round < 8; round++ {
		n := 0
		for _, b := range f.Blocks {
			for i := 0; i < len(b.Instrs); i++ {
				v := b.Instrs[i]
				ch := false
				if r := simplify(f, b, i, v, &ch); r != nil && r != v {
					f.ReplaceAllUses(v, r)
					b.Instrs = append(b.Instrs[:i], b.Instrs[i+1:]...)
					i--
					n++
				} else if ch {
					n++
				}
			}
		}
		n += replaceTrivialPhis(f)
		total += n
		if n == 0 {
			break
		}
	}
	return total
}
