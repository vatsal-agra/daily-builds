package ir

import (
	"fmt"
	"strconv"
	"strings"
)

// Result of running a program in the reference interpreter.
type Result struct {
	Ret   int64
	Out   string
	Trap  string // "" if the run completed
	Steps int64
}

func (r Result) String() string {
	if r.Trap != "" {
		return fmt.Sprintf("out=%q trap=%s", r.Out, r.Trap)
	}
	return fmt.Sprintf("out=%q ret=%d", r.Out, r.Ret)
}

// Same reports behavioural equality (ignoring step counts).
func (r Result) Same(o Result) bool {
	return r.Trap == o.Trap && r.Out == o.Out && (r.Trap != "" || r.Ret == o.Ret)
}

// Trap kinds (shared with the VM so results compare directly).
const (
	TrapDivZero = "division by zero"
	TrapOOB     = "out-of-bounds access"
	TrapFuel    = "fuel exhausted"
	TrapStack   = "stack overflow"
	TrapOutput  = "output limit exceeded"

	// MaxOutput bounds the bytes a program may print.
	MaxOutput = 1 << 20
)

type trapErr struct{ msg string }

type interp struct {
	m     *Module
	out   strings.Builder
	fuel  int64
	steps int64
	depth int
}

const MaxCallDepth = 400

// Run executes @main (no arguments) with the given instruction budget.
func (m *Module) Run(fuel int64) (res Result) {
	main := m.Func("main")
	if main == nil || len(main.Params) != 0 {
		return Result{Trap: "no parameterless function @main"}
	}
	return m.RunFunc(main, nil, fuel)
}

// RunFunc executes an arbitrary function.
func (m *Module) RunFunc(f *Func, args []int64, fuel int64) (res Result) {
	in := &interp{m: m, fuel: fuel}
	defer func() {
		if r := recover(); r != nil {
			t, ok := r.(trapErr)
			if !ok {
				panic(r)
			}
			res = Result{Out: in.out.String(), Trap: t.msg, Steps: in.steps}
		}
	}()
	ret := in.call(f, args)
	return Result{Ret: ret, Out: in.out.String(), Steps: in.steps}
}

func (in *interp) tick() {
	in.steps++
	if in.steps > in.fuel {
		panic(trapErr{TrapFuel})
	}
}

func (in *interp) call(f *Func, args []int64) int64 {
	in.depth++
	if in.depth > MaxCallDepth {
		panic(trapErr{TrapStack})
	}
	defer func() { in.depth-- }()
	vals := make([]int64, f.NumIDs())
	mem := map[int][]int64{}
	for i, p := range f.Params {
		vals[p.ID] = args[i]
	}
	get := func(v *Value) int64 {
		if v.Op == OpConst {
			return v.Const
		}
		return vals[v.ID]
	}
	b := f.Entry()
	var prev *Block
	for {
		if prev != nil && len(b.Phis) > 0 {
			k := b.PredIndex(prev)
			tmp := make([]int64, len(b.Phis))
			for i, ph := range b.Phis {
				tmp[i] = get(ph.Args[k])
			}
			for i, ph := range b.Phis {
				vals[ph.ID] = tmp[i]
			}
			in.steps += int64(len(b.Phis))
		}
		for _, v := range b.Instrs {
			in.tick()
			switch v.Op {
			case OpAlloca:
				mem[v.ID] = make([]int64, v.Const)
			case OpLoad:
				s := mem[v.Args[0].ID]
				i := get(v.Args[1])
				if i < 0 || i >= int64(len(s)) {
					panic(trapErr{TrapOOB})
				}
				vals[v.ID] = s[i]
			case OpStore:
				s := mem[v.Args[0].ID]
				i := get(v.Args[1])
				if i < 0 || i >= int64(len(s)) {
					panic(trapErr{TrapOOB})
				}
				s[i] = get(v.Args[2])
			case OpCall:
				c := in.m.Func(v.Callee)
				as := make([]int64, len(v.Args))
				for i, a := range v.Args {
					as[i] = get(a)
				}
				vals[v.ID] = in.call(c, as)
			case OpPrint:
				if in.out.Len() > MaxOutput {
					panic(trapErr{TrapOutput})
				}
				in.out.WriteString(strconv.FormatInt(get(v.Args[0]), 10))
				in.out.WriteByte('\n')
			default:
				x := int64(0)
				if len(v.Args) > 0 {
					x = get(v.Args[0])
				}
				y := int64(0)
				if len(v.Args) > 1 {
					y = get(v.Args[1])
				}
				z := int64(0)
				if len(v.Args) > 2 {
					z = get(v.Args[2])
				}
				r, ok := Eval(v.Op, x, y, z)
				if !ok {
					panic(trapErr{TrapDivZero})
				}
				vals[v.ID] = r
			}
		}
		in.tick()
		switch b.Term {
		case TermBr:
			prev, b = b, b.Succs[0]
		case TermCondBr:
			prev = b
			if get(b.Ctrl) != 0 {
				b = b.Succs[0]
			} else {
				b = b.Succs[1]
			}
		case TermRet:
			return get(b.Ctrl)
		default:
			panic("ir: block without terminator")
		}
	}
}

// Eval computes a pure operation; ok=false means the operation traps (division by zero).
func Eval(op Op, x, y, z int64) (int64, bool) {
	b2i := func(c bool) int64 {
		if c {
			return 1
		}
		return 0
	}
	switch op {
	case OpAdd:
		return x + y, true
	case OpSub:
		return x - y, true
	case OpMul:
		return x * y, true
	case OpDiv:
		if y == 0 {
			return 0, false
		}
		return x / y, true
	case OpRem:
		if y == 0 {
			return 0, false
		}
		return x % y, true
	case OpAnd:
		return x & y, true
	case OpOr:
		return x | y, true
	case OpXor:
		return x ^ y, true
	case OpShl:
		return x << (uint64(y) & 63), true
	case OpShr:
		return x >> (uint64(y) & 63), true
	case OpEq:
		return b2i(x == y), true
	case OpNe:
		return b2i(x != y), true
	case OpLt:
		return b2i(x < y), true
	case OpLe:
		return b2i(x <= y), true
	case OpGt:
		return b2i(x > y), true
	case OpGe:
		return b2i(x >= y), true
	case OpNeg:
		return -x, true
	case OpNot:
		return ^x, true
	case OpSelect:
		if x != 0 {
			return y, true
		}
		return z, true
	}
	panic("ir.Eval: not a pure op: " + op.String())
}
