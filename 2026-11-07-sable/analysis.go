package sable

// CFG analyses: reverse postorder, dominators (Cooper–Harvey–Kennedy),
// dominance frontiers, natural loops.

type Analysis struct {
	F        *Func
	RPO      []*Block
	Index    map[*Block]int // RPO index
	Idom     map[*Block]*Block
	Children map[*Block][]*Block // dominator tree
	DF       map[*Block][]*Block
}

func (f *Func) rpo() []*Block {
	seen := map[*Block]bool{}
	var post []*Block
	type fr struct {
		b *Block
		i int
	}
	stack := []fr{{f.Entry, 0}}
	seen[f.Entry] = true
	for len(stack) > 0 {
		t := &stack[len(stack)-1]
		if t.i < len(t.b.Succs) {
			s := t.b.Succs[t.i]
			t.i++
			if !seen[s] {
				seen[s] = true
				stack = append(stack, fr{s, 0})
			}
			continue
		}
		post = append(post, t.b)
		stack = stack[:len(stack)-1]
	}
	for i, j := 0, len(post)-1; i < j; i, j = i+1, j-1 {
		post[i], post[j] = post[j], post[i]
	}
	return post
}

// Analyze computes dominators and frontiers. The function must have no unreachable blocks.
func Analyze(f *Func) *Analysis {
	a := &Analysis{F: f, RPO: f.rpo(), Index: map[*Block]int{}, Idom: map[*Block]*Block{},
		Children: map[*Block][]*Block{}, DF: map[*Block][]*Block{}}
	for i, b := range a.RPO {
		a.Index[b] = i
	}
	a.Idom[f.Entry] = f.Entry
	intersect := func(x, y *Block) *Block {
		for x != y {
			for a.Index[x] > a.Index[y] {
				x = a.Idom[x]
			}
			for a.Index[y] > a.Index[x] {
				y = a.Idom[y]
			}
		}
		return x
	}
	for changed := true; changed; {
		changed = false
		for _, b := range a.RPO[1:] {
			var nd *Block
			for _, p := range b.Preds {
				if _, ok := a.Idom[p]; !ok {
					continue
				}
				if nd == nil {
					nd = p
				} else {
					nd = intersect(p, nd)
				}
			}
			if a.Idom[b] != nd {
				a.Idom[b] = nd
				changed = true
			}
		}
	}
	for _, b := range a.RPO[1:] {
		a.Children[a.Idom[b]] = append(a.Children[a.Idom[b]], b)
	}
	for _, b := range a.RPO {
		if len(b.Preds) < 2 {
			continue
		}
		for _, p := range b.Preds {
			r := p
			for r != a.Idom[b] {
				if !containsBlock(a.DF[r], b) {
					a.DF[r] = append(a.DF[r], b)
				}
				r = a.Idom[r]
			}
		}
	}
	return a
}

func containsBlock(l []*Block, b *Block) bool {
	for _, x := range l {
		if x == b {
			return true
		}
	}
	return false
}

// Dominates reports whether a dominates b (reflexive).
func (a *Analysis) Dominates(x, y *Block) bool {
	for {
		if x == y {
			return true
		}
		if y == a.F.Entry {
			return false
		}
		y = a.Idom[y]
	}
}

// Loop is a natural loop (all back edges to one header merged).
type Loop struct {
	Header  *Block
	Blocks  map[*Block]bool
	Latches []*Block
}

func (a *Analysis) Loops() []*Loop {
	byHeader := map[*Block]*Loop{}
	var order []*Loop
	for _, b := range a.RPO {
		for _, s := range b.Succs {
			if !a.Dominates(s, b) {
				continue
			}
			lp := byHeader[s]
			if lp == nil {
				lp = &Loop{Header: s, Blocks: map[*Block]bool{s: true}}
				byHeader[s] = lp
				order = append(order, lp)
			}
			lp.Latches = append(lp.Latches, b)
			stack := []*Block{b}
			for len(stack) > 0 {
				x := stack[len(stack)-1]
				stack = stack[:len(stack)-1]
				if lp.Blocks[x] {
					continue
				}
				lp.Blocks[x] = true
				stack = append(stack, x.Preds...)
			}
		}
	}
	return order
}
