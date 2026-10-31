package cas

import (
	"fmt"
	"math"
	"math/cmplx"
	"sort"
	"strings"
)

// Session holds REPL state: variable bindings and the previous result.
type Session struct {
	Vars map[string]E
	Ans  E
}

func NewSession() *Session { return &Session{Vars: map[string]E{}} }

type command struct {
	usage string
	doc   string
}

var commands = map[string]command{
	"simplify":  {"simplify(expr)", "canonical exact form"},
	"expand":    {"expand(expr)", "distribute products and integer powers"},
	"factor":    {"factor(poly [, x])", "factor over the rationals"},
	"diff":      {"diff(expr, x [, n])", "n-th derivative (default 1)"},
	"integrate": {"integrate(expr, x [, a, b])", "antiderivative, or definite integral; certified"},
	"solve":     {"solve(a = b, x)  |  solve([eqs], [vars])", "exact roots; linear systems"},
	"gcd":       {"gcd(p, q [, x])", "polynomial greatest common divisor"},
	"apart":     {"apart(expr, x)", "partial fractions"},
	"together":  {"together(expr, x)", "common denominator, cancelled"},
	"subst":     {"subst(expr, x, value)", "substitute"},
	"taylor":    {"taylor(expr, x, a, n)", "Taylor polynomial of degree n about a"},
	"N":         {"N(expr)", "numeric value"},
	"nroots":    {"nroots(poly, x)", "all complex roots, numerically"},
	"equal":     {"equal(a, b)", "decide whether two expressions are identical (exact, then numeric check)"},
	"det":       {"det(M)", "determinant"},
	"inv":       {"inv(M)", "inverse (rational matrices)"},
	"transpose": {"transpose(M)", "transpose"},
	"rref":      {"rref(M)", "reduced row echelon form"},
	"rank":      {"rank(M)", "rank"},
	"nullspace": {"nullspace(M)", "basis of the null space"},
	"charpoly":  {"charpoly(M [, x])", "characteristic polynomial"},
	"eigen":     {"eigen(M)", "eigenvalues with multiplicity, eigenvectors for rational ones"},
	"linsolve":  {"linsolve(A, b)", "solve A x = b exactly"},
	"limit":     {"limit(expr, x, a [, dir])", "limit; a may be oo or -oo; dir = -1 / 1 for one-sided"},
	"eq":        {"", ""},
}

func init() {
	Callable = func(name string) bool { _, ok := commands[name]; return ok }
}

// Help returns the command reference.
func Help() string {
	var names []string
	for n, c := range commands {
		if c.usage != "" {
			names = append(names, n)
		}
	}
	sort.Strings(names)
	var sb strings.Builder
	sb.WriteString("Commands:\n")
	for _, n := range names {
		c := commands[n]
		sb.WriteString(fmt.Sprintf("  %-34s %s\n", c.usage, c.doc))
	}
	sb.WriteString("\nFunctions: sin cos tan sec csc cot asin acos atan sinh cosh tanh exp ln log sqrt abs\n")
	sb.WriteString("Constants: pi e i oo (infinity).  Assign with  name = expr ;  use ans for the last result.\n")
	sb.WriteString("Matrices: [[1,2],[3,4]] with + - * ^ operators.  Implicit multiplication: 2x, 3(x+1).\n")
	return sb.String()
}

// Eval evaluates one input line and returns the lines to print.
func (s *Session) Eval(line string) (out []string, err error) {
	defer func() {
		if r := recover(); r != nil {
			out, err = nil, fmt.Errorf("internal error: %v (this is a bug in Abel; the session is still usable)", r)
		}
	}()
	line = strings.TrimSpace(line)
	if line == "" {
		return nil, nil
	}
	if line == "help" || line == "?" {
		return []string{strings.TrimRight(Help(), "\n")}, nil
	}
	if line == "vars" {
		var names []string
		for n := range s.Vars {
			names = append(names, n)
		}
		sort.Strings(names)
		for _, n := range names {
			out = append(out, fmt.Sprintf("%s = %s", n, s.Vars[n]))
		}
		if len(out) == 0 {
			out = []string{"(no variables defined)"}
		}
		return out, nil
	}
	e, perr := Parse(line)
	if perr != nil {
		return nil, perr
	}
	if e.K == KFn && e.S == "eq" && e.A[0].K == KSym && !isConstSym(e.A[0]) {
		name := e.A[0].S
		var val E
		if gerr := Guard(func() { val = s.subst(e.A[1]) }); gerr != nil {
			return nil, gerr
		}
		s.Vars[name] = val
		s.Ans = val
		return []string{fmt.Sprintf("%s = %s", name, val)}, nil
	}
	gerr := Guard(func() { out = s.run(e) })
	return out, gerr
}

func (s *Session) subst(e E) E {
	m := map[string]E{}
	for k, v := range s.Vars {
		m[k] = v
	}
	if s.Ans != nil {
		m["ans"] = s.Ans
	}
	if len(m) == 0 {
		return e
	}
	return Subst(e, m)
}

func (s *Session) run(e E) []string {
	if e.K == KFn && commands[e.S].usage != "" {
		return s.command(e)
	}
	if e.K == KFn && e.S == "eq" {
		return []string{fmt.Sprintf("%s = %s", s.subst(e.A[0]), s.subst(e.A[1]))}
	}
	r := s.subst(e)
	s.Ans = r
	return []string{r.String()}
}

func symName(e E) string {
	if e.K != KSym || isConstSym(e) {
		fail("expected a variable name, got %s", e.String())
	}
	return e.S
}

func (s *Session) command(c E) []string {
	args := c.A
	argc := func(lo, hi int) {
		if len(args) < lo || len(args) > hi {
			fail("%s expects %s", commands[c.S].usage, "different arguments")
		}
	}
	ex := func(i int) E { return s.subst(args[i]) }
	// pick the default variable when omitted
	defVar := func(e E) string {
		fv := FreeSyms(e)
		if len(fv) == 1 {
			return fv[0]
		}
		if Contains(e, "x") {
			return "x"
		}
		if len(fv) == 0 {
			return "x"
		}
		fail("which variable? use %s(expr, var)", c.S)
		return ""
	}
	result := func(r E) []string { s.Ans = r; return []string{r.String()} }
	switch c.S {
	case "simplify":
		argc(1, 1)
		return result(ex(0))
	case "expand":
		argc(1, 1)
		return result(Expand(ex(0)))
	case "factor":
		argc(1, 2)
		e := ex(0)
		v := ""
		if len(args) == 2 {
			v = symName(args[1])
		} else {
			v = defVar(e)
		}
		r := Factor(e, v)
		out := result(r)
		if p, ok := ToPoly(e, v); ok && Equal(Expand(r), Expand(e)) && len(p) > 0 {
			out = append(out, "  ✓ certified: expanding the factors reproduces the input")
		}
		return out
	case "diff":
		argc(2, 3)
		e := ex(0)
		n := 1
		if len(args) == 3 {
			k, ok := intExp(args[2])
			if !ok || k < 0 || k > 50 {
				fail("order must be an integer between 0 and 50")
			}
			n = int(k)
		}
		return result(DiffN(e, symName(args[1]), n))
	case "integrate":
		if len(args) != 2 && len(args) != 4 {
			fail("usage: %s", commands[c.S].usage)
		}
		e, v := ex(0), symName(args[1])
		if len(args) == 4 {
			r, checked, err := DefiniteIntegral(e, v, ex(2), ex(3))
			if err != nil {
				fail("%s", err.Error())
			}
			out := result(r)
			if val, err := EvalNum(r, nil); err == nil && imag(val) == 0 && !isConstNum(r) {
				out = append(out, fmt.Sprintf("  ≈ %.12g", real(val)))
			}
			if checked {
				out = append(out, "  ✓ cross-checked against numeric quadrature")
			}
			return out
		}
		F, err := Integrate(e, v)
		if err != nil {
			fail("%s", err.Error())
		}
		out := result(F)
		if ok, detail := Verify(e, F, v); ok {
			out = append(out, "  ✓ certified: "+detail)
		} else {
			out = append(out, "  ⚠ could not certify: "+detail)
		}
		return append(out, "  (+ C)")
	case "solve":
		argc(2, 2)
		if args[0].K == KMat {
			return s.solveSystem(args[0], args[1])
		}
		v := symName(args[1])
		roots := Solve(ex(0), v)
		if len(roots) == 0 {
			return []string{"no solutions"}
		}
		var out []string
		var exact []E
		for _, r := range roots {
			line := fmt.Sprintf("%s = %s", v, r.String())
			if r.Mult > 1 {
				line += fmt.Sprintf("   (multiplicity %d)", r.Mult)
			}
			if r.Exact != nil {
				if r.Exact.K != KNum && len(FreeSyms(r.Exact)) == 0 {
					line += fmt.Sprintf("   ≈ %s", fmtComplex(r.Approx))
				}
				exact = append(exact, r.Exact)
			}
			out = append(out, line)
		}
		if len(exact) > 0 {
			s.Ans = exact[0]
		}
		return out
	case "gcd":
		argc(2, 3)
		a, b := ex(0), ex(1)
		v := ""
		if len(args) == 3 {
			v = symName(args[2])
		} else {
			v = defVar(Add(a, b))
		}
		return result(PolyGCD(a, b, v))
	case "apart":
		argc(1, 2)
		e := ex(0)
		v := defVar(e)
		if len(args) == 2 {
			v = symName(args[1])
		}
		return result(Apart(e, v))
	case "together":
		argc(1, 2)
		e := ex(0)
		v := defVar(e)
		if len(args) == 2 {
			v = symName(args[1])
		}
		return result(Together(e, v))
	case "subst":
		argc(3, 3)
		return result(Sub1(ex(0), symName(args[1]), ex(2)))
	case "taylor":
		argc(4, 4)
		n, ok := intExp(args[3])
		if !ok {
			fail("order must be an integer")
		}
		return result(Taylor(ex(0), symName(args[1]), ex(2), int(n)))
	case "limit":
		argc(3, 4)
		dir := 0
		if len(args) == 4 {
			k, ok := intExp(args[3])
			if !ok || k < -1 || k > 1 {
				fail("direction must be -1, 0 or 1")
			}
			dir = int(k)
		}
		return result(Limit(ex(0), symName(args[1]), ex(2), dir))
	case "N":
		argc(1, 1)
		v, err := EvalNum(ex(0), nil)
		if err != nil {
			fail("%s", err.Error())
		}
		return []string{fmtComplex(v)}
	case "nroots":
		argc(1, 2)
		e := ex(0)
		v := defVar(e)
		if len(args) == 2 {
			v = symName(args[1])
		}
		p, ok := ToPoly(e, v)
		if !ok {
			fail("nroots needs a polynomial in %s with rational coefficients", v)
		}
		var out []string
		for _, z := range NumericRoots(p) {
			out = append(out, fmtComplex(z))
		}
		return out
	case "equal":
		argc(2, 2)
		a, b := ex(0), ex(1)
		if Equal(a, b) || Equal(Expand(Sub(a, b)), Zero) {
			return []string{"true (exactly equal after expansion)"}
		}
		if numericallyEqual(a, b) {
			return []string{"true (numerically equal at 25 random points; not exactly canonicalised)"}
		}
		return []string{"false"}
	case "det", "inv", "transpose", "rref", "rank", "nullspace", "charpoly", "eigen", "linsolve":
		return s.matrixCommand(c)
	}
	fail("unknown command %s", c.S)
	return nil
}

func isConstNum(e E) bool { return e.K == KNum }

func numericallyEqual(a, b E) bool {
	vars := map[string]bool{}
	for _, v := range FreeSyms(a) {
		vars[v] = true
	}
	for _, v := range FreeSyms(b) {
		vars[v] = true
	}
	seed := uint64(1234567)
	rnd := func() float64 {
		seed = seed*6364136223846793005 + 1442695040888963407
		return 0.3 + float64(seed>>40)/float64(1<<24)*2.4
	}
	valid := 0
	for i := 0; i < 25; i++ {
		env := map[string]complex128{}
		for v := range vars {
			env[v] = complex(rnd(), 0)
		}
		x, e1 := EvalNum(a, env)
		y, e2 := EvalNum(b, env)
		if e1 != nil || e2 != nil || cmplx.IsNaN(x) || cmplx.IsNaN(y) {
			continue
		}
		valid++
		if cmplx.Abs(x-y) > 1e-9*(1+cmplx.Abs(x)) || math.IsInf(real(x), 0) {
			return false
		}
	}
	return valid >= 5
}

func (s *Session) solveSystem(eqs, vars E) []string {
	if vars.K != KMat || eqs.R != 1 || vars.R != 1 {
		fail("usage: solve([eq1, eq2, ...], [x, y, ...])")
	}
	names := make([]string, vars.C)
	for i := range names {
		names[i] = symName(vars.A[i])
	}
	if eqs.C != vars.C {
		fail("need as many equations as unknowns (%d vs %d)", eqs.C, vars.C)
	}
	n := vars.C
	cells := make([]E, 0, n*n)
	rhs := make([]E, n)
	for i := 0; i < n; i++ {
		eq := s.subst(eqs.A[i])
		var diff E
		if eq.K == KFn && eq.S == "eq" {
			diff = Sub(eq.A[0], eq.A[1])
		} else {
			diff = eq
		}
		diff = Expand(diff)
		rest := diff
		for _, v := range names {
			c := Diff(diff, v)
			if Contains(c, v) {
				fail("equation %d is not linear in %s", i+1, v)
			}
			cells = append(cells, c)
			rest = Sub1(rest, v, Zero)
		}
		if len(FreeSyms(Add(append(append([]E{}, cells[i*n:(i+1)*n]...), rest)...))) > 0 {
			fail("solve() for systems needs numeric coefficients")
		}
		rhs[i] = Neg(rest)
	}
	sol := SolveLinear(NewMat(n, n, cells), NewMat(n, 1, rhs))
	out := make([]string, n)
	for i, v := range names {
		out[i] = fmt.Sprintf("%s = %s", v, sol.A[i])
	}
	return out
}

func (s *Session) matrixCommand(c E) []string {
	if len(c.A) < 1 {
		fail("usage: %s", commands[c.S].usage)
	}
	m := s.subst(c.A[0])
	if m.K != KMat {
		fail("%s needs a matrix argument like [[1,2],[3,4]]", c.S)
	}
	show := func(e E) []string { s.Ans = e; return matLines(e) }
	switch c.S {
	case "det":
		return show(Det(m))
	case "inv":
		return show(Inverse(m))
	case "transpose":
		return show(Transpose(m))
	case "rref":
		return show(Rref(m))
	case "rank":
		return show(Int(int64(Rank(m))))
	case "nullspace":
		ns := Nullspace(m)
		if len(ns) == 0 {
			return []string{"{0}  (trivial null space)"}
		}
		var out []string
		for _, v := range ns {
			out = append(out, v.String())
		}
		return out
	case "charpoly":
		v := "x"
		if len(c.A) == 2 {
			v = symName(c.A[1])
		}
		return show(CharPoly(m, v))
	case "linsolve":
		if len(c.A) != 2 {
			fail("usage: linsolve(A, b)")
		}
		return show(SolveLinear(m, s.subst(c.A[1])))
	case "eigen":
		return eigenLines(m)
	}
	return nil
}

func matLines(e E) []string {
	if e.K != KMat {
		return []string{e.String()}
	}
	w := make([]int, e.C)
	cells := make([]string, len(e.A))
	for i, a := range e.A {
		cells[i] = a.String()
		if l := len([]rune(cells[i])); l > w[i%e.C] {
			w[i%e.C] = l
		}
	}
	var out []string
	for i := 0; i < e.R; i++ {
		var row []string
		for j := 0; j < e.C; j++ {
			c := cells[i*e.C+j]
			row = append(row, strings.Repeat(" ", w[j]-len([]rune(c)))+c)
		}
		out = append(out, "| "+strings.Join(row, "  ")+" |")
	}
	return out
}

func eigenLines(m E) []string {
	if m.R != m.C {
		fail("eigen needs a square matrix")
	}
	cp := CharPoly(m, "lambda")
	out := []string{"characteristic polynomial: " + cp.String()}
	roots := Solve(cp, "lambda")
	total := 0
	for _, r := range roots {
		total += r.Mult
	}
	for _, r := range roots {
		line := fmt.Sprintf("lambda = %s", r.String())
		if r.Mult > 1 {
			line += fmt.Sprintf("  (algebraic multiplicity %d)", r.Mult)
		}
		out = append(out, line)
		if r.Exact != nil && r.Exact.K == KNum {
			shifted := Add(m, Mul(Neg(r.Exact), Identity(m.R)))
			for _, v := range Nullspace(shifted) {
				out = append(out, "    eigenvector: "+colString(v))
			}
		}
	}
	for _, r := range roots {
		if r.Exact != nil && r.Exact.K != KNum {
			out = append(out, "note: eigenvectors are only computed for rational eigenvalues")
			break
		}
	}
	if total != m.R {
		out = append(out, fmt.Sprintf("note: found %d of %d eigenvalues (the rest are not reported)", total, m.R))
	}
	return out
}

func colString(v E) string {
	parts := make([]string, len(v.A))
	for i, a := range v.A {
		parts[i] = a.String()
	}
	return "(" + strings.Join(parts, ", ") + ")^T"
}
