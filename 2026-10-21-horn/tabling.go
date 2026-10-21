package main

import (
	"strconv"
	"strings"
)

// Tabling: variant tabling with answer subsumption modes, evaluated by iteration to a fixpoint.
//
//   :- table path/2.            plain variant tabling (terminates on left recursion)
//   :- table path(_,_,min).     mode-directed: keep only the minimal 3rd argument per (1st,2nd)
//
// Each call variant owns a table. The first call evaluates the renamed implementation predicate
// repeatedly until no table gained an answer during a whole pass (an SCC-aware naive fixpoint:
// recursive variant calls consume the answers found so far). Tables that depended on a still
// running table stay "pending" and are completed together with the leader that they depend on.

type tabledInfo struct {
	impl  *Pred
	modes []string // "" for index arguments, else min/max/first/last
	moded bool
}

type table struct {
	key        string
	answers    []Term
	ground     []bool
	index      map[string]int // answer key (non-moded args) -> position
	complete   bool
	evaluating bool
	stackIdx   int
	minDep     int
	usedInc    bool  // consumed an incomplete table, so a re-run may find more answers
	epoch      int64 // m.tblEpoch when last evaluated
	seq        int
}

type tableState struct {
	tables  map[string]*table
	stack   []*table
	epoch   int64
	pending []*table
	seq     int
}

func (m *Machine) tstate() *tableState {
	if m.tbl == nil {
		m.tbl = &tableState{tables: map[string]*table{}}
	}
	return m.tbl
}

func variantKey(t Term, extraName string) string {
	var vs []*Var
	termVars(t, map[*Var]bool{}, &vs)
	names := make(map[*Var]string, len(vs))
	for i, v := range vs {
		names[v] = "_V" + strconv.Itoa(i)
	}
	return formatTermOpts(t, writeOpts{quoted: true, ignoreOps: true, varNames: names})
}

func (m *Machine) declareTable(spec Term) error {
	spec = deref(spec)
	switch x := spec.(type) {
	case *Var:
		return instErr()
	case *Compound:
		if (x.Fn == atComma || x.Fn == atDot) && len(x.Args) == 2 {
			if err := m.declareTable(x.Args[0]); err != nil {
				return err
			}
			return m.declareTable(x.Args[1])
		}
		if x.Fn == atColon && len(x.Args) == 2 {
			return m.declareTable(x.Args[1])
		}
		if (x.Fn == atSlash || x.Fn.Name == "//") && len(x.Args) == 2 {
			n, err := getAtom(x.Args[0])
			if err != nil {
				return err
			}
			ar, err := getInt(x.Args[1])
			if err != nil {
				return err
			}
			if x.Fn.Name == "//" {
				ar += 2
			}
			return m.makeTabled(n, ar, nil)
		}
		modes := make([]string, len(x.Args))
		moded := false
		for i, a := range x.Args {
			switch y := deref(a).(type) {
			case *Atom:
				switch y.Name {
				case "min", "max", "first", "last":
					modes[i] = y.Name
					moded = true
				case "index", "_", "-":
				default:
					return domErr("table_mode", y)
				}
			case *Var:
			default:
				return domErr("table_mode", y)
			}
		}
		if !moded {
			modes = nil
		}
		return m.makeTabled(x.Fn, len(x.Args), modes)
	case *Atom:
		if x == atNil {
			return nil
		}
		return m.makeTabled(x, 0, nil)
	}
	return typeErr("predicate_indicator", spec)
}

func (m *Machine) makeTabled(name *Atom, arity int, modes []string) error {
	p := m.lookupPred(name, arity, true)
	if p.isBuiltin() {
		return permErr("modify", "static_procedure", pi(name, arity))
	}
	if p.tabled != nil {
		return nil
	}
	impl := m.lookupPred(mkAtom(name.Name+" tabled"), arity, true)
	impl.defined = true
	impl.dynamic = false
	// move clauses that were loaded before the declaration
	for _, c := range p.clauses {
		c.pred = impl
	}
	impl.clauses, p.clauses = p.clauses, nil
	p.tabled = &tabledInfo{impl: impl, modes: modes, moded: modes != nil}
	p.defined = true
	return nil
}

func (m *Machine) abolishAllTables() {
	m.tbl = nil
}

// answerKey identifies an answer: the whole term, or only its non-moded arguments.
func (ti *tabledInfo) answerKey(t Term) string {
	if !ti.moded {
		return variantKey(t, "")
	}
	c, ok := deref(t).(*Compound)
	if !ok {
		return variantKey(t, "")
	}
	var parts []Term
	for i, a := range c.Args {
		if ti.modes[i] == "" {
			parts = append(parts, a)
		}
	}
	return variantKey(mkList(parts, atNil), "")
}

// better reports whether answer a improves on b under the table modes.
func (ti *tabledInfo) better(a, b Term) (bool, bool) {
	ca, cb := deref(a).(*Compound), deref(b).(*Compound)
	for i, md := range ti.modes {
		switch md {
		case "min":
			if c := compareTerms(ca.Args[i], cb.Args[i]); c != 0 {
				return c < 0, true
			}
		case "max":
			if c := compareTerms(ca.Args[i], cb.Args[i]); c != 0 {
				return c > 0, true
			}
		case "last":
			return compareTerms(a, b) != 0, true
		}
	}
	return false, false
}

func (m *Machine) addAnswer(ts *tableState, ti *tabledInfo, tb *table, ans Term) bool {
	k := ti.answerKey(ans)
	if pos, ok := tb.index[k]; ok {
		if ti.moded {
			if better, _ := ti.better(ans, tb.answers[pos]); better {
				tb.answers[pos] = ans
				tb.ground[pos] = isGround(ans)
				ts.epoch++
				return true
			}
		}
		return false
	}
	tb.index[k] = len(tb.answers)
	tb.answers = append(tb.answers, ans)
	tb.ground = append(tb.ground, isGround(ans))
	ts.epoch++
	return true
}

// tabledCall returns the pattern/solutions pair for a call to a tabled predicate.
func (m *Machine) tabledCall(p *Pred, goal Term) (*table, error) {
	ts := m.tstate()
	ti := p.tabled
	key := variantKey(goal, "")
	tb := ts.tables[key]
	if tb != nil && tb.complete {
		return tb, nil
	}
	if tb != nil && tb.evaluating {
		// recursive variant call: consume what exists so far and record the dependency
		if top := len(ts.stack) - 1; top >= 0 && tb.stackIdx < ts.stack[top].minDep {
			ts.stack[top].minDep = tb.stackIdx
		}
		ts.markCycle(tb.stackIdx)
		return tb, nil
	}
	if tb != nil && tb.epoch == ts.epoch {
		// pending table that is already up to date for the current state of all tables
		if top := len(ts.stack) - 1; top >= 0 && tb.minDep < ts.stack[top].minDep {
			ts.stack[top].minDep = tb.minDep
		}
		ts.markCycle(tb.minDep)
		return tb, nil
	}
	if tb == nil {
		ts.seq++
		tb = &table{key: key, index: map[string]int{}, seq: ts.seq}
		ts.tables[key] = tb
	}
	tb.evaluating = true
	tb.usedInc = false
	tb.stackIdx = len(ts.stack)
	tb.minDep = tb.stackIdx
	ts.stack = append(ts.stack, tb)
	startSeq := tb.seq
	pendingStart := len(ts.pending)
	failed := true
	defer func() {
		if failed { // exception: forget everything this evaluation created
			ts.stack = ts.stack[:tb.stackIdx]
			delete(ts.tables, key)
			for _, pt := range ts.pending[pendingStart:] {
				delete(ts.tables, pt.key)
			}
			ts.pending = ts.pending[:pendingStart]
		}
	}()
	// build the implementation goal sharing the call's arguments
	var impl Term = ti.impl.name
	if c, ok := goal.(*Compound); ok {
		impl = &Compound{Fn: ti.impl.name, Args: c.Args}
	}
	for {
		before := ts.epoch
		q := m.newQuery(impl)
		for {
			ok, err := q.next()
			if err != nil {
				q.close()
				return nil, err
			}
			if !ok {
				break
			}
			m.addAnswer(ts, ti, tb, m.copyTerm(goal, map[*Var]Term{}))
		}
		q.close()
		tb.epoch = ts.epoch
		if ts.epoch == before || !tb.usedInc {
			break
		}
	}
	failed = false
	ts.stack = ts.stack[:tb.stackIdx]
	tb.evaluating = false
	if tb.minDep < tb.stackIdx {
		// depends on a table that is still being evaluated: stay pending until its leader completes
		ts.pending = append(ts.pending, tb)
		ts.markCycle(tb.minDep)
		if parent := len(ts.stack) - 1; parent >= 0 && tb.minDep < ts.stack[parent].minDep {
			ts.stack[parent].minDep = tb.minDep
		}
	} else {
		tb.complete = true
		keep := ts.pending[:pendingStart]
		for _, pt := range ts.pending[pendingStart:] {
			if pt.seq >= startSeq {
				pt.complete = true
			} else {
				keep = append(keep, pt)
			}
		}
		ts.pending = keep
	}
	return tb, nil
}

// markCycle flags every running table from stack index from upwards as part of a recursive cycle.
func (ts *tableState) markCycle(from int) {
	for i := from; i >= 0 && i < len(ts.stack); i++ {
		ts.stack[i].usedInc = true
	}
}

func (m *Machine) installTablingBuiltins() {
	m.det("table", 1, func(m *Machine, a []Term) (bool, error) { return true, m.declareTable(a[0]) })
	m.det("abolish_all_tables", 0, func(m *Machine, a []Term) (bool, error) { m.abolishAllTables(); return true, nil })
	m.det("$table_stats", 1, func(m *Machine, a []Term) (bool, error) {
		ts := m.tstate()
		n, ans := 0, 0
		for _, t := range ts.tables {
			n++
			ans += len(t.answers)
		}
		return m.unify(a[0], mk("tables", Int(n), Int(ans))), nil
	})
	_ = strings.TrimSpace
}
