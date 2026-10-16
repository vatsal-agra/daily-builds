// Package ir defines Dominion's SSA intermediate representation.
package ir

import (
	"fmt"
	"sort"
)

// Op is an instruction opcode.
type Op int

const (
	OpInvalid Op = iota
	OpConst
	OpParam
	OpAlloca // Const = number of words
	OpAdd
	OpSub
	OpMul
	OpDiv // signed, traps on zero
	OpRem
	OpAnd
	OpOr
	OpXor
	OpShl
	OpShr // arithmetic
	OpEq
	OpNe
	OpLt
	OpLe
	OpGt
	OpGe
	OpNeg
	OpNot // bitwise complement
	OpSelect
	OpLoad  // Args: slot(alloca), idx
	OpStore // Args: slot, idx, val
	OpCall  // Callee, Args
	OpPrint // Args: val
	OpPhi   // Args aligned with Block.Preds
	numOps
)

var opNames = [...]string{
	"invalid", "const", "param", "alloca", "add", "sub", "mul", "div", "rem", "and", "or", "xor",
	"shl", "shr", "eq", "ne", "lt", "le", "gt", "ge", "neg", "not", "select", "load", "store",
	"call", "print", "phi",
}

func (o Op) String() string {
	if o >= 0 && int(o) < len(opNames) {
		return opNames[o]
	}
	return "?"
}

// OpByName looks up an opcode by its textual name.
func OpByName(s string) (Op, bool) {
	for i, n := range opNames {
		if n == s && Op(i) != OpInvalid && Op(i) != OpConst && Op(i) != OpParam {
			return Op(i), true
		}
	}
	return 0, false
}

func (o Op) IsBinary() bool  { return o >= OpAdd && o <= OpGe }
func (o Op) IsCompare() bool { return o >= OpEq && o <= OpGe }
func (o Op) IsCommutative() bool {
	switch o {
	case OpAdd, OpMul, OpAnd, OpOr, OpXor, OpEq, OpNe:
		return true
	}
	return false
}

// NumArgs returns the fixed arity of an opcode (-1 for variable).
func (o Op) NumArgs() int {
	switch {
	case o.IsBinary():
		return 2
	}
	switch o {
	case OpNeg, OpNot, OpPrint:
		return 1
	case OpSelect, OpStore:
		return 3
	case OpLoad:
		return 2
	}
	return -1
}

// Value is both an instruction and the SSA value it defines.
type Value struct {
	ID     int
	Op     Op
	Args   []*Value
	Const  int64  // OpConst value, OpAlloca size
	Callee string // OpCall
	Block  *Block // nil for constants and params
	Index  int    // OpParam index
}

func (v *Value) IsConst() bool { return v.Op == OpConst }

// HasResult reports whether the instruction defines a usable value.
func (v *Value) HasResult() bool { return v.Op != OpStore && v.Op != OpPrint }

// Terminator kinds.
type TermKind int

const (
	TermNone TermKind = iota
	TermBr
	TermCondBr
	TermRet
)

// Block is a basic block.
type Block struct {
	Name   string
	ID     int
	Fn     *Func
	Phis   []*Value
	Instrs []*Value
	Term   TermKind
	Ctrl   *Value // condbr condition or ret value
	Succs  []*Block
	Preds  []*Block
}

// Func is a function.
type Func struct {
	Name    string
	Params  []*Value
	Blocks  []*Block // Blocks[0] is the entry
	consts  map[int64]*Value
	nextID  int
	nextBlk int
}

// Module is a set of functions.
type Module struct {
	Funcs []*Func
}

func (m *Module) Func(name string) *Func {
	for _, f := range m.Funcs {
		if f.Name == name {
			return f
		}
	}
	return nil
}

func NewFunc(name string, nparams int) *Func {
	f := &Func{Name: name, consts: map[int64]*Value{}}
	for i := 0; i < nparams; i++ {
		f.Params = append(f.Params, &Value{ID: f.NewID(), Op: OpParam, Index: i})
	}
	return f
}

func (f *Func) NewID() int { f.nextID++; return f.nextID - 1 }

// NumIDs is an upper bound on value IDs (for dense tables).
func (f *Func) NumIDs() int { return f.nextID }

// NumBlockIDs is an upper bound on block IDs.
func (f *Func) NumBlockIDs() int { return f.nextBlk }

func (f *Func) Entry() *Block { return f.Blocks[0] }

// Const returns the uniqued constant value.
func (f *Func) Const(c int64) *Value {
	if v, ok := f.consts[c]; ok {
		return v
	}
	v := &Value{ID: f.NewID(), Op: OpConst, Const: c}
	f.consts[c] = v
	return v
}

// NewBlock appends a fresh block.
func (f *Func) NewBlock(name string) *Block {
	b := &Block{Name: name, ID: f.nextBlk, Fn: f}
	f.nextBlk++
	f.Blocks = append(f.Blocks, b)
	return b
}

// UniqueBlockName avoids collisions in printed names.
func (f *Func) UniqueBlockName(base string) string {
	used := map[string]bool{}
	for _, b := range f.Blocks {
		used[b.Name] = true
	}
	if !used[base] {
		return base
	}
	for i := 1; ; i++ {
		n := fmt.Sprintf("%s.%d", base, i)
		if !used[n] {
			return n
		}
	}
}

// NewValue creates (but does not insert) an instruction.
func (f *Func) NewValue(op Op, args ...*Value) *Value {
	return &Value{ID: f.NewID(), Op: op, Args: append([]*Value(nil), args...)}
}

// Append adds v at the end of block b (phis go to the phi list).
func (b *Block) Append(v *Value) *Value {
	v.Block = b
	if v.Op == OpPhi {
		b.Phis = append(b.Phis, v)
	} else {
		b.Instrs = append(b.Instrs, v)
	}
	return v
}

// InsertBefore inserts v before position idx of Instrs.
func (b *Block) InsertAt(idx int, v *Value) {
	v.Block = b
	b.Instrs = append(b.Instrs, nil)
	copy(b.Instrs[idx+1:], b.Instrs[idx:])
	b.Instrs[idx] = v
}

// SetBr sets an unconditional branch terminator.
func (b *Block) SetBr(t *Block) {
	b.clearTerm()
	b.Term = TermBr
	b.Succs = []*Block{t}
	t.Preds = append(t.Preds, b)
}

func (b *Block) SetCondBr(c *Value, t, e *Block) {
	b.clearTerm()
	b.Term = TermCondBr
	b.Ctrl = c
	b.Succs = []*Block{t, e}
	t.Preds = append(t.Preds, b)
	e.Preds = append(e.Preds, b)
}

func (b *Block) SetRet(v *Value) {
	b.clearTerm()
	b.Term = TermRet
	b.Ctrl = v
}

// clearTerm detaches the block from successors' pred lists WITHOUT touching phis
// (callers that re-target edges must maintain phis themselves).
func (b *Block) clearTerm() {
	for _, s := range b.Succs {
		s.removePredOnce(b)
	}
	b.Term = TermNone
	b.Ctrl = nil
	b.Succs = nil
}

func (b *Block) removePredOnce(p *Block) {
	for i, q := range b.Preds {
		if q == p {
			b.Preds = append(b.Preds[:i], b.Preds[i+1:]...)
			return
		}
	}
}

// PredIndex returns the index of p in b.Preds, or -1.
func (b *Block) PredIndex(p *Block) int {
	for i, q := range b.Preds {
		if q == p {
			return i
		}
	}
	return -1
}

// RemovePredEdge removes pred p (one occurrence) and the matching phi args.
func (b *Block) RemovePredEdge(p *Block) {
	i := b.PredIndex(p)
	if i < 0 {
		return
	}
	b.Preds = append(b.Preds[:i], b.Preds[i+1:]...)
	for _, ph := range b.Phis {
		ph.Args = append(ph.Args[:i], ph.Args[i+1:]...)
	}
}

// ReplaceSucc retargets the terminator edge b->old to b->new keeping phis consistent
// on the old side (removed) — new-side phi args must be added by the caller.
func (b *Block) ReplaceSucc(old, nw *Block) {
	for i, s := range b.Succs {
		if s == old {
			b.Succs[i] = nw
			nw.Preds = append(nw.Preds, b)
			old.RemovePredEdge(b)
			return
		}
	}
}

// AllValues iterates every instruction (phis then instrs) in block order.
func (f *Func) ForEachInstr(fn func(b *Block, v *Value)) {
	for _, b := range f.Blocks {
		for _, v := range b.Phis {
			fn(b, v)
		}
		for _, v := range b.Instrs {
			fn(b, v)
		}
	}
}

// ReplaceAllUses rewrites every use of old with nw (args and terminators).
func (f *Func) ReplaceAllUses(old, nw *Value) {
	for _, b := range f.Blocks {
		for _, v := range b.Phis {
			for i, a := range v.Args {
				if a == old {
					v.Args[i] = nw
				}
			}
		}
		for _, v := range b.Instrs {
			for i, a := range v.Args {
				if a == old {
					v.Args[i] = nw
				}
			}
		}
		if b.Ctrl == old {
			b.Ctrl = nw
		}
	}
}

// UseCounts returns, per value ID, how many operand slots reference it.
func (f *Func) UseCounts() []int {
	n := make([]int, f.NumIDs())
	f.ForEachInstr(func(b *Block, v *Value) {
		for _, a := range v.Args {
			n[a.ID]++
		}
	})
	for _, b := range f.Blocks {
		if b.Ctrl != nil {
			n[b.Ctrl.ID]++
		}
	}
	return n
}

// RemoveInstr deletes v from its block.
func (b *Block) RemoveInstr(v *Value) {
	l := &b.Instrs
	if v.Op == OpPhi {
		l = &b.Phis
	}
	for i, x := range *l {
		if x == v {
			*l = append((*l)[:i], (*l)[i+1:]...)
			return
		}
	}
}

// Side-effect and purity queries.

// HasSideEffect: must be kept even if unused.
func (v *Value) HasSideEffect() bool {
	switch v.Op {
	case OpStore, OpPrint, OpCall:
		return true
	case OpDiv, OpRem:
		// may trap unless the divisor is a known non-zero (and not -1 for overflow-free) constant
		d := v.Args[1]
		return !(d.IsConst() && d.Const != 0)
	}
	return false
}

// IsPure: result depends only on operands, no effects, safe to CSE/hoist (div excluded when it may trap).
func (v *Value) IsPure() bool {
	switch v.Op {
	case OpConst, OpParam, OpAlloca, OpLoad, OpStore, OpCall, OpPrint, OpPhi:
		return false
	}
	return !v.HasSideEffect()
}

// RemoveUnreachable deletes blocks not reachable from entry, fixing preds/phis.
func (f *Func) RemoveUnreachable() bool {
	seen := map[*Block]bool{}
	var walk func(b *Block)
	walk = func(b *Block) {
		if seen[b] {
			return
		}
		seen[b] = true
		for _, s := range b.Succs {
			walk(s)
		}
	}
	walk(f.Entry())
	if len(seen) == len(f.Blocks) {
		return false
	}
	var keep []*Block
	for _, b := range f.Blocks {
		if seen[b] {
			keep = append(keep, b)
			continue
		}
		for _, s := range b.Succs {
			if seen[s] {
				s.RemovePredEdge(b)
			}
		}
	}
	f.Blocks = keep
	return true
}

// SortedFuncNames is a helper for deterministic output.
func (m *Module) SortedFuncNames() []string {
	var n []string
	for _, f := range m.Funcs {
		n = append(n, f.Name)
	}
	sort.Strings(n)
	return n
}

// Replacer batches "replace all uses of old with new" requests so that a pass can rewrite the whole
// function in one linear sweep (Apply) instead of one sweep per replacement.
type Replacer struct{ m map[*Value]*Value }

func NewReplacer() *Replacer { return &Replacer{m: map[*Value]*Value{}} }

// Add records old -> nw (nw may itself be replaced later; Resolve follows chains).
func (r *Replacer) Add(old, nw *Value) { r.m[old] = nw }

// Len is the number of recorded replacements.
func (r *Replacer) Len() int { return len(r.m) }

// Resolve follows replacement chains.
func (r *Replacer) Resolve(v *Value) *Value {
	for {
		n, ok := r.m[v]
		if !ok {
			return v
		}
		v = n
	}
}

// ResolveArgs rewrites the operands of v in place.
func (r *Replacer) ResolveArgs(v *Value) {
	for i, a := range v.Args {
		v.Args[i] = r.Resolve(a)
	}
}

// Apply rewrites every operand and terminator control value in f, then clears the batch.
func (f *Func) Apply(r *Replacer) {
	if len(r.m) == 0 {
		return
	}
	for _, b := range f.Blocks {
		for _, v := range b.Phis {
			r.ResolveArgs(v)
		}
		for _, v := range b.Instrs {
			r.ResolveArgs(v)
		}
		if b.Ctrl != nil {
			b.Ctrl = r.Resolve(b.Ctrl)
		}
	}
	r.m = map[*Value]*Value{}
}
