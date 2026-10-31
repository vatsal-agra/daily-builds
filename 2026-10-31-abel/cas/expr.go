// Package cas is a small exact computer algebra system.
//
// Expressions are immutable trees kept in a canonical form by the smart
// constructors (Add, Mul, Pow, Fn): two mathematically-equal expressions that
// differ only by ordering, nesting, like terms or rational/surd arithmetic
// normalise to the same tree, so equality is a string comparison of Key().
package cas

import (
	"fmt"
	"math/big"
	"sort"
	"strings"
)

// Kind tags the node type of an Expr.
type Kind int

const (
	KNum Kind = iota // exact rational
	KSym             // symbol or constant (pi, e, i)
	KAdd
	KMul
	KPow
	KFn
	KMat
)

// Expr is an immutable expression node.
type Expr struct {
	K    Kind
	N    *big.Rat // KNum
	S    string   // KSym / KFn name
	A    []*Expr  // children (Add terms, Mul factors, Pow [base,exp], Fn args, Mat entries row-major)
	R, C int      // matrix dimensions
	key  string
}

// E is the usual handle type.
type E = *Expr

// MathError is raised (via panic) for mathematical failures such as division
// by zero; Guard converts it back into an error at API boundaries.
type MathError string

func (m MathError) Error() string { return string(m) }

func fail(format string, a ...any) { panic(MathError(fmt.Sprintf(format, a...))) }

// Guard runs f and returns any MathError it raised.
func Guard(f func()) (err error) {
	defer func() {
		if r := recover(); r != nil {
			if m, ok := r.(MathError); ok {
				err = m
				return
			}
			panic(r)
		}
	}()
	f()
	return nil
}

// ---------- leaf constructors ----------

func Num(r *big.Rat) E           { return &Expr{K: KNum, N: new(big.Rat).Set(r)} }
func Int(n int64) E              { return &Expr{K: KNum, N: new(big.Rat).SetInt64(n)} }
func Frac(a, b int64) E          { return &Expr{K: KNum, N: big.NewRat(a, b)} }
func Sym(name string) E          { return &Expr{K: KSym, S: name} }
func isNum(e E) bool             { return e.K == KNum }
func isInt(e E) bool             { return e.K == KNum && e.N.IsInt() }
func isNumVal(e E, v int64) bool { return e.K == KNum && e.N.Cmp(new(big.Rat).SetInt64(v)) == 0 }

var (
	Zero     = Int(0)
	One      = Int(1)
	MinusOne = Int(-1)
	Pi       = Sym("pi")
	EulerE   = Sym("e")
	I        = Sym("i")
)

func isConstSym(e E) bool { return e.K == KSym && (e.S == "pi" || e.S == "e" || e.S == "i") }

// Key returns a canonical full-precision serialisation used for equality and ordering.
func (e E) Key() string {
	if e.key != "" {
		return e.key
	}
	var s string
	switch e.K {
	case KNum:
		s = e.N.RatString()
	case KSym:
		s = e.S
	case KAdd, KMul, KPow, KFn:
		parts := make([]string, len(e.A))
		for i, a := range e.A {
			parts[i] = a.Key()
		}
		tag := map[Kind]string{KAdd: "+", KMul: "*", KPow: "^"}[e.K]
		if e.K == KFn {
			tag = e.S
		}
		s = "(" + tag + " " + strings.Join(parts, " ") + ")"
	case KMat:
		parts := make([]string, len(e.A))
		for i, a := range e.A {
			parts[i] = a.Key()
		}
		s = fmt.Sprintf("(mat %dx%d %s)", e.R, e.C, strings.Join(parts, " "))
	}
	e.key = s
	return s
}

// Equal reports structural (canonical) equality.
func Equal(a, b E) bool { return a.Key() == b.Key() }

// ---------- ordering ----------

func baseRank(e E) int {
	switch e.K {
	case KSym:
		return 0
	case KFn:
		return 1
	case KAdd:
		return 2
	case KMul:
		return 3
	case KPow:
		return 4
	case KMat:
		return 5
	}
	return 6
}

func factorBaseExp(f E) (E, E) {
	if f.K == KPow {
		return f.A[0], f.A[1]
	}
	return f, One
}

func cmpFactor(a, b E) bool {
	ba, ea := factorBaseExp(a)
	bb, eb := factorBaseExp(b)
	if ra, rb := baseRank(ba), baseRank(bb); ra != rb {
		return ra < rb
	}
	if ka, kb := ba.Key(), bb.Key(); ka != kb {
		return ka < kb
	}
	return ea.Key() < eb.Key()
}

// termDegree is the total polynomial degree of a term (used only for ordering sums).
func termDegree(e E) int {
	switch e.K {
	case KSym:
		if isConstSym(e) {
			return 0
		}
		return 1
	case KPow:
		if e.A[1].K == KNum && e.A[1].N.IsInt() && e.A[1].N.Sign() > 0 && e.A[1].N.Num().IsInt64() && e.A[1].N.Num().Int64() < 1<<20 {
			return termDegree(e.A[0]) * int(e.A[1].N.Num().Int64())
		}
	case KMul:
		d := 0
		for _, f := range e.A {
			d += termDegree(f)
		}
		return d
	case KAdd:
		d := 0
		for _, f := range e.A {
			if x := termDegree(f); x > d {
				d = x
			}
		}
		return d
	}
	return 0
}

func sortTerms(ts []E) {
	type kd struct {
		e E
		d int
		k string
		z int
	}
	tmp := make([]kd, len(ts))
	for i, t := range ts {
		tmp[i] = kd{t, termDegree(t), t.Key(), size(t)}
	}
	sort.SliceStable(tmp, func(i, j int) bool {
		if tmp[i].d != tmp[j].d {
			return tmp[i].d > tmp[j].d
		}
		if tmp[i].z != tmp[j].z {
			return tmp[i].z > tmp[j].z
		}
		return tmp[i].k < tmp[j].k
	})
	for i := range ts {
		ts[i] = tmp[i].e
	}
}

// ---------- tree utilities ----------

// Contains reports whether symbol name occurs in e.
func Contains(e E, name string) bool {
	if e.K == KSym {
		return e.S == name
	}
	for _, a := range e.A {
		if Contains(a, name) {
			return true
		}
	}
	return false
}

// FreeSyms returns the sorted non-constant symbols in e.
func FreeSyms(e E) []string {
	set := map[string]bool{}
	var walk func(E)
	walk = func(x E) {
		if x.K == KSym && !isConstSym(x) {
			set[x.S] = true
		}
		for _, a := range x.A {
			walk(a)
		}
	}
	walk(e)
	out := make([]string, 0, len(set))
	for s := range set {
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}

// rebuild reconstructs a node of the same kind with new children via the smart constructors.
func rebuild(e E, kids []E) E {
	switch e.K {
	case KAdd:
		return Add(kids...)
	case KMul:
		return Mul(kids...)
	case KPow:
		return Pow(kids[0], kids[1])
	case KFn:
		return Fn(e.S, kids...)
	case KMat:
		return &Expr{K: KMat, A: kids, R: e.R, C: e.C}
	}
	return e
}

// Map applies f to every direct child and rebuilds.
func Map(e E, f func(E) E) E {
	if len(e.A) == 0 {
		return e
	}
	kids := make([]E, len(e.A))
	for i, a := range e.A {
		kids[i] = f(a)
	}
	return rebuild(e, kids)
}

// Subst replaces symbols by expressions (simultaneously) and re-simplifies.
func Subst(e E, m map[string]E) E {
	if e.K == KSym {
		if r, ok := m[e.S]; ok {
			return r
		}
		return e
	}
	return Map(e, func(c E) E { return Subst(c, m) })
}

// SubstExpr replaces every occurrence of the sub-expression `from` by `to`.
func SubstExpr(e, from, to E) E {
	if Equal(e, from) {
		return to
	}
	return Map(e, func(c E) E { return SubstExpr(c, from, to) })
}

// Sub1 substitutes a single symbol.
func Sub1(e E, name string, v E) E { return Subst(e, map[string]E{name: v}) }

func ratOf(e E) *big.Rat { return new(big.Rat).Set(e.N) }

func ratInt64(r *big.Rat) (int64, bool) {
	if !r.IsInt() || !r.Num().IsInt64() {
		return 0, false
	}
	return r.Num().Int64(), true
}

// intExp returns e as a small int64 when it is an integer number.
func intExp(e E) (int64, bool) {
	if e.K != KNum {
		return 0, false
	}
	return ratInt64(e.N)
}
