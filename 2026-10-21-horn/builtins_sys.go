package main

import (
	"fmt"
	"math"
	"math/rand"
	"os"
	"runtime"
	"strings"
	"time"
)

func (m *Machine) installSystemBuiltins() {
	m.det("throw", 1, func(m *Machine, a []Term) (bool, error) {
		b := deref(a[0])
		if _, isv := b.(*Var); isv {
			return false, instErr()
		}
		return false, &PrologError{Ball: m.copyTerm(b, map[*Var]Term{})}
	})
	m.det("halt", 0, func(m *Machine, a []Term) (bool, error) { return false, &haltSignal{0} })
	m.det("halt", 1, func(m *Machine, a []Term) (bool, error) {
		n, err := getInt(a[0])
		if err != nil {
			return false, err
		}
		return false, &haltSignal{n}
	})
	m.det("op", 3, func(m *Machine, a []Term) (bool, error) {
		p, err := getInt(a[0])
		if err != nil {
			return false, err
		}
		if p < 0 || p > 1200 {
			return false, domErr("operator_priority", a[0])
		}
		ty, err := getAtom(a[1])
		if err != nil {
			return false, err
		}
		switch ty.Name {
		case "xfx", "xfy", "yfx", "fy", "fx", "xf", "yf":
		default:
			return false, domErr("operator_specifier", ty)
		}
		var names []Term
		if n := deref(a[2]); n == Term(atNil) {
			names = nil
		} else if _, ok := isCons(n); ok {
			names, err = getList(n)
			if err != nil {
				return false, err
			}
		} else {
			names = []Term{n}
		}
		for _, n := range names {
			at, err := getAtom(n)
			if err != nil {
				return false, err
			}
			if at == atComma {
				return false, permErr("modify", "operator", at)
			}
			if at.Name == "|" && (p < 1001 && p != 0 || len(ty.Name) != 3) {
				return false, permErr("create", "operator", at)
			}
			if at == atNil || at == atCurly {
				return false, permErr("create", "operator", at)
			}
			m.ops.add(p, ty.Name, at.Name)
		}
		return true, nil
	})
	m.nondet("current_op", 3, func(m *Machine, a []Term) (Term, []Term, error) {
		if p := deref(a[0]); p != nil {
			if _, isv := p.(*Var); !isv {
				if n, ok := p.(Int); !ok || n < 0 || n > 1200 {
					return nil, nil, domErr("operator_priority", p)
				}
			}
		}
		if t := deref(a[1]); t != nil {
			if _, isv := t.(*Var); !isv {
				at, ok := t.(*Atom)
				if !ok {
					return nil, nil, domErr("operator_specifier", t)
				}
				switch at.Name {
				case "xfx", "xfy", "yfx", "fy", "fx", "xf", "yf":
				default:
					return nil, nil, domErr("operator_specifier", t)
				}
			}
		}
		var sols []Term
		add := func(name string, d *opDef) {
			if d != nil {
				sols = append(sols, mk("op", Int(d.pri), mkAtom(d.typ), mkAtom(name)))
			}
		}
		if n, ok := deref(a[2]).(*Atom); ok {
			if e := m.ops[n.Name]; e != nil {
				add(n.Name, e.prefix)
				add(n.Name, e.infix)
				add(n.Name, e.postfix)
			}
		} else {
			for name, e := range m.ops {
				add(name, e.prefix)
				add(name, e.infix)
				add(name, e.postfix)
			}
		}
		return mk("op", a[0], a[1], a[2]), sols, nil
	})
	m.det("set_prolog_flag", 2, func(m *Machine, a []Term) (bool, error) {
		f, err := getAtom(a[0])
		if err != nil {
			return false, err
		}
		v, err := getAtom(a[1])
		if err != nil {
			return false, err
		}
		switch f.Name {
		case "double_quotes":
			switch v.Name {
			case "codes", "chars", "atom", "string":
				if v.Name == "string" {
					m.flags[f.Name] = "atom"
				} else {
					m.flags[f.Name] = v.Name
				}
			default:
				return false, domErr("flag_value", v)
			}
		case "occurs_check":
			m.occursCheck = v.Name == "true" || v.Name == "error"
			m.flags[f.Name] = v.Name
		case "unknown":
			m.flags[f.Name] = v.Name
		default:
			m.flags[f.Name] = v.Name
		}
		return true, nil
	})
	m.nondet("current_prolog_flag", 2, func(m *Machine, a []Term) (Term, []Term, error) {
		var sols []Term
		for k, v := range m.flags {
			sols = append(sols, mk("f", mkAtom(k), mkAtom(v)))
		}
		sols = append(sols,
			mk("f", mkAtom("bounded"), atFalse),
			mk("f", mkAtom("max_integer"), Int(math.MaxInt64)),
			mk("f", mkAtom("min_integer"), Int(math.MinInt64)),
			mk("f", mkAtom("version"), Int(90000)),
			mk("f", mkAtom("dialect"), mkAtom("horn")),
		)
		return mk("f", a[0], a[1]), sols, nil
	})
	m.det("nb_setval", 2, func(m *Machine, a []Term) (bool, error) {
		k, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		m.globals[k] = m.copyTerm(a[1], map[*Var]Term{})
		return true, nil
	})
	m.det("b_setval", 2, func(m *Machine, a []Term) (bool, error) {
		k, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		old, had := m.globals[k]
		m.globals[k] = deref(a[1])
		m.pushUndo(func() {
			if had {
				m.globals[k] = old
			} else {
				delete(m.globals, k)
			}
		})
		return true, nil
	})
	getv := func(m *Machine, a []Term) (bool, error) {
		k, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		v, ok := m.globals[k]
		if !ok {
			return false, existErr("variable", mkAtom(k))
		}
		return m.unify(a[1], v), nil
	}
	m.det("nb_getval", 2, getv)
	m.det("b_getval", 2, getv)
	m.det("statistics", 2, func(m *Machine, a []Term) (bool, error) {
		k, err := getAtom(a[0])
		if err != nil {
			return false, err
		}
		ms := Int(time.Since(startTime).Milliseconds())
		switch k.Name {
		case "runtime", "cputime", "process_cputime", "real_time", "walltime", "system_time":
			if k.Name == "cputime" || k.Name == "process_cputime" {
				return m.unify(a[1], Float(time.Since(startTime).Seconds())), nil
			}
			return m.unify(a[1], mkList([]Term{ms, Int(0)}, atNil)), nil
		case "inferences":
			return m.unify(a[1], Int(m.infer)), nil
		case "memory", "heapused":
			var ms runtime.MemStats
			runtime.ReadMemStats(&ms)
			return m.unify(a[1], Int(ms.HeapAlloc)), nil
		}
		return false, domErr("statistics_key", k)
	})
	m.det("get_time", 1, func(m *Machine, a []Term) (bool, error) {
		return m.unify(a[0], Float(float64(time.Now().UnixNano())/1e9)), nil
	})
	m.det("sleep", 1, func(m *Machine, a []Term) (bool, error) {
		v, err := m.eval(a[0])
		if err != nil {
			return false, err
		}
		time.Sleep(time.Duration(toFloat(v) * float64(time.Second)))
		return true, nil
	})
	m.det("random", 1, func(m *Machine, a []Term) (bool, error) {
		return m.unify(a[0], Float(rand.Float64())), nil
	})
	m.det("random_between", 3, func(m *Machine, a []Term) (bool, error) {
		l, err := getInt(a[0])
		if err != nil {
			return false, err
		}
		h, err := getInt(a[1])
		if err != nil {
			return false, err
		}
		if h < l {
			return false, nil
		}
		return m.unify(a[2], Int(l+rand.Intn(h-l+1))), nil
	})
	m.det("set_random", 1, func(m *Machine, a []Term) (bool, error) {
		if c, ok := deref(a[0]).(*Compound); ok && c.Fn.Name == "seed" {
			if n, ok := deref(c.Args[0]).(Int); ok {
				rand.Seed(int64(n))
			}
		}
		return true, nil
	})
	m.det("getenv", 2, func(m *Machine, a []Term) (bool, error) {
		k, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		v, ok := os.LookupEnv(k)
		return ok && m.unify(a[1], mkAtom(v)), nil
	})
	m.det("trace", 0, func(m *Machine, a []Term) (bool, error) { m.tracing = true; return true, nil })
	m.det("notrace", 0, func(m *Machine, a []Term) (bool, error) { m.tracing = false; return true, nil })
	m.det("tracing", 0, func(m *Machine, a []Term) (bool, error) { return m.tracing, nil })
	m.det("nodebug", 0, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("debug", 0, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("style_check", 1, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("use_module", 1, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("use_module", 2, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("module", 2, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("set_stream", 2, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("prompt", 2, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("license", 1, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("initialization", 1, func(m *Machine, a []Term) (bool, error) {
		if m.loading {
			m.inits = append(m.inits, m.copyTerm(a[0], map[*Var]Term{}))
			return true, nil
		}
		return m.solveOnce(a[0])
	})
	m.det("initialization", 2, func(m *Machine, a []Term) (bool, error) {
		w, _ := deref(a[1]).(*Atom)
		g := m.copyTerm(a[0], map[*Var]Term{})
		if w != nil && w.Name == "main" {
			g = mk(",", g, mkAtom("halt"))
		}
		if m.loading {
			m.inits = append(m.inits, g)
			return true, nil
		}
		return m.solveOnce(g)
	})
	m.det("consult", 1, func(m *Machine, a []Term) (bool, error) { return true, m.consultSpec(a[0]) })
	m.det("ensure_loaded", 1, func(m *Machine, a []Term) (bool, error) { return true, m.consultSpec(a[0]) })
	m.det("$dcg_body", 4, func(m *Machine, a []Term) (bool, error) {
		t, err := m.dcgBody(a[0], a[1], a[2])
		if err != nil {
			return false, err
		}
		return m.unify(a[3], t), nil
	})
	m.det("dcg_translate_rule", 2, func(m *Machine, a []Term) (bool, error) {
		c, ok := deref(a[0]).(*Compound)
		if !ok || c.Fn != atDCG || len(c.Args) != 2 {
			return false, typeErr("dcg_rule", a[0])
		}
		t, err := m.dcgRule(c)
		if err != nil {
			return false, err
		}
		return m.unify(a[1], t), nil
	})
	m.det("print_message", 2, func(m *Machine, a []Term) (bool, error) {
		kind, _ := deref(a[0]).(*Atom)
		if kind == nil {
			return true, nil
		}
		switch kind.Name {
		case "error":
			m.printMessage("ERROR", messageText(a[1]), "")
		case "warning":
			m.printMessage("Warning", messageText(a[1]), "")
		case "informational", "silent", "debug", "help", "banner":
		}
		return true, nil
	})
	m.det("print_message_lines", 3, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("message_to_codes", 3, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("$inferences", 1, func(m *Machine, a []Term) (bool, error) { return m.unify(a[0], Int(m.infer)), nil })
	m.det("tabling_noop", 0, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("$bench_gc", 0, func(m *Machine, a []Term) (bool, error) { runtime.GC(); return true, nil })
	m.det("shell", 1, func(m *Machine, a []Term) (bool, error) { return false, permErr("execute", "shell", a[0]) })
	m.det("$write_err", 1, func(m *Machine, a []Term) (bool, error) {
		s, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		m.streamWrite(m.streams[2], s)
		return true, nil
	})
	m.det("prolog_load_context", 2, func(m *Machine, a []Term) (bool, error) {
		if k, ok := deref(a[0]).(*Atom); ok && k.Name == "source" && m.loadFile != "" {
			return m.unify(a[1], mkAtom(m.loadFile)), nil
		}
		return false, nil
	})
}

// ---------- messages ----------

func (m *Machine) printMessage(kind, text, loc string) {
	m.flushOut()
	var sb strings.Builder
	if loc != "" {
		sb.WriteString(kind + ": " + loc + ":\n")
		for _, l := range strings.Split(text, "\n") {
			sb.WriteString(kind + ":    " + l + "\n")
		}
	} else {
		for i, l := range strings.Split(text, "\n") {
			if i == 0 {
				sb.WriteString(kind + ": " + l + "\n")
			} else {
				sb.WriteString(kind + ":    " + l + "\n")
			}
		}
	}
	m.errOut.WriteString(sb.String())
	m.errOut.Flush()
}

func describeKind(t Term) string {
	switch t.(type) {
	case Int, *bigIntT:
		return "an integer"
	case Float:
		return "a float"
	case *Atom:
		return "an atom"
	case *Compound:
		return "a compound"
	case *Var:
		return "a var"
	}
	return "a term"
}

func messageText(ball Term) string {
	ball = deref(ball)
	q := func(t Term) string { return formatTermOpts(t, writeOpts{quoted: true, numberVars: true}) }
	c, ok := ball.(*Compound)
	if !ok || c.Fn != atError || len(c.Args) != 2 {
		return "Unhandled exception: Unknown message: " + q(ball)
	}
	formal := deref(c.Args[0])
	ctx := ""
	if cc, ok := deref(c.Args[1]).(*Compound); ok && cc.Fn.Name == "context" && len(cc.Args) == 2 {
		if _, isv := deref(cc.Args[0]).(*Var); !isv {
			ctx = q(cc.Args[0]) + ": "
		}
	}
	switch f := formal.(type) {
	case *Atom:
		switch f.Name {
		case "instantiation_error":
			return ctx + "Arguments are not sufficiently instantiated"
		}
	case *Compound:
		switch f.Fn.Name {
		case "existence_error":
			if len(f.Args) == 2 {
				k := formatTerm(f.Args[0], false)
				if k == "procedure" {
					return ctx + "Unknown procedure: " + q(f.Args[1])
				}
				return ctx + "Unknown " + k + ": " + q(f.Args[1])
			}
		case "type_error":
			if len(f.Args) == 2 {
				return ctx + fmt.Sprintf("Type error: `%s' expected, found `%s' (%s)", formatTerm(f.Args[0], false), q(f.Args[1]), describeKind(deref(f.Args[1])))
			}
		case "domain_error":
			if len(f.Args) == 2 {
				return ctx + fmt.Sprintf("Domain error: `%s' expected, found `%s'", formatTerm(f.Args[0], false), q(f.Args[1]))
			}
		case "evaluation_error":
			return ctx + "Arithmetic: evaluation error: " + q(f.Args[0])
		case "permission_error":
			if len(f.Args) == 3 {
				return ctx + fmt.Sprintf("No permission to %s %s `%s'", formatTerm(f.Args[0], false), formatTerm(f.Args[1], false), q(f.Args[2]))
			}
		case "representation_error":
			return ctx + "Cannot represent due to `" + q(f.Args[0]) + "'"
		case "syntax_error":
			return ctx + "Syntax error: " + formatTerm(f.Args[0], false)
		case "resource_error":
			return ctx + "Not enough resources: " + q(f.Args[0])
		case "format":
			return ctx + "Format error: " + formatTerm(f.Args[0], false)
		}
	}
	return ctx + "Unknown error term: " + q(formal)
}
