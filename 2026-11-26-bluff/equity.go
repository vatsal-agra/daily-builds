package main

import (
	"fmt"
	"math"
	"math/rand"
	"sync"
)

// EquityResult is the outcome for each player.
type EquityResult struct {
	Equity  []float64 // share of the pot
	Win     []float64 // outright wins
	Tie     []float64 // tie (any split) frequency
	StdErr  []float64 // Monte-Carlo standard error of Equity (0 when exact)
	Samples int64
	Exact   bool
}

// EquityOpts configures a calculation.
type EquityOpts struct {
	Board      []int
	Dead       []int
	Samples    int   // Monte-Carlo samples (default 200000)
	Seed       int64 // RNG seed (default 1)
	ExactLimit int64 // max evaluations for exact enumeration (default 4e6)
}

func binom(n, k int) float64 {
	if k < 0 || k > n {
		return 0
	}
	r := 1.0
	for i := 1; i <= k; i++ {
		r = r * float64(n-k+i) / float64(i)
	}
	return r
}

// Equity computes equities for 2..6 players, each with a range of possible holdings.
func Equity(ranges [][]Combo, o EquityOpts) (*EquityResult, error) {
	np := len(ranges)
	if np < 2 || np > 6 {
		return nil, fmt.Errorf("need 2 to 6 players, got %d", np)
	}
	if len(o.Board) > 5 {
		return nil, fmt.Errorf("board has %d cards (max 5)", len(o.Board))
	}
	if len(o.Board) > 0 && len(o.Board) < 3 {
		return nil, fmt.Errorf("board must have 0 or 3-5 cards, got %d", len(o.Board))
	}
	var blocked uint64
	for _, c := range append(append([]int{}, o.Board...), o.Dead...) {
		if c < 0 || c > 51 {
			return nil, fmt.Errorf("bad card index %d", c)
		}
		if blocked>>uint(c)&1 == 1 {
			return nil, fmt.Errorf("card %s appears twice among board/dead cards", CardString(c))
		}
		blocked |= 1 << uint(c)
	}
	live := make([][]Combo, np)
	for i, r := range ranges {
		for _, c := range r {
			if c.mask()&blocked == 0 {
				live[i] = append(live[i], c)
			}
		}
		if len(live[i]) == 0 {
			return nil, fmt.Errorf("player %d has no possible holdings once board/dead cards are removed", i+1)
		}
	}
	if o.Samples <= 0 {
		o.Samples = 200000
	}
	if o.Seed == 0 {
		o.Seed = 1
	}
	if o.ExactLimit <= 0 {
		o.ExactLimit = 4_000_000
	}
	need := 5 - len(o.Board)
	deckLeft := 52 - popcount(blocked) - 0
	work := binom(deckLeft-2*np, need)
	for _, l := range live {
		work *= float64(len(l))
	}
	// feasibility: can every player get distinct cards at all?
	if deckLeft-2*np < need {
		return nil, fmt.Errorf("not enough cards left in the deck")
	}
	res := &EquityResult{
		Equity: make([]float64, np), Win: make([]float64, np),
		Tie: make([]float64, np), StdErr: make([]float64, np),
	}
	if work <= float64(o.ExactLimit) {
		if err := exactEquity(live, o, blocked, need, res); err != nil {
			return nil, err
		}
		return res, nil
	}
	if err := mcEquity(live, o, blocked, need, res); err != nil {
		return nil, err
	}
	return res, nil
}

// scoreShowdown fills per-player scores into sc and returns nothing; helper for tally.
func tally(scores []uint32, eq, win, tie []float64, w float64) {
	best := uint32(0)
	for _, s := range scores {
		if s > best {
			best = s
		}
	}
	n := 0
	for _, s := range scores {
		if s == best {
			n++
		}
	}
	for i, s := range scores {
		if s == best {
			eq[i] += w / float64(n)
			if n == 1 {
				win[i] += w
			} else {
				tie[i] += w
			}
		}
	}
}

func exactEquity(live [][]Combo, o EquityOpts, blocked uint64, need int, res *EquityResult) error {
	np := len(live)
	eq := make([]float64, np)
	win := make([]float64, np)
	tie := make([]float64, np)
	var total float64
	choice := make([]Combo, np)
	scores := make([]uint32, np)
	cards := make([]int, 0, 7)
	var recur func(p int, used uint64)
	recur = func(p int, used uint64) {
		if p == np {
			var rest []int
			for c := 0; c < 52; c++ {
				if used>>uint(c)&1 == 0 {
					rest = append(rest, c)
				}
			}
			board := append([]int{}, o.Board...)
			var enum func(start, k int)
			enum = func(start, k int) {
				if k == 0 {
					for i := 0; i < np; i++ {
						cards = append(cards[:0], board...)
						cards = append(cards, choice[i].A, choice[i].B)
						scores[i] = Eval(cards)
					}
					tally(scores, eq, win, tie, 1)
					total++
					return
				}
				for i := start; i <= len(rest)-k; i++ {
					board = append(board, rest[i])
					enum(i+1, k-1)
					board = board[:len(board)-1]
				}
			}
			enum(0, need)
			return
		}
		for _, c := range live[p] {
			if c.mask()&used != 0 {
				continue
			}
			choice[p] = c
			recur(p+1, used|c.mask())
		}
	}
	recur(0, blocked)
	if total == 0 {
		return fmt.Errorf("no valid deals: the players' ranges conflict with each other")
	}
	for i := 0; i < np; i++ {
		res.Equity[i], res.Win[i], res.Tie[i] = eq[i]/total, win[i]/total, tie[i]/total
	}
	res.Samples, res.Exact = int64(total), true
	return nil
}

func mcEquity(live [][]Combo, o EquityOpts, blocked uint64, need int, res *EquityResult) error {
	np := len(live)
	const workers = 8 // fixed so results are reproducible regardless of CPU count
	type acc struct {
		eq, win, tie, sq []float64
		n                int64
		err              error
	}
	accs := make([]*acc, workers)
	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		cnt := o.Samples / workers
		if w < o.Samples%workers {
			cnt++
		}
		a := &acc{eq: make([]float64, np), win: make([]float64, np), tie: make([]float64, np), sq: make([]float64, np)}
		accs[w] = a
		wg.Add(1)
		go func(w, cnt int) {
			defer wg.Done()
			rng := rand.New(rand.NewSource(o.Seed*1000003 + int64(w)))
			scores := make([]uint32, np)
			share := make([]float64, np)
			cards := make([]int, 0, 7)
			choice := make([]Combo, np)
			var rest []int
			for s := 0; s < cnt; s++ {
				ok := false
				var used uint64
				for try := 0; try < 1000 && !ok; try++ {
					used = blocked
					ok = true
					for p := 0; p < np; p++ {
						c := live[p][rng.Intn(len(live[p]))]
						if c.mask()&used != 0 {
							ok = false
							break
						}
						choice[p] = c
						used |= c.mask()
					}
				}
				if !ok {
					a.err = fmt.Errorf("could not deal non-conflicting hands: ranges overlap too heavily")
					return
				}
				rest = rest[:0]
				for c := 0; c < 52; c++ {
					if used>>uint(c)&1 == 0 {
						rest = append(rest, c)
					}
				}
				board := append(cards[:0], o.Board...)
				for k := 0; k < need; k++ {
					j := k + rng.Intn(len(rest)-k)
					rest[k], rest[j] = rest[j], rest[k]
					board = append(board, rest[k])
				}
				bl := len(board)
				for i := 0; i < np; i++ {
					board = append(board[:bl], choice[i].A, choice[i].B)
					scores[i] = Eval(board)
				}
				for i := range share {
					share[i] = 0
				}
				tally(scores, share, a.win, a.tie, 1)
				for i := range share {
					a.eq[i] += share[i]
					a.sq[i] += share[i] * share[i]
				}
				a.n++
			}
		}(w, cnt)
	}
	wg.Wait()
	var n int64
	eq := make([]float64, np)
	sq := make([]float64, np)
	win := make([]float64, np)
	tie := make([]float64, np)
	for _, a := range accs {
		if a.err != nil {
			return a.err
		}
		n += a.n
		for i := 0; i < np; i++ {
			eq[i] += a.eq[i]
			sq[i] += a.sq[i]
			win[i] += a.win[i]
			tie[i] += a.tie[i]
		}
	}
	for i := 0; i < np; i++ {
		m := eq[i] / float64(n)
		v := sq[i]/float64(n) - m*m
		if v < 0 {
			v = 0
		}
		res.Equity[i], res.Win[i], res.Tie[i] = m, win[i]/float64(n), tie[i]/float64(n)
		res.StdErr[i] = math.Sqrt(v / float64(n))
	}
	res.Samples = n
	return nil
}
