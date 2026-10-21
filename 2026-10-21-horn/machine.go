package main

import (
	"bufio"
	"math/big"
	"os"
)

type DetFn func(m *Machine, a []Term) (bool, error)
type NondetFn func(m *Machine, a []Term) (pattern Term, sols []Term, err error)

// GenFn is a lazy nondeterministic builtin: next yields successive solution terms to unify with pattern.
type GenFn func(m *Machine, a []Term) (pattern Term, next func() (Term, bool), err error)

type Clause struct {
	head   Term
	body   []Term // flattened top-level conjunction
	nvars  int
	key    argKey
	keys   callKeys // keys of the first maxIdxArgs head arguments, for clause pre-selection
	erased bool
	pred   *Pred
	id     int64
	src    Term // original (head :- body) copy for clause/2, listing
}

type Pred struct {
	name    *Atom
	arity   int
	clauses []*Clause
	dynamic bool
	defined bool
	det     DetFn
	nondet  NondetFn
	ctl     int
	library bool // defined by the bundled library
	discont bool
	tabled  *tabledInfo
	gen     GenFn

	nErased   int                  // erased clauses still present in clauses (compacted lazily)
	nVarFirst int                  // clauses whose first argument is a variable
	idx       map[argKey][]*Clause // first-argument hash index, built on demand
}

func (p *Pred) isBuiltin() bool { return p.det != nil || p.nondet != nil || p.gen != nil || p.ctl != 0 }

func (p *Pred) liveCount() int { return len(p.clauses) - p.nErased }

// candidates returns the clauses that can match a call whose first argument has the given key.
func (p *Pred) candidates(key argKey) []*Clause {
	if key.k == 0 || p.nVarFirst > 0 || len(p.clauses) < 8 {
		return p.clauses
	}
	if p.idx == nil {
		p.idx = make(map[argKey][]*Clause)
		for _, c := range p.clauses {
			if !c.erased {
				p.idx[c.key] = append(p.idx[c.key], c)
			}
		}
	}
	return p.idx[key]
}

func (p *Pred) resetClauses() {
	p.clauses, p.nErased, p.nVarFirst, p.idx = nil, 0, 0, nil
}

const maxIdxArgs = 4

type callKeys [maxIdxArgs]argKey

type argKey struct {
	k uint8 // 0 any, 1 atom, 2 int, 3 compound
	p *Atom
	n int64
}

func keyOf(t Term) argKey {
	switch x := t.(type) {
	case *Atom:
		return argKey{1, x, 0}
	case Int:
		return argKey{2, nil, int64(x)}
	case *Compound:
		return argKey{3, x.Fn, int64(len(x.Args))}
	}
	return argKey{}
}

func (k argKey) matches(o argKey) bool { return k.k == 0 || o.k == 0 || k == o }

// frame ops
const (
	opGoal = iota
	opCutTo
	opCatchExit
	opSoftCut
	opCutFail
	opTraceExit
	opPopCall
)

type Frame struct {
	goal Term
	cutB int
	next *Frame
	op   uint8
	n    int
	dep  int
}

type cpKind uint8

const (
	cpClauses cpKind = iota
	cpAlts
	cpGoal
	cpCatch
	cpBarrier
	cpDead
	cpTable
	cpTraceFail
	cpGen
)

type ChoicePoint struct {
	kind     cpKind
	trailTop int
	varMark  int64
	cont     *Frame
	// clauses
	args    []Term
	clauses []*Clause
	idx     int
	keys    *callKeys
	pred    *Pred
	dep     int
	// alts
	pat  Term
	sols []Term
	// lazy generator
	next    func() (Term, bool)
	pending Term
	// tabled consumer
	tb *table
	// goal alt
	alt *Frame
	// catch
	catcher, recovery Term
	cutB              int
	active            bool
	id                int64
}

type Machine struct {
	cps           []ChoicePoint
	trail         []*Var
	cont          *Frame
	varCnt        int64
	hb            int64
	ops           OpTable
	flags         map[string]string
	flagVal       map[string]Term
	out           *bufio.Writer
	errOut        *bufio.Writer
	infer         int64
	uniq          int64
	globals       map[string]Term
	clauseByID    map[int64]*Clause
	occursCheck   bool
	tracing       bool
	loadFile      string
	inits         []Term
	streams       map[int64]*Stream
	nextStream    int64
	curIn, curOut int64
	loading       bool
	warnedDiscont map[*Pred]bool
	stopFrame     *Frame
	definedInFile map[*Pred]bool
	tbl           *tableState
	lastPred      *Pred
}

var gm *Machine

func newMachine() *Machine {
	m := &Machine{
		ops:           newOpTable(),
		flags:         map[string]string{"double_quotes": "string", "unknown": "error", "occurs_check": "false"},
		globals:       map[string]Term{},
		clauseByID:    map[int64]*Clause{},
		streams:       map[int64]*Stream{},
		warnedDiscont: map[*Pred]bool{},
		definedInFile: map[*Pred]bool{},
	}
	m.out = bufio.NewWriterSize(os.Stdout, 1<<16)
	m.errOut = bufio.NewWriterSize(os.Stderr, 1<<12)
	m.stopFrame = &Frame{}
	gm = m
	m.initStreams()
	m.installBuiltins()
	return m
}

func (m *Machine) newVar() *Var {
	m.varCnt++
	return &Var{id: m.varCnt}
}

func (m *Machine) bind(v *Var, t Term) {
	v.ref = t
	if v.id <= m.hb {
		m.trail = append(m.trail, v)
	}
}

func (m *Machine) undoTrail(to int) {
	for i := len(m.trail) - 1; i >= to; i-- {
		v := m.trail[i]
		if v.undo != nil {
			f := v.undo
			v.undo = nil
			f()
		} else {
			v.ref = nil
		}
	}
	m.trail = m.trail[:to]
}

func (m *Machine) pushUndo(f func()) {
	m.trail = append(m.trail, &Var{undo: f})
}

func (m *Machine) setCPs(n int) {
	m.cps = m.cps[:n]
	if n > 0 {
		m.hb = m.cps[n-1].varMark
	} else {
		m.hb = 0
	}
}

func (m *Machine) pushCP(cp ChoicePoint) {
	cp.trailTop = len(m.trail)
	cp.varMark = m.varCnt
	m.cps = append(m.cps, cp)
	m.hb = m.varCnt
}

// ---------- unification ----------

func (m *Machine) unify(a, b Term) bool {
	for {
		a, b = deref(a), deref(b)
		if a == b {
			return true
		}
		if va, ok := a.(*Var); ok {
			if vb, ok := b.(*Var); ok && vb.id > va.id {
				m.bind(vb, va)
				return true
			}
			if m.occursCheck && occurs(va, b) {
				return false
			}
			m.bind(va, b)
			return true
		}
		if vb, ok := b.(*Var); ok {
			if m.occursCheck && occurs(vb, a) {
				return false
			}
			m.bind(vb, a)
			return true
		}
		switch x := a.(type) {
		case *Compound:
			y, ok := b.(*Compound)
			if !ok || x.Fn != y.Fn || len(x.Args) != len(y.Args) {
				return false
			}
			n := len(x.Args)
			for i := 0; i < n-1; i++ {
				if !m.unify(x.Args[i], y.Args[i]) {
					return false
				}
			}
			a, b = x.Args[n-1], y.Args[n-1]
			continue
		case Int:
			y, ok := b.(Int)
			return ok && x == y
		case Str:
			y, ok := b.(Str)
			return ok && x == y
		case Float:
			y, ok := b.(Float)
			return ok && (x == y || (x != x && y != y))
		case *big.Int:
			y, ok := b.(*big.Int)
			return ok && x.Cmp(y) == 0
		}
		return false
	}
}

func occurs(v *Var, t Term) bool {
	t = deref(t)
	switch x := t.(type) {
	case *Var:
		return x == v
	case *Compound:
		for _, a := range x.Args {
			if occurs(v, a) {
				return true
			}
		}
	}
	return false
}

// ---------- clause compilation ----------

type compiler struct {
	vars map[*Var]int
}

func (c *compiler) conv(t Term) Term {
	t = deref(t)
	switch x := t.(type) {
	case *Var:
		i, ok := c.vars[x]
		if !ok {
			i = len(c.vars)
			c.vars[x] = i
		}
		return LVar(i)
	case *Compound:
		args := make([]Term, len(x.Args))
		g := true
		for i, a := range x.Args {
			args[i] = c.conv(a)
			switch y := args[i].(type) {
			case LVar:
				g = false
			case *Compound:
				if !y.ground {
					g = false
				}
			}
		}
		return &Compound{Fn: x.Fn, Args: args, ground: g}
	}
	return t
}

func flattenConj(t Term, out []Term) []Term {
	for {
		t = deref(t)
		if c, ok := t.(*Compound); ok && c.Fn == atComma && len(c.Args) == 2 {
			out = flattenConj(c.Args[0], out)
			t = c.Args[1]
			continue
		}
		if t == Term(atTrue) {
			return out
		}
		return append(out, t)
	}
}

func (m *Machine) compileClause(head, body Term) (*Clause, error) {
	head = deref(head)
	if _, ok := head.(*Var); ok {
		return nil, instErr()
	}
	if !isCallable(head) {
		return nil, typeErr("callable", head)
	}
	body = deref(body)
	if err := checkBody(body); err != nil {
		return nil, err
	}
	body = wrapVarGoalsIn(body, false)
	c := &compiler{vars: map[*Var]int{}}
	ch := c.conv(head)
	var goals []Term
	for _, g := range flattenConj(body, nil) {
		g = deref(g)
		if _, ok := g.(*Var); ok {
			g = &Compound{Fn: atCall, Args: []Term{g}}
		}
		goals = append(goals, c.conv(g))
	}
	cl := &Clause{head: ch, body: goals, nvars: len(c.vars)}
	if hc, ok := ch.(*Compound); ok {
		cl.key = keyOf(hc.Args[0])
		for i := 0; i < len(hc.Args) && i < maxIdxArgs; i++ {
			cl.keys[i] = keyOf(hc.Args[i])
		}
	}
	m.uniq++
	cl.id = m.uniq
	cl.src = &Compound{Fn: atNeck, Args: []Term{ch, bodyTerm(goals)}}
	return cl, nil
}

func bodyTerm(goals []Term) Term {
	if len(goals) == 0 {
		return atTrue
	}
	t := goals[len(goals)-1]
	for i := len(goals) - 2; i >= 0; i-- {
		t = &Compound{Fn: atComma, Args: []Term{goals[i], t}}
	}
	return t
}

func checkBody(t Term) error {
	t = deref(t)
	switch x := t.(type) {
	case *Var, *Atom:
		return nil
	case *Compound:
		if len(x.Args) == 2 && (x.Fn == atComma || x.Fn == atSemi || x.Fn == atArrow || x.Fn == atSoft) {
			if err := checkBody(x.Args[0]); err != nil {
				return err
			}
			return checkBody(x.Args[1])
		}
		return nil
	}
	return typeErr("callable", t)
}

// rename instantiates a clause term with the variable frame.
func (m *Machine) rename(t Term, vars []Term) Term {
	switch x := t.(type) {
	case LVar:
		v := vars[x]
		if v == nil {
			nv := m.newVar()
			vars[x] = nv
			return nv
		}
		return v
	case *Compound:
		if x.ground {
			return x
		}
		nc := newComp(x.Fn, len(x.Args))
		args := nc.Args
		for i, a := range x.Args {
			switch y := a.(type) {
			case LVar:
				v := vars[y]
				if v == nil {
					nv := m.newVar()
					vars[y] = nv
					v = nv
				}
				args[i] = v
			case *Compound:
				if y.ground {
					args[i] = y
				} else {
					args[i] = m.rename(y, vars)
				}
			default:
				args[i] = a
			}
		}
		return nc
	}
	return t
}

func (m *Machine) unifyHead(p Term, t Term, vars []Term) bool {
	switch x := p.(type) {
	case LVar:
		if vars[x] == nil {
			vars[x] = t
			return true
		}
		return m.unify(vars[x], t)
	case *Atom:
		t = deref(t)
		if t == p {
			return true
		}
		if v, ok := t.(*Var); ok {
			m.bind(v, x)
			return true
		}
		return false
	case *Compound:
		t = deref(t)
		switch y := t.(type) {
		case *Compound:
			if y.Fn != x.Fn || len(y.Args) != len(x.Args) {
				return false
			}
			if x.ground {
				return m.unify(x, y)
			}
			for i, a := range x.Args {
				if !m.unifyHead(a, y.Args[i], vars) {
					return false
				}
			}
			return true
		case *Var:
			nt := m.rename(x, vars)
			if m.occursCheck && occurs(y, nt) {
				return false
			}
			m.bind(y, nt)
			return true
		}
		return false
	default:
		return m.unify(p, t)
	}
}

// ---------- predicates table ----------

func (m *Machine) lookupPred(a *Atom, arity int, create bool) *Pred {
	if arity < len(a.preds) {
		if p := a.preds[arity]; p != nil {
			return p
		}
	}
	if !create {
		return nil
	}
	for len(a.preds) <= arity {
		a.preds = append(a.preds, nil)
	}
	p := &Pred{name: a, arity: arity}
	a.preds[arity] = p
	return p
}

func (m *Machine) addClause(t Term, atEnd bool, fromLib bool) error {
	t = deref(t)
	var head, body Term = t, atTrue
	if c, ok := t.(*Compound); ok && c.Fn == atNeck && len(c.Args) == 2 {
		head, body = deref(c.Args[0]), c.Args[1]
	}
	if c, ok := head.(*Compound); ok && c.Fn == atColon && len(c.Args) == 2 {
		head = deref(c.Args[1])
	}
	cl, err := m.compileClause(head, body)
	if err != nil {
		return err
	}
	var name *Atom
	arity := 0
	switch h := head.(type) {
	case *Atom:
		name = h
	case *Compound:
		name, arity = h.Fn, len(h.Args)
	}
	p := m.lookupPred(name, arity, true)
	if p.tabled != nil {
		p = p.tabled.impl
	}
	if p.isBuiltin() {
		return permErr("modify", "static_procedure", pi(name, arity))
	}
	if p.library && !fromLib && !p.dynamic && m.loading {
		// user redefines a library predicate: wipe the library definition
		p.resetClauses()
		p.library = false
	}
	if fromLib {
		p.library = true
	}
	cl.pred = p
	p.defined = true
	m.clauseByID[cl.id] = cl
	if cl.key.k == 0 {
		p.nVarFirst++
		p.idx = nil
	}
	if atEnd {
		p.clauses = append(p.clauses, cl)
		if p.idx != nil {
			p.idx[cl.key] = append(p.idx[cl.key], cl)
		}
	} else {
		nc := make([]*Clause, 0, len(p.clauses)+1)
		nc = append(nc, cl)
		p.clauses = append(nc, p.clauses...)
		p.idx = nil
	}
	return nil
}

func (m *Machine) eraseClause(cl *Clause) {
	if cl.erased {
		return
	}
	cl.erased = true
	p := cl.pred
	delete(m.clauseByID, cl.id)
	p.nErased++
	if cl.key.k == 0 {
		p.nVarFirst--
	}
	// compact lazily; running iterations keep their own snapshot of the old slice
	if p.nErased > 16 && p.nErased > len(p.clauses)/2 {
		nc := make([]*Clause, 0, len(p.clauses)-p.nErased)
		for _, c := range p.clauses {
			if !c.erased {
				nc = append(nc, c)
			}
		}
		p.clauses, p.nErased, p.idx = nc, 0, nil
	}
}

// wrapVarGoals turns variable goals in control positions into call(Var), so that a cut
// inside a goal bound at run time stays local to it (ISO 7.6.2).
func wrapVarGoals(t Term) Term {
	return wrapVarGoalsIn(deref(t), true)
}

func wrapVarGoalsIn(t Term, top bool) Term {
	t = deref(t)
	switch x := t.(type) {
	case *Var:
		if top {
			return x
		}
		return &Compound{Fn: atCall, Args: []Term{x}}
	case *Compound:
		if len(x.Args) == 2 && (x.Fn == atComma || x.Fn == atSemi || x.Fn == atArrow || x.Fn == atSoft) {
			l, r := wrapVarGoalsIn(x.Args[0], false), wrapVarGoalsIn(x.Args[1], false)
			return &Compound{Fn: x.Fn, Args: []Term{l, r}}
		}
		if len(x.Args) == 1 && x.Fn == atNot {
			return &Compound{Fn: x.Fn, Args: []Term{wrapVarGoalsIn(x.Args[0], false)}}
		}
	}
	return t
}
