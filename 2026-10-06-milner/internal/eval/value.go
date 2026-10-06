// Package eval compiles type-checked Milner programs to a closure tree and runs them with proper
// tail calls.
package eval

import (
	"fmt"
	"strconv"
	"strings"

	"milner/internal/syntax"
)

// Value is a runtime value: int64, string, bool, Unit, *Tuple, *Con, *Closure, *PAP, *Builtin, *ConFn, *Ref.
type Value interface{}

// Unit is the value of ().
type Unit struct{}

// Tuple is a tuple value.
type Tuple struct{ Elems []Value }

// Con is a constructor value. Arg is nil for nullary constructors; for arity > 1 it is a *Tuple.
type Con struct {
	Name string
	Idx  int
	Arg  Value
}

// Closure is a user function.
type Closure struct {
	Fn  *cFun
	Env *Env
}

// PAP is a partially applied function.
type PAP struct {
	Fn   Value
	Args []Value
}

// Builtin is a primitive implemented in Go.
type Builtin struct {
	Name  string
	Arity int
	Fn    func(m *Machine, args []Value) Value
}

// ConFn is a constructor used as a first-class function.
type ConFn struct {
	Name string
	Idx  int
}

// Record is a record value; labels are sorted so field lookup is a binary search.
type Record struct {
	Labels []string
	Vals   []Value
}

func (r *Record) index(label string) int {
	lo, hi := 0, len(r.Labels)
	for lo < hi {
		mid := (lo + hi) / 2
		if r.Labels[mid] < label {
			lo = mid + 1
		} else {
			hi = mid
		}
	}
	if lo < len(r.Labels) && r.Labels[lo] == label {
		return lo
	}
	return -1
}

// Ref is a mutable cell.
type Ref struct{ V Value }

// Env is the runtime environment (a linked list; variables are addressed by de Bruijn index).
type Env struct {
	val  Value
	next *Env
}

// RuntimeError is an error raised while evaluating.
type RuntimeError struct {
	Msg  string
	Span syntax.Span
}

func (r *RuntimeError) Error() string { return r.Msg }

// Diag converts to a diagnostic.
func (r *RuntimeError) Diag() *syntax.Diag {
	return &syntax.Diag{Kind: "runtime", Span: r.Span, Msg: r.Msg}
}

// ---------- printing ----------

const maxListPrint = 100

// Show renders a value ML-style.
func Show(v Value) string {
	var b strings.Builder
	show(&b, v, 0, 0)
	return b.String()
}

const (
	maxShowDepth = 64     // nesting beyond this prints "..." (also protects against cyclic values built with refs)
	maxShowBytes = 200000 // total output cap
)

// prec: 0 = top level, 1 = constructor argument (needs parens for applications / negatives)
func show(b *strings.Builder, v Value, prec int, depth int) {
	if depth > maxShowDepth || b.Len() > maxShowBytes {
		b.WriteString("...")
		return
	}
	switch x := v.(type) {
	case int64:
		if x < 0 && prec > 0 {
			b.WriteString("(" + strconv.FormatInt(x, 10) + ")")
		} else {
			b.WriteString(strconv.FormatInt(x, 10))
		}
	case string:
		b.WriteString(strconv.Quote(x))
	case bool:
		b.WriteString(strconv.FormatBool(x))
	case Unit:
		b.WriteString("()")
	case *Tuple:
		b.WriteByte('(')
		for i, e := range x.Elems {
			if i > 0 {
				b.WriteString(", ")
			}
			show(b, e, 0, depth+1)
		}
		b.WriteByte(')')
	case *Con:
		if x.Name == "[]" || x.Name == "::" {
			b.WriteByte('[')
			n := 0
			var cur Value = x
			for {
				c := cur.(*Con)
				if c.Name == "[]" {
					break
				}
				if n > 0 {
					b.WriteString("; ")
				}
				if n >= maxListPrint {
					b.WriteString("...")
					break
				}
				pair := c.Arg.(*Tuple)
				show(b, pair.Elems[0], 0, depth+1)
				cur = pair.Elems[1]
				n++
			}
			b.WriteByte(']')
			return
		}
		if x.Arg == nil {
			b.WriteString(x.Name)
			return
		}
		if prec > 0 {
			b.WriteByte('(')
		}
		b.WriteString(x.Name + " ")
		show(b, x.Arg, 1, depth+1)
		if prec > 0 {
			b.WriteByte(')')
		}
	case *Record:
		b.WriteString("{ ")
		for i, l := range x.Labels {
			if i > 0 {
				b.WriteString("; ")
			}
			b.WriteString(l + " = ")
			show(b, x.Vals[i], 0, depth+1)
		}
		b.WriteString(" }")
	case *Ref:
		b.WriteString("{contents = ")
		show(b, x.V, 0, depth+1)
		b.WriteString("}")
	case *Closure, *PAP, *Builtin, *ConFn:
		b.WriteString("<fun>")
	default:
		fmt.Fprintf(b, "<%T>", v)
	}
}
