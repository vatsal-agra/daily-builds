package sable

import (
	"fmt"
	"sort"
	"strings"
)

type Op uint8

const (
	OpConst Op = iota
	OpParam    // Imm = parameter index
	OpLoad     // Imm = slot (pre-SSA only)
	OpStore    // Imm = slot, Args[0] = value (pre-SSA only)
	OpPhi      // Args[i] flows in from Block.Preds[i]
	OpAdd
	OpSub
	OpMul
	OpDiv
	OpMod
	OpAnd
	OpOr
	OpXor
	OpShl
	OpShr
	OpLt
	OpLe
	OpGt
	OpGe
	OpEq
	OpNe
	OpNeg
	OpNot
	OpBNot
	OpCall  // Callee, Args
	OpPrint // Args[0]
	numOps
)

var opName = [numOps]string{"const", "param", "load", "store", "phi", "add", "sub", "mul", "div", "mod",
	"and", "or", "xor", "shl", "shr", "lt", "le", "gt", "ge", "eq", "ne", "neg", "not", "bnot", "call", "print"}

var opSym = map[Op]string{OpAdd: "+", OpSub: "-", OpMul: "*", OpDiv: "/", OpMod: "%", OpAnd: "&", OpOr: "|",
	OpXor: "^", OpShl: "<<", OpShr: ">>", OpLt: "<", OpLe: "<=", OpGt: ">", OpGe: ">=", OpEq: "==", OpNe: "!=",
	OpNeg: "-", OpNot: "!", OpBNot: "~"}

var binOpOf = map[string]Op{"+": OpAdd, "-": OpSub, "*": OpMul, "/": OpDiv, "%": OpMod, "&": OpAnd, "|": OpOr,
	"^": OpXor, "<<": OpShl, ">>": OpShr, "<": OpLt, "<=": OpLe, ">": OpGt, ">=": OpGe, "==": OpEq, "!=": OpNe}

func (o Op) String() string  { return opName[o] }
func (o Op) IsBinary() bool  { return o >= OpAdd && o <= OpNe }
func (o Op) IsUnary() bool   { return o >= OpNeg && o <= OpBNot }
func (o Op) IsCompare() bool { return o >= OpLt && o <= OpNe }
func (o Op) Commutative() bool {
	switch o {
	case OpAdd, OpMul, OpAnd, OpOr, OpXor, OpEq, OpNe:
		return true
	}
	return false
}

// Value is an SSA value (or, pre-SSA, an instruction).
type Value struct {
	ID     int
	Op     Op
	Args   []*Value
	Imm    int64
	Callee string
	Block  *Block
}

func (v *Value) String() string { return fmt.Sprintf("v%d", v.ID) }

// HasSideEffect reports whether v must be kept even when unused.
func (v *Value) HasSideEffect() bool {
	switch v.Op {
	case OpStore, OpCall, OpPrint:
		return true
	case OpDiv, OpMod:
		// may trap unless the divisor is a known non-zero constant
		d := v.Args[1]
		return !(d.Op == OpConst && d.Imm != 0)
	}
	return false
}

// Pure reports whether v can be freely duplicated/merged/moved if its args dominate.
func (v *Value) Pure() bool {
	switch v.Op {
	case OpConst, OpAdd, OpSub, OpMul, OpAnd, OpOr, OpXor, OpShl, OpShr, OpLt, OpLe, OpGt, OpGe, OpEq, OpNe, OpNeg, OpNot, OpBNot:
		return true
	case OpDiv, OpMod:
		return !v.HasSideEffect()
	}
	return false
}

type Kind uint8

const (
	KJump Kind = iota
	KBr
	KRet
)

type Block struct {
	ID     int
	Instrs []*Value
	Kind   Kind
	Ctrl   *Value   // KBr condition / KRet value
	Succs  []*Block // KJump: [t]; KBr: [ifTrue, ifFalse]
	Preds  []*Block
	Fn     *Func
}

func (b *Block) String() string { return fmt.Sprintf("b%d", b.ID) }

type Func struct {
	Name    string
	NParams int
	NSlots  int
	Blocks  []*Block
	Entry   *Block
	nextVal int
	nextBlk int
}

type Module struct {
	Funcs  []*Func
	ByName map[string]*Func
}

func (m *Module) Func(name string) *Func { return m.ByName[name] }

func NewFunc(name string, nparams int) *Func {
	f := &Func{Name: name, NParams: nparams}
	f.Entry = f.NewBlock()
	return f
}

func (f *Func) NewBlock() *Block {
	b := &Block{ID: f.nextBlk, Fn: f}
	f.nextBlk++
	f.Blocks = append(f.Blocks, b)
	return b
}

func (f *Func) newValue(op Op, args ...*Value) *Value {
	v := &Value{ID: f.nextVal, Op: op, Args: args}
	f.nextVal++
	return v
}

// Emit appends a new value at the end of b's instructions.
func (b *Block) Emit(op Op, args ...*Value) *Value {
	v := b.Fn.newValue(op, args...)
	v.Block = b
	b.Instrs = append(b.Instrs, v)
	return v
}
func (b *Block) EmitConst(c int64) *Value {
	v := b.Emit(OpConst)
	v.Imm = c
	return v
}

// InsertAt inserts v (already allocated by newValue) at index i.
func (b *Block) insertAt(i int, v *Value) {
	v.Block = b
	b.Instrs = append(b.Instrs, nil)
	copy(b.Instrs[i+1:], b.Instrs[i:])
	b.Instrs[i] = v
}

// NumPhis returns how many leading instructions are phis.
func (b *Block) NumPhis() int {
	n := 0
	for n < len(b.Instrs) && b.Instrs[n].Op == OpPhi {
		n++
	}
	return n
}

// ---- CFG editing ----

func link(from, to *Block) {
	from.Succs = append(from.Succs, to)
	to.Preds = append(to.Preds, from)
}

func (b *Block) SetJump(to *Block) {
	b.Kind, b.Ctrl, b.Succs = KJump, nil, nil
	link(b, to)
}
func (b *Block) SetBr(c *Value, t, f *Block) {
	b.Kind, b.Ctrl, b.Succs = KBr, c, nil
	link(b, t)
	link(b, f)
}
func (b *Block) SetRet(v *Value) { b.Kind, b.Ctrl, b.Succs = KRet, v, nil }

func (b *Block) predIndex(p *Block) int {
	for i, q := range b.Preds {
		if q == p {
			return i
		}
	}
	return -1
}

// removePredAt deletes predecessor i and the matching phi operands.
func (b *Block) removePredAt(i int) {
	for _, v := range b.Instrs {
		if v.Op != OpPhi {
			break
		}
		v.Args = append(v.Args[:i:i], v.Args[i+1:]...)
	}
	b.Preds = append(b.Preds[:i:i], b.Preds[i+1:]...)
}

// unlinkSucc removes one edge from b to its succ slot idx (without touching b.Succs).
func dropEdgeTo(from, to *Block) {
	if i := to.predIndex(from); i >= 0 {
		to.removePredAt(i)
	}
}

// replaceAllUses rewrites every use of a key in m (transitively) with its value.
func (f *Func) replaceAllUses(m map[*Value]*Value) {
	if len(m) == 0 {
		return
	}
	res := func(v *Value) *Value {
		for n := 0; ; n++ {
			w, ok := m[v]
			if !ok || w == v {
				return v
			}
			if n > len(m)+1 {
				panic("replaceAllUses: cycle")
			}
			v = w
		}
	}
	for _, b := range f.Blocks {
		for _, v := range b.Instrs {
			for i, a := range v.Args {
				v.Args[i] = res(a)
			}
		}
		if b.Ctrl != nil {
			b.Ctrl = res(b.Ctrl)
		}
	}
}

func (f *Func) replaceUse(old, new *Value) { f.replaceAllUses(map[*Value]*Value{old: new}) }

// removeBlocks drops blocks not in keep and fixes preds of the survivors.
func (f *Func) removeUnreachable() bool {
	seen := map[*Block]bool{f.Entry: true}
	stack := []*Block{f.Entry}
	for len(stack) > 0 {
		b := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		for _, s := range b.Succs {
			if !seen[s] {
				seen[s] = true
				stack = append(stack, s)
			}
		}
	}
	if len(seen) == len(f.Blocks) {
		return false
	}
	var keep []*Block
	for _, b := range f.Blocks {
		if seen[b] {
			keep = append(keep, b)
		}
	}
	for _, b := range keep {
		for i := len(b.Preds) - 1; i >= 0; i-- {
			if !seen[b.Preds[i]] {
				b.removePredAt(i)
			}
		}
	}
	f.Blocks = keep
	return true
}

// NumInstrs counts non-terminator instructions.
func (f *Func) NumInstrs() int {
	n := 0
	for _, b := range f.Blocks {
		n += len(b.Instrs)
	}
	return n
}

// ---- printing ----

func (v *Value) Format() string {
	var sb strings.Builder
	args := func() string {
		s := make([]string, len(v.Args))
		for i, a := range v.Args {
			s[i] = a.String()
		}
		return strings.Join(s, ", ")
	}
	switch v.Op {
	case OpConst:
		fmt.Fprintf(&sb, "%s = const %d", v, v.Imm)
	case OpParam:
		fmt.Fprintf(&sb, "%s = param %d", v, v.Imm)
	case OpLoad:
		fmt.Fprintf(&sb, "%s = load $%d", v, v.Imm)
	case OpStore:
		fmt.Fprintf(&sb, "store $%d, %s", v.Imm, args())
	case OpPhi:
		var ps []string
		for i, a := range v.Args {
			from := "?"
			if v.Block != nil && i < len(v.Block.Preds) {
				from = v.Block.Preds[i].String()
			}
			ps = append(ps, fmt.Sprintf("[%s: %s]", from, a))
		}
		fmt.Fprintf(&sb, "%s = phi %s", v, strings.Join(ps, " "))
	case OpCall:
		fmt.Fprintf(&sb, "%s = call %s(%s)", v, v.Callee, args())
	case OpPrint:
		fmt.Fprintf(&sb, "print %s", args())
	default:
		fmt.Fprintf(&sb, "%s = %s %s", v, v.Op, args())
	}
	return sb.String()
}

func (b *Block) FormatTerm() string {
	switch b.Kind {
	case KJump:
		return fmt.Sprintf("jmp %s", b.Succs[0])
	case KBr:
		return fmt.Sprintf("br %s, %s, %s", b.Ctrl, b.Succs[0], b.Succs[1])
	}
	return fmt.Sprintf("ret %s", b.Ctrl)
}

func (f *Func) String() string {
	var sb strings.Builder
	fmt.Fprintf(&sb, "func %s(%d):\n", f.Name, f.NParams)
	for _, b := range f.Blocks {
		var ps []string
		for _, p := range b.Preds {
			ps = append(ps, p.String())
		}
		fmt.Fprintf(&sb, "  %s:", b)
		if len(ps) > 0 {
			fmt.Fprintf(&sb, "   ; preds %s", strings.Join(ps, " "))
		}
		sb.WriteByte('\n')
		for _, v := range b.Instrs {
			fmt.Fprintf(&sb, "    %s\n", v.Format())
		}
		fmt.Fprintf(&sb, "    %s\n", b.FormatTerm())
	}
	return sb.String()
}

func (m *Module) String() string {
	var sb strings.Builder
	for _, f := range m.Funcs {
		sb.WriteString(f.String())
	}
	return sb.String()
}

// sortedBlocksByID is a helper for deterministic iteration.
func sortedBlocksByID(bs []*Block) []*Block {
	out := append([]*Block(nil), bs...)
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

// renumber compacts value and block IDs so dumps stay readable.
func (f *Func) renumber() {
	f.nextVal = 0
	for i, b := range f.Blocks {
		b.ID = i
	}
	f.nextBlk = len(f.Blocks)
	for _, b := range f.Blocks {
		for _, v := range b.Instrs {
			v.ID = f.nextVal
			f.nextVal++
		}
	}
}

// Clone deep-copies a module (so pipelines can be compared stage by stage).
func (m *Module) Clone() *Module {
	nm := &Module{ByName: map[string]*Func{}}
	for _, f := range m.Funcs {
		nf := f.Clone()
		nm.Funcs = append(nm.Funcs, nf)
		nm.ByName[nf.Name] = nf
	}
	return nm
}

func (f *Func) Clone() *Func {
	nf := &Func{Name: f.Name, NParams: f.NParams, NSlots: f.NSlots, nextVal: f.nextVal, nextBlk: f.nextBlk}
	bm := map[*Block]*Block{}
	vm := map[*Value]*Value{}
	for _, b := range f.Blocks {
		nb := &Block{ID: b.ID, Kind: b.Kind, Fn: nf}
		bm[b] = nb
		nf.Blocks = append(nf.Blocks, nb)
	}
	nf.Entry = bm[f.Entry]
	for _, b := range f.Blocks {
		for _, v := range b.Instrs {
			nv := &Value{ID: v.ID, Op: v.Op, Imm: v.Imm, Callee: v.Callee, Block: bm[b]}
			vm[v] = nv
			bm[b].Instrs = append(bm[b].Instrs, nv)
		}
	}
	for _, b := range f.Blocks {
		nb := bm[b]
		for i, v := range b.Instrs {
			nv := nb.Instrs[i]
			nv.Args = make([]*Value, len(v.Args))
			for j, a := range v.Args {
				nv.Args[j] = vm[a]
			}
		}
		if b.Ctrl != nil {
			nb.Ctrl = vm[b.Ctrl]
		}
		for _, s := range b.Succs {
			nb.Succs = append(nb.Succs, bm[s])
		}
		for _, p := range b.Preds {
			nb.Preds = append(nb.Preds, bm[p])
		}
	}
	return nf
}
