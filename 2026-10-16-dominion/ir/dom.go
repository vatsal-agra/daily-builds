package ir

// DomInfo holds dominator-tree information for a function (reachable blocks only).
type DomInfo struct {
	F         *Func
	RPO       []*Block
	rpoNum    map[*Block]int
	Idom      map[*Block]*Block // entry maps to nil
	Children  map[*Block][]*Block
	pre, post map[*Block]int
}

// ReversePostorder computes RPO from entry.
func ReversePostorder(f *Func) []*Block {
	seen := map[*Block]bool{}
	var post []*Block
	var walk func(b *Block)
	walk = func(b *Block) {
		seen[b] = true
		for _, s := range b.Succs {
			if !seen[s] {
				walk(s)
			}
		}
		post = append(post, b)
	}
	walk(f.Entry())
	for i, j := 0, len(post)-1; i < j; i, j = i+1, j-1 {
		post[i], post[j] = post[j], post[i]
	}
	return post
}

// ComputeDom implements Cooper, Harvey & Kennedy, "A Simple, Fast Dominance Algorithm".
func ComputeDom(f *Func) *DomInfo {
	d := &DomInfo{F: f, Idom: map[*Block]*Block{}, Children: map[*Block][]*Block{},
		rpoNum: map[*Block]int{}, pre: map[*Block]int{}, post: map[*Block]int{}}
	d.RPO = ReversePostorder(f)
	for i, b := range d.RPO {
		d.rpoNum[b] = i
	}
	entry := f.Entry()
	idom := map[*Block]*Block{entry: entry}
	intersect := func(a, b *Block) *Block {
		for a != b {
			for d.rpoNum[a] > d.rpoNum[b] {
				a = idom[a]
			}
			for d.rpoNum[b] > d.rpoNum[a] {
				b = idom[b]
			}
		}
		return a
	}
	for changed := true; changed; {
		changed = false
		for _, b := range d.RPO[1:] {
			var nd *Block
			for _, p := range b.Preds {
				if _, ok := d.rpoNum[p]; !ok {
					continue // unreachable pred
				}
				if idom[p] == nil {
					continue
				}
				if nd == nil {
					nd = p
				} else {
					nd = intersect(p, nd)
				}
			}
			if nd != nil && idom[b] != nd {
				idom[b] = nd
				changed = true
			}
		}
	}
	for _, b := range d.RPO {
		if b == entry {
			d.Idom[b] = nil
			continue
		}
		d.Idom[b] = idom[b]
		d.Children[idom[b]] = append(d.Children[idom[b]], b)
	}
	// pre/post numbering for O(1) dominance queries
	n := 0
	var walk func(b *Block)
	walk = func(b *Block) {
		d.pre[b] = n
		n++
		for _, c := range d.Children[b] {
			walk(c)
		}
		d.post[b] = n
		n++
	}
	walk(entry)
	return d
}

// Reachable reports whether b is reachable from entry.
func (d *DomInfo) Reachable(b *Block) bool { _, ok := d.rpoNum[b]; return ok }

// Dominates: a dominates b (reflexive).
func (d *DomInfo) Dominates(a, b *Block) bool {
	if !d.Reachable(a) || !d.Reachable(b) {
		return false
	}
	return d.pre[a] <= d.pre[b] && d.post[b] <= d.post[a]
}

// StrictlyDominates: a dominates b and a != b.
func (d *DomInfo) StrictlyDominates(a, b *Block) bool { return a != b && d.Dominates(a, b) }

// Frontiers computes dominance frontiers (Cytron et al. via CHK's join-walk).
func (d *DomInfo) Frontiers() map[*Block][]*Block {
	df := map[*Block][]*Block{}
	has := map[[2]*Block]bool{}
	for _, b := range d.RPO {
		var preds []*Block
		for _, p := range b.Preds {
			if d.Reachable(p) {
				preds = append(preds, p)
			}
		}
		if len(preds) < 2 {
			continue
		}
		for _, p := range preds {
			for r := p; r != nil && r != d.Idom[b]; r = d.Idom[r] {
				k := [2]*Block{r, b}
				if !has[k] {
					has[k] = true
					df[r] = append(df[r], b)
				}
			}
		}
	}
	return df
}
