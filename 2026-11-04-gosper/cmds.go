package main

import (
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"strings"
	"time"

	"gosper/life"
)

func cmdInfo(args []string) error {
	fs := newFlags("info")
	rule := fs.String("rule", "", "override rule")
	arg, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	l, err := loadPattern(arg, *rule)
	if err != nil {
		return err
	}
	s := l.newSim()
	fmt.Printf("name:       %s\nrule:       %s\n", l.name, l.rule)
	fmt.Printf("population: %s\n", human(s.Population()))
	if x0, y0, x1, y1, ok := s.BBox(); ok {
		fmt.Printf("bounding:   %d x %d  (x %d..%d, y %d..%d)\n", x1-x0+1, y1-y0+1, x0, x1, y0, y1)
	} else {
		fmt.Println("bounding:   (empty)")
	}
	fmt.Printf("quadtree:   level %d, %s distinct nodes\n", s.Root.Level(), human(uint64(s.U.Size())))
	return nil
}

func cmdRun(args []string) error {
	fs := newFlags("run")
	rule := fs.String("rule", "", "override rule")
	gens := fs.String("gens", "1", "generations to advance (e.g. 1000, 2^40, 1e9)")
	out := fs.String("o", "", "write result to file (.rle, .cells or .mc)")
	show := fs.Bool("show", false, "print the final pattern as ASCII when small")
	arg, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	n, err := parseGens(*gens)
	if err != nil {
		return err
	}
	l, err := loadPattern(arg, *rule)
	if err != nil {
		return err
	}
	s := l.newSim()
	t0 := time.Now()
	if err := s.Step(n); err != nil {
		return err
	}
	el := since(t0)
	fmt.Printf("%s  rule %s  generation %s\n", l.name, l.rule, human(s.Gen))
	fmt.Printf("population: %s\n", human(s.Population()))
	if x0, y0, x1, y1, ok := s.BBox(); ok {
		fmt.Printf("bounding:   %s x %s  (x %d..%d, y %d..%d)\n", human(uint64(x1-x0+1)), human(uint64(y1-y0+1)), x0, x1, y0, y1)
	}
	fmt.Printf("nodes:      %s   hits %s  misses %s   time %s\n", human(uint64(s.U.Size())), human(s.U.Hits), human(s.U.Misses), el)
	if *show {
		pts, ok := s.Cells(20000)
		if !ok {
			fmt.Println("(too many cells to print)")
		} else {
			fmt.Print(life.EncodeCells(pts, ""))
		}
	}
	if *out != "" {
		return writeOut(*out, s, l.name)
	}
	return nil
}

func writeOut(path string, s *life.Sim, name string) error {
	var data string
	switch strings.ToLower(filepath.Ext(path)) {
	case ".mc":
		data = s.WriteMacrocell()
	case ".cells":
		pts, ok := s.Cells(life.MaxListCells)
		if !ok {
			return fmt.Errorf("too many cells for plaintext output; use .mc")
		}
		data = life.EncodeCells(pts, name)
	case ".rle":
		pts, ok := s.Cells(life.MaxListCells)
		if !ok {
			return fmt.Errorf("too many cells for RLE output; use .mc")
		}
		data = life.EncodeRLE(pts, s.U.Rule, name)
	default:
		return fmt.Errorf("unknown output extension %q (use .rle, .cells or .mc)", filepath.Ext(path))
	}
	if err := os.WriteFile(path, []byte(data), 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s\n", path)
	return nil
}

func cmdAnalyze(args []string) error {
	fs := newFlags("analyze")
	rule := fs.String("rule", "", "override rule")
	maxPeriod := fs.Int("max-period", 256, "longest period to search for")
	maxGens := fs.Int("max-gens", 6000, "generations to single-step when looking for settling")
	horizon := fs.Int("horizon", 24, "verify settling by jumping 2^N generations ahead (0 = skip)")
	growth := fs.Int("growth", 36, "population checkpoints at generations 2^0..2^N")
	arg, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	if *maxPeriod < 1 || *maxGens < 1 || *horizon < 0 || *horizon > 56 || *growth < 0 || *growth > 56 {
		return fmt.Errorf("analyze: need -max-period>=1, -max-gens>=1, -horizon in [0,56], -growth in [0,56]")
	}
	l, err := loadPattern(arg, *rule)
	if err != nil {
		return err
	}
	pts, err := l.cellsOf()
	if err != nil {
		return err
	}
	fmt.Printf("== %s   rule %s   %s cells\n", l.name, l.rule, human(uint64(len(pts))))
	pr, err := life.FindPeriod(l.rule, pts, *maxPeriod)
	if err != nil {
		return err
	}
	switch pr.Kind {
	case life.KindEmpty:
		fmt.Println("shape:      empty pattern")
		return nil
	case life.KindDies:
		fmt.Printf("shape:      dies out at generation %d\n", pr.DiesAt)
		return nil
	case life.KindStill:
		fmt.Printf("shape:      still life (%d cells, %dx%d)\n", pr.Population, pr.W, pr.H)
		return nil
	case life.KindOscillator:
		fmt.Printf("shape:      oscillator, period %d (%d cells in phase 0, %dx%d)\n", pr.Period, pr.Population, pr.W, pr.H)
		return nil
	case life.KindSpaceship:
		fmt.Printf("shape:      spaceship, period %d, displacement (%d,%d) per period, speed %s\n", pr.Period, pr.Dx, pr.Dy, pr.Speed())
		return nil
	}
	fmt.Printf("shape:      not translation-periodic within %d generations\n", *maxPeriod)
	st, err := life.FindSettle(l.rule, pts, *maxGens, *horizon)
	if err != nil {
		return err
	}
	switch {
	case st.Died:
		fmt.Printf("fate:       dies out at generation %s (peak population %s at gen %s)\n", human(st.DiedAt), human(st.PeakPop), human(st.PeakGen))
	case st.Settled:
		fmt.Printf("fate:       population settles into period %d from generation %s (peak %s at gen %s, then %s)\n",
			st.PopPeriod, human(st.AtGen), human(st.PeakPop), human(st.PeakGen), human(st.FinalPop))
		if st.HorizonGen > 0 {
			ok := "CONFIRMED"
			if !st.HorizonOK {
				ok = "FAILED (late activity!)"
			}
			fmt.Printf("look-ahead: Hashlife jumped to generation %s: population %s, predicted %s — %s\n",
				human(st.HorizonGen), human(st.HorizonPop), human(st.HorizonWant), ok)
		}
	default:
		fmt.Printf("fate:       not settled after %s generations (peak %s at gen %s, now %s)\n",
			human(st.Generations), human(st.PeakPop), human(st.PeakGen), human(st.FinalPop))
	}
	cps, gc, err := life.GrowthReport(l.rule, pts, *growth)
	if len(cps) > 0 {
		fmt.Printf("growth:     %s (fitted pop ~ t^%.2f)\n", gc.Label, gc.Exponent)
		fmt.Println("            gen            population        bbox")
		for _, c := range cps {
			if c.J%4 == 0 || c.J == len(cps)-1 {
				fmt.Printf("            2^%-2d %-14s %-17s %s x %s\n", c.J, human(c.Gen), human(c.Pop), human(c.W), human(c.H))
			}
		}
	}
	if err != nil {
		fmt.Println("            (stopped early:", err, ")")
	}
	return nil
}

func randRule(rng *rand.Rand) life.Rule {
	for {
		var r life.Rule
		for i := 1; i <= 8; i++ {
			r.Born[i] = rng.Intn(3) == 0
			r.Survive[i] = rng.Intn(3) == 0
		}
		r.Survive[0] = rng.Intn(4) == 0
		if !r.Born[0] {
			return r
		}
	}
}

func cmdVerify(args []string) error {
	fs := newFlags("verify")
	trials := fs.Int("n", 300, "number of random trials")
	seed := fs.Int64("seed", 1, "random seed")
	size := fs.Int("size", 24, "max soup side")
	maxGens := fs.Int("gens", 80, "max total generations per trial")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *trials < 0 || *size < 1 || *maxGens < 1 {
		return fmt.Errorf("verify: need -n >= 0, -size >= 1, -gens >= 1")
	}
	rng := rand.New(rand.NewSource(*seed))
	named := []string{"B3/S23", "B36/S23", "B2/S", "B3678/S34678", "B34/S34", "B1357/S1357", "B368/S245", "B35678/S5678"}
	var cmp, bad int
	t0 := time.Now()
	for t := 0; t < *trials; t++ {
		var rule life.Rule
		if t%3 == 2 {
			rule = randRule(rng)
		} else {
			rule, _ = life.ParseRule(named[rng.Intn(len(named))])
		}
		w, h := 1+rng.Intn(*size), 1+rng.Intn(*size)
		dens := 0.1 + rng.Float64()*0.6
		var pts []life.Point
		for y := 0; y < h; y++ {
			for x := 0; x < w; x++ {
				if rng.Float64() < dens {
					pts = append(pts, life.Point{X: int64(x) - int64(w/2), Y: int64(y) - int64(h/2)})
				}
			}
		}
		s := life.NewSim(rule)
		if err := s.SetCells(append([]life.Point(nil), pts...), false); err != nil {
			return err
		}
		if t%7 == 3 {
			s.MaxNodes = 500 // force frequent compaction
		}
		nv := life.NewNaive(rule, pts)
		total := 0
		for total < *maxGens {
			var step uint64
			if rng.Intn(4) == 0 {
				j := rng.Intn(5)
				if err := s.StepPow(j); err != nil {
					return err
				}
				step = 1 << uint(j)
			} else {
				step = uint64(1 + rng.Intn(20))
				if err := s.Step(step); err != nil {
					return err
				}
			}
			nv.StepN(step)
			total += int(step)
			cmp++
			if !nv.EqualSim(s, 0, 0) {
				bad++
				fmt.Printf("MISMATCH trial %d rule %s gen %d (naive pop %d, hashlife pop %d)\n", t, rule, nv.Gen, len(nv.Cells), s.Population())
				break
			}
			if s.Gen != nv.Gen {
				return fmt.Errorf("generation counters disagree: %d vs %d", s.Gen, nv.Gen)
			}
		}
		// round-trip through RLE and Macrocell
		cur, _ := s.Cells(0)
		if len(cur) > 0 {
			p, err := life.ParseRLE(life.EncodeRLE(cur, rule, ""))
			if err != nil || !sameSet(p.Cells, cur, true) {
				bad++
				fmt.Printf("RLE round-trip failure in trial %d\n", t)
			}
			s2, err := life.LoadMacrocell(s.WriteMacrocell(), rule)
			if err != nil {
				bad++
				fmt.Printf("macrocell load failure in trial %d: %v\n", t, err)
			} else if c2, _ := s2.Cells(0); !sameSet(c2, cur, false) || s2.Gen != s.Gen {
				bad++
				fmt.Printf("macrocell round-trip failure in trial %d\n", t)
			}
		}
	}
	fmt.Printf("verify: %d trials, %d state comparisons, %d failures (%s)\n", *trials, cmp, bad, since(t0))
	if bad > 0 {
		return fmt.Errorf("%d verification failures", bad)
	}
	return nil
}

// sameSet compares two cell lists; if shift is true, the first is compared up to
// the translation that aligns bounding-box corners.
func sameSet(a, b []life.Point, shift bool) bool {
	if len(a) != len(b) {
		return false
	}
	var dx, dy int64
	if shift && len(a) > 0 {
		ax, ay := a[0].X, a[0].Y
		bx, by := b[0].X, b[0].Y
		for _, p := range a {
			ax, ay = min(ax, p.X), min(ay, p.Y)
		}
		for _, p := range b {
			bx, by = min(bx, p.X), min(by, p.Y)
		}
		dx, dy = bx-ax, by-ay
	}
	m := make(map[life.Point]bool, len(b))
	for _, p := range b {
		m[p] = true
	}
	for _, p := range a {
		if !m[life.Point{X: p.X + dx, Y: p.Y + dy}] {
			return false
		}
	}
	return true
}
