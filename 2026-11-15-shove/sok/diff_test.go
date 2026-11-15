package sok

import (
	"math/rand"
	"sort"
	"testing"
)

// bruteOptimalPushes is an independent oracle: plain BFS over (box set, player region)
// with no heuristic and no deadlock pruning at all. Returns -1 if unsolvable, -2 if over cap.
func bruteOptimalPushes(lv *Level, cap int) int {
	type st struct {
		boxes  []int
		player int
	}
	region := func(boxes []int, p int) (map[int]bool, int) {
		bs := map[int]bool{}
		for _, b := range boxes {
			bs[b] = true
		}
		seen := map[int]bool{p: true}
		q := []int{p}
		min := p
		for len(q) > 0 {
			c := q[0]
			q = q[1:]
			if c < min {
				min = c
			}
			for d := 0; d < 4; d++ {
				n := c + delta(d, lv.W)
				if !lv.Wall[n] && !bs[n] && !seen[n] {
					seen[n] = true
					q = append(q, n)
				}
			}
		}
		return seen, min
	}
	keyOf := func(boxes []int, pc int) string {
		b := append([]int(nil), boxes...)
		sort.Ints(b)
		out := make([]byte, 0, 3*len(b)+3)
		for _, x := range b {
			out = append(out, byte(x), byte(x>>8), ',')
		}
		out = append(out, byte(pc), byte(pc>>8))
		return string(out)
	}
	_, pc := region(lv.Boxes, lv.Player)
	seen := map[string]bool{keyOf(lv.Boxes, pc): true}
	level := []st{{append([]int(nil), lv.Boxes...), lv.Player}}
	for depth := 0; len(level) > 0; depth++ {
		var next []st
		for _, s := range level {
			if lv.Solved(s.boxes) {
				return depth
			}
			reach, _ := region(s.boxes, s.player)
			bs := map[int]bool{}
			for _, b := range s.boxes {
				bs[b] = true
			}
			for i, b := range s.boxes {
				for d := 0; d < 4; d++ {
					dl := delta(d, lv.W)
					if !reach[b-dl] || lv.Wall[b+dl] || bs[b+dl] {
						continue
					}
					nb := append([]int(nil), s.boxes...)
					nb[i] = b + dl
					_, pc := region(nb, b)
					k := keyOf(nb, pc)
					if !seen[k] {
						seen[k] = true
						next = append(next, st{nb, b})
						if len(seen) > cap {
							return -2
						}
					}
				}
			}
		}
		level = next
	}
	return -1
}

// TestSolverMatchesBruteForce: optimal push counts from the A* solver (with every
// optimisation) must equal the unpruned oracle on hundreds of random solvable levels,
// and ablated variants must agree too.
func TestSolverMatchesBruteForce(t *testing.T) {
	rng := rand.New(rand.NewSource(99))
	checked := 0
	for i := 0; i < 4000 && checked < 250; i++ {
		o := GenOptions{W: 6 + rng.Intn(3), H: 6 + rng.Intn(2), Boxes: 1 + rng.Intn(4), Seed: int64(i), WallDens: 0.1}
		if o.Validate() != nil {
			continue
		}
		o.Pulls = 25 * o.Boxes
		lv := candidate(rng, o)
		if lv == nil {
			continue
		}
		want := bruteOptimalPushes(lv, 150000)
		if want == -2 {
			continue
		}
		if want < 0 {
			t.Fatalf("reverse-play produced an unsolvable level (brute force says so):\n%s", lv)
		}
		for name, opt := range map[string]Options{"full": {}, "nofreeze": {NoFreeze: true}, "nomatch": {NoMatching: true}} {
			sol, err := Solve(lv, opt)
			if err != nil {
				t.Fatalf("%s: solver failed on solvable level: %v\n%s", name, err, lv)
			}
			if sol.Pushes != want {
				t.Fatalf("%s: solver says %d pushes, oracle says %d\n%s", name, sol.Pushes, want, lv)
			}
			if _, err := lv.Verify(sol.Moves); err != nil {
				t.Fatalf("%s: solution does not verify: %v\n%s", name, err, lv)
			}
		}
		checked++
	}
	if checked < 150 {
		t.Fatalf("only %d levels cross-checked", checked)
	}
	t.Logf("cross-checked %d random levels against brute force", checked)
}
