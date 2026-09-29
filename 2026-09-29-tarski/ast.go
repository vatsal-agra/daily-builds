package main

import (
	"fmt"
	"strconv"
	"strings"
)

// Val is a Datalog constant: a 64-bit integer or a string/symbol.
type Val struct {
	S     string
	I     int64
	IsStr bool
}

func Int(i int64) Val  { return Val{I: i} }
func Str(s string) Val { return Val{S: s, IsStr: true} }
func (v Val) String() string {
	if !v.IsStr {
		return strconv.FormatInt(v.I, 10)
	}
	if isSymbol(v.S) {
		return v.S
	}
	return strconv.Quote(v.S)
}

func isSymbol(s string) bool {
	if s == "" || s[0] < 'a' || s[0] > 'z' || s == "not" || s == "mod" {
		return false
	}
	for i := 0; i < len(s); i++ {
		c := s[i]
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_') {
			return false
		}
	}
	return true
}

// Compare orders ints before strings, then naturally.
func (v Val) Compare(o Val) int {
	if v.IsStr != o.IsStr {
		if !v.IsStr {
			return -1
		}
		return 1
	}
	if v.IsStr {
		return strings.Compare(v.S, o.S)
	}
	switch {
	case v.I < o.I:
		return -1
	case v.I > o.I:
		return 1
	}
	return 0
}

func tupleKey(t []Val) string {
	var b strings.Builder
	for _, v := range t {
		writeKey(&b, v)
	}
	return b.String()
}

func writeKey(b *strings.Builder, v Val) {
	if v.IsStr {
		b.WriteByte('s')
		b.WriteString(strconv.Itoa(len(v.S)))
		b.WriteByte(':')
		b.WriteString(v.S)
	} else {
		b.WriteByte('i')
		b.WriteString(strconv.FormatInt(v.I, 10))
		b.WriteByte(';')
	}
}

func tupleString(pred string, t []Val) string {
	if len(t) == 0 {
		return pred
	}
	parts := make([]string, len(t))
	for i, v := range t {
		parts[i] = v.String()
	}
	return pred + "(" + strings.Join(parts, ", ") + ")"
}

// Term is an atom argument: variable, constant, or (in heads) an aggregate.
type Term struct {
	Var   bool
	Name  string // variable name
	C     Val
	Agg   string // "", "count", "sum", "min", "max"
	AggOf string // aggregated variable ("" for count(*))
}

func (t Term) String() string {
	switch {
	case t.Agg != "":
		if t.AggOf == "" {
			return t.Agg + "(*)"
		}
		return t.Agg + "(" + t.AggOf + ")"
	case t.Var:
		if strings.HasPrefix(t.Name, "_#") {
			return "_"
		}
		return t.Name
	}
	return t.C.String()
}

type Atom struct {
	Pred string
	Args []Term
}

func (a Atom) String() string {
	if len(a.Args) == 0 {
		return a.Pred
	}
	parts := make([]string, len(a.Args))
	for i, t := range a.Args {
		parts[i] = t.String()
	}
	return a.Pred + "(" + strings.Join(parts, ", ") + ")"
}

// Expr is an arithmetic expression tree.
type Expr struct {
	Op   string // "" leaf, else + - * / mod
	L, R *Expr
	T    Term
}

func (e *Expr) String() string {
	if e.Op == "" {
		return e.T.String()
	}
	return "(" + e.L.String() + " " + e.Op + " " + e.R.String() + ")"
}

func (e *Expr) vars(out *[]string) {
	if e.Op == "" {
		if e.T.Var {
			*out = append(*out, e.T.Name)
		}
		return
	}
	e.L.vars(out)
	e.R.vars(out)
}

type LitKind int

const (
	LPos LitKind = iota
	LNeg
	LCmp
)

type Literal struct {
	Kind LitKind
	Atom Atom
	Op   string // = != < <= > >=
	L, R *Expr
}

func (l Literal) String() string {
	switch l.Kind {
	case LPos:
		return l.Atom.String()
	case LNeg:
		return "not " + l.Atom.String()
	}
	return fmt.Sprintf("%s %s %s", strip(l.L), l.Op, strip(l.R))
}

func strip(e *Expr) string {
	s := e.String()
	if e.Op != "" {
		return s[1 : len(s)-1]
	}
	return s
}

type Rule struct {
	Head Atom
	Body []Literal
	Line int
	Col  int
}

func (r *Rule) String() string {
	if len(r.Body) == 0 {
		return r.Head.String() + "."
	}
	parts := make([]string, len(r.Body))
	for i, l := range r.Body {
		parts[i] = l.String()
	}
	return r.Head.String() + " :- " + strings.Join(parts, ", ") + "."
}

func (r *Rule) HasAgg() bool {
	for _, t := range r.Head.Args {
		if t.Agg != "" {
			return true
		}
	}
	return false
}

type Query struct {
	Body []Literal
	Line int
}

type Program struct {
	Rules   []*Rule // includes facts (empty body)
	Queries []*Query
}
