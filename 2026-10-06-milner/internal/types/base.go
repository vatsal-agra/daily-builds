package types

import (
	"fmt"

	"milner/internal/syntax"
)

// BuiltinSigs lists the primitive values (implemented in Go by the evaluator) with their types.
var BuiltinSigs = []struct{ Name, Sig string }{
	{"+", "int -> int -> int"}, {"-", "int -> int -> int"}, {"*", "int -> int -> int"},
	{"/", "int -> int -> int"}, {"mod", "int -> int -> int"}, {"~-", "int -> int"},
	{"^", "string -> string -> string"}, {"@", "'a list -> 'a list -> 'a list"},
	{"=", "'a -> 'a -> bool"}, {"<>", "'a -> 'a -> bool"}, {"<", "'a -> 'a -> bool"},
	{">", "'a -> 'a -> bool"}, {"<=", "'a -> 'a -> bool"}, {">=", "'a -> 'a -> bool"},
	{"compare", "'a -> 'a -> int"},
	{"ref", "'a -> 'a ref"}, {"!", "'a ref -> 'a"}, {":=", "'a ref -> 'a -> unit"},
	{"print_string", "string -> unit"}, {"print_endline", "string -> unit"}, {"print_int", "int -> unit"},
	{"string_of_int", "int -> string"}, {"int_of_string_opt", "string -> int option"},
	{"string_length", "string -> int"}, {"string_sub", "string -> int -> int -> string"},
	{"string_explode", "string -> string list"}, {"char_code", "string -> int"},
	{"char_of_code", "int -> string"}, {"failwith", "string -> 'a"},
}

// NewBaseEnv returns the initial environment: built-in types, list/option constructors and
// primitive values.
func NewBaseEnv() *Env {
	env := &Env{Types: map[string]*TypeInfo{}, Cons: map[string]*ConInfo{}}
	for _, h := range []*Head{HInt, HBool, HString, HUnit, HRef} {
		env.Types[h.Name] = &TypeInfo{Head: h, Params: h.Arity}
	}
	a := &TVar{ID: 1, Level: Generic}
	list := &TypeInfo{Head: HList, Params: 1}
	la := Type(&TCon{Head: HList, Args: []Type{a}})
	list.Cons = []*ConInfo{
		{Name: "[]", Type: list, Arity: 0, Scheme: &Scheme{Type: la}, Index: 0},
		{Name: "::", Type: list, Arity: 2, Scheme: &Scheme{Type: Arrow(Tuple([]Type{a, la}), la)}, Index: 1},
	}
	env.Types["list"] = list
	opt := &TypeInfo{Head: HOption, Params: 1}
	oa := Type(&TCon{Head: HOption, Args: []Type{a}})
	opt.Cons = []*ConInfo{
		{Name: "None", Type: opt, Arity: 0, Scheme: &Scheme{Type: oa}, Index: 0},
		{Name: "Some", Type: opt, Arity: 1, Scheme: &Scheme{Type: Arrow(a, oa)}, Index: 1},
	}
	env.Types["option"] = opt
	for _, c := range list.Cons {
		env.Cons[c.Name] = c
	}
	for _, c := range opt.Cons {
		env.Cons[c.Name] = c
	}
	in := &inferer{env: env, tyvars: map[string]Type{}}
	for _, b := range BuiltinSigs {
		te, d := syntax.ParseType(b.Sig)
		if d != nil {
			panic(fmt.Sprintf("bad builtin signature for %s: %v", b.Name, d))
		}
		vars := map[string]Type{}
		t := in.convType(te, func(name string, sp syntax.Span) Type {
			if v, ok := vars[name]; ok {
				return v
			}
			v := &TVar{ID: len(vars) + 1, Level: Generic}
			vars[name] = v
			return v
		})
		env = env.Extend(b.Name, &Scheme{Type: t})
	}
	return env
}
