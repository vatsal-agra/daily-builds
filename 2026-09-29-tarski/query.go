package main

import (
	"fmt"
	"sort"
	"strings"
)

// Answer is one row of query results, aligned with QueryResult.Vars.
type QueryResult struct {
	Vars []string
	Rows [][]Val
}

// Ask evaluates a conjunctive query against the (already evaluated) database.
func (e *Engine) Ask(q *Query) (res *QueryResult, err error) {
	defer func() {
		if r := recover(); r != nil {
			if ee, ok := r.(*EvalError); ok {
				err = ee
				return
			}
			panic(r)
		}
	}()
	var vars []string
	seen := map[string]bool{}
	for _, l := range q.Body {
		for _, v := range litVars(l) {
			if !isAnon(v) && !seen[v] {
				seen[v] = true
				vars = append(vars, v)
			}
		}
	}
	for _, l := range q.Body {
		if l.Kind != LCmp {
			if n, ok := e.Arity[l.Atom.Pred]; !ok {
				return nil, fmt.Errorf("unknown predicate %s", l.Atom.Pred)
			} else if n != len(l.Atom.Args) {
				return nil, fmt.Errorf("predicate %s has %d arguments, query uses %d", l.Atom.Pred, n, len(l.Atom.Args))
			}
		}
	}
	head := Atom{Pred: "?"}
	for _, v := range vars {
		head.Args = append(head.Args, Term{Var: true, Name: v})
	}
	fake := &Rule{Head: head, Body: q.Body, Line: q.Line}
	cr, err := compileRule(head, q.Body, fake)
	if err != nil {
		return nil, fmt.Errorf("query: %v", strings.TrimPrefix(err.Error(), fmt.Sprintf("line %d: ", q.Line)))
	}
	c := e.newCtx(cr)
	copy(c.ranges, e.fullRanges(cr))
	dup := map[string]bool{}
	res = &QueryResult{Vars: vars}
	c.emit = func(c *runCtx) {
		t := c.instantiate(cr.Head)
		k := tupleKey(t)
		if !dup[k] {
			dup[k] = true
			res.Rows = append(res.Rows, t)
		}
	}
	c.run(0)
	sort.Slice(res.Rows, func(i, j int) bool { return cmpTuple(res.Rows[i], res.Rows[j]) < 0 })
	return res, nil
}

func cmpTuple(a, b []Val) int {
	for i := range a {
		if c := a[i].Compare(b[i]); c != 0 {
			return c
		}
	}
	return 0
}

// Format renders results the way a Prolog toplevel would.
func (r *QueryResult) Format() string {
	if len(r.Vars) == 0 {
		if len(r.Rows) > 0 {
			return "true.\n"
		}
		return "false.\n"
	}
	if len(r.Rows) == 0 {
		return "no answers.\n"
	}
	var b strings.Builder
	for _, row := range r.Rows {
		parts := make([]string, len(row))
		for i, v := range row {
			parts[i] = r.Vars[i] + " = " + v.String()
		}
		b.WriteString(strings.Join(parts, ", ") + "\n")
	}
	fmt.Fprintf(&b, "(%d answer%s)\n", len(r.Rows), map[bool]string{true: "", false: "s"}[len(r.Rows) == 1])
	return b.String()
}

// Facts returns the sorted tuples of a predicate.
func (e *Engine) Facts(pred string) [][]Val {
	r := e.Rels[pred]
	if r == nil {
		return nil
	}
	out := append([][]Val(nil), r.Tuples...)
	sort.Slice(out, func(i, j int) bool { return cmpTuple(out[i], out[j]) < 0 })
	return out
}

// ParseFact parses "pred(a, 1)" (ground) into a predicate name and tuple.
func ParseFact(s string) (string, []Val, error) {
	s = strings.TrimSpace(strings.TrimSuffix(strings.TrimSpace(s), "."))
	p, err := Parse(s + ".")
	if err != nil {
		return "", nil, err
	}
	if len(p.Rules) != 1 || len(p.Rules[0].Body) != 0 {
		return "", nil, fmt.Errorf("expected a single ground fact like path(a, d)")
	}
	r := p.Rules[0]
	t := make([]Val, len(r.Head.Args))
	for i, a := range r.Head.Args {
		if a.Var || a.Agg != "" {
			return "", nil, fmt.Errorf("fact must be ground (no variables)")
		}
		t[i] = a.C
	}
	return r.Head.Pred, t, nil
}
