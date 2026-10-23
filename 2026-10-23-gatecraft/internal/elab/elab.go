// Package elab turns parsed Verilog modules into a flattened And-Inverter Graph:
// parameter evaluation, hierarchy flattening, width inference, symbolic execution
// of procedural blocks and bit-blasting of every operator.
package elab

import (
	"fmt"
	"math/big"
	"sort"
	"strings"

	"gatecraft/internal/aig"
	"gatecraft/internal/hdl"
)

// Options configure elaboration.
type Options struct {
	Top    string
	Params map[string]*big.Int // overrides for the top module's parameters
}

type elabError struct{ err error }

type signal struct {
	name   string
	full   string
	width  int
	lsb    int
	dir    hdl.Dir
	isReg  bool
	isInt  bool
	decl   *hdl.Decl
	val    []aig.Lit
	driver []*driver
	latch  []int // latch index per bit, -1 if none
	init   *big.Int
	ctx    *ctx
}

type bitRef struct {
	sig *signal
	bit int
}

type peekRec struct {
	sig *signal
	bit int
	lit aig.Lit
}

type driver struct {
	what    string
	targets []bitRef
	eval    func() []aig.Lit
	state   int // 0 idle, 1 running, 2 done
	// A running combinational block can answer reads of its own outputs that arrive
	// through other logic (a legal, non-looping dependency) with the value it has
	// computed so far; the value must still be the final one when the block ends.
	peek   func(s *signal, bit int) (aig.Lit, bool)
	peeked []peekRec
}

type clockedBlock struct {
	c        *ctx
	a        *hdl.Always
	assigned []*signal
	clock    string
}

type elaborator struct {
	g       *aig.AIG
	mods    map[string]*hdl.Module
	ctxs    []*ctx
	clocked []*clockedBlock
	stack   []string
	nprops  int
}

type ctx struct {
	e      *elaborator
	mod    *hdl.Module
	path   string
	params map[string]*big.Int
	sigs   map[string]*signal
	order  []*signal
	parent *ctx
	inst   *hdl.Instance
}

func (c *ctx) warn(pos hdl.Pos, format string, args ...any) {
	where := c.mod.File
	if where == "" {
		where = c.mod.Name
	}
	c.e.g.Warnings = append(c.e.g.Warnings, fmt.Sprintf("%s:%s: warning: %s", where, pos, fmt.Sprintf(format, args...)))
}

func (c *ctx) fail(pos hdl.Pos, format string, args ...any) {
	where := c.mod.File
	if where == "" {
		where = c.mod.Name
	}
	msg := fmt.Sprintf(format, args...)
	if c.path != "" {
		msg += fmt.Sprintf(" (in instance %s of module %s)", strings.TrimSuffix(c.path, "."), c.mod.Name)
	}
	panic(elabError{fmt.Errorf("%s:%s: %s", where, pos, msg)})
}

// Elaborate flattens the design rooted at opt.Top (or the only/last uninstantiated module).
func Elaborate(files []*hdl.File, opt Options) (g *aig.AIG, err error) {
	e := &elaborator{g: aig.New(), mods: map[string]*hdl.Module{}}
	var order []*hdl.Module
	for _, f := range files {
		for _, m := range f.Modules {
			if _, dup := e.mods[m.Name]; dup {
				return nil, fmt.Errorf("%s:%s: module %s defined twice", f.Name, m.At, m.Name)
			}
			e.mods[m.Name] = m
			order = append(order, m)
		}
	}
	if len(order) == 0 {
		var names []string
		for _, f := range files {
			names = append(names, f.Name)
		}
		return nil, fmt.Errorf("no modules found in %s", strings.Join(names, ", "))
	}
	top := opt.Top
	if top == "" {
		inst := map[string]bool{}
		for _, m := range order {
			for _, in := range m.Insts {
				inst[in.Module] = true
			}
		}
		var roots []string
		for _, m := range order {
			if !inst[m.Name] {
				roots = append(roots, m.Name)
			}
		}
		if len(roots) != 1 {
			return nil, fmt.Errorf("cannot infer top module (candidates: %s); use -top", strings.Join(roots, ", "))
		}
		top = roots[0]
	}
	tm, ok := e.mods[top]
	if !ok {
		return nil, fmt.Errorf("top module %q not found", top)
	}
	defer func() {
		if r := recover(); r != nil {
			if ee, ok := r.(elabError); ok {
				g, err = nil, ee.err
				return
			}
			panic(r)
		}
	}()
	e.run(tm, opt.Params)
	return e.g, nil
}

func (e *elaborator) run(tm *hdl.Module, over map[string]*big.Int) {
	top := e.newCtx(tm, "", over, nil, nil)

	// top-level ports
	for _, name := range tm.PortOrder {
		s := top.sigs[name]
		switch s.dir {
		case hdl.DirInput:
			bits := make([]aig.Lit, s.width)
			copy(bits, s.val)
			e.g.Inputs = append(e.g.Inputs, aig.Port{Name: name, Bits: bits})
		}
	}
	// phase A: latches for every register assigned in a clocked block
	for _, cb := range e.clocked {
		cb.c.declareLatches(cb)
	}
	// phase B: clock nets
	for _, cb := range e.clocked {
		cb.c.resolveClock(cb)
	}
	// phase C: next-state logic
	for _, cb := range e.clocked {
		cb.c.execClocked(cb)
	}
	// phase D: properties, outputs, then every named signal
	for _, c := range e.ctxs {
		c.buildProps()
	}
	for _, name := range tm.PortOrder {
		s := top.sigs[name]
		if s.dir == hdl.DirOutput {
			v := top.readSignal(s, tm.At)
			e.g.Outputs = append(e.g.Outputs, aig.Port{Name: name, Bits: append([]aig.Lit(nil), v...)})
		} else if s.dir == hdl.DirInout {
			top.fail(s.decl.At, "inout ports are not supported")
		}
	}
	for _, c := range e.ctxs {
		for _, s := range c.order {
			if s.isInt {
				continue
			}
			if v, ok := c.tryRead(s); ok {
				e.g.SetName(s.full, v)
			}
		}
	}
}

// ------------------------------------------------------------------ contexts

const maxDepth = 32

func (e *elaborator) newCtx(m *hdl.Module, path string, over map[string]*big.Int, parent *ctx, inst *hdl.Instance) *ctx {
	depth := 0
	for p := parent; p != nil; p = p.parent {
		depth++
	}
	c := &ctx{e: e, mod: m, path: path, params: map[string]*big.Int{}, sigs: map[string]*signal{}, parent: parent, inst: inst}
	if depth > maxDepth {
		c.fail(m.At, "instantiation depth exceeds %d (recursive instantiation of %s?)", maxDepth, m.Name)
	}
	e.ctxs = append(e.ctxs, c)

	// parameters
	for _, p := range m.Params {
		if v, ok := over[p.Name]; ok && !p.Local {
			c.params[p.Name] = new(big.Int).Set(v)
			continue
		}
		v, ok := c.tryConst(nil, p.Value)
		if !ok {
			c.fail(p.At, "parameter %s is not a constant expression", p.Name)
		}
		c.params[p.Name] = v
	}
	for n := range over {
		found := false
		for _, p := range m.Params {
			if p.Name == n && !p.Local {
				found = true
			}
		}
		if !found {
			c.fail(m.At, "module %s has no overridable parameter %q", m.Name, n)
		}
	}

	// declarations
	for _, d := range m.Decls {
		c.declare(d)
	}
	// top-level inputs become primary inputs
	if parent == nil {
		for _, s := range c.order {
			if s.dir == hdl.DirInput {
				for i := 0; i < s.width; i++ {
					s.val[i] = e.g.AddInput(s.name, i)
				}
			}
		}
	}

	// continuous assignments
	for _, a := range m.Assigns {
		c.installAssign(a)
	}
	// procedural blocks
	for _, a := range m.Always {
		if a.Comb {
			c.installComb(a)
		} else {
			e.clocked = append(e.clocked, &clockedBlock{c: c, a: a})
		}
	}
	for _, in := range m.Initials {
		c.runInitial(in)
	}
	// register initial values & unassigned regs with init
	// instances
	for _, in := range m.Insts {
		c.installInstance(in)
	}
	return c
}

func (c *ctx) declare(d *hdl.Decl) {
	w, lsb := 1, 0
	if d.Rng != nil {
		hi, ok1 := c.tryConst(nil, d.Rng.Hi)
		lo, ok2 := c.tryConst(nil, d.Rng.Lo)
		if !ok1 || !ok2 {
			c.fail(d.At, "range of %s is not a constant expression", d.Name)
		}
		if hi.Cmp(lo) < 0 {
			c.fail(d.At, "ascending range [%s:%s] of %s is not supported (use [msb:lsb] with msb >= lsb)", hi, lo, d.Name)
		}
		if !hi.IsInt64() || !lo.IsInt64() || hi.Int64()-lo.Int64() >= 1<<16 || lo.Sign() < 0 {
			c.fail(d.At, "unreasonable range [%s:%s] for %s", hi, lo, d.Name)
		}
		w, lsb = int(hi.Int64()-lo.Int64())+1, int(lo.Int64())
	}
	if d.IsInt {
		w = 32
	}
	if old, ok := c.sigs[d.Name]; ok {
		// non-ANSI: "output y; reg [3:0] y;" style redeclaration
		if old.dir != hdl.DirNone && d.Dir == hdl.DirNone && (d.IsReg || d.Rng != nil) {
			if d.Rng != nil && old.decl.Rng == nil {
				old.width, old.lsb = w, lsb
				old.val = undefVec(w)
				old.driver = make([]*driver, w)
				old.latch = filledInts(w, -1)
			}
			if d.IsReg {
				old.isReg = true
			}
			if d.Init != nil {
				c.setInit(old, d.Init)
			}
			return
		}
		if old.dir == hdl.DirNone && d.Dir != hdl.DirNone {
			old.dir = d.Dir
			return
		}
		c.fail(d.At, "'%s' is declared twice", d.Name)
	}
	s := &signal{name: d.Name, full: c.path + d.Name, width: w, lsb: lsb, dir: d.Dir, isReg: d.IsReg, isInt: d.IsInt,
		decl: d, val: undefVec(w), driver: make([]*driver, w), latch: filledInts(w, -1), ctx: c}
	c.sigs[d.Name] = s
	c.order = append(c.order, s)
	if d.Init != nil {
		c.setInit(s, d.Init)
	}
}

func (c *ctx) setInit(s *signal, x hdl.Expr) {
	v, ok := c.tryConst(nil, x)
	if !ok {
		c.fail(x.P(), "initial value of %s must be a constant", s.name)
	}
	s.init = v
}

func undefVec(w int) []aig.Lit {
	v := make([]aig.Lit, w)
	for i := range v {
		v[i] = aig.Undef
	}
	return v
}
func filledInts(w, x int) []int {
	v := make([]int, w)
	for i := range v {
		v[i] = x
	}
	return v
}

func (c *ctx) sigByName(pos hdl.Pos, name string) *signal {
	s, ok := c.sigs[name]
	if !ok {
		c.fail(pos, "undeclared identifier '%s'", name)
	}
	return s
}

// ------------------------------------------------------------------ driver machinery

func (c *ctx) setDriver(pos hdl.Pos, d *driver) {
	for _, t := range d.targets {
		if t.sig.driver[t.bit] != nil || t.sig.latch[t.bit] >= 0 {
			c.fail(pos, "multiple drivers for %s[%d]", t.sig.name, t.bit+t.sig.lsb)
		}
		if t.sig.dir == hdl.DirInput && c.parent == nil {
			c.fail(pos, "cannot drive top-level input '%s'", t.sig.name)
		}
		t.sig.driver[t.bit] = d
	}
}

func (e *elaborator) runDriver(d *driver) {
	switch d.state {
	case 2:
		return
	case 1:
		// report the cycle
		start := 0
		for i, w := range e.stack {
			if w == d.what {
				start = i
			}
		}
		cyc := append(append([]string(nil), e.stack[start:]...), d.what)
		panic(elabError{fmt.Errorf("combinational loop: %s", strings.Join(cyc, " -> "))})
	}
	d.state = 1
	e.stack = append(e.stack, d.what)
	vals := d.eval()
	e.stack = e.stack[:len(e.stack)-1]
	for i, t := range d.targets {
		t.sig.val[t.bit] = vals[i]
	}
	d.state = 2
}

// readSignal returns the fully-resolved value of s, driving lazily.
func (c *ctx) readSignal(s *signal, at hdl.Pos) []aig.Lit {
	return c.readRange(s, at, 0, s.width)
}

// readRange resolves only bits [lo,hi) of s, so bit-level references do not
// create false combinational loops through the rest of a vector.
func (c *ctx) readRange(s *signal, at hdl.Pos, lo, hi int) []aig.Lit {
	var early map[int]aig.Lit
	for i := lo; i < hi; i++ {
		if s.val[i] != aig.Undef {
			continue
		}
		d := s.driver[i]
		if d == nil {
			if s.isReg && s.init != nil && s.latch[i] < 0 {
				s.val[i] = bitOf(s.init, i)
				continue
			}
			c.fail(at, "signal '%s' bit %d is never driven", s.name, i+s.lsb)
		}
		if d.state == 1 && d.peek != nil {
			if v, ok := d.peek(s, i); ok {
				if early == nil {
					early = map[int]aig.Lit{}
				}
				early[i] = v
				d.peeked = append(d.peeked, peekRec{s, i, v})
				continue
			}
		}
		c.e.runDriver(d)
	}
	if early == nil {
		return s.val
	}
	out := append([]aig.Lit(nil), s.val...)
	for i, v := range early {
		out[i] = v
	}
	return out
}

func (c *ctx) tryRead(s *signal) ([]aig.Lit, bool) {
	for i := range s.val {
		if s.val[i] == aig.Undef && s.driver[i] == nil && !(s.isReg && s.init != nil && s.latch[i] < 0) {
			return nil, false
		}
	}
	return c.readSignal(s, s.decl.At), true
}

func bitOf(v *big.Int, i int) aig.Lit {
	if v.Bit(i) == 1 {
		return aig.True
	}
	return aig.False
}

// ------------------------------------------------------------------ continuous assign

func (c *ctx) installAssign(a *hdl.ContAssign) {
	w, writes := c.lvalue(nil, a.LHS)
	d := &driver{what: fmt.Sprintf("assign@%s", a.At)}
	for _, wr := range writes {
		if wr.cond != aig.True {
			c.fail(a.At, "continuous assignment needs a constant index")
		}
		if wr.sig.isReg {
			c.fail(a.At, "cannot continuously assign to reg '%s'; declare it wire or use an always block", wr.sig.name)
		}
		d.targets = append(d.targets, bitRef{wr.sig, wr.bit})
	}
	// targets must be ordered by value bit
	sort.SliceStable(writes, func(i, j int) bool { return writes[i].valIdx < writes[j].valIdx })
	d.targets = d.targets[:0]
	for _, wr := range writes {
		d.targets = append(d.targets, bitRef{wr.sig, wr.bit})
	}
	d.eval = func() []aig.Lit { return c.assignWidth(nil, a.RHS, w) }
	c.setDriver(a.At, d)
}

// ------------------------------------------------------------------ initial blocks

func (c *ctx) runInitial(in *hdl.Initial) {
	var walk func(s hdl.Stmt)
	walk = func(s hdl.Stmt) {
		switch s := s.(type) {
		case *hdl.Block:
			for _, x := range s.Stmts {
				walk(x)
			}
		case *hdl.Assign:
			id, ok := s.LHS.(*hdl.Ident)
			if !ok {
				c.fail(s.At, "initial blocks may only assign whole registers")
			}
			sg := c.sigByName(s.At, id.Name)
			if !sg.isReg {
				c.fail(s.At, "initial assignment target '%s' must be a reg", id.Name)
			}
			c.setInit(sg, s.RHS)
		default:
			c.fail(s.SP(), "initial blocks may contain only constant assignments")
		}
	}
	walk(in.Body)
}

// ------------------------------------------------------------------ instances

func (c *ctx) installInstance(in *hdl.Instance) {
	m, ok := c.e.mods[in.Module]
	if !ok {
		c.fail(in.At, "unknown module '%s'", in.Module)
	}
	over := map[string]*big.Int{}
	var overridable []string
	for _, p := range m.Params {
		if !p.Local {
			overridable = append(overridable, p.Name)
		}
	}
	for i, pc := range in.Params {
		name := pc.Name
		if name == "" {
			if i >= len(overridable) {
				c.fail(in.At, "too many positional parameters for %s", m.Name)
			}
			name = overridable[i]
		}
		v, ok := c.tryConst(nil, pc.X)
		if !ok {
			c.fail(pc.X.P(), "parameter override %s must be constant", name)
		}
		over[name] = v
	}
	child := c.e.newCtx(m, c.path+in.Name+".", over, c, in)

	connected := map[string]bool{}
	for i, pc := range in.Conns {
		name := pc.Name
		if name == "" {
			if i >= len(m.PortOrder) {
				c.fail(in.At, "too many ports for instance %s of %s", in.Name, m.Name)
			}
			name = m.PortOrder[i]
		}
		ps, ok := child.sigs[name]
		if !ok || ps.dir == hdl.DirNone {
			c.fail(in.At, "module %s has no port '%s'", m.Name, name)
		}
		if connected[name] {
			c.fail(in.At, "port '%s' connected twice", name)
		}
		connected[name] = true
		if pc.X == nil {
			continue
		}
		switch ps.dir {
		case hdl.DirInput:
			x, pw := pc.X, ps.width
			if num, isNum := x.(*hdl.Number); !(isNum && num.Width == 0) {
				if w := c.selfWidth(nil, x); w != pw {
					c.warn(in.At, "port '%s' of instance %s is %d bits but the connected expression is %d bits (%s)",
						name, in.Name, pw, w, map[bool]string{true: "truncated", false: "zero-extended"}[w > pw])
				}
			}
			d := &driver{what: fmt.Sprintf("%s%s", child.path, name)}
			for b := 0; b < pw; b++ {
				d.targets = append(d.targets, bitRef{ps, b})
			}
			d.eval = func() []aig.Lit { return c.assignWidth(nil, x, pw) }
			child.setDriver(in.At, d)
		case hdl.DirOutput:
			w, writes := c.lvalue(nil, pc.X)
			if w != ps.width {
				c.warn(in.At, "output port '%s' of instance %s is %d bits but the connected net is %d bits (%s)",
					name, in.Name, ps.width, w, map[bool]string{true: "truncated", false: "zero-extended"}[ps.width > w])
			}
			sort.SliceStable(writes, func(i, j int) bool { return writes[i].valIdx < writes[j].valIdx })
			d := &driver{what: fmt.Sprintf("%s%s", child.path, name)}
			for _, wr := range writes {
				if wr.cond != aig.True {
					c.fail(in.At, "output port connection needs constant indices")
				}
				if wr.sig.isReg {
					c.fail(in.At, "output port '%s' of %s cannot drive reg '%s'", name, in.Name, wr.sig.name)
				}
				d.targets = append(d.targets, bitRef{wr.sig, wr.bit})
			}
			d.eval = func() []aig.Lit {
				v := child.readSignal(ps, in.At)
				return aig.Ext(v, w)
			}
			c.setDriver(in.At, d)
		default:
			c.fail(in.At, "inout port '%s' is not supported", name)
		}
	}
	for _, n := range m.PortOrder {
		ps := child.sigs[n]
		if ps.dir == hdl.DirInput && !connected[n] {
			c.fail(in.At, "input port '%s' of instance %s is not connected", n, in.Name)
		}
		if ps.dir == hdl.DirInout {
			c.fail(in.At, "inout port '%s' is not supported", n)
		}
	}
}

// ------------------------------------------------------------------ properties

func (c *ctx) buildProps() {
	for _, p := range c.mod.Props {
		c.e.nprops++
		name := p.Name
		if name == "" {
			kind := "assert"
			if p.Assume {
				kind = "assume"
			}
			name = fmt.Sprintf("%s_%d", kind, c.e.nprops)
		}
		l := c.boolOf(nil, p.X)
		pr := aig.Prop{Name: c.path + name, Lit: l}
		if p.Assume {
			c.e.g.Assumes = append(c.e.g.Assumes, pr)
		} else {
			c.e.g.Asserts = append(c.e.g.Asserts, pr)
		}
	}
}
