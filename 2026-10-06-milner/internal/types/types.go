// Package types implements Hindley–Milner type inference for Milner ML.
package types

import (
	"sort"
	"strings"
)

// Generic is the level marking a quantified (generalised) variable.
const Generic = 1 << 30

// Type is a TVar, *TCon.
type Type interface{}

// TVar is a unification variable. Ref != nil once bound.
type TVar struct {
	ID    int
	Ref   Type
	Level int
}

// Head identifies a type constructor by identity (so redefining `type t` makes a distinct type).
type Head struct {
	Name  string
	Arity int // -1 for tuples (any arity)
	Label string
	Row   bool // a row constructor: HRowEmpty, or a field extension (Label: t, rest)
}

// TCon is an applied type constructor.
type TCon struct {
	Head *Head
	Args []Type
}

// Built-in heads.
var (
	HArrow  = &Head{Name: "->", Arity: 2}
	HTuple  = &Head{Name: "*", Arity: -1}
	HInt    = &Head{Name: "int", Arity: 0}
	HBool   = &Head{Name: "bool", Arity: 0}
	HString = &Head{Name: "string", Arity: 0}
	HUnit   = &Head{Name: "unit", Arity: 0}
	HList   = &Head{Name: "list", Arity: 1}
	HRef    = &Head{Name: "ref", Arity: 1}
	HOption = &Head{Name: "option", Arity: 1}

	// Records: `{x : int; y : bool}` is TCon{HRecord, [row]} where the row is built from HRowEmpty and
	// one extension head per label. An unresolved row variable at the end makes the record open.
	HRecord   = &Head{Name: "record", Arity: 1}
	HRowEmpty = &Head{Name: "{}", Arity: 0, Row: true}
)

var labelHeads = map[string]*Head{}

// LabelHead returns the (unique) row-extension head for a field label.
func LabelHead(label string) *Head {
	if h, ok := labelHeads[label]; ok {
		return h
	}
	h := &Head{Name: "." + label, Arity: 2, Label: label, Row: true}
	labelHeads[label] = h
	return h
}

// RowExt builds the row `label : t | rest`.
func RowExt(label string, t, rest Type) Type {
	return &TCon{Head: LabelHead(label), Args: []Type{t, rest}}
}

// RecordOf wraps a row as a record type.
func RecordOf(row Type) Type { return &TCon{Head: HRecord, Args: []Type{row}} }

var (
	TInt    Type = &TCon{Head: HInt}
	TBool   Type = &TCon{Head: HBool}
	TString Type = &TCon{Head: HString}
	TUnit   Type = &TCon{Head: HUnit}
)

func Arrow(a, b Type) Type { return &TCon{Head: HArrow, Args: []Type{a, b}} }
func Tuple(ts []Type) Type { return &TCon{Head: HTuple, Args: ts} }
func ListOf(t Type) Type   { return &TCon{Head: HList, Args: []Type{t}} }

// Prune follows bound variables.
func Prune(t Type) Type {
	for {
		v, ok := t.(*TVar)
		if !ok || v.Ref == nil {
			return t
		}
		// path compression
		if w, ok := v.Ref.(*TVar); ok && w.Ref != nil {
			v.Ref = w.Ref
		}
		t = v.Ref
	}
}

// Scheme is a possibly polymorphic type: generic variables (Level == Generic) are quantified.
type Scheme struct {
	Type Type
}

// TypeInfo describes a declared algebraic data type.
type TypeInfo struct {
	Head   *Head
	Params int
	Cons   []*ConInfo
	// Alias types (`type 'a pair = 'a * 'a`) are expanded wherever they are used: AliasVars are the
	// generic parameter variables and AliasBody the type they occur in.
	IsAlias   bool
	AliasVars []*TVar
	AliasBody Type
}

// ConInfo describes a data constructor.
type ConInfo struct {
	Name   string
	Type   *TypeInfo
	Arity  int     // number of declared arguments (0 = nullary)
	Scheme *Scheme // nullary: the result type; otherwise `payload -> result` (payload is a tuple when Arity > 1)
	Index  int
}

type vnode struct {
	name string
	sc   *Scheme
	next *vnode
}

// Env is a persistent typing environment.
type Env struct {
	vars  *vnode
	Types map[string]*TypeInfo
	Cons  map[string]*ConInfo
}

// Lookup finds a variable's scheme.
func (e *Env) Lookup(name string) (*Scheme, bool) {
	for n := e.vars; n != nil; n = n.next {
		if n.name == name {
			return n.sc, true
		}
	}
	return nil, false
}

// Extend returns a copy of e with name bound (maps are shared: only type declarations copy them).
func (e *Env) Extend(name string, sc *Scheme) *Env {
	return &Env{vars: &vnode{name, sc, e.vars}, Types: e.Types, Cons: e.Cons}
}

// VisibleNames returns the distinct names in scope (for "did you mean" and holes).
func (e *Env) VisibleNames() []string {
	seen := map[string]bool{}
	var out []string
	for n := e.vars; n != nil; n = n.next {
		if !seen[n.name] {
			seen[n.name] = true
			out = append(out, n.name)
		}
	}
	sort.Strings(out)
	return out
}

func (e *Env) withTypes(types map[string]*TypeInfo, cons map[string]*ConInfo) *Env {
	return &Env{vars: e.vars, Types: types, Cons: cons}
}

// NamesSince lists the names bound in e after base (most recent first, shadowed duplicates removed).
func (e *Env) NamesSince(base *Env) []string {
	seen := map[string]bool{}
	var out []string
	for n := e.vars; n != nil && n != base.vars; n = n.next {
		if !seen[n.name] && !strings.HasPrefix(n.name, "$") {
			seen[n.name] = true
			out = append(out, n.name)
		}
	}
	return out
}
