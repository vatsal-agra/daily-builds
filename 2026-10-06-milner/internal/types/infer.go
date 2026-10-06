package types

import (
	"fmt"
	"sort"
	"strings"

	"milner/internal/syntax"
)

// Bound is a name introduced by a declaration, with its inferred scheme.
type Bound struct {
	Name   string
	Scheme *Scheme
}

// DeclResult is the outcome of type-checking one declaration.
type DeclResult struct {
	Env      *Env
	Bound    []Bound
	Expr     Type // for bare expressions
	NewTypes []*TypeInfo
}

type inferer struct {
	env    *Env
	level  int
	u      unifier
	nextID int
	tyvars map[string]Type // 'a names in annotations (shared across one declaration)
	holes  []hole
	tr     *Tracer
	depth  int
	inDecl bool // converting a `type` declaration (open record types are not allowed there)
}

type hole struct {
	sp  syntax.Span
	t   Type
	env *Env
}

func (i *inferer) newVar() *TVar {
	i.nextID++
	return &TVar{ID: i.nextID, Level: i.level}
}

func (i *inferer) enter() { i.level++ }
func (i *inferer) leave() { i.level-- }

// ---------- generalisation / instantiation ----------

func (i *inferer) generalize(t Type) {
	t = Prune(t)
	switch x := t.(type) {
	case *TVar:
		if x.Level > i.level && x.Level != Generic {
			x.Level = Generic
		}
	case *TCon:
		for _, a := range x.Args {
			i.generalize(a)
		}
	}
}

// weaken lowers every variable in t to the current level (value restriction: not generalised).
func (i *inferer) weaken(t Type) {
	t = Prune(t)
	switch x := t.(type) {
	case *TVar:
		if x.Level > i.level && x.Level != Generic {
			x.Level = i.level
		}
	case *TCon:
		for _, a := range x.Args {
			i.weaken(a)
		}
	}
}

func (i *inferer) instantiate(t Type, m map[*TVar]Type) Type {
	t = Prune(t)
	switch x := t.(type) {
	case *TVar:
		if x.Level == Generic {
			if r, ok := m[x]; ok {
				return r
			}
			v := i.newVar()
			m[x] = v
			return v
		}
		return x
	case *TCon:
		if len(x.Args) == 0 {
			return x
		}
		args := make([]Type, len(x.Args))
		changed := false
		for k, a := range x.Args {
			args[k] = i.instantiate(a, m)
			if args[k] != a {
				changed = true
			}
		}
		if !changed {
			return x
		}
		return &TCon{Head: x.Head, Args: args}
	}
	return t
}

// ---------- error helpers ----------

func (i *inferer) fail(d *syntax.Diag) { panic(d) }

func (i *inferer) unifyAt(sp syntax.Span, expected, actual Type, note string) {
	before := len(i.u.trail)
	// snapshot the operands before unification binds anything, so the trace reads naturally
	var ea, aa string
	var tp *Printer
	if i.tr != nil {
		tp = i.tr.printer()
		ea, aa = tp.String(expected), tp.String(actual)
	}
	err := i.u.unify(expected, actual)
	if i.tr != nil {
		var bound []string
		for _, v := range i.u.trail[before:] {
			bound = append(bound, fmt.Sprintf("%s := %s", tp.nameOf(v), tp.String(v.Ref)))
		}
		i.tr.unifyStr(i.depth, ea, aa, bound, err != nil)
	}
	if err != nil {
		i.fail(i.mismatch(sp, expected, actual, err, note))
	}
}

func (i *inferer) mismatch(sp syntax.Span, expected, actual Type, err *UnifyErr, note string) *syntax.Diag {
	pr := NewPrinter()
	pr.Plain = true
	e, a := pr.String(expected), pr.String(actual)
	d := &syntax.Diag{Kind: "type", Span: sp}
	if err.Occurs {
		d.Msg = "cannot construct an infinite type"
		d.Label = fmt.Sprintf("`%s` would have to contain itself: `%s` = `%s`", pr.String(err.A), pr.String(err.A), pr.String(err.B))
		d.Notes = append(d.Notes, "this usually means a value is used at two different shapes, or a function is applied to itself")
		return d
	}
	d.Msg = fmt.Sprintf("mismatched types: expected `%s`, found `%s`", e, a)
	d.Label = fmt.Sprintf("expected `%s`", e)
	if note != "" {
		d.Notes = append(d.Notes, note)
	}
	if err.Field != "" {
		if err.LacksLeft {
			d.Notes = append(d.Notes, fmt.Sprintf("the expected record type is closed and has no field `%s` (write `; ..` at the end of the annotation to accept records with more fields)", err.Field))
		} else {
			d.Notes = append(d.Notes, fmt.Sprintf("the record given here has no field `%s`", err.Field))
		}
	} else if err.Arity {
		d.Notes = append(d.Notes, fmt.Sprintf("`%s` and `%s` have different numbers of components", pr.String(err.A), pr.String(err.B)))
	} else if ea, eb := pr.String(err.A), pr.String(err.B); (ea != e || eb != a) && ea != eb {
		d.Notes = append(d.Notes, fmt.Sprintf("specifically, `%s` is not `%s`", ea, eb))
	} else if ea == eb {
		d.Notes = append(d.Notes, fmt.Sprintf("two different types are both named `%s` (one comes from an earlier definition of the type)", ea))
	}
	return d
}

func levenshtein(a, b string) int {
	ra, rb := []rune(a), []rune(b)
	prev := make([]int, len(rb)+1)
	for j := range prev {
		prev[j] = j
	}
	for x := 1; x <= len(ra); x++ {
		cur := make([]int, len(rb)+1)
		cur[0] = x
		for y := 1; y <= len(rb); y++ {
			c := 1
			if ra[x-1] == rb[y-1] {
				c = 0
			}
			cur[y] = min(prev[y]+1, cur[y-1]+1, prev[y-1]+c)
		}
		prev = cur
	}
	return prev[len(rb)]
}

func suggest(name string, cands []string) string {
	best, bd := "", 3
	for _, c := range cands {
		if strings.HasPrefix(c, "$") || c == name {
			continue
		}
		d := levenshtein(name, c)
		if len([]rune(name)) <= 2 {
			continue
		}
		if d < bd {
			best, bd = c, d
		}
	}
	return best
}

// ---------- type expressions ----------

type tyScope func(name string, sp syntax.Span) Type

func (i *inferer) convType(te syntax.TyExpr, scope tyScope) Type {
	switch t := te.(type) {
	case *syntax.TyVar:
		return scope(t.Name, t.Sp)
	case *syntax.TyArrow:
		return Arrow(i.convType(t.From, scope), i.convType(t.To, scope))
	case *syntax.TyTuple:
		ts := make([]Type, len(t.Elems))
		for k, e := range t.Elems {
			ts[k] = i.convType(e, scope)
		}
		return Tuple(ts)
	case *syntax.TyRecord:
		seen := map[string]bool{}
		var tail Type = &TCon{Head: HRowEmpty}
		if t.Open {
			if i.inDecl {
				i.fail(syntax.Errorf("type", t.Sp, "open record types (`; ..`) are only allowed in annotations, not in `type` declarations"))
			}
			tail = i.newVar()
		}
		fts := make([]Type, len(t.Fields))
		for k, f := range t.Fields {
			if seen[f.Name] {
				i.fail(syntax.Errorf("type", t.Sp, "field `%s` appears twice in this record type", f.Name))
			}
			seen[f.Name] = true
			fts[k] = i.convType(f.Ty, scope)
		}
		for k := len(t.Fields) - 1; k >= 0; k-- {
			tail = RowExt(t.Fields[k].Name, fts[k], tail)
		}
		return RecordOf(tail)
	case *syntax.TyCon:
		info, ok := i.env.Types[t.Name]
		if !ok {
			names := make([]string, 0, len(i.env.Types))
			for n := range i.env.Types {
				names = append(names, n)
			}
			d := syntax.Errorf("type", t.Sp, "unknown type `%s`", t.Name)
			if s := suggest(t.Name, names); s != "" {
				d.Notes = append(d.Notes, fmt.Sprintf("did you mean `%s`?", s))
			}
			i.fail(d)
		}
		if len(t.Args) != info.Head.Arity {
			i.fail(syntax.Errorf("type", t.Sp, "type `%s` expects %d argument(s) but is given %d", t.Name, info.Head.Arity, len(t.Args)))
		}
		args := make([]Type, len(t.Args))
		for k, a := range t.Args {
			args[k] = i.convType(a, scope)
		}
		if info.IsAlias {
			if info.AliasBody == nil {
				i.fail(syntax.Errorf("type", t.Sp, "type alias `%s` is used before it is defined (aliases cannot be recursive)", t.Name))
			}
			m := map[*TVar]Type{}
			for k, v := range info.AliasVars {
				m[v] = args[k]
			}
			return substGeneric(info.AliasBody, m)
		}
		return &TCon{Head: info.Head, Args: args}
	}
	panic("unreachable")
}

// substGeneric replaces the generic variables in m inside t (used to expand type aliases).
func substGeneric(t Type, m map[*TVar]Type) Type {
	switch x := Prune(t).(type) {
	case *TVar:
		if r, ok := m[x]; ok {
			return r
		}
		return x
	case *TCon:
		if len(x.Args) == 0 {
			return x
		}
		args := make([]Type, len(x.Args))
		for k, a := range x.Args {
			args[k] = substGeneric(a, m)
		}
		return &TCon{Head: x.Head, Args: args}
	}
	return t
}

// hasGeneric reports whether t mentions a generalised variable (an annotation variable that an inner
// `let` generalised must not be reused by a later annotation of the same name).
func hasGeneric(t Type) bool {
	switch x := Prune(t).(type) {
	case *TVar:
		return x.Level == Generic
	case *TCon:
		for _, a := range x.Args {
			if hasGeneric(a) {
				return true
			}
		}
	}
	return false
}

func (i *inferer) annotScope() tyScope {
	return func(name string, sp syntax.Span) Type {
		if v, ok := i.tyvars[name]; ok && !hasGeneric(v) {
			return v
		}
		v := i.newVar()
		i.tyvars[name] = v
		return v
	}
}

// ---------- expressions ----------

func nonExpansive(e syntax.Expr) bool {
	switch x := e.(type) {
	case *syntax.EInt, *syntax.EStr, *syntax.EBool, *syntax.EUnit, *syntax.EVar, *syntax.EFun, *syntax.EHole:
		return true
	case *syntax.ECon:
		return x.Arg == nil || nonExpansive(x.Arg)
	case *syntax.ETuple:
		for _, el := range x.Elems {
			if !nonExpansive(el) {
				return false
			}
		}
		return true
	case *syntax.EAnnot:
		return nonExpansive(x.E)
	case *syntax.ELet:
		for _, b := range x.Bindings {
			if !nonExpansive(b.Expr) {
				return false
			}
		}
		return nonExpansive(x.Body)
	case *syntax.ERecord:
		for _, f := range x.Fields {
			if !nonExpansive(f.Expr) {
				return false
			}
		}
		return true
	case *syntax.ERecordWith:
		for _, f := range x.Fields {
			if !nonExpansive(f.Expr) {
				return false
			}
		}
		return nonExpansive(x.Base)
	case *syntax.EField:
		return nonExpansive(x.E)
	}
	return false
}

func unwrapAnnot(e syntax.Expr) syntax.Expr {
	for {
		a, ok := e.(*syntax.EAnnot)
		if !ok {
			return e
		}
		e = a.E
	}
}

func isOperatorName(n string) bool {
	if n == "mod" {
		return true
	}
	c := n[0]
	return !(c == '_' || c == '$' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c >= 0x80)
}

// schemeArity counts the syntactic parameters of a scheme's type (without looking through variables).
func schemeArity(t Type) int {
	n := 0
	for {
		c, ok := Prune(t).(*TCon)
		if !ok || c.Head != HArrow {
			return n
		}
		n++
		t = c.Args[1]
	}
}

func headName(e syntax.Expr) (string, int) {
	n := 0
	for {
		switch x := e.(type) {
		case *syntax.EApp:
			n++
			e = x.Fn
		case *syntax.EVar:
			return x.Name, n
		default:
			return "", n
		}
	}
}

func (i *inferer) infer(env *Env, e syntax.Expr) Type {
	if i.tr != nil {
		i.depth++
		defer func() { i.depth-- }()
	}
	if i.tr != nil {
		i.tr.enter(i.depth, e)
	}
	t := i.inferInner(env, e)
	if i.tr != nil {
		i.tr.expr(i.depth, e, t)
	}
	return t
}

func (i *inferer) inferInner(env *Env, e syntax.Expr) Type {
	switch x := e.(type) {
	case *syntax.EInt:
		return TInt
	case *syntax.EStr:
		return TString
	case *syntax.EBool:
		return TBool
	case *syntax.EUnit:
		return TUnit
	case *syntax.EVar:
		sc, ok := env.Lookup(x.Name)
		if !ok {
			d := syntax.Errorf("type", x.Sp, "unbound variable `%s`", x.Name)
			d.Label = "not found in this scope"
			if s := suggest(x.Name, env.VisibleNames()); s != "" {
				d.Notes = append(d.Notes, fmt.Sprintf("did you mean `%s`?", s))
			}
			i.fail(d)
		}
		t := i.instantiate(sc.Type, map[*TVar]Type{})
		if i.tr != nil {
			i.tr.inst(i.depth, x.Name, sc.Type, t)
		}
		return t
	case *syntax.ECon:
		ci := i.lookupCon(env, x.Name, x.Sp)
		t := i.instantiate(ci.Scheme.Type, map[*TVar]Type{})
		if ci.Arity == 0 {
			if x.Arg != nil {
				i.fail(syntax.Errorf("type", x.Arg.ESpan(), "constructor `%s` takes no argument", x.Name))
			}
			return t
		}
		fn := Prune(t).(*TCon)
		if x.Arg == nil {
			return t // a constructor used as a function
		}
		if x.Name == "::" {
			return i.inferListChain(env, x)
		}
		if tup, ok := x.Arg.(*syntax.ETuple); ok && ci.Arity > 1 && len(tup.Elems) == ci.Arity {
			// check each component separately so a mismatch is reported at the offending component
			pt := Prune(fn.Args[0]).(*TCon)
			for k, el := range tup.Elems {
				te := i.infer(env, el)
				i.unifyAt(el.ESpan(), pt.Args[k], te, fmt.Sprintf("component %d of constructor `%s`", k+1, x.Name))
			}
			return fn.Args[1]
		}
		ta := i.infer(env, x.Arg)
		note := fmt.Sprintf("constructor `%s` expects %s", x.Name, payloadDesc(ci))
		i.unifyAt(x.Arg.ESpan(), fn.Args[0], ta, note)
		return fn.Args[1]
	case *syntax.EFun:
		var ptypes []Type
		cur := env
		seen := map[string]bool{}
		for _, p := range x.Params {
			pt := Type(i.newVar())
			ptypes = append(ptypes, pt)
			binds := i.inferPat(env, p, pt, nil)
			for _, b := range binds {
				if seen[b.name] {
					i.fail(syntax.Errorf("type", b.sp, "parameter `%s` is bound twice in this function", b.name))
				}
				seen[b.name] = true
				cur = cur.Extend(b.name, &Scheme{Type: b.t})
			}
		}
		bt := i.infer(cur, x.Body)
		for k := len(ptypes) - 1; k >= 0; k-- {
			bt = Arrow(ptypes[k], bt)
		}
		return bt
	case *syntax.EApp:
		return i.inferApp(env, x)
	case *syntax.ELet:
		return i.inferLet(env, x)
	case *syntax.EIf:
		tc := i.infer(env, x.Cond)
		i.unifyAt(x.Cond.ESpan(), TBool, tc, "the condition of an `if` must be a `bool`")
		tt := i.infer(env, x.Then)
		if u, ok := x.Else.(*syntax.EUnit); ok && u.Sp.Start.Off == u.Sp.End.Off {
			i.unifyAt(x.Then.ESpan(), TUnit, tt, "an `if` without an `else` must have type `unit`")
			return TUnit
		}
		te := i.infer(env, x.Else)
		i.unifyAt(x.Else.ESpan(), tt, te, fmt.Sprintf("both branches of an `if` must have the same type; the `then` branch has type `%s`", TypeString(tt)))
		return tt
	case *syntax.EMatch:
		ts := i.infer(env, x.Scrut)
		res := Type(i.newVar())
		for k, arm := range x.Arms {
			binds := i.inferPat(env, arm.Pat, ts, nil)
			cur := env
			for _, b := range binds {
				cur = cur.Extend(b.name, &Scheme{Type: b.t})
			}
			if arm.Guard != nil {
				tg := i.infer(cur, arm.Guard)
				i.unifyAt(arm.Guard.ESpan(), TBool, tg, "a `when` guard must be a `bool`")
			}
			tb := i.infer(cur, arm.Body)
			note := ""
			if k > 0 {
				note = fmt.Sprintf("all arms of a `match` must have the same type; earlier arms have type `%s`", TypeString(res))
			}
			i.unifyAt(arm.Body.ESpan(), res, tb, note)
		}
		return res
	case *syntax.ETuple:
		ts := make([]Type, len(x.Elems))
		for k, el := range x.Elems {
			ts[k] = i.infer(env, el)
		}
		return Tuple(ts)
	case *syntax.ESeq:
		ta := i.infer(env, x.A)
		i.unifyAt(x.A.ESpan(), TUnit, ta, "the left side of `;` is evaluated for its effect and must have type `unit` (use `let _ = ... in` to discard a value)")
		return i.infer(env, x.B)
	case *syntax.EAnd:
		i.unifyAt(x.L.ESpan(), TBool, i.infer(env, x.L), "operands of `&&` must be `bool`")
		i.unifyAt(x.R.ESpan(), TBool, i.infer(env, x.R), "operands of `&&` must be `bool`")
		return TBool
	case *syntax.EOr:
		i.unifyAt(x.L.ESpan(), TBool, i.infer(env, x.L), "operands of `||` must be `bool`")
		i.unifyAt(x.R.ESpan(), TBool, i.infer(env, x.R), "operands of `||` must be `bool`")
		return TBool
	case *syntax.EAnnot:
		t := i.infer(env, x.E)
		at := i.convType(x.Ty, i.annotScope())
		i.unifyAt(x.E.ESpan(), at, t, "this expression was annotated with `"+TypeString(at)+"`")
		return at
	case *syntax.ERecord:
		seen := map[string]bool{}
		fts := make([]Type, len(x.Fields))
		for k, f := range x.Fields {
			if seen[f.Name] {
				i.fail(syntax.Errorf("type", f.Sp, "field `%s` is defined twice in this record", f.Name))
			}
			seen[f.Name] = true
			fts[k] = i.infer(env, f.Expr)
		}
		var row Type = &TCon{Head: HRowEmpty}
		for k := len(x.Fields) - 1; k >= 0; k-- {
			row = RowExt(x.Fields[k].Name, fts[k], row)
		}
		return RecordOf(row)
	case *syntax.EField:
		return i.selectField(i.infer(env, x.E), x.Name, x.NameSp, x.E.ESpan())
	case *syntax.ERecordWith:
		tb := i.infer(env, x.Base)
		seen := map[string]bool{}
		for _, f := range x.Fields {
			if seen[f.Name] {
				i.fail(syntax.Errorf("type", f.Sp, "field `%s` is updated twice", f.Name))
			}
			seen[f.Name] = true
			ft := i.selectField(tb, f.Name, f.Sp, x.Base.ESpan())
			ta := i.infer(env, f.Expr)
			i.unifyAt(f.Expr.ESpan(), ft, ta, fmt.Sprintf("field `%s` has type `%s`; a record update cannot change a field's type", f.Name, TypeString(ft)))
		}
		return tb
	case *syntax.EHole:
		t := Type(i.newVar())
		i.holes = append(i.holes, hole{sp: x.Sp, t: t, env: env})
		return t
	}
	panic(fmt.Sprintf("infer: unhandled expression %T", e))
}

// inferListChain types a right-nested chain of `::` (which is how list literals are parsed), checking
// every element against the element type so errors point at the offending element.
func (i *inferer) inferListChain(env *Env, x *syntax.ECon) Type {
	elem := Type(i.newVar())
	var cur syntax.Expr = x
	first := true
	for {
		c, ok := cur.(*syntax.ECon)
		if !ok || c.Name != "::" || c.Arg == nil {
			break
		}
		tup, ok := c.Arg.(*syntax.ETuple)
		if !ok || len(tup.Elems) != 2 {
			break
		}
		te := i.infer(env, tup.Elems[0])
		note := ""
		if !first {
			note = fmt.Sprintf("all elements of a list must have the same type; the earlier elements have type `%s`", TypeString(elem))
		}
		i.unifyAt(tup.Elems[0].ESpan(), elem, te, note)
		first = false
		cur = tup.Elems[1]
	}
	tt := i.infer(env, cur)
	i.unifyAt(cur.ESpan(), ListOf(elem), tt, "the right side of `::` must be a list")
	return ListOf(elem)
}

// rowFields lists the labels of a record type's row and whether the row is closed.
func rowFields(row Type) (labels []string, closed bool) {
	for {
		c, ok := Prune(row).(*TCon)
		if !ok {
			return labels, false
		}
		if c.Head == HRowEmpty {
			return labels, true
		}
		labels = append(labels, c.Head.Label)
		row = c.Args[1]
	}
}

// selectField returns the type of field `name` of a record of type t, constraining t to have it.
func (i *inferer) selectField(t Type, name string, sp, subjSp syntax.Span) Type {
	switch x := Prune(t).(type) {
	case *TCon:
		if x.Head != HRecord {
			d := syntax.Errorf("type", subjSp, "this expression has type `%s`, which is not a record, so it has no field `%s`", TypeString(t), name)
			d.Label = "not a record"
			i.fail(d)
		}
		if labels, closed := rowFields(x.Args[0]); closed {
			found := false
			for _, l := range labels {
				if l == name {
					found = true
				}
			}
			if !found {
				sort.Strings(labels)
				d := syntax.Errorf("type", sp, "this record has no field `%s`", name)
				d.Label = "no such field"
				d.Notes = append(d.Notes, "its type is `"+TypeString(t)+"`")
				if s := suggest(name, labels); s != "" {
					d.Notes = append(d.Notes, fmt.Sprintf("did you mean `%s`?", s))
				}
				i.fail(d)
			}
		}
	}
	a := Type(i.newVar())
	rho := Type(i.newVar())
	i.unifyAt(subjSp, RecordOf(RowExt(name, a, rho)), t, "")
	return a
}

func payloadDesc(ci *ConInfo) string {
	if ci.Arity == 1 {
		return "one argument"
	}
	return fmt.Sprintf("%d arguments written as a tuple, e.g. `%s (a, b, ...)`", ci.Arity, ci.Name)
}

func (i *inferer) lookupCon(env *Env, name string, sp syntax.Span) *ConInfo {
	ci, ok := env.Cons[name]
	if !ok {
		names := make([]string, 0, len(env.Cons))
		for n := range env.Cons {
			names = append(names, n)
		}
		sort.Strings(names)
		d := syntax.Errorf("type", sp, "unknown constructor `%s`", name)
		d.Label = "no type declares a constructor with this name"
		if s := suggest(name, names); s != "" {
			d.Notes = append(d.Notes, fmt.Sprintf("did you mean `%s`?", s))
		}
		i.fail(d)
	}
	return ci
}

func (i *inferer) inferApp(env *Env, x *syntax.EApp) Type {
	tf := i.infer(env, x.Fn)
	switch f := Prune(tf).(type) {
	case *TCon:
		if f.Head != HArrow {
			name, n := headName(x.Fn)
			d := syntax.Errorf("type", x.Fn.ESpan(), "this expression has type `%s`, so it cannot be applied to an argument", TypeString(tf))
			d.Label = "not a function"
			if name != "" && n > 0 {
				d.Notes = append(d.Notes, fmt.Sprintf("`%s` takes fewer arguments than it was given", name))
			}
			i.fail(d)
		}
		ta := i.infer(env, x.Arg)
		name, n := headName(x.Fn)
		note := ""
		if sc, ok := env.Lookup(name); name != "" && ok && n+1 > schemeArity(sc.Type) {
			name = "" // the head's own type has fewer parameters: this argument belongs to a returned function
		}
		if name != "" {
			if isOperatorName(name) {
				note = fmt.Sprintf("operand %d of `%s`", n+1, name)
			} else {
				note = fmt.Sprintf("argument %d of `%s`", n+1, name)
			}
		}
		i.unifyAt(x.Arg.ESpan(), f.Args[0], ta, note)
		return f.Args[1]
	case *TVar:
		ta := i.infer(env, x.Arg)
		res := Type(i.newVar())
		i.unifyAt(x.Sp, tf, Arrow(ta, res), "")
		return res
	}
	panic("unreachable")
}

// ---------- let ----------

func (i *inferer) inferLet(env *Env, x *syntax.ELet) Type {
	cur := i.inferBindings(env, x.Rec, x.Bindings, nil)
	return i.infer(cur, x.Body)
}

// inferBindings types a group of bindings and returns env extended with their names. When out != nil
// it receives the new names in order.
func (i *inferer) inferBindings(env *Env, rec bool, bs []*syntax.Binding, out *[]Bound) *Env {
	type pending struct {
		b     *syntax.Binding
		t     Type
		binds []bind
	}
	var ps []pending
	i.enter()
	recEnv := env
	if rec {
		for _, b := range bs {
			pv := b.Pat.(*syntax.PVar)
			if _, ok := unwrapAnnot(b.Expr).(*syntax.EFun); !ok {
				i.leave()
				i.fail(syntax.Errorf("type", b.Expr.ESpan(), "the right-hand side of `let rec` must be a function (`fun ... ->`)"))
			}
			tv := Type(i.newVar())
			ps = append(ps, pending{b: b, t: tv, binds: []bind{{pv.Name, tv, pv.Sp}}})
			recEnv = recEnv.Extend(pv.Name, &Scheme{Type: tv})
		}
		for _, p := range ps {
			t := i.infer(recEnv, p.b.Expr)
			i.unifyAt(p.b.Expr.ESpan(), p.t, t, "")
		}
	} else {
		for _, b := range bs {
			t := i.infer(env, b.Expr)
			binds := i.inferPat(env, b.Pat, t, nil)
			ps = append(ps, pending{b: b, t: t, binds: binds})
		}
	}
	i.leave()
	cur := env
	seen := map[string]bool{}
	for _, p := range ps {
		gen := rec || nonExpansive(p.b.Expr)
		for _, bd := range p.binds {
			if seen[bd.name] {
				i.fail(syntax.Errorf("type", bd.sp, "`%s` is bound twice in the same `let ... and ...`", bd.name))
			}
			seen[bd.name] = true
			if gen {
				i.generalize(bd.t)
				if i.tr != nil {
					i.tr.generalize(i.depth, bd.name, bd.t)
				}
			} else {
				i.weaken(bd.t)
			}
			sc := &Scheme{Type: bd.t}
			cur = cur.Extend(bd.name, sc)
			if out != nil {
				*out = append(*out, Bound{bd.name, sc})
			}
		}
	}
	return cur
}

// ---------- patterns ----------

type bind struct {
	name string
	t    Type
	sp   syntax.Span
}

func (i *inferer) addBind(binds []bind, b bind) []bind {
	for _, o := range binds {
		if o.name == b.name {
			i.fail(syntax.Errorf("type", b.sp, "variable `%s` is bound more than once in this pattern", b.name))
		}
	}
	return append(binds, b)
}

func (i *inferer) inferPat(env *Env, p syntax.Pat, expected Type, binds []bind) []bind {
	switch x := p.(type) {
	case *syntax.PWild:
		return binds
	case *syntax.PVar:
		return i.addBind(binds, bind{x.Name, expected, x.Sp})
	case *syntax.PInt:
		i.unifyAt(x.Sp, expected, TInt, "")
	case *syntax.PStr:
		i.unifyAt(x.Sp, expected, TString, "")
	case *syntax.PBool:
		i.unifyAt(x.Sp, expected, TBool, "")
	case *syntax.PUnit:
		i.unifyAt(x.Sp, expected, TUnit, "")
	case *syntax.PTuple:
		vs := make([]Type, len(x.Elems))
		for k := range vs {
			vs[k] = i.newVar()
		}
		i.unifyAt(x.Sp, expected, Tuple(vs), "this is a tuple pattern with "+fmt.Sprint(len(vs))+" components")
		for k, el := range x.Elems {
			binds = i.inferPat(env, el, vs[k], binds)
		}
	case *syntax.PCon:
		ci := i.lookupCon(env, x.Name, x.Sp)
		t := i.instantiate(ci.Scheme.Type, map[*TVar]Type{})
		if ci.Arity == 0 {
			if x.Arg != nil {
				i.fail(syntax.Errorf("type", x.Arg.PSpan(), "constructor `%s` takes no argument", x.Name))
			}
			i.unifyAt(x.Sp, expected, t, "")
			return binds
		}
		fn := Prune(t).(*TCon)
		if x.Arg == nil {
			d := syntax.Errorf("type", x.Sp, "constructor `%s` expects %s in a pattern", x.Name, payloadDesc(ci))
			d.Notes = append(d.Notes, fmt.Sprintf("write `%s _` to ignore the payload", x.Name))
			i.fail(d)
		}
		i.unifyAt(x.Sp, expected, fn.Args[1], "")
		binds = i.inferPat(env, x.Arg, fn.Args[0], binds)
	case *syntax.PRecord:
		seen := map[string]bool{}
		fts := make([]Type, len(x.Fields))
		for k, f := range x.Fields {
			if seen[f.Name] {
				i.fail(syntax.Errorf("type", f.Sp, "field `%s` appears twice in this pattern", f.Name))
			}
			seen[f.Name] = true
			fts[k] = i.newVar()
		}
		var row Type = i.newVar() // open: the matched record may have other fields
		for k := len(x.Fields) - 1; k >= 0; k-- {
			row = RowExt(x.Fields[k].Name, fts[k], row)
		}
		i.unifyAt(x.Sp, expected, RecordOf(row), "a record pattern matches any record that has at least these fields")
		for k, f := range x.Fields {
			binds = i.inferPat(env, f.Pat, fts[k], binds)
		}
	case *syntax.POr:
		l := i.inferPat(env, x.L, expected, nil)
		r := i.inferPat(env, x.R, expected, nil)
		for _, lb := range l {
			found := false
			for _, rb := range r {
				if rb.name == lb.name {
					found = true
					i.unifyAt(rb.sp, lb.t, rb.t, "the variable `"+lb.name+"` must have the same type on both sides of `|`")
				}
			}
			if !found {
				i.fail(syntax.Errorf("type", x.Sp, "variable `%s` is bound on the left of `|` but not on the right", lb.name))
			}
		}
		for _, rb := range r {
			found := false
			for _, lb := range l {
				if lb.name == rb.name {
					found = true
				}
			}
			if !found {
				i.fail(syntax.Errorf("type", x.Sp, "variable `%s` is bound on the right of `|` but not on the left", rb.name))
			}
		}
		for _, lb := range l {
			binds = i.addBind(binds, lb)
		}
	case *syntax.PAs:
		binds = i.inferPat(env, x.P, expected, binds)
		binds = i.addBind(binds, bind{x.Name, expected, x.Sp})
	case *syntax.PAnnot:
		at := i.convType(x.Ty, i.annotScope())
		i.unifyAt(x.Sp, at, expected, "")
		binds = i.inferPat(env, x.P, at, binds)
	default:
		panic(fmt.Sprintf("inferPat: unhandled %T", p))
	}
	return binds
}
