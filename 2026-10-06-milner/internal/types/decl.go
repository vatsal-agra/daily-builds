package types

import (
	"fmt"
	"sort"
	"strings"

	"milner/internal/syntax"
)

// InferDecl type-checks one top-level declaration against env. On error env is unchanged
// (including any weak type variables the failed attempt had refined).
func InferDecl(env *Env, d syntax.Decl) (res *DeclResult, err *syntax.Diag) {
	return InferDeclTrace(env, d, nil)
}

// InferDeclTrace is InferDecl with an optional trace sink.
func InferDeclTrace(env *Env, d syntax.Decl, tr *Tracer) (res *DeclResult, err *syntax.Diag) {
	in := &inferer{env: env, tyvars: map[string]Type{}, tr: tr, nextID: 1000000}
	defer func() {
		if r := recover(); r != nil {
			dg, ok := r.(*syntax.Diag)
			if !ok {
				panic(r)
			}
			in.u.undo()
			res, err = nil, dg
		}
	}()
	switch x := d.(type) {
	case *syntax.DType:
		return in.declTypes(env, x), nil
	case *syntax.DLet:
		var bound []Bound
		ne := in.inferBindings(env, x.Rec, x.Bindings, &bound)
		in.reportHoles()
		return &DeclResult{Env: ne, Bound: bound}, nil
	case *syntax.DExpr:
		in.enter()
		t := in.infer(env, x.E)
		in.leave()
		if nonExpansive(x.E) {
			in.generalize(t)
		} else {
			in.weaken(t)
		}
		in.reportHoles()
		return &DeclResult{Env: env, Expr: t}, nil
	}
	panic("unknown declaration")
}

// InferExpr types a single expression in env (no generalisation of weak vars is reported specially).
func InferExpr(env *Env, e syntax.Expr, tr *Tracer) (t Type, err *syntax.Diag) {
	r, d := InferDeclTrace(env, &syntax.DExpr{E: e, Sp: e.ESpan()}, tr)
	if d != nil {
		return nil, d
	}
	return r.Expr, nil
}

func (i *inferer) reportHoles() {
	if len(i.holes) == 0 {
		return
	}
	h := i.holes[0]
	pr := NewPrinter()
	pr.Plain = true
	d := &syntax.Diag{Kind: "hole", Span: h.sp}
	d.Msg = fmt.Sprintf("this hole `_` must be filled with a value of type `%s`", pr.String(h.t))
	d.Label = "hole"
	var cands []string
	if _, free := Prune(h.t).(*TVar); free {
		// nothing constrains the hole yet: every binding would "fit", which is not informative
		d.Notes = append(d.Notes, "nothing constrains the type of this hole yet; use it in a context that does (or annotate it)")
		i.fail(d)
	}
	for _, n := range h.env.VisibleNames() {
		if strings.HasPrefix(n, "$") {
			continue
		}
		sc, _ := h.env.Lookup(n)
		probe := &inferer{env: h.env, level: Generic - 1, nextID: 2000000}
		it := probe.instantiate(sc.Type, map[*TVar]Type{})
		ht := probe.instantiate(h.t, map[*TVar]Type{})
		if probe.u.unify(ht, it) == nil {
			cands = append(cands, fmt.Sprintf("%s : %s", n, TypeString(sc.Type)))
		}
		probe.u.undo()
	}
	sort.Strings(cands)
	if len(cands) > 8 {
		cands = append(cands[:8], "…")
	}
	if len(cands) > 0 {
		d.Notes = append(d.Notes, "bindings that could fit:\n      "+strings.Join(cands, "\n      "))
	}
	i.fail(d)
}

// ---------- type declarations ----------

func (i *inferer) declTypes(env *Env, d *syntax.DType) *DeclResult {
	types := make(map[string]*TypeInfo, len(env.Types)+len(d.Types))
	for k, v := range env.Types {
		types[k] = v
	}
	cons := make(map[string]*ConInfo, len(env.Cons))
	for k, v := range env.Cons {
		cons[k] = v
	}
	var infos []*TypeInfo
	seenT := map[string]bool{}
	for _, td := range d.Types {
		if seenT[td.Name] {
			i.fail(syntax.Errorf("type", td.Sp, "type `%s` is defined twice in this declaration", td.Name))
		}
		seenT[td.Name] = true
		seenP := map[string]bool{}
		for _, p := range td.Params {
			if seenP[p] {
				i.fail(syntax.Errorf("type", td.Sp, "type parameter '%s is repeated", p))
			}
			seenP[p] = true
		}
		info := &TypeInfo{Head: &Head{Name: td.Name, Arity: len(td.Params)}, Params: len(td.Params), IsAlias: td.Alias != nil}
		types[td.Name] = info
		infos = append(infos, info)
	}
	ne := env.withTypes(types, cons)
	i.env = ne
	i.inDecl = true
	// aliases are expanded in declaration order (before constructors that may mention them)
	for k, td := range d.Types {
		if td.Alias == nil {
			continue
		}
		info := infos[k]
		pv := map[string]Type{}
		for j, p := range td.Params {
			v := &TVar{ID: j + 1, Level: Generic}
			info.AliasVars = append(info.AliasVars, v)
			pv[p] = v
		}
		info.AliasBody = i.convType(td.Alias, func(name string, sp syntax.Span) Type {
			v, ok := pv[name]
			if !ok {
				i.fail(syntax.Errorf("type", sp, "type parameter '%s is not declared by `type ... %s`", name, td.Name))
			}
			return v
		})
	}
	seenC := map[string]bool{}
	for k, td := range d.Types {
		if td.Alias != nil {
			continue
		}
		info := infos[k]
		params := make([]Type, len(td.Params))
		pv := map[string]Type{}
		for j, p := range td.Params {
			v := &TVar{ID: j + 1, Level: Generic}
			params[j] = v
			pv[p] = v
		}
		result := Type(&TCon{Head: info.Head, Args: params})
		scope := func(name string, sp syntax.Span) Type {
			v, ok := pv[name]
			if !ok {
				i.fail(syntax.Errorf("type", sp, "type parameter '%s is not declared by `type ... %s`", name, td.Name))
			}
			return v
		}
		for ci, cd := range td.Cons {
			if seenC[cd.Name] {
				i.fail(syntax.Errorf("type", cd.Sp, "constructor `%s` is defined twice in this declaration", cd.Name))
			}
			seenC[cd.Name] = true
			if cd.Name == "::" || cd.Name == "[]" {
				i.fail(syntax.Errorf("type", cd.Sp, "`%s` is reserved for lists", cd.Name))
			}
			con := &ConInfo{Name: cd.Name, Type: info, Arity: len(cd.Args), Index: ci}
			switch len(cd.Args) {
			case 0:
				con.Scheme = &Scheme{Type: result}
			default:
				args := make([]Type, len(cd.Args))
				for a, te := range cd.Args {
					args[a] = i.convType(te, scope)
				}
				var payload Type = args[0]
				if len(args) > 1 {
					payload = Tuple(args)
				}
				con.Scheme = &Scheme{Type: Arrow(payload, result)}
			}
			info.Cons = append(info.Cons, con)
			cons[cd.Name] = con
		}
	}
	return &DeclResult{Env: ne, NewTypes: infos}
}
