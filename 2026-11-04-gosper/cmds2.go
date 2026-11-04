package main

import (
	"fmt"
	"os"
	"runtime"
	"strconv"
	"strings"

	"gosper/life"
)

func cmdCensus(args []string) error {
	fs := newFlags("census")
	rule := fs.String("rule", "B3/S23", "rule")
	soups := fs.Int("soups", 2000, "number of random soups")
	size := fs.Int("size", 16, "soup side length")
	density := fs.Float64("density", 0.5, "initial live-cell density")
	gens := fs.String("gens", "2000", "generations to run before reading the ash")
	seed := fs.Int64("seed", 1, "random seed (result is deterministic per seed)")
	top := fs.Int("top", 20, "rows to print")
	if err := fs.Parse(args); err != nil {
		return err
	}
	r, err := life.ParseRule(*rule)
	if err != nil {
		return err
	}
	g, err := parseGens(*gens)
	if err != nil {
		return err
	}
	if *soups < 1 || *size < 1 || *size > 4096 || *density <= 0 || *density > 1 {
		return fmt.Errorf("census: need -soups>=1, 1<=-size<=4096, 0<-density<=1")
	}
	t0 := nowFn()
	res, err := life.Census(life.CensusOptions{Rule: r, Soups: *soups, Size: *size, Density: *density, Gens: g, Seed: *seed, Workers: runtime.NumCPU()})
	if err != nil {
		return err
	}
	fmt.Printf("census: %d soups %dx%d at density %.2f, rule %s, ash read at generation %s (%s)\n", *soups, *size, *size, *density, r, human(g), since(t0))
	live := *soups - res.DiedOut - res.TooBig - res.OverBudget
	fmt.Printf("  %d soups left ash (%d died out, %d too large to classify, %d over node budget)\n", live, res.DiedOut, res.TooBig, res.OverBudget)
	if live > 0 {
		fmt.Printf("  mean final population %.1f, %d objects total (%.2f per surviving soup)\n", float64(res.SumFinalPop)/float64(live), res.TotalObj, float64(res.TotalObj)/float64(live))
	}
	fmt.Printf("  %-34s %8s %8s\n", "object", "count", "share")
	for i, row := range res.Sorted() {
		if i >= *top {
			fmt.Printf("  … %d more kinds\n", len(res.Objects)-*top)
			break
		}
		fmt.Printf("  %-34s %8d %7.2f%%\n", row.Name, row.Count, 100*float64(row.Count)/float64(res.TotalObj))
	}
	return nil
}

func cmdRender(args []string) error {
	fs := newFlags("render")
	rule := fs.String("rule", "", "override rule")
	gens := fs.String("gens", "0", "generation to render")
	size := fs.Int("size", 800, "image side in pixels")
	out := fs.String("o", "", "output PNG path (required)")
	light := fs.Bool("light", false, "light theme")
	view := fs.String("view", "", "x0,y0,cells-per-pixel to override the automatic fit")
	arg, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	if *out == "" {
		return fmt.Errorf("render: -o out.png is required")
	}
	if *size < 16 || *size > 8192 {
		return fmt.Errorf("render: -size must be in [16, 8192]")
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
	if err := s.Step(n); err != nil {
		return err
	}
	v := life.FitView(s, *size, *size)
	if *view != "" {
		f := strings.Split(*view, ",")
		if len(f) != 3 {
			return fmt.Errorf("render: -view wants x0,y0,scale")
		}
		var vals [3]float64
		for i := range f {
			if vals[i], err = strconv.ParseFloat(strings.TrimSpace(f[i]), 64); err != nil {
				return fmt.Errorf("render: bad -view value %q", f[i])
			}
		}
		if vals[2] <= 0 {
			return fmt.Errorf("render: -view scale must be positive")
		}
		v = life.View{X0: vals[0], Y0: vals[1], Scale: vals[2]}
	}
	th := life.DarkTheme
	if *light {
		th = life.LightTheme
	}
	data, err := life.EncodePNG(life.RenderImage(s, v, *size, *size, th))
	if err != nil {
		return err
	}
	if err := os.WriteFile(*out, data, 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%dx%d, generation %s, %s cells, %.3g cells/pixel)\n", *out, *size, *size, human(s.Gen), human(s.Population()), v.Scale)
	return nil
}

func cmdReport(args []string) error {
	fs := newFlags("report")
	rule := fs.String("rule", "", "override rule")
	out := fs.String("o", "report.html", "output HTML path")
	snaps := fs.String("snaps", "", "comma-separated generations to snapshot (default: automatic)")
	curve := fs.Int("curve", 1500, "generations of per-generation population curve")
	growth := fs.Int("growth", 30, "population checkpoints at generations 2^0..2^N")
	arg, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	if *curve < 0 || *curve > 200000 || *growth < 0 || *growth > 56 {
		return fmt.Errorf("report: need 0<=-curve<=200000 and 0<=-growth<=56")
	}
	l, err := loadPattern(arg, *rule)
	if err != nil {
		return err
	}
	pts, err := l.cellsOf()
	if err != nil {
		return err
	}
	d := life.ReportData{Name: l.name, Rule: l.rule, Cells: pts}
	if d.Period, err = life.FindPeriod(l.rule, pts, 256); err != nil {
		return err
	}
	if d.Period.Kind == life.KindAperiodic {
		if d.Settle, err = life.FindSettle(l.rule, pts, 6000, 24); err != nil {
			return err
		}
	}
	if *growth >= 3 && d.Period.Kind != life.KindEmpty {
		var gerr error
		d.Growth, d.GrowthC, gerr = life.GrowthReport(l.rule, pts, *growth)
		if gerr != nil {
			d.Notes = append(d.Notes, "Growth checkpoints stopped early: "+gerr.Error())
		}
	}
	if *curve > 0 && len(pts) > 0 {
		if st, err := life.FindSettle(l.rule, pts, *curve, 0); err == nil {
			d.PopCurve = st.PopSeries
		}
	}
	if *snaps != "" {
		for _, f := range strings.Split(*snaps, ",") {
			g, err := parseGens(f)
			if err != nil {
				return err
			}
			d.Snaps = append(d.Snaps, g)
		}
	} else {
		d.Snaps = autoSnaps(d)
	}
	page, err := life.HTMLReport(d)
	if err != nil {
		return err
	}
	if err := os.WriteFile(*out, []byte(page), 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%d KB)\n", *out, len(page)/1024)
	return nil
}

func autoSnaps(d life.ReportData) []uint64 {
	g := []uint64{0}
	switch {
	case d.Period.Kind == life.KindSpaceship || d.Period.Kind == life.KindOscillator:
		p := uint64(d.Period.Period)
		g = append(g, p/4, p/2, p)
		g = []uint64{0}
		for _, x := range []uint64{p / 4, p / 2, p, 4 * p} {
			if x > g[len(g)-1] {
				g = append(g, x)
			}
		}
	case d.Settle != nil && d.Settle.Settled && !d.Settle.Died:
		a := d.Settle.AtGen
		g = append(g, a/8+1, a/2+1, a+1, 1<<16)
	case d.Settle != nil && d.Settle.Died:
		a := d.Settle.DiedAt
		g = append(g, a/3, 2*a/3, a-1)
	default:
		g = append(g, 100, 1000, 1<<14, 1<<24)
	}
	// dedupe, ascending
	var out []uint64
	for _, x := range g {
		if len(out) == 0 || x > out[len(out)-1] {
			out = append(out, x)
		}
	}
	return out
}
