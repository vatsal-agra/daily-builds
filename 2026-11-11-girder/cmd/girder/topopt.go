package main

import (
	"flag"
	"fmt"
	"os"

	"girder/fem"
)

func cmdTopopt(args []string) error {
	fs := flag.NewFlagSet("topopt", flag.ContinueOnError)
	cs := fs.String("case", "mbb", "design problem: mbb, cantilever, bridge")
	nx := fs.Int("nx", 120, "elements in x")
	ny := fs.Int("ny", 40, "elements in y")
	vf := fs.Float64("vol", 0.4, "target volume fraction")
	pen := fs.Float64("p", 3, "SIMP penalty")
	rmin := fs.Float64("rmin", 2.4, "density-filter radius (elements)")
	iters := fs.Int("iter", 150, "max iterations")
	out := fs.String("o", "", "write an HTML report")
	quiet := fs.Bool("q", false, "no per-iteration output")
	if err := fs.Parse(args); err != nil {
		return err
	}
	p := fem.TopOptParams{Case: fem.TopOptCase(*cs), NX: *nx, NY: *ny, VolFrac: *vf, Penal: *pen, RMin: *rmin, MaxIter: *iters, Tol: 0.01, SnapEvery: 10}
	r, err := fem.OptimizeTopology(p, func(it int, c, v, ch float64) {
		if !*quiet && (it == 1 || it%10 == 0) {
			fmt.Printf("it %3d  compliance %10.4f  vol %.3f  change %.3f\n", it, c, v, ch)
		}
	})
	if err != nil {
		return err
	}
	last := r.Compl[len(r.Compl)-1]
	fmt.Printf("done: %d iterations (converged=%v), compliance %.4f (%.1fx stiffer than uniform), volume %.4f, gray %.1f%%\n",
		r.Iters, r.Converged, last, r.Initial/last, r.Vol[len(r.Vol)-1], 100*fem.GrayFraction(r.Rho))
	if *out != "" {
		return os.WriteFile(*out, []byte(fem.TopOptReport(r)), 0o644)
	}
	return nil
}
