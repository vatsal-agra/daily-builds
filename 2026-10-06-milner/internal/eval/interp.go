package eval

import (
	"io"

	"milner/internal/syntax"
	"milner/internal/types"
)

// Interp holds the global value environment and executes declarations.
type Interp struct {
	M       *Machine
	Globals map[string]*Cell
	comp    *Compiler
}

// NewInterp creates an interpreter with the primitive builtins installed.
func NewInterp(out io.Writer) *Interp {
	in := &Interp{M: NewMachine(out), Globals: map[string]*Cell{}}
	for name, b := range Builtins() {
		in.Globals[name] = &Cell{Name: name, V: b}
	}
	in.comp = &Compiler{Globals: in.Globals}
	return in
}

// Named is a name bound by a declaration together with its value.
type Named struct {
	Name string
	V    Value
}

// Result of executing a declaration.
type Result struct {
	Bound []Named
	Value Value // for bare expressions
	IsExp bool
}

// Exec runs one type-checked declaration. cons is the constructor table after type checking it.
func (in *Interp) Exec(d syntax.Decl, cons map[string]*types.ConInfo) (res *Result, err *RuntimeError) {
	in.comp.Cons = cons
	var undo func()
	defer func() {
		if r := recover(); r != nil {
			if undo != nil {
				undo()
			}
			if re, ok := r.(*RuntimeError); ok {
				res, err = nil, re
				return
			}
			panic(r)
		}
	}()
	switch x := d.(type) {
	case *syntax.DType:
		return &Result{}, nil
	case *syntax.DExpr:
		n := in.comp.Compile(x.E)
		v, e := in.M.Run(n)
		if e != nil {
			return nil, e
		}
		return &Result{Value: v, IsExp: true}, nil
	case *syntax.DLet:
		return in.execLet(x, &undo)
	}
	panic("unknown declaration")
}

func (in *Interp) install(name string, cell *Cell, saved map[string]*Cell, had map[string]bool) {
	if _, ok := had[name]; !ok {
		old, exists := in.Globals[name]
		had[name] = exists
		saved[name] = old
	}
	in.Globals[name] = cell
}

func (in *Interp) execLet(x *syntax.DLet, undo *func()) (*Result, *RuntimeError) {
	saved := map[string]*Cell{}
	had := map[string]bool{}
	*undo = func() {
		for name, existed := range had {
			if existed {
				in.Globals[name] = saved[name]
			} else {
				delete(in.Globals, name)
			}
		}
	}
	res := &Result{}
	if x.Rec {
		cells := make([]*Cell, len(x.Bindings))
		for i, b := range x.Bindings {
			name := b.Pat.(*syntax.PVar).Name
			cells[i] = &Cell{Name: name}
			in.install(name, cells[i], saved, had)
		}
		for i, b := range x.Bindings {
			n := in.comp.Compile(b.Expr)
			v, e := in.M.Run(n)
			if e != nil {
				return nil, e
			}
			cells[i].V = v
			res.Bound = append(res.Bound, Named{cells[i].Name, v})
		}
		return res, nil
	}
	type staged struct {
		pat cPat
		val Value
		sp  syntax.Span
	}
	var sts []staged
	for _, b := range x.Bindings {
		n := in.comp.Compile(b.Expr)
		v, e := in.M.Run(n)
		if e != nil {
			return nil, e
		}
		sts = append(sts, staged{in.comp.compilePat(b.Pat), v, b.Sp})
	}
	for _, st := range sts {
		slots := make([]Value, st.pat.nslots())
		if !matchPat(&st.pat, st.val, slots) {
			return nil, &RuntimeError{Msg: "Match_failure: let-pattern did not match the value " + Show(st.val), Span: st.sp}
		}
		for i, name := range st.pat.Slots {
			cell := &Cell{Name: name, V: slots[i]}
			in.install(name, cell, saved, had)
			res.Bound = append(res.Bound, Named{name, slots[i]})
		}
	}
	return res, nil
}
