package main

import (
	"runtime"
	"strings"
)

const (
	ctlNone = iota
	ctlConj
	ctlTrue
	ctlFail
	ctlCut
	ctlDisj
	ctlIf
	ctlSoft
	ctlNot
	ctlCall
	ctlCatch
	ctlOnce
	ctlIgnore
	ctlForall
	ctlFindall
	ctlColon
)

func nextMatch(cl []*Clause, from int, key argKey) int {
	for i := from; i < len(cl); i++ {
		c := cl[i]
		if !c.erased && key.matches(c.key) {
			return i
		}
	}
	return -1
}

type Query struct {
	m       *Machine
	base    int
	goal    Term
	started bool
	done    bool
}

func (m *Machine) newQuery(goal Term) *Query {
	return &Query{m: m, base: len(m.cps), goal: wrapVarGoals(goal)}
}

func (q *Query) next() (bool, error) {
	m := q.m
	if q.done {
		return false, nil
	}
	saved := m.cont
	savedDepth := m.depth
	defer func() { m.cont = saved; m.depth = savedDepth }()
	if !q.started {
		q.started = true
		m.pushCP(ChoicePoint{kind: cpBarrier})
		m.cont = &Frame{goal: q.goal, cutB: len(m.cps), next: m.stopFrame}
	} else {
		if !m.backtrack(q.base) {
			q.done = true
			return false, nil
		}
	}
	ok, err := m.run(q.base)
	if !ok || err != nil {
		q.done = true
	}
	return ok, err
}

func (q *Query) close() {
	if q.started && !q.done {
		q.m.setCPs(q.base)
	}
	q.done = true
}

// solveOnce runs goal once, keeping its bindings on success.
func (m *Machine) solveOnce(goal Term) (bool, error) {
	q := m.newQuery(goal)
	ok, err := q.next()
	q.close()
	return ok, err
}

func (m *Machine) run(base int) (bool, error) {
	for {
		fr := m.cont
		if fr == m.stopFrame {
			return true, nil
		}
		m.cont = fr.next
		ok, err := m.exec(fr)
		if err != nil {
			if !m.handleError(err, base) {
				return false, err
			}
			continue
		}
		if !ok {
			if !m.backtrack(base) {
				return false, nil
			}
		}
	}
}

func (m *Machine) handleError(err error, base int) bool {
	pe, ok := err.(*PrologError)
	if !ok {
		m.setCPs(base)
		return false
	}
	for len(m.cps) > base+1 {
		n := len(m.cps)
		cp := m.cps[n-1]
		m.setCPs(n - 1)
		if cp.kind == cpCatch && cp.active {
			m.undoTrail(cp.trailTop)
			mark := len(m.trail)
			if m.unify(cp.catcher, pe.Ball) {
				m.cont = &Frame{goal: cp.recovery, cutB: cp.cutB, next: cp.cont}
				return true
			}
			m.undoTrail(mark)
		}
	}
	if len(m.cps) > base {
		m.undoTrail(m.cps[base].trailTop)
	}
	m.setCPs(base)
	return false
}

func (m *Machine) backtrack(base int) bool {
	for {
		n := len(m.cps)
		cp := &m.cps[n-1]
		m.undoTrail(cp.trailTop)
		switch cp.kind {
		case cpBarrier:
			m.setCPs(n - 1)
			return false
		case cpGoal:
			m.cont = cp.alt
			m.setCPs(n - 1)
			return true
		case cpCatch, cpDead:
			m.setCPs(n - 1)
		case cpAlts:
			pat, sol := cp.pat, cp.sols[cp.idx]
			cont := cp.cont
			cp.idx++
			if cp.idx >= len(cp.sols) {
				m.setCPs(n - 1)
			}
			if m.unify(pat, sol) {
				m.cont = cont
				return true
			}
		case cpClauses:
			c := cp.clauses[cp.idx]
			args, cont, dep, p := cp.args, cp.cont, cp.dep, cp.pred
			j := nextMatch(cp.clauses, cp.idx+1, cp.key)
			if j < 0 {
				m.setCPs(n - 1)
			} else {
				cp.idx = j
			}
			if m.tracing {
				m.tracePort("Redo", p, args, dep)
			}
			if m.tryClause(c, args, cont, n-1, dep) {
				return true
			}
			if m.tracing && j < 0 {
				m.tracePort("Fail", p, args, dep)
			}
		}
	}
}

func (m *Machine) tryClause(c *Clause, args []Term, next *Frame, cutB int, dep int) bool {
	vars := make([]Term, c.nvars)
	if hc, ok := c.head.(*Compound); ok {
		for i, p := range hc.Args {
			if !m.unifyHead(p, args[i], vars) {
				return false
			}
		}
	}
	cont := next
	for i := len(c.body) - 1; i >= 0; i-- {
		cont = &Frame{goal: m.rename(c.body[i], vars), cutB: cutB, next: cont, dep: dep}
	}
	m.cont = cont
	return true
}

var memLimit uint64 = 1 << 30

var memThresh = memLimit

func (m *Machine) checkMemory() error {
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	if ms.HeapAlloc > memThresh {
		runtime.GC()
		runtime.ReadMemStats(&ms)
		if ms.HeapAlloc > memLimit {
			memThresh = memLimit
			return throwTerm(mk("resource_error", mkAtom("stack")), nil)
		}
		memThresh = max(memLimit, ms.HeapAlloc*2)
	}
	return nil
}

func (m *Machine) exec(fr *Frame) (bool, error) {
	switch fr.op {
	case opGoal:
	case opCutTo:
		m.setCPs(fr.n)
		return true, nil
	case opCutFail:
		m.setCPs(fr.n)
		return false, nil
	case opSoftCut:
		m.cps[fr.n].kind = cpDead
		return true, nil
	case opCatchExit:
		b := fr.n
		if len(m.cps)-1 == b {
			m.setCPs(b)
		} else {
			id := m.cps[b].id
			m.cps[b].active = false
			m.pushUndo(func() {
				if b < len(m.cps) && m.cps[b].kind == cpCatch && m.cps[b].id == id {
					m.cps[b].active = true
				}
			})
		}
		return true, nil
	case opTraceExit:
		m.tracePort("Exit", nil, []Term{fr.goal}, fr.dep)
		return true, nil
	}
	goal := deref(fr.goal)
	var name *Atom
	var args []Term
	switch g := goal.(type) {
	case *Atom:
		name = g
	case *Compound:
		name, args = g.Fn, g.Args
	case *Var:
		return false, instErr()
	default:
		return false, typeErr("callable", goal)
	}
	m.infer++
	if m.infer&(1<<22-1) == 0 {
		if err := m.checkMemory(); err != nil {
			return false, err
		}
	}
	var p *Pred
	if len(args) < len(name.preds) {
		p = name.preds[len(args)]
	}
	if p == nil || (!p.defined && !p.dynamic && p.det == nil && p.nondet == nil && p.ctl == 0) {
		if m.flags["unknown"] == "fail" {
			return false, nil
		}
		return false, &PrologError{Ball: &Compound{Fn: atError, Args: []Term{
			mk("existence_error", mkAtom("procedure"), pi(name, len(args))), pi(name, len(args))}}}
	}
	switch {
	case p.ctl != 0:
		return m.control(p.ctl, args, fr)
	case p.det != nil:
		return p.det(m, args)
	case p.nondet != nil:
		pat, sols, err := p.nondet(m, args)
		if err != nil || len(sols) == 0 {
			return false, err
		}
		if len(sols) > 1 {
			m.pushCP(ChoicePoint{kind: cpAlts, cont: m.cont, pat: pat, sols: sols, idx: 1})
		}
		return m.unify(pat, sols[0]), nil
	}
	if m.tracing {
		return m.callTraced(p, args, fr)
	}
	return m.callPred(p, args, fr)
}

func (m *Machine) callPred(p *Pred, args []Term, fr *Frame) (bool, error) {
	clauses := p.clauses
	var key argKey
	if len(args) > 0 {
		key = keyOf(deref(args[0]))
	}
	i := nextMatch(clauses, 0, key)
	if i < 0 {
		return false, nil
	}
	j := nextMatch(clauses, i+1, key)
	b := len(m.cps)
	if j >= 0 {
		m.pushCP(ChoicePoint{kind: cpClauses, cont: m.cont, args: args, clauses: clauses, idx: j, key: key, pred: p, dep: fr.dep + 1})
	}
	return m.tryClause(clauses[i], args, m.cont, b, fr.dep+1), nil
}

func addArgs(goal Term, extra []Term) (Term, error) {
	goal = deref(goal)
	for {
		if c, ok := goal.(*Compound); ok && c.Fn == atColon && len(c.Args) == 2 {
			goal = deref(c.Args[1])
			continue
		}
		break
	}
	if len(extra) == 0 {
		return goal, nil
	}
	switch g := goal.(type) {
	case *Atom:
		return &Compound{Fn: g, Args: append([]Term(nil), extra...)}, nil
	case *Compound:
		na := make([]Term, 0, len(g.Args)+len(extra))
		na = append(na, g.Args...)
		na = append(na, extra...)
		return &Compound{Fn: g.Fn, Args: na}, nil
	case *Var:
		return nil, instErr()
	}
	return nil, typeErr("callable", goal)
}

func (m *Machine) ite(cond, then, els Term, fr *Frame, soft bool) {
	cond = wrapVarGoals(cond)
	b := len(m.cps)
	m.pushCP(ChoicePoint{kind: cpGoal, alt: &Frame{goal: els, cutB: fr.cutB, next: m.cont, dep: fr.dep}})
	op := uint8(opCutTo)
	if soft {
		op = opSoftCut
	}
	m.cont = &Frame{goal: cond, cutB: b + 1, dep: fr.dep, next: &Frame{op: op, n: b,
		next: &Frame{goal: then, cutB: fr.cutB, next: m.cont, dep: fr.dep}}}
}

func (m *Machine) control(id int, args []Term, fr *Frame) (bool, error) {
	switch id {
	case ctlTrue:
		return true, nil
	case ctlFail:
		return false, nil
	case ctlConj:
		m.cont = &Frame{goal: args[0], cutB: fr.cutB, dep: fr.dep, next: &Frame{goal: args[1], cutB: fr.cutB, dep: fr.dep, next: m.cont}}
		return true, nil
	case ctlCut:
		m.setCPs(fr.cutB)
		return true, nil
	case ctlDisj:
		l := deref(args[0])
		if c, ok := l.(*Compound); ok && len(c.Args) == 2 {
			if c.Fn == atArrow {
				m.ite(c.Args[0], c.Args[1], args[1], fr, false)
				return true, nil
			}
			if c.Fn == atSoft {
				m.ite(c.Args[0], c.Args[1], args[1], fr, true)
				return true, nil
			}
		}
		m.pushCP(ChoicePoint{kind: cpGoal, alt: &Frame{goal: args[1], cutB: fr.cutB, next: m.cont, dep: fr.dep}})
		m.cont = &Frame{goal: l, cutB: fr.cutB, next: m.cont, dep: fr.dep}
		return true, nil
	case ctlIf:
		m.ite(args[0], args[1], atFail, fr, false)
		return true, nil
	case ctlSoft:
		m.ite(args[0], args[1], atFail, fr, true)
		return true, nil
	case ctlNot:
		b := len(m.cps)
		m.pushCP(ChoicePoint{kind: cpGoal, alt: &Frame{goal: atTrue, next: m.cont, dep: fr.dep}})
		m.cont = &Frame{goal: args[0], cutB: b + 1, dep: fr.dep, next: &Frame{op: opCutFail, n: b}}
		return true, nil
	case ctlOnce:
		m.ite(args[0], atTrue, atFail, fr, false)
		return true, nil
	case ctlIgnore:
		m.ite(args[0], atTrue, atTrue, fr, false)
		return true, nil
	case ctlForall:
		inner := &Compound{Fn: atComma, Args: []Term{args[0], &Compound{Fn: atNot, Args: []Term{args[1]}}}}
		m.cont = &Frame{goal: &Compound{Fn: atNot, Args: []Term{inner}}, cutB: fr.cutB, next: m.cont, dep: fr.dep}
		return true, nil
	case ctlCall:
		goal, err := addArgs(args[0], args[1:])
		if err != nil {
			return false, err
		}
		if err := checkBody(goal); err != nil {
			return false, err
		}
		if _, isVar := goal.(*Var); isVar {
			return false, instErr()
		}
		goal = wrapVarGoals(goal)
		m.cont = &Frame{goal: goal, cutB: len(m.cps), next: m.cont, dep: fr.dep}
		return true, nil
	case ctlColon:
		m.cont = &Frame{goal: args[1], cutB: fr.cutB, next: m.cont, dep: fr.dep}
		return true, nil
	case ctlCatch:
		b := len(m.cps)
		m.uniq++
		m.pushCP(ChoicePoint{kind: cpCatch, cont: m.cont, catcher: args[1], recovery: args[2], cutB: fr.cutB, active: true, id: m.uniq})
		m.cont = &Frame{goal: wrapVarGoals(args[0]), cutB: b + 1, dep: fr.dep, next: &Frame{op: opCatchExit, n: b, next: m.cont}}
		return true, nil
	}
	return false, nil
}

// ---------- tracer ----------

func (m *Machine) tracePort(port string, p *Pred, args []Term, dep int) {
	var goal Term
	if p != nil {
		if len(args) == 0 {
			goal = p.name
		} else {
			goal = &Compound{Fn: p.name, Args: args}
		}
	} else {
		goal = args[0]
	}
	m.flushOut()
	s := formatTermOpts(goal, writeOpts{quoted: true, numberVars: true})
	m.errOut.WriteString("   " + port + ": " + strings.Repeat(" ", min(dep, 20)) + "(" + itoa(dep) + ") " + s + "\n")
	m.errOut.Flush()
}

func (m *Machine) callTraced(p *Pred, args []Term, fr *Frame) (bool, error) {
	var goal Term = p.name
	if len(args) > 0 {
		goal = &Compound{Fn: p.name, Args: args}
	}
	m.tracePort("Call", p, args, fr.dep+1)
	before := len(m.cps)
	_ = before
	m.cont = &Frame{op: opTraceExit, goal: goal, dep: fr.dep + 1, next: m.cont}
	ok, err := m.callPred(p, args, fr)
	if err == nil && !ok {
		// callPred failed to find a clause; unwind the exit marker
		m.tracePort("Fail", p, args, fr.dep+1)
	} else if err == nil && ok {
		// body frames were pushed in front of the exit marker by tryClause (it used m.cont as next)
	}
	return ok, err
}
