package eval

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"unicode/utf8"
)

func b2(name string, f func(m *Machine, a, b int64) Value) *Builtin {
	return &Builtin{Name: name, Arity: 2, Fn: func(m *Machine, a []Value) Value { return f(m, a[0].(int64), a[1].(int64)) }}
}

func cmpBuiltin(name string, test func(c int) bool) *Builtin {
	return &Builtin{Name: name, Arity: 2, Fn: func(m *Machine, a []Value) Value {
		return test(m.compare(a[0], a[1]))
	}}
}

func list(vs []Value) Value {
	var res Value = &Con{Name: "[]", Idx: 0}
	for i := len(vs) - 1; i >= 0; i-- {
		res = &Con{Name: "::", Idx: 1, Arg: &Tuple{Elems: []Value{vs[i], res}}}
	}
	return res
}

func unlist(v Value) []Value {
	var out []Value
	for {
		c := v.(*Con)
		if c.Name == "[]" {
			return out
		}
		p := c.Arg.(*Tuple)
		out = append(out, p.Elems[0])
		v = p.Elems[1]
	}
}

// compare is the polymorphic structural comparison behind `=`, `<`, `compare`, ...
// It iterates along list spines and last components, and gives up (with an error) on structures that
// are nested too deeply or cyclic instead of overflowing the Go stack or looping forever.
func (m *Machine) compare(a, b Value) int {
	m.cmpOps = 0
	return m.cmp(a, b, 0)
}

const (
	maxCmpDepth = 100000
	maxCmpOps   = 200_000_000
)

func sign(c int) int {
	switch {
	case c < 0:
		return -1
	case c > 0:
		return 1
	}
	return 0
}

func (m *Machine) cmp(a, b Value, depth int) int {
	if depth > maxCmpDepth {
		m.fail("compare: structure is nested too deeply (or cyclic)")
	}
	for {
		m.cmpOps++
		if m.cmpOps > maxCmpOps {
			m.fail("compare: gave up after too many steps (is a value cyclic?)")
		}
		switch x := a.(type) {
		case int64:
			y := b.(int64)
			switch {
			case x < y:
				return -1
			case x > y:
				return 1
			}
			return 0
		case string:
			return sign(strings.Compare(x, b.(string)))
		case bool:
			y := b.(bool)
			switch {
			case x == y:
				return 0
			case !x:
				return -1
			}
			return 1
		case Unit:
			return 0
		case *Tuple:
			y := b.(*Tuple)
			n := len(x.Elems)
			for i := 0; i < n-1; i++ {
				if c := m.cmp(x.Elems[i], y.Elems[i], depth+1); c != 0 {
					return c
				}
			}
			a, b = x.Elems[n-1], y.Elems[n-1]
		case *Con:
			y := b.(*Con)
			if x.Idx != y.Idx {
				if x.Idx < y.Idx {
					return -1
				}
				return 1
			}
			if x.Arg == nil {
				return 0
			}
			a, b = x.Arg, y.Arg
		case *Record:
			y := b.(*Record)
			n := len(x.Vals)
			for i := 0; i < n-1; i++ {
				if c := m.cmp(x.Vals[i], y.Vals[i], depth+1); c != 0 {
					return c
				}
			}
			a, b = x.Vals[n-1], y.Vals[n-1]
		case *Ref:
			a, b = x.V, b.(*Ref).V
		default:
			m.fail("compare: cannot compare functional values")
		}
	}
}

func intOfString(s string) (int64, bool) {
	if s == "" {
		return 0, false
	}
	n, err := strconv.ParseInt(s, 10, 64)
	return n, err == nil
}

func someV(v Value) Value { return &Con{Name: "Some", Idx: 1, Arg: v} }

// Builtins returns the primitive values keyed by name; the set must match types.BuiltinSigs.
func Builtins() map[string]*Builtin {
	bs := map[string]*Builtin{}
	add := func(b *Builtin) { bs[b.Name] = b }
	add(b2("+", func(m *Machine, a, b int64) Value { return a + b }))
	add(b2("-", func(m *Machine, a, b int64) Value { return a - b }))
	add(b2("*", func(m *Machine, a, b int64) Value { return a * b }))
	add(b2("/", func(m *Machine, a, b int64) Value {
		if b == 0 {
			m.fail("Division_by_zero: %d / 0", a)
		}
		if a == math.MinInt64 && b == -1 {
			return a
		}
		return a / b
	}))
	add(b2("mod", func(m *Machine, a, b int64) Value {
		if b == 0 {
			m.fail("Division_by_zero: %d mod 0", a)
		}
		if b == -1 {
			return int64(0)
		}
		return a % b
	}))
	add(&Builtin{Name: "~-", Arity: 1, Fn: func(m *Machine, a []Value) Value { return -a[0].(int64) }})
	add(&Builtin{Name: "^", Arity: 2, Fn: func(m *Machine, a []Value) Value { return a[0].(string) + a[1].(string) }})
	add(&Builtin{Name: "@", Arity: 2, Fn: func(m *Machine, a []Value) Value {
		xs := unlist(a[0])
		res := a[1]
		for i := len(xs) - 1; i >= 0; i-- {
			res = &Con{Name: "::", Idx: 1, Arg: &Tuple{Elems: []Value{xs[i], res}}}
		}
		return res
	}})
	add(cmpBuiltin("=", func(c int) bool { return c == 0 }))
	add(cmpBuiltin("<>", func(c int) bool { return c != 0 }))
	add(cmpBuiltin("<", func(c int) bool { return c < 0 }))
	add(cmpBuiltin(">", func(c int) bool { return c > 0 }))
	add(cmpBuiltin("<=", func(c int) bool { return c <= 0 }))
	add(cmpBuiltin(">=", func(c int) bool { return c >= 0 }))
	add(&Builtin{Name: "compare", Arity: 2, Fn: func(m *Machine, a []Value) Value { return int64(m.compare(a[0], a[1])) }})
	add(&Builtin{Name: "ref", Arity: 1, Fn: func(m *Machine, a []Value) Value { return &Ref{V: a[0]} }})
	add(&Builtin{Name: "!", Arity: 1, Fn: func(m *Machine, a []Value) Value { return a[0].(*Ref).V }})
	add(&Builtin{Name: ":=", Arity: 2, Fn: func(m *Machine, a []Value) Value { a[0].(*Ref).V = a[1]; return Unit{} }})
	add(&Builtin{Name: "print_string", Arity: 1, Fn: func(m *Machine, a []Value) Value {
		fmt.Fprint(m.Out, a[0].(string))
		return Unit{}
	}})
	add(&Builtin{Name: "print_endline", Arity: 1, Fn: func(m *Machine, a []Value) Value {
		fmt.Fprintln(m.Out, a[0].(string))
		return Unit{}
	}})
	add(&Builtin{Name: "print_int", Arity: 1, Fn: func(m *Machine, a []Value) Value {
		fmt.Fprint(m.Out, a[0].(int64))
		return Unit{}
	}})
	add(&Builtin{Name: "string_of_int", Arity: 1, Fn: func(m *Machine, a []Value) Value { return strconv.FormatInt(a[0].(int64), 10) }})
	add(&Builtin{Name: "int_of_string_opt", Arity: 1, Fn: func(m *Machine, a []Value) Value {
		if n, ok := intOfString(a[0].(string)); ok {
			return someV(n)
		}
		return &Con{Name: "None", Idx: 0}
	}})
	add(&Builtin{Name: "string_length", Arity: 1, Fn: func(m *Machine, a []Value) Value {
		return int64(utf8.RuneCountInString(a[0].(string)))
	}})
	add(&Builtin{Name: "string_sub", Arity: 3, Fn: func(m *Machine, a []Value) Value {
		rs := []rune(a[0].(string))
		start, n := a[1].(int64), a[2].(int64)
		if start < 0 || n < 0 || start+n > int64(len(rs)) {
			m.fail("Invalid_argument: string_sub %q %d %d (string has length %d)", a[0].(string), start, n, len(rs))
		}
		return string(rs[start : start+n])
	}})
	add(&Builtin{Name: "string_explode", Arity: 1, Fn: func(m *Machine, a []Value) Value {
		var vs []Value
		for _, r := range a[0].(string) {
			vs = append(vs, string(r))
		}
		return list(vs)
	}})
	add(&Builtin{Name: "char_code", Arity: 1, Fn: func(m *Machine, a []Value) Value {
		r, n := utf8.DecodeRuneInString(a[0].(string))
		if n == 0 {
			m.fail("Invalid_argument: char_code of the empty string")
		}
		return int64(r)
	}})
	add(&Builtin{Name: "char_of_code", Arity: 1, Fn: func(m *Machine, a []Value) Value {
		c := a[0].(int64)
		if c < 0 || c > utf8.MaxRune || (c >= 0xD800 && c <= 0xDFFF) {
			m.fail("Invalid_argument: char_of_code %d is not a valid code point", c)
		}
		return string(rune(c))
	}})
	add(&Builtin{Name: "failwith", Arity: 1, Fn: func(m *Machine, a []Value) Value {
		m.fail("Failure: %s", a[0].(string))
		return nil
	}})
	return bs
}
