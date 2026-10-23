package aig

// SeqClean removes dead latches, latches stuck at their initial value
// (a greatest-fixpoint induction over "latch == init" claims) and duplicate
// latches (same clock, init and next-state function). Every removal is recorded
// in AIG.Removed so the equivalence checker can re-prove the result.
func SeqClean(g *AIG) (*AIG, int) {
	cur := g
	removed := 0
	for iter := 0; iter < 64; iter++ {
		subs := make([]latchSub, len(cur.Latches))
		live := cur.LiveLatches()
		for i, l := range live {
			if !l {
				subs[i].kind = 3
			}
		}
		// 1) constant latches: assume all live latches sit at init; refute until stable.
		cand := make([]bool, len(cur.Latches))
		for i := range cand {
			cand[i] = live[i]
		}
		for {
			trial := make([]latchSub, len(cur.Latches))
			copy(trial, subs)
			for i := range trial {
				if cand[i] {
					trial[i] = latchSub{kind: 1, val: cur.Latches[i].Init}
				}
			}
			rb := newRebuilder(cur, true, trial)
			changed := false
			for i := range cur.Latches {
				if !cand[i] {
					continue
				}
				d := rb.lit(cur.Latches[i].D)
				want := False
				if cur.Latches[i].Init {
					want = True
				}
				if d != want {
					cand[i] = false
					changed = true
				}
			}
			if !changed {
				break
			}
		}
		for i := range cand {
			if cand[i] {
				subs[i] = latchSub{kind: 1, val: cur.Latches[i].Init}
			}
		}
		// 2) duplicate latches: partition by (clock, init), refine by mapped D until stable.
		rep := make([]int, len(cur.Latches))
		type ck struct {
			clock string
			init  bool
		}
		first := map[ck]int{}
		for i, l := range cur.Latches {
			rep[i] = i
			if subs[i].kind != 0 {
				continue
			}
			k := ck{l.Clock, l.Init}
			if f, ok := first[k]; ok {
				rep[i] = f
			} else {
				first[k] = i
			}
		}
		for {
			trial := make([]latchSub, len(cur.Latches))
			copy(trial, subs)
			for i := range trial {
				if rep[i] != i {
					trial[i] = latchSub{kind: 2, to: rep[i]}
				}
			}
			rb := newRebuilder(cur, true, trial)
			type dk struct {
				cls int
				d   Lit
			}
			seen := map[dk]int{}
			changed := false
			next := make([]int, len(rep))
			copy(next, rep)
			for i := range cur.Latches {
				if subs[i].kind != 0 {
					continue
				}
				k := dk{rep[i], rb.lit(cur.Latches[i].D)}
				if f, ok := seen[k]; ok {
					next[i] = f
				} else {
					seen[k] = i
					next[i] = i
				}
				if next[i] != rep[i] {
					changed = true
				}
			}
			// a latch that is its own rep keeps its class; members split off get new reps
			rep = next
			if !changed {
				break
			}
			// re-seed: members whose rep changed to themselves remain classes of their own
		}
		n := 0
		for i := range subs {
			if rep[i] != i && subs[i].kind == 0 {
				subs[i] = latchSub{kind: 2, to: rep[i]}
			}
			if subs[i].kind != 0 {
				n++
			}
		}
		next := newRebuilder(cur, true, subs).finish()
		// finish() only translates what is live; count removals
		delta := len(cur.Latches) - len(next.Latches)
		cur = next
		removed += delta
		if delta == 0 {
			break
		}
		_ = n
	}
	return cur, removed
}
