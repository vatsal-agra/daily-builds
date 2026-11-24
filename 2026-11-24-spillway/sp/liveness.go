package sp

import "math/bits"

// Bitset is a fixed-capacity set of small non-negative ints.
type Bitset []uint64

func NewBitset(n int) Bitset { return make(Bitset, (n+63)/64) }
func (b Bitset) Set(i int)   { b[i>>6] |= 1 << uint(i&63) }
func (b Bitset) Clear(i int) { b[i>>6] &^= 1 << uint(i&63) }
func (b Bitset) Has(i int) bool {
	return i>>6 < len(b) && b[i>>6]&(1<<uint(i&63)) != 0
}
func (b Bitset) Copy() Bitset { return append(Bitset(nil), b...) }
func (b Bitset) count() int {
	n := 0
	for _, w := range b {
		n += bits.OnesCount64(w)
	}
	return n
}
func (b Bitset) each(fn func(int)) {
	for wi, w := range b {
		for w != 0 {
			t := bits.TrailingZeros64(w)
			fn(wi*64 + t)
			w &= w - 1
		}
	}
}

// union ORs o into b and reports whether b changed.
func (b Bitset) union(o Bitset) bool {
	ch := false
	for i := range b {
		n := b[i] | o[i]
		if n != b[i] {
			b[i], ch = n, true
		}
	}
	return ch
}

// Liveness holds block-level live-in/live-out sets.
type Liveness struct {
	In, Out []Bitset
}

// Liveness runs backward iterative dataflow to a fixed point.
func (f *Function) Liveness() *Liveness {
	n := len(f.Blocks)
	use := make([]Bitset, n)
	def := make([]Bitset, n)
	lv := &Liveness{In: make([]Bitset, n), Out: make([]Bitset, n)}
	for i, b := range f.Blocks {
		use[i], def[i] = NewBitset(f.NumRegs), NewBitset(f.NumRegs)
		lv.In[i], lv.Out[i] = NewBitset(f.NumRegs), NewBitset(f.NumRegs)
		for j := range b.Instrs {
			in := &b.Instrs[j]
			for _, u := range in.Uses() {
				if !def[i].Has(u) {
					use[i].Set(u)
				}
			}
			if in.HasDst() {
				def[i].Set(in.Dst)
			}
		}
	}
	for changed := true; changed; {
		changed = false
		for i := n - 1; i >= 0; i-- {
			b := f.Blocks[i]
			for _, s := range b.Succs {
				if lv.Out[i].union(lv.In[s]) {
					changed = true
				}
			}
			// in = use ∪ (out − def)
			nin := lv.Out[i].Copy()
			for w := range nin {
				nin[w] &^= def[i][w]
				nin[w] |= use[i][w]
			}
			if lv.In[i].union(nin) {
				changed = true
			}
		}
	}
	return lv
}

// LiveAfter calls fn(blockIdx, instrIdx, liveAfterSet) for every instruction,
// walking each block backwards. The set passed to fn is reused: copy it to keep it.
func (f *Function) LiveAfter(lv *Liveness, fn func(bi, ii int, live Bitset)) {
	for bi, b := range f.Blocks {
		live := lv.Out[bi].Copy()
		for ii := len(b.Instrs) - 1; ii >= 0; ii-- {
			in := &b.Instrs[ii]
			fn(bi, ii, live)
			if in.HasDst() {
				live.Clear(in.Dst)
			}
			for _, u := range in.Uses() {
				live.Set(u)
			}
		}
	}
}

// LoopDepth computes, for each block, the number of natural loops containing it.
func (f *Function) LoopDepth() []int {
	n := len(f.Blocks)
	rc := f.Reachable()
	// iterative dominator sets
	dom := make([]Bitset, n)
	for i := range dom {
		dom[i] = NewBitset(n)
		if i == 0 {
			dom[i].Set(0)
		} else {
			for j := 0; j < n; j++ {
				dom[i].Set(j)
			}
		}
	}
	for changed := true; changed; {
		changed = false
		for i := 1; i < n; i++ {
			if !rc[i] {
				continue
			}
			nd := NewBitset(n)
			first := true
			for _, p := range f.Blocks[i].Preds {
				if !rc[p] {
					continue
				}
				if first {
					copy(nd, dom[p])
					first = false
				} else {
					for w := range nd {
						nd[w] &= dom[p][w]
					}
				}
			}
			if first {
				continue
			}
			nd.Set(i)
			for w := range nd {
				if nd[w] != dom[i][w] {
					changed = true
					dom[i] = nd
					break
				}
			}
		}
	}
	depth := make([]int, n)
	// group back edges by header; a header's loop is the union of its back-edge bodies
	bodies := map[int]Bitset{}
	for t := 0; t < n; t++ {
		if !rc[t] {
			continue
		}
		for _, h := range f.Blocks[t].Succs {
			if !dom[t].Has(h) {
				continue
			}
			body, ok := bodies[h]
			if !ok {
				body = NewBitset(n)
				body.Set(h)
				bodies[h] = body
			}
			stack := []int{t}
			for len(stack) > 0 {
				x := stack[len(stack)-1]
				stack = stack[:len(stack)-1]
				if body.Has(x) {
					continue
				}
				body.Set(x)
				stack = append(stack, f.Blocks[x].Preds...)
			}
		}
	}
	for _, body := range bodies {
		body.each(func(b int) { depth[b]++ })
	}
	return depth
}

// Interval is a conservative single live range [Start, End] over doubled
// positions: for the instruction numbered p, its uses happen at 2p and its
// definition at 2p+1; live-in at a block start is 2*first, live-out at a block
// end is 2*last+1. Two intervals conflict iff neither ends before the other starts.
type Interval struct {
	Reg        int
	Start, End int
}

// Position numbering: instruction number k (counting across blocks in layout
// order) occupies position k. Block b spans [BlockStart[b], BlockEnd[b]].
type Numbering struct {
	BlockStart, BlockEnd []int
	Total                int
}

// Intervals builds one conservative live interval per register that is ever
// live or defined, using block live-in/out to extend across control flow.
func (f *Function) Intervals(lv *Liveness) ([]Interval, *Numbering) {
	nm := &Numbering{BlockStart: make([]int, len(f.Blocks)), BlockEnd: make([]int, len(f.Blocks))}
	pos := 0
	for i, b := range f.Blocks {
		nm.BlockStart[i] = pos
		pos += len(b.Instrs)
		nm.BlockEnd[i] = pos - 1
	}
	nm.Total = pos
	start := make([]int, f.NumRegs)
	end := make([]int, f.NumRegs)
	for i := range start {
		start[i], end[i] = 1<<30, -1
	}
	touch := func(r, p int) {
		if p < start[r] {
			start[r] = p
		}
		if p > end[r] {
			end[r] = p
		}
	}
	for bi, b := range f.Blocks {
		lv.In[bi].each(func(r int) { touch(r, 2*nm.BlockStart[bi]) })
		lv.Out[bi].each(func(r int) { touch(r, 2*nm.BlockEnd[bi]+1) })
		for ii := range b.Instrs {
			in := &b.Instrs[ii]
			p := nm.BlockStart[bi] + ii
			if in.HasDst() {
				touch(in.Dst, 2*p+1)
			}
			for _, u := range in.Uses() {
				touch(u, 2*p)
			}
		}
	}
	var out []Interval
	for r := 0; r < f.NumRegs; r++ {
		if end[r] >= 0 {
			out = append(out, Interval{r, start[r], end[r]})
		}
	}
	return out, nm
}
