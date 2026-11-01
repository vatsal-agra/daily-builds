// Command wayfinder is the CLI for the Wayfinder pathfinding laboratory.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"wayfinder/grid"
	"wayfinder/plan"
	"wayfinder/viz"
)

const usage = `wayfinder — pathfinding laboratory

usage: wayfinder <command> [flags]

  gen      generate a map            -kind random|maze|rooms|caves|open -w 60 -h 30 -seed 1 [-density 0.25] [-terrain 0.3] [-o file]
  solve    run one planner           -map file|- -algo dijkstra|astar|jps|theta|hpa [-draw]
  compare  run every applicable planner on a map and tabulate     -map file|-
  explore  D* Lite agent in an unknown world   -map file|- -radius 3 [-draw]
  html     write the HTML replay viewer        -map file|- -o out.html [-radius 3]
  fuzz     cross-validate planners on random maps   -n 500 [-seed 1]
  bench    benchmark across map families       [-size 120] [-seeds 5]

A map file is ASCII: '#' wall, '.' open, ',' ';' '~' '%' '&' terrain (cost 2,3,5,7,9),
digits 1-9 explicit costs, 'S' start, 'G' goal.
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	var err error
	args := os.Args[2:]
	switch os.Args[1] {
	case "gen":
		err = cmdGen(args)
	case "solve":
		err = cmdSolve(args)
	case "compare":
		err = cmdCompare(args)
	case "explore":
		err = cmdExplore(args)
	case "html":
		err = cmdHTML(args)
	case "fuzz":
		err = cmdFuzz(args)
	case "bench":
		err = cmdBench(args)
	case "help", "-h", "--help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s", os.Args[1], usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func newFlags(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	return fs
}

func loadMap(path string) (*grid.Grid, error) {
	if path == "" {
		return nil, fmt.Errorf("-map is required (a file path, or - for stdin)")
	}
	var b []byte
	var err error
	if path == "-" {
		b, err = io.ReadAll(os.Stdin)
	} else {
		b, err = os.ReadFile(path)
	}
	if err != nil {
		return nil, err
	}
	return grid.Parse(string(b))
}

func cmdGen(args []string) error {
	fs := newFlags("gen")
	kind := fs.String("kind", "rooms", "map kind")
	w := fs.Int("w", 60, "width")
	h := fs.Int("h", 30, "height")
	seed := fs.Int64("seed", 1, "seed")
	density := fs.Float64("density", 0.25, "wall density for random maps (0..0.6)")
	terrain := fs.Float64("terrain", 0, "fraction of cells covered by weighted terrain (0..1)")
	out := fs.String("o", "", "write to file instead of stdout")
	if err := fs.Parse(args); err != nil {
		return err
	}
	g, err := grid.Generate(*kind, *w, *h, *seed, *density, *terrain)
	if err != nil {
		return err
	}
	if *out != "" {
		return os.WriteFile(*out, []byte(g.Format()), 0o644)
	}
	fmt.Print(g.Format())
	return nil
}

func runAlgo(name string, g *grid.Grid) (*plan.Result, error) {
	switch name {
	case "dijkstra":
		return plan.Dijkstra(g, g.Start, g.Goal)
	case "astar":
		return plan.AStar(g, g.Start, g.Goal)
	case "jps":
		return plan.JPS(g, g.Start, g.Goal)
	case "theta":
		return plan.ThetaStar(g, g.Start, g.Goal)
	case "hpa":
		return plan.HPA(g, g.Start, g.Goal, 10)
	}
	return nil, fmt.Errorf("unknown algorithm %q (dijkstra, astar, jps, theta, hpa)", name)
}

func cmdSolve(args []string) error {
	fs := newFlags("solve")
	mp := fs.String("map", "", "map file or -")
	algo := fs.String("algo", "astar", "algorithm")
	draw := fs.Bool("draw", false, "print the map with the path")
	if err := fs.Parse(args); err != nil {
		return err
	}
	g, err := loadMap(*mp)
	if err != nil {
		return err
	}
	r, err := runAlgo(*algo, g)
	if err != nil {
		return err
	}
	fmt.Println(r)
	if *draw {
		fmt.Print(drawPath(g, r.Path, nil))
	}
	if !r.Found {
		os.Exit(3)
	}
	return nil
}

// drawPath renders the map with a path ('*') and optional trail overlay ('o').
func drawPath(g *grid.Grid, path []grid.Point, trail []grid.Point) string {
	rows := strings.Split(strings.TrimRight(g.Format(), "\n"), "\n")
	b := make([][]byte, len(rows))
	for i := range rows {
		b[i] = []byte(rows[i])
	}
	mark := func(ps []grid.Point, ch byte) {
		for _, p := range ps {
			if b[p.Y][p.X] != 'S' && b[p.Y][p.X] != 'G' {
				b[p.Y][p.X] = ch
			}
		}
	}
	if trail != nil {
		mark(plan.Densify(trail), 'o')
	}
	if path != nil {
		mark(rasterize(path), '*')
	}
	var sb strings.Builder
	for _, r := range b {
		sb.Write(r)
		sb.WriteByte('\n')
	}
	return sb.String()
}

func cmdCompare(args []string) error {
	fs := newFlags("compare")
	mp := fs.String("map", "", "map file or -")
	if err := fs.Parse(args); err != nil {
		return err
	}
	g, err := loadMap(*mp)
	if err != nil {
		return err
	}
	rs := allResults(g, true)
	for _, r := range rs {
		fmt.Println(r)
	}
	return nil
}

// allResults runs every applicable planner; skipped ones are reported on stderr when verbose.
func allResults(g *grid.Grid, verbose bool) []*plan.Result {
	var out []*plan.Result
	for _, name := range []string{"dijkstra", "astar", "jps", "theta", "hpa"} {
		r, err := runAlgo(name, g)
		if err != nil {
			if verbose {
				fmt.Fprintf(os.Stderr, "%-9s skipped: %v\n", name, err)
			}
			continue
		}
		out = append(out, r)
	}
	return out
}

func cmdExplore(args []string) error {
	fs := newFlags("explore")
	mp := fs.String("map", "", "map file or -")
	radius := fs.Int("radius", 3, "sensor radius")
	draw := fs.Bool("draw", false, "print the final trail")
	if err := fs.Parse(args); err != nil {
		return err
	}
	g, err := loadMap(*mp)
	if err != nil {
		return err
	}
	ex, err := plan.Explore(g, *radius)
	if err != nil {
		return err
	}
	status := "reached goal"
	if ex.Stuck {
		status = "goal is unreachable (agent enclosed)"
	}
	fmt.Printf("%s: %d steps, travelled %.2f, %d replans\n", status, len(ex.Trail)-1, ex.Travelled, len(ex.Events))
	ratio := 0.0
	if ex.DStarTotal > 0 {
		ratio = float64(ex.AStarTotal) / float64(ex.DStarTotal)
	}
	fmt.Printf("D* Lite expansions: %d   from-scratch A* expansions at the same replans: %d   (%.1fx less work)\n",
		ex.DStarTotal, ex.AStarTotal, ratio)
	fmt.Println("every replan cross-checked against A*: costs identical")
	if *draw {
		fmt.Print(drawPath(g, nil, ex.Trail))
	}
	return nil
}

func cmdHTML(args []string) error {
	fs := newFlags("html")
	mp := fs.String("map", "", "map file or -")
	out := fs.String("o", "wayfinder.html", "output file")
	radius := fs.Int("radius", 3, "sensor radius for the D* Lite walk (0 = skip)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	g, err := loadMap(*mp)
	if err != nil {
		return err
	}
	const maxCells = 640_000 // ~800x800; beyond this the embedded traces make the page unusably heavy
	if g.W*g.H > maxCells {
		return fmt.Errorf("map is %dx%d (%d cells); the HTML viewer supports at most %d cells — use solve/compare/bench for larger maps", g.W, g.H, g.W*g.H, maxCells)
	}
	var ex *plan.Exploration
	if *radius > 0 {
		if ex, err = plan.Explore(g, *radius); err != nil {
			return err
		}
	}
	page, err := viz.Page(fmt.Sprintf("%dx%d", g.W, g.H), g, allResults(g, true), ex)
	if err != nil {
		return err
	}
	if err := os.WriteFile(*out, []byte(page), 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%d KB)\n", *out, len(page)/1024)
	return nil
}

// rasterize turns waypoints (grid steps, JPS runs or any-angle segments) into
// the cells to draw, using Bresenham between consecutive waypoints.
func rasterize(p []grid.Point) []grid.Point {
	if len(p) == 0 {
		return nil
	}
	out := []grid.Point{p[0]}
	for i := 1; i < len(p); i++ {
		a, b := p[i-1], p[i]
		dx, dy := abs(b.X-a.X), abs(b.Y-a.Y)
		sx, sy := 1, 1
		if a.X > b.X {
			sx = -1
		}
		if a.Y > b.Y {
			sy = -1
		}
		err := dx - dy
		for a != b {
			e2 := 2 * err
			if e2 > -dy {
				err -= dy
				a.X += sx
			}
			if e2 < dx {
				err += dx
				a.Y += sy
			}
			out = append(out, a)
		}
	}
	return out
}

func abs(v int) int {
	if v < 0 {
		return -v
	}
	return v
}
