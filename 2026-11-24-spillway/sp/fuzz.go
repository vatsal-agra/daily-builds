package sp

import "fmt"

// FuzzReport summarises a differential fuzzing run.
type FuzzReport struct {
	Programs, Allocations, Executions int
	Failures                          []string
	Spilly                            int // programs where at least one allocation spilled
}

// Fuzz generates n random programs from seed, allocates each with every
// allocator at several register counts, and checks the machine code against
// the reference interpreter on several inputs. Any divergence is a failure.
func Fuzz(n int, seed int64, ks []int, cfg GenConfig) FuzzReport {
	var rep FuzzReport
	inputs := [][]int64{{0, 0}, {1, -1}, {7, 13}, {-100, 55}, {1 << 40, 3}}
	for i := 0; i < n; i++ {
		s := seed + int64(i)
		c := cfg
		// vary pressure and shape per program
		c.Vars = cfg.Vars/2 + int(s%int64(cfg.Vars+1))
		if c.Vars < 2 {
			c.Vars = 2
		}
		c.Depth = 1 + int(s%int64(max(cfg.Depth, 1)))
		c.Shuffle = s%2 == 1
		src := Generate(s, c)
		f, err := Parse(src)
		if err != nil {
			rep.Failures = append(rep.Failures, fmt.Sprintf("seed %d: generator emitted unparsable IR: %v", s, err))
			continue
		}
		if err := f.Validate(); err != nil {
			rep.Failures = append(rep.Failures, fmt.Sprintf("seed %d: generator emitted invalid IR: %v", s, err))
			continue
		}
		rep.Programs++
		spilled := false
		for _, name := range Allocators {
			for _, K := range ks {
				for _, co := range []bool{true, false} {
					if name != "color" && !co {
						continue
					}
					rep.Allocations++
					a, err := Allocate(f, name, K, Options{Coalesce: co})
					if err != nil {
						rep.Failures = append(rep.Failures, fmt.Sprintf("seed %d %s K=%d coalesce=%v: %v", s, name, K, co, err))
						continue
					}
					if a.Static().SpillLoads > 0 {
						spilled = true
					}
					st, err := Verify(f, a, inputs)
					rep.Executions += len(inputs)
					_ = st
					if err != nil {
						rep.Failures = append(rep.Failures, fmt.Sprintf("seed %d %s K=%d coalesce=%v: %v", s, name, K, co, err))
					}
				}
			}
		}
		if spilled {
			rep.Spilly++
		}
	}
	return rep
}
