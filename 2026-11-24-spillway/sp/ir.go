// Package sp implements Spillway: a three-address IR, liveness analysis,
// two register allocators (graph colouring and linear scan), a K-register
// machine VM with a cost model, and differential verification.
package sp

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// Op is an IR / machine opcode.
type Op int

const (
	OpConst Op = iota // dst = const imm
	OpMov             // dst = mov a
	OpArg             // dst = arg n
	OpAdd
	OpSub
	OpMul
	OpDiv
	OpRem
	OpAnd
	OpOr
	OpXor
	OpShl
	OpShr
	OpLt
	OpLe
	OpEq
	OpNe
	OpLoad    // dst = load addr
	OpStore   // store addr, val
	OpPrint   // print val
	OpBr      // br cond, T, F
	OpJmp     // jmp L
	OpRet     // ret val
	OpSpillLd // dst = spill_ld slot   (machine only)
	OpSpillSt // spill_st slot, src    (machine only)
)

var opNames = map[Op]string{
	OpConst: "const", OpMov: "mov", OpArg: "arg", OpAdd: "add", OpSub: "sub", OpMul: "mul",
	OpDiv: "div", OpRem: "rem", OpAnd: "and", OpOr: "or", OpXor: "xor", OpShl: "shl", OpShr: "shr",
	OpLt: "lt", OpLe: "le", OpEq: "eq", OpNe: "ne", OpLoad: "load", OpStore: "store",
	OpPrint: "print", OpBr: "br", OpJmp: "jmp", OpRet: "ret", OpSpillLd: "spill_ld", OpSpillSt: "spill_st",
}

var nameToOp = func() map[string]Op {
	m := map[string]Op{}
	for o, n := range opNames {
		m[n] = o
	}
	return m
}()

func (o Op) String() string { return opNames[o] }

// IsBinary reports whether o is a two-operand arithmetic/compare op.
func (o Op) IsBinary() bool { return o >= OpAdd && o <= OpNe }

// Operand is a virtual (or, after allocation, physical) register or an immediate.
type Operand struct {
	Imm bool
	Val int64 // immediate value
	Reg int   // register id when !Imm
}

func R(r int) Operand   { return Operand{Reg: r} }
func I(v int64) Operand { return Operand{Imm: true, Val: v} }

// Instr is one instruction. For OpConst/OpArg/OpSpillLd/OpSpillSt the number
// is stored in Args[0].Val (an immediate). Branch targets are block indices.
type Instr struct {
	Op      Op
	Dst     int // -1 when none
	Args    []Operand
	Targets []int
}

// Uses returns the registers read by the instruction.
func (in *Instr) Uses() []int {
	var u []int
	switch in.Op {
	case OpConst, OpArg, OpSpillLd, OpJmp:
		return nil
	}
	for i, a := range in.Args {
		if in.Op == OpSpillSt && i == 0 {
			continue // slot number
		}
		if !a.Imm {
			u = append(u, a.Reg)
		}
	}
	return u
}

// HasDst reports whether the instruction defines a register.
func (in *Instr) HasDst() bool { return in.Dst >= 0 }

// IsTerm reports whether the instruction ends a block.
func (in *Instr) IsTerm() bool { return in.Op == OpBr || in.Op == OpJmp || in.Op == OpRet }

// Block is a basic block.
type Block struct {
	Name   string
	Instrs []Instr
	Succs  []int
	Preds  []int
}

// Function is a single IR function (or its allocated machine form).
type Function struct {
	Name    string
	Params  int // number of declared params (informational; `arg n` reads them)
	Blocks  []*Block
	Names   []string // vreg id -> name (empty after allocation)
	NumRegs int      // number of virtual regs (or physical regs after allocation)
	Slots   int      // stack slots used by spills
}

// Clone deep-copies a function.
func (f *Function) Clone() *Function {
	g := &Function{Name: f.Name, Params: f.Params, NumRegs: f.NumRegs, Slots: f.Slots}
	g.Names = append([]string(nil), f.Names...)
	for _, b := range f.Blocks {
		nb := &Block{Name: b.Name, Succs: append([]int(nil), b.Succs...), Preds: append([]int(nil), b.Preds...)}
		for _, in := range b.Instrs {
			ni := in
			ni.Args = append([]Operand(nil), in.Args...)
			ni.Targets = append([]int(nil), in.Targets...)
			nb.Instrs = append(nb.Instrs, ni)
		}
		g.Blocks = append(g.Blocks, nb)
	}
	return g
}

// NumInstrs counts instructions.
func (f *Function) NumInstrs() int {
	n := 0
	for _, b := range f.Blocks {
		n += len(b.Instrs)
	}
	return n
}

// RegName names a register for printing.
func (f *Function) RegName(r int) string {
	if r >= 0 && r < len(f.Names) && f.Names[r] != "" {
		return f.Names[r]
	}
	return "r" + strconv.Itoa(r)
}

func (f *Function) opnd(o Operand) string {
	if o.Imm {
		return strconv.FormatInt(o.Val, 10)
	}
	return f.RegName(o.Reg)
}

// FormatInstr renders one instruction.
func (f *Function) FormatInstr(in *Instr) string {
	var sb strings.Builder
	if in.HasDst() {
		sb.WriteString(f.RegName(in.Dst) + " = ")
	}
	sb.WriteString(in.Op.String())
	var parts []string
	for _, a := range in.Args {
		parts = append(parts, f.opnd(a))
	}
	for _, t := range in.Targets {
		parts = append(parts, f.Blocks[t].Name)
	}
	if len(parts) > 0 {
		sb.WriteString(" " + strings.Join(parts, ", "))
	}
	return sb.String()
}

// String prints the function in parseable text form.
func (f *Function) String() string {
	var sb strings.Builder
	fmt.Fprintf(&sb, "func %s(%d) {\n", f.Name, f.Params)
	for _, b := range f.Blocks {
		sb.WriteString(b.Name + ":\n")
		for i := range b.Instrs {
			sb.WriteString("  " + f.FormatInstr(&b.Instrs[i]) + "\n")
		}
	}
	sb.WriteString("}\n")
	return sb.String()
}

// ---------- parsing ----------

// ParseError carries a line number.
type ParseError struct {
	Line int
	Msg  string
}

func (e *ParseError) Error() string { return fmt.Sprintf("line %d: %s", e.Line, e.Msg) }

func isIdent(s string) bool {
	if s == "" {
		return false
	}
	for i, c := range s {
		ok := c == '_' || c == '.' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (i > 0 && c >= '0' && c <= '9')
		if !ok {
			return false
		}
	}
	return true
}

// Parse reads the textual IR. Grammar:
//
//	func name(nparams) { label: instr... }
//	instr := [dst =] op operands | store a, v | print v | br c, L1, L2 | jmp L | ret v
//
// Comments start with ';' or '#'. A block that does not end in a terminator
// falls through to the next block with an implicit jmp.
func Parse(src string) (*Function, error) {
	f := &Function{}
	regIdx := map[string]int{}
	reg := func(name string) int {
		if i, ok := regIdx[name]; ok {
			return i
		}
		i := len(f.Names)
		regIdx[name] = i
		f.Names = append(f.Names, name)
		return i
	}
	type pend struct {
		blk, ins, line int
		labels         []string
	}
	var pends []pend
	blockIdx := map[string]int{}
	var cur *Block
	started, closed := false, false
	lines := strings.Split(src, "\n")
	for ln, raw := range lines {
		lineNo := ln + 1
		if i := strings.IndexAny(raw, ";#"); i >= 0 {
			raw = raw[:i]
		}
		line := strings.TrimSpace(raw)
		if line == "" {
			continue
		}
		if closed {
			return nil, &ParseError{lineNo, "text after closing brace"}
		}
		if !started {
			if !strings.HasPrefix(line, "func ") || !strings.HasSuffix(line, "{") {
				return nil, &ParseError{lineNo, "expected `func name(n) {`"}
			}
			h := strings.TrimSpace(strings.TrimSuffix(strings.TrimPrefix(line, "func "), "{"))
			lp, rp := strings.Index(h, "("), strings.LastIndex(h, ")")
			if lp < 0 || rp < lp {
				return nil, &ParseError{lineNo, "bad function header"}
			}
			f.Name = strings.TrimSpace(h[:lp])
			if !isIdent(f.Name) {
				return nil, &ParseError{lineNo, "bad function name"}
			}
			n, err := strconv.Atoi(strings.TrimSpace(h[lp+1 : rp]))
			if err != nil || n < 0 {
				return nil, &ParseError{lineNo, "param count must be a non-negative integer"}
			}
			f.Params = n
			started = true
			continue
		}
		if line == "}" {
			closed = true
			continue
		}
		if strings.HasSuffix(line, ":") {
			name := strings.TrimSuffix(line, ":")
			if !isIdent(name) {
				return nil, &ParseError{lineNo, "bad label " + strconv.Quote(name)}
			}
			if _, dup := blockIdx[name]; dup {
				return nil, &ParseError{lineNo, "duplicate label " + name}
			}
			blockIdx[name] = len(f.Blocks)
			cur = &Block{Name: name}
			f.Blocks = append(f.Blocks, cur)
			continue
		}
		if cur == nil {
			return nil, &ParseError{lineNo, "instruction before first label"}
		}
		in := Instr{Dst: -1}
		body := line
		dst := ""
		if i := strings.Index(body, "="); i >= 0 {
			dst = strings.TrimSpace(body[:i])
			body = strings.TrimSpace(body[i+1:])
			if !isIdent(dst) {
				return nil, &ParseError{lineNo, "bad destination " + strconv.Quote(dst)}
			}
		}
		fields := strings.Fields(body)
		if len(fields) == 0 {
			return nil, &ParseError{lineNo, "missing opcode"}
		}
		op, ok := nameToOp[fields[0]]
		if !ok || op == OpSpillLd || op == OpSpillSt {
			return nil, &ParseError{lineNo, "unknown opcode " + strconv.Quote(fields[0])}
		}
		in.Op = op
		rest := strings.TrimSpace(strings.TrimPrefix(body, fields[0]))
		var args []string
		if rest != "" {
			for _, a := range strings.Split(rest, ",") {
				args = append(args, strings.TrimSpace(a))
			}
		}
		wantDst := op != OpStore && op != OpPrint && op != OpBr && op != OpJmp && op != OpRet
		if wantDst && dst == "" {
			return nil, &ParseError{lineNo, op.String() + " needs a destination (`x = " + op.String() + " ...`)"}
		}
		if !wantDst && dst != "" {
			return nil, &ParseError{lineNo, op.String() + " does not produce a value"}
		}
		nArgs := map[Op]int{OpConst: 1, OpMov: 1, OpArg: 1, OpLoad: 1, OpStore: 2, OpPrint: 1, OpBr: 3, OpJmp: 1, OpRet: 1}
		want := 2
		if n, ok := nArgs[op]; ok {
			want = n
		}
		if len(args) != want {
			return nil, &ParseError{lineNo, fmt.Sprintf("%s takes %d operand(s), got %d", op, want, len(args))}
		}
		parseOpnd := func(s string) (Operand, error) {
			if v, err := strconv.ParseInt(s, 0, 64); err == nil {
				return I(v), nil
			}
			if !isIdent(s) {
				return Operand{}, &ParseError{lineNo, "bad operand " + strconv.Quote(s)}
			}
			return R(reg(s)), nil
		}
		switch op {
		case OpJmp:
			pends = append(pends, pend{len(f.Blocks) - 1, len(cur.Instrs), lineNo, []string{args[0]}})
		case OpBr:
			c, err := parseOpnd(args[0])
			if err != nil {
				return nil, err
			}
			in.Args = []Operand{c}
			pends = append(pends, pend{len(f.Blocks) - 1, len(cur.Instrs), lineNo, []string{args[1], args[2]}})
		case OpConst, OpArg:
			v, err := strconv.ParseInt(args[0], 0, 64)
			if err != nil {
				return nil, &ParseError{lineNo, op.String() + " needs an integer literal"}
			}
			if op == OpArg && v < 0 {
				return nil, &ParseError{lineNo, "arg index must be >= 0"}
			}
			in.Args = []Operand{I(v)}
		default:
			for _, a := range args {
				o, err := parseOpnd(a)
				if err != nil {
					return nil, err
				}
				in.Args = append(in.Args, o)
			}
		}
		if dst != "" {
			in.Dst = reg(dst)
		}
		cur.Instrs = append(cur.Instrs, in)
	}
	if !started {
		return nil, &ParseError{1, "empty program"}
	}
	if !closed {
		return nil, &ParseError{len(lines), "missing closing brace"}
	}
	if len(f.Blocks) == 0 {
		return nil, &ParseError{1, "function has no blocks"}
	}
	// terminators must be last; implicit fallthrough
	for bi, b := range f.Blocks {
		for i := range b.Instrs {
			if b.Instrs[i].IsTerm() && i != len(b.Instrs)-1 {
				return nil, &ParseError{0, fmt.Sprintf("block %s: terminator %s is not last", b.Name, b.Instrs[i].Op)}
			}
		}
		if len(b.Instrs) == 0 || !b.Instrs[len(b.Instrs)-1].IsTerm() {
			if bi+1 >= len(f.Blocks) {
				return nil, &ParseError{0, fmt.Sprintf("block %s falls off the end of the function (needs ret/jmp)", b.Name)}
			}
			b.Instrs = append(b.Instrs, Instr{Op: OpJmp, Dst: -1, Targets: []int{bi + 1}})
		}
	}
	for _, p := range pends {
		in := &f.Blocks[p.blk].Instrs[p.ins]
		for _, l := range p.labels {
			t, ok := blockIdx[l]
			if !ok {
				return nil, &ParseError{p.line, "undefined label " + l}
			}
			in.Targets = append(in.Targets, t)
		}
	}
	f.NumRegs = len(f.Names)
	f.buildEdges()
	return f, nil
}

func (f *Function) buildEdges() {
	for _, b := range f.Blocks {
		b.Succs, b.Preds = nil, nil
	}
	for bi, b := range f.Blocks {
		t := &b.Instrs[len(b.Instrs)-1]
		seen := map[int]bool{}
		for _, s := range t.Targets {
			if !seen[s] {
				seen[s] = true
				b.Succs = append(b.Succs, s)
				f.Blocks[s].Preds = append(f.Blocks[s].Preds, bi)
			}
		}
	}
}

// Reachable returns the set of blocks reachable from the entry.
func (f *Function) Reachable() []bool {
	seen := make([]bool, len(f.Blocks))
	var walk func(int)
	walk = func(b int) {
		if seen[b] {
			return
		}
		seen[b] = true
		for _, s := range f.Blocks[b].Succs {
			walk(s)
		}
	}
	walk(0)
	return seen
}

// Validate checks structural soundness and that no register may be read
// before it is defined (live-in at entry must be empty, over reachable code).
func (f *Function) Validate() error {
	rc := f.Reachable()
	hasRet := false
	for bi, b := range f.Blocks {
		if rc[bi] && b.Instrs[len(b.Instrs)-1].Op == OpRet {
			hasRet = true
		}
	}
	if !hasRet {
		return fmt.Errorf("no reachable `ret`: function can never return")
	}
	lv := f.Liveness()
	if len(lv.In[0]) > 0 && lv.In[0].count() > 0 {
		var names []string
		lv.In[0].each(func(r int) { names = append(names, f.RegName(r)) })
		sort.Strings(names)
		return fmt.Errorf("possibly-undefined register(s) read before assignment: %s", strings.Join(names, ", "))
	}
	return nil
}
