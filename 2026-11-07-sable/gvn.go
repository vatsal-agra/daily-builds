package sable

import (
	"fmt"
	"sort"
)

// GVN performs dominator-tree-scoped global value numbering: an instruction is
// replaced by an equal one that dominates it. Commutative operands are ordered
// canonically; phis are keyed per block; div/mod are numbered too (a dominating
// identical division would already have trapped).
func GVN(f *Func) bool {
	an := Analyze(f)
	type scope struct{ keys []string }
	table := map[string]*Value{}
	repl := map[*Value]*Value{}
	res := func(v *Value) *Value {
		for {
			w, ok := repl[v]
			if !ok {
				return v
			}
			v = w
		}
	}
	key := func(v *Value) (string, bool) {
		switch {
		case v.Op == OpConst:
			return fmt.Sprintf("c%d", v.Imm), true
		case v.Op == OpPhi:
			s := fmt.Sprintf("phi@%d", v.Block.ID)
			for _, a := range v.Args {
				s += fmt.Sprintf(",%d", a.ID)
			}
			return s, true
		case v.Op == OpParam:
			return fmt.Sprintf("p%d", v.Imm), true
		case v.Op.IsBinary() || v.Op.IsUnary():
			ids := make([]int, len(v.Args))
			for i, a := range v.Args {
				ids[i] = a.ID
			}
			if v.Op.Commutative() {
				sort.Ints(ids)
			}
			return fmt.Sprintf("%d%v", v.Op, ids), true
		}
		return "", false
	}
	changed := false
	var walk func(b *Block)
	walk = func(b *Block) {
		var added []string
		for _, v := range b.Instrs {
			for i, a := range v.Args {
				v.Args[i] = res(a)
			}
			k, ok := key(v)
			if !ok {
				continue
			}
			if lead, found := table[k]; found {
				repl[v] = lead
				changed = true
				continue
			}
			table[k] = v
			added = append(added, k)
		}
		if b.Ctrl != nil {
			b.Ctrl = res(b.Ctrl)
		}
		for _, c := range an.Children[b] {
			walk(c)
		}
		for _, k := range added {
			delete(table, k)
		}
	}
	walk(f.Entry)
	if !changed {
		return false
	}
	for _, b := range f.Blocks {
		keep := b.Instrs[:0]
		for _, v := range b.Instrs {
			if _, dead := repl[v]; !dead {
				keep = append(keep, v)
			}
		}
		b.Instrs = keep
	}
	f.replaceAllUses(repl)
	return true
}
