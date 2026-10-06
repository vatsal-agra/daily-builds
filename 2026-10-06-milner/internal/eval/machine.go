package eval

import (
	"fmt"
	"io"

	"milner/internal/syntax"
)

// Machine executes compiled nodes.
type Machine struct {
	Out      io.Writer
	MaxDepth int   // maximum non-tail recursion depth (default 400000)
	MaxSteps int64 // 0 = unlimited
	depth    int
	steps    int64
	cmpOps   int
	scratch  []Value // reusable pattern-slot buffer (slots are copied into the environment right after a match)
	loc      syntax.Span
}

// NewMachine returns a machine writing program output to out.
func NewMachine(out io.Writer) *Machine {
	return &Machine{Out: out, MaxDepth: 400000}
}

func (m *Machine) fail(format string, a ...any) {
	panic(&RuntimeError{Msg: fmt.Sprintf(format, a...), Span: m.loc})
}

// Run evaluates n at the top level, converting runtime panics to an error.
func (m *Machine) Run(n node) (v Value, err *RuntimeError) {
	m.depth = 0
	m.steps = 0
	defer func() {
		if r := recover(); r != nil {
			if re, ok := r.(*RuntimeError); ok {
				err = re
				return
			}
			panic(r)
		}
	}()
	return m.eval(n, nil), nil
}

func (m *Machine) eval(n node, env *Env) Value {
	m.depth++
	if m.depth > m.MaxDepth {
		m.fail("stack overflow: recursion deeper than %d calls (is a recursive call missing a base case, or not in tail position?)", m.MaxDepth)
	}
	v := m.loop(n, env)
	m.depth--
	return v
}

func (m *Machine) lookup(env *Env, idx int) Value {
	for ; idx > 0; idx-- {
		env = env.next
	}
	return env.val
}

func (m *Machine) loop(n node, env *Env) Value {
	for {
		if m.MaxSteps > 0 {
			m.steps++
			if m.steps > m.MaxSteps {
				m.fail("step limit of %d exceeded (possible infinite loop)", m.MaxSteps)
			}
		}
		switch x := n.(type) {
		case *nConst:
			return x.V
		case *nLocal:
			return m.lookup(env, x.Idx)
		case *nGlobal:
			return x.C.V
		case *nFun:
			return &Closure{Fn: x.F, Env: env}
		case *nTuple:
			elems := make([]Value, len(x.Elems))
			for i, e := range x.Elems {
				elems[i] = m.eval(e, env)
			}
			return &Tuple{Elems: elems}
		case *nCon:
			return &Con{Name: x.Name, Idx: x.Idx, Arg: m.eval(x.Arg, env)}
		case *nSeq:
			m.eval(x.A, env)
			n = x.B
		case *nAnd:
			if !m.eval(x.L, env).(bool) {
				return false
			}
			n = x.R
		case *nOr:
			if m.eval(x.L, env).(bool) {
				return true
			}
			n = x.R
		case *nIf:
			if m.eval(x.C, env).(bool) {
				n = x.T
			} else {
				n = x.E
			}
		case *nLet:
			n, env = m.doLet(x, env)
		case *nMatch:
			n, env = m.doMatch(x, env)
		case *nApp:
			var v Value
			var done bool
			n, env, v, done = m.doApp(x, env)
			if done {
				return v
			}
		default:
			panic(fmt.Sprintf("eval: unknown node %T", n))
		}
	}
}

func (m *Machine) bindParams(c *Closure, args []Value) *Env {
	env := c.Env
	if c.Fn.Simple {
		for _, a := range args {
			env = &Env{val: a, next: env}
		}
		return env
	}
	for i := range c.Fn.Params {
		p := &c.Fn.Params[i]
		slots := m.slotBuf(p.nslots())
		if !matchPat(p, args[i], slots) {
			m.loc = c.Fn.Sp
			m.fail("Match_failure: function parameter pattern did not match the value %s", Show(args[i]))
		}
		for _, s := range slots {
			env = &Env{val: s, next: env}
		}
	}
	return env
}

func (m *Machine) bindIrrefutable(p *cPat, v Value, env *Env, _ *nLet) *Env {
	if p.Kind == pkVar {
		return &Env{val: v, next: env}
	}
	var slots []Value
	if k := p.nslots(); k > 0 {
		slots = make([]Value, k)
	}
	if !matchPat(p, v, slots) {
		m.fail("Match_failure: let-pattern did not match the value %s", Show(v))
	}
	for _, s := range slots {
		env = &Env{val: s, next: env}
	}
	return env
}

// Steps returns the number of evaluation steps taken by the last top-level run.
func (m *Machine) Steps() int64 { return m.steps }

// Apply calls a function value with arguments (used by the top level and builtins).
func (m *Machine) Apply(f Value, args ...Value) Value {
	return m.eval(&nApp{Fn: &nConst{V: f}, Args: constNodes(args)}, nil)
}

func constNodes(vs []Value) []node {
	ns := make([]node, len(vs))
	for i, v := range vs {
		ns[i] = &nConst{V: v}
	}
	return ns
}

func matchPat(p *cPat, v Value, slots []Value) bool {
	switch p.Kind {
	case pkWild:
		return true
	case pkVar:
		slots[p.Slot] = v
		return true
	case pkInt:
		return v.(int64) == p.Int
	case pkStr:
		return v.(string) == p.Str
	case pkBool:
		return v.(bool) == p.Bool
	case pkUnit:
		return true
	case pkTuple:
		t := v.(*Tuple)
		for i := range p.Subs {
			if !matchPat(&p.Subs[i], t.Elems[i], slots) {
				return false
			}
		}
		return true
	case pkCon:
		c := v.(*Con)
		if c.Idx != p.Idx {
			return false
		}
		if len(p.Subs) == 1 {
			return matchPat(&p.Subs[0], c.Arg, slots)
		}
		return true
	case pkOr:
		if matchPat(&p.Subs[0], v, slots) {
			return true
		}
		return matchPat(&p.Subs[1], v, slots)
	case pkAs:
		if !matchPat(&p.Subs[0], v, slots) {
			return false
		}
		slots[p.Slot] = v
		return true
	}
	panic("matchPat: bad pattern kind")
}

func (m *Machine) doLet(x *nLet, env *Env) (node, *Env) {
	if x.Rec {
		cells := make([]*Env, len(x.Binds))
		for i := range x.Binds {
			env = &Env{next: env}
			cells[i] = env
		}
		for i, b := range x.Binds {
			cells[i].val = m.eval(b.E, env)
		}
	} else {
		vals := make([]Value, len(x.Binds))
		for i, b := range x.Binds {
			vals[i] = m.eval(b.E, env)
		}
		for i := range x.Binds {
			env = m.bindIrrefutable(&x.Binds[i].Pat, vals[i], env, x)
		}
	}
	return x.Body, env
}

// slotBuf returns a scratch slice of k slots. It is only valid until the next call: callers copy the
// values into the environment immediately after matching and never evaluate in between.
func (m *Machine) slotBuf(k int) []Value {
	if k == 0 {
		return nil
	}
	if cap(m.scratch) < k {
		m.scratch = make([]Value, k+8)
	}
	return m.scratch[:k]
}

func (m *Machine) doMatch(x *nMatch, env *Env) (node, *Env) {
	v := m.eval(x.Scrut, env)
	for i := range x.Arms {
		arm := &x.Arms[i]
		slots := m.slotBuf(arm.Pat.nslots())
		if !matchPat(&arm.Pat, v, slots) {
			continue
		}
		ne := env
		for _, s := range slots {
			ne = &Env{val: s, next: ne}
		}
		if arm.Guard != nil && !m.eval(arm.Guard, ne).(bool) {
			continue
		}
		return arm.Body, ne
	}
	m.loc = x.Sp
	m.fail("Match_failure: no pattern matched the value %s", Show(v))
	return nil, nil
}

// doApp evaluates a call. For a saturated call of a user closure it returns the closure body and its
// new environment so the caller's loop continues there (a proper tail call); otherwise done is true.
func (m *Machine) doApp(x *nApp, env *Env) (n node, ne *Env, result Value, done bool) {
	f := m.eval(x.Fn, env)
	args := make([]Value, len(x.Args))
	for i, a := range x.Args {
		args[i] = m.eval(a, env)
	}
	m.loc = x.Sp
	for {
		switch fv := f.(type) {
		case *Closure:
			k := len(fv.Fn.Params)
			if len(args) < k {
				return nil, nil, &PAP{Fn: fv, Args: args}, true
			}
			newEnv := m.bindParams(fv, args[:k])
			if len(args) == k {
				return fv.Fn.Body, newEnv, nil, false
			}
			f = m.eval(fv.Fn.Body, newEnv)
			args = args[k:]
		case *PAP:
			all := make([]Value, 0, len(fv.Args)+len(args))
			all = append(all, fv.Args...)
			all = append(all, args...)
			f, args = fv.Fn, all
		case *Builtin:
			if len(args) < fv.Arity {
				return nil, nil, &PAP{Fn: fv, Args: args}, true
			}
			r := fv.Fn(m, args[:fv.Arity])
			if len(args) == fv.Arity {
				return nil, nil, r, true
			}
			f, args = r, args[fv.Arity:]
		case *ConFn:
			r := &Con{Name: fv.Name, Idx: fv.Idx, Arg: args[0]}
			if len(args) == 1 {
				return nil, nil, r, true
			}
			f, args = r, args[1:]
		default:
			m.fail("internal error: applying a non-function %s", Show(f))
		}
	}
}
