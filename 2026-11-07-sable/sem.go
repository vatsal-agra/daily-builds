package sable

import (
	"fmt"
	"math"
)

// Shared runtime semantics — every executor (AST, IR, machine) uses these.

const MaxDepth = 1000

// Trap kinds.
const (
	TrapDivZero  = "division by zero"
	TrapStack    = "stack overflow"
	TrapFuel     = "out of fuel"
	TrapInternal = "internal error"
)

// Outcome is the observable behaviour of a program run.
type Outcome struct {
	Output []int64
	Ret    int64
	Trap   string // "" when the program returned normally
	Steps  int64  // executor-specific work counter
}

func (o Outcome) String() string {
	s := fmt.Sprint(o.Output)
	if o.Trap != "" {
		return fmt.Sprintf("%s trap=%q", s, o.Trap)
	}
	return fmt.Sprintf("%s ret=%d", s, o.Ret)
}

// Resource reports whether the run ended for a resource reason that is not
// comparable across executors (inlining changes stack depth, fuel is per-executor).
func (o Outcome) Resource() bool { return o.Trap == TrapStack || o.Trap == TrapFuel }

// Same reports whether two outcomes are observably identical.
func (o Outcome) Same(p Outcome) bool {
	if o.Trap != p.Trap || len(o.Output) != len(p.Output) {
		return false
	}
	for i := range o.Output {
		if o.Output[i] != p.Output[i] {
			return false
		}
	}
	return o.Trap != "" || o.Ret == p.Ret
}

type trapPanic struct{ kind string }

func trap(kind string) { panic(trapPanic{kind}) }

// EvalBin is the single definition of binary operator semantics.
func EvalBin(op string, a, b int64) int64 {
	switch op {
	case "+":
		return a + b
	case "-":
		return a - b
	case "*":
		return a * b
	case "/":
		if b == 0 {
			trap(TrapDivZero)
		}
		if b == -1 {
			return -a // avoids the MinInt64 / -1 hardware fault; wraps like Go
		}
		return a / b
	case "%":
		if b == 0 {
			trap(TrapDivZero)
		}
		if b == -1 {
			return 0
		}
		return a % b
	case "&":
		return a & b
	case "|":
		return a | b
	case "^":
		return a ^ b
	case "<<":
		return a << (uint64(b) & 63)
	case ">>":
		return a >> (uint64(b) & 63)
	case "<":
		return b2i(a < b)
	case "<=":
		return b2i(a <= b)
	case ">":
		return b2i(a > b)
	case ">=":
		return b2i(a >= b)
	case "==":
		return b2i(a == b)
	case "!=":
		return b2i(a != b)
	}
	panic("EvalBin: bad op " + op)
}

// EvalUn is the single definition of unary operator semantics.
func EvalUn(op string, a int64) int64 {
	switch op {
	case "-":
		return -a
	case "!":
		return b2i(a == 0)
	case "~":
		return ^a
	}
	panic("EvalUn: bad op " + op)
}

func b2i(b bool) int64 {
	if b {
		return 1
	}
	return 0
}

var _ = math.MaxInt64
