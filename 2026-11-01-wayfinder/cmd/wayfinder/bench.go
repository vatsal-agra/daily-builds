package main

import (
	"fmt"
	"math"
	"strings"
	"time"

	"wayfinder/grid"
	"wayfinder/plan"
)

func cmdBench(args []string) error {
	fs := newFlags("bench")
	size := fs.Int("size", 120, "map width and height")
	seeds := fs.Int("seeds", 5, "maps per family")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *size < 20 || *size > 2000 {
		return fmt.Errorf("-size must be within 20..2000")
	}
	if *seeds < 1 {
		return fmt.Errorf("-seeds must be >= 1")
	}
	algos := []string{"dijkstra", "astar", "jps", "theta", "hpa"}
	fmt.Printf("benchmark: %dx%d maps, %d seeds per family, mean values\n\n", *size, *size, *seeds)
	fmt.Printf("%-8s %-9s %12s %10s %12s\n", "family", "algo", "expansions", "time", "cost/optimal")
	fmt.Println(strings.Repeat("-", 56))
	for _, kind := range []string{"open", "random", "rooms", "maze", "caves"} {
		type acc struct {
			exp, ratio float64
			dur        time.Duration
			n          int
		}
		tot := map[string]*acc{}
		for s := 0; s < *seeds; s++ {
			g, err := grid.Generate(kind, *size, *size, int64(100+s), 0.25, 0)
			if err != nil {
				continue
			}
			opt, _ := plan.AStar(g, g.Start, g.Goal)
			for _, name := range algos {
				r, err := runAlgo(name, g)
				if err != nil || !r.Found {
					continue
				}
				a := tot[name]
				if a == nil {
					a = &acc{}
					tot[name] = a
				}
				a.exp += float64(r.Expanded)
				a.dur += r.Dur
				a.ratio += r.Cost / math.Max(opt.Cost, 1e-12)
				a.n++
			}
		}
		for _, name := range algos {
			if a := tot[name]; a != nil {
				fmt.Printf("%-8s %-9s %12.0f %10v %12.4f\n", kind, name, a.exp/float64(a.n),
					(a.dur / time.Duration(a.n)).Round(time.Microsecond), a.ratio/float64(a.n))
			}
		}
		fmt.Println()
	}
	fmt.Println("cost/optimal < 1 for theta* is expected: any-angle paths beat the 8-connected grid optimum.")
	fmt.Println("hpa* > 1 is expected: it trades optimality for speed on large maps.")
	return nil
}
