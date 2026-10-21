package main

import (
	"math/big"
	"sort"
	"strings"
)

// Term is one of: *Atom, Int, *big.Int, Float, *Var, *Compound, LVar (clause-local, compiled clauses only).
type Term interface{}

type Atom struct {
	Name  string
	preds []*Pred // indexed by arity
}

type Int int64
type Float float64
type LVar int

type Var struct {
	ref  Term
	undo func()
	id   int64
}

type Compound struct {
	Fn     *Atom
	Args   []Term
	ground bool // set by the clause compiler: contains no LVar, can be shared
}

var atomTable = map[string]*Atom{}

func mkAtom(name string) *Atom {
	if a, ok := atomTable[name]; ok {
		return a
	}
	a := &Atom{Name: name}
	atomTable[name] = a
	return a
}

var (
	atNil     = mkAtom("[]")
	atDot     = mkAtom(".")
	atTrue    = mkAtom("true")
	atFalse   = mkAtom("false")
	atFail    = mkAtom("fail")
	atComma   = mkAtom(",")
	atSemi    = mkAtom(";")
	atArrow   = mkAtom("->")
	atSoft    = mkAtom("*->")
	atNeck    = mkAtom(":-")
	atDCG     = mkAtom("-->")
	atCut     = mkAtom("!")
	atCurly   = mkAtom("{}")
	atMinus   = mkAtom("-")
	atPlus    = mkAtom("+")
	atEq      = mkAtom("=")
	atSlash   = mkAtom("/")
	atColon   = mkAtom(":")
	atError   = mkAtom("error")
	atCaret   = mkAtom("^")
	atCall    = mkAtom("call")
	atBar     = mkAtom("|")
	atEOF     = mkAtom("end_of_file")
	atUser    = mkAtom("user")
	atNot     = mkAtom("\\+")
	atEmpty   = mkAtom("")
	atVarFn   = mkAtom("$VAR")
	atLibrary = mkAtom("library")
)

func mk(name string, args ...Term) Term {
	if len(args) == 0 {
		return mkAtom(name)
	}
	return &Compound{Fn: mkAtom(name), Args: args}
}

func cons(h, t Term) Term { return &Compound{Fn: atDot, Args: []Term{h, t}} }

func mkList(items []Term, tail Term) Term {
	l := tail
	for i := len(items) - 1; i >= 0; i-- {
		l = cons(items[i], l)
	}
	return l
}

func isCons(t Term) (*Compound, bool) {
	c, ok := t.(*Compound)
	if ok && c.Fn == atDot && len(c.Args) == 2 {
		return c, true
	}
	return nil, false
}

func deref(t Term) Term {
	for {
		v, ok := t.(*Var)
		if !ok || v.ref == nil {
			return t
		}
		t = v.ref
	}
}

// listToSlice converts a proper list; ok=false if partial or improper (tail returned).
func listToSlice(t Term) (items []Term, tail Term) {
	t = deref(t)
	for {
		c, ok := isCons(t)
		if !ok {
			return items, t
		}
		items = append(items, c.Args[0])
		t = deref(c.Args[1])
	}
}

func normBig(b *big.Int) Term {
	if b.IsInt64() {
		return Int(b.Int64())
	}
	return b
}

func isCallable(t Term) bool {
	switch t.(type) {
	case *Atom, *Compound:
		return true
	}
	return false
}

func isAtomic(t Term) bool {
	switch t.(type) {
	case *Atom, Int, *big.Int, Float:
		return true
	}
	return false
}

func isNumber(t Term) bool {
	switch t.(type) {
	case Int, *big.Int, Float:
		return true
	}
	return false
}

// ---------- standard order ----------

func typeRank(t Term) int {
	switch t.(type) {
	case *Var:
		return 0
	case Float, Int, *big.Int:
		return 1
	case *Atom:
		return 3
	}
	return 4
}

func cmpNum(a, b Term) int {
	switch x := a.(type) {
	case Int:
		switch y := b.(type) {
		case Int:
			if x < y {
				return -1
			} else if x > y {
				return 1
			}
			return 0
		case *big.Int:
			return -y.Sign()
		case Float:
			return cmpFloat(float64(x), float64(y))
		}
	case *big.Int:
		switch y := b.(type) {
		case Int:
			return x.Sign()
		case *big.Int:
			return x.Cmp(y)
		case Float:
			f, _ := new(big.Float).SetInt(x).Float64()
			return cmpFloat(f, float64(y))
		}
	case Float:
		switch y := b.(type) {
		case Int:
			return cmpFloat(float64(x), float64(y))
		case *big.Int:
			f, _ := new(big.Float).SetInt(y).Float64()
			return cmpFloat(float64(x), f)
		case Float:
			return cmpFloat(float64(x), float64(y))
		}
	}
	return 0
}

func cmpFloat(a, b float64) int {
	if a < b {
		return -1
	} else if a > b {
		return 1
	}
	return 0
}

func compareTerms(a, b Term) int {
	for {
		a, b = deref(a), deref(b)
		if a == b {
			return 0
		}
		ra, rb := typeRank(a), typeRank(b)
		if ra != rb {
			if ra < rb {
				return -1
			}
			return 1
		}
		switch x := a.(type) {
		case *Var:
			y := b.(*Var)
			if x.id < y.id {
				return -1
			} else if x.id > y.id {
				return 1
			}
			return 0
		case *Atom:
			return strings.Compare(x.Name, b.(*Atom).Name)
		case *Compound:
			y := b.(*Compound)
			if len(x.Args) != len(y.Args) {
				if len(x.Args) < len(y.Args) {
					return -1
				}
				return 1
			}
			if x.Fn != y.Fn {
				return strings.Compare(x.Fn.Name, y.Fn.Name)
			}
			n := len(x.Args)
			for i := 0; i < n-1; i++ {
				if c := compareTerms(x.Args[i], y.Args[i]); c != 0 {
					return c
				}
			}
			a, b = x.Args[n-1], y.Args[n-1]
			continue
		default:
			c := cmpNum(a, b)
			if c != 0 {
				return c
			}
			_, fa := a.(Float)
			_, fb := b.(Float)
			if fa && !fb {
				return -1
			}
			if fb && !fa {
				return 1
			}
			return 0
		}
	}
}

func sortTerms(ts []Term, dedup bool) []Term {
	sort.SliceStable(ts, func(i, j int) bool { return compareTerms(ts[i], ts[j]) < 0 })
	if !dedup {
		return ts
	}
	out := ts[:0]
	for i, t := range ts {
		if i == 0 || compareTerms(out[len(out)-1], t) != 0 {
			out = append(out, t)
		}
	}
	return out
}

// ---------- term utilities ----------

func termVars(t Term, seen map[*Var]bool, out *[]*Var) {
	for {
		t = deref(t)
		switch x := t.(type) {
		case *Var:
			if !seen[x] {
				seen[x] = true
				*out = append(*out, x)
			}
			return
		case *Compound:
			n := len(x.Args)
			for i := 0; i < n-1; i++ {
				termVars(x.Args[i], seen, out)
			}
			t = x.Args[n-1]
			continue
		}
		return
	}
}

func isGround(t Term) bool {
	for {
		t = deref(t)
		switch x := t.(type) {
		case *Var:
			return false
		case *Compound:
			if x.ground {
				return true
			}
			n := len(x.Args)
			for i := 0; i < n-1; i++ {
				if !isGround(x.Args[i]) {
					return false
				}
			}
			t = x.Args[n-1]
			continue
		}
		return true
	}
}

// resolve fully dereferences a term, copying structure only where needed.
func (m *Machine) copyTerm(t Term, mp map[*Var]Term) Term {
	t = deref(t)
	switch x := t.(type) {
	case *Var:
		if n, ok := mp[x]; ok {
			return n
		}
		n := m.newVar()
		mp[x] = n
		return n
	case *Compound:
		if x.ground {
			return x
		}
		// iterate along last argument to keep Go stack shallow on long lists
		root := newComp(x.Fn, len(x.Args))
		cur, src := root, x
		for {
			n := len(src.Args)
			for i := 0; i < n-1; i++ {
				cur.Args[i] = m.copyTerm(src.Args[i], mp)
			}
			last := deref(src.Args[n-1])
			if lc, ok := last.(*Compound); ok && !lc.ground {
				nc := newComp(lc.Fn, len(lc.Args))
				cur.Args[n-1] = nc
				cur, src = nc, lc
				continue
			}
			cur.Args[n-1] = m.copyTerm(last, mp)
			break
		}
		return root
	}
	return t
}

func pi(name *Atom, arity int) Term {
	return &Compound{Fn: atSlash, Args: []Term{name, Int(arity)}}
}

func sortStable(ts []Term, less func(a, b Term) bool) {
	sort.SliceStable(ts, func(i, j int) bool { return less(ts[i], ts[j]) })
}

type bigIntT = big.Int

type comp1 struct {
	c Compound
	a [1]Term
}
type comp2 struct {
	c Compound
	a [2]Term
}
type comp3 struct {
	c Compound
	a [3]Term
}
type comp4 struct {
	c Compound
	a [4]Term
}

// newComp allocates a compound and its argument array in a single allocation for small arities.
func newComp(fn *Atom, n int) *Compound {
	switch n {
	case 1:
		x := &comp1{}
		x.c.Fn, x.c.Args = fn, x.a[:]
		return &x.c
	case 2:
		x := &comp2{}
		x.c.Fn, x.c.Args = fn, x.a[:]
		return &x.c
	case 3:
		x := &comp3{}
		x.c.Fn, x.c.Args = fn, x.a[:]
		return &x.c
	case 4:
		x := &comp4{}
		x.c.Fn, x.c.Args = fn, x.a[:]
		return &x.c
	}
	return &Compound{Fn: fn, Args: make([]Term, n)}
}
