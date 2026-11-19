// Command tier lays out graphs (DOT subset) as layered drawings.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"tier/dot"
	"tier/gen"
	"tier/layout"
	"tier/render"
)

const usage = `tier — layered graph drawing

usage:
  tier layout  [flags] <file.dot|->     draw SVG (or -format json)
  tier metrics [flags] <file.dot|->     print layout quality metrics
  tier report  [flags] <file.dot|->     HTML report comparing strategies
  tier gen     [flags]                  generate a random test graph as DOT
  tier exact   [flags] <file.dot|->     optimal crossings vs heuristic (small graphs)

run 'tier <command> -h' for flags.`

func main() { os.Exit(run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr)) }

type common struct {
	rankdir, ranker, acyclic, order, coord string
	nodesep, ranksep                       float64
	sweeps                                 int
}

func (c *common) bind(fs *flag.FlagSet) {
	fs.StringVar(&c.rankdir, "rankdir", "", "TB or LR (default: graph attribute, else TB)")
	fs.StringVar(&c.ranker, "ranker", "simplex", "layering: simplex | longest")
	fs.StringVar(&c.acyclic, "acyclic", "greedy", "cycle removal: greedy | dfs")
	fs.StringVar(&c.order, "order", "sweep", "crossing minimisation: sweep | none")
	fs.StringVar(&c.coord, "coord", "bk", "x coordinates: bk | packed")
	fs.Float64Var(&c.nodesep, "nodesep", 0, "gap between nodes in a layer (points)")
	fs.Float64Var(&c.ranksep, "ranksep", 0, "gap between layers (points)")
	fs.IntVar(&c.sweeps, "sweeps", 24, "max crossing-minimisation iterations")
}

func (c *common) opts() layout.Options {
	return layout.Options{RankDir: strings.ToUpper(c.rankdir), Ranker: c.ranker, Acyclic: c.acyclic, Order: c.order,
		Coord: c.coord, NodeSep: c.nodesep, RankSep: c.ranksep, Sweeps: c.sweeps}
}

func readInput(path string, stdin io.Reader) (string, error) {
	var b []byte
	var err error
	if path == "-" {
		b, err = io.ReadAll(stdin)
	} else {
		b, err = os.ReadFile(path)
	}
	return string(b), err
}

func loadGraph(path string, stdin io.Reader, c *common) (*dot.Graph, layout.Graph, layout.Options, error) {
	src, err := readInput(path, stdin)
	if err != nil {
		return nil, layout.Graph{}, layout.Options{}, err
	}
	dg, err := dot.Parse(src)
	if err != nil {
		return nil, layout.Graph{}, layout.Options{}, fmt.Errorf("%s: %w", path, err)
	}
	lg, o, err := dg.ToLayout(c.opts())
	if err != nil {
		return nil, layout.Graph{}, layout.Options{}, fmt.Errorf("%s: %w", path, err)
	}
	return dg, lg, o, nil
}

func run(args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	if len(args) == 0 || args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
		fmt.Fprintln(stderr, usage)
		if len(args) == 0 {
			return 2
		}
		return 0
	}
	cmd, rest := args[0], args[1:]
	fail := func(err error) int { fmt.Fprintln(stderr, "tier:", err); return 1 }
	switch cmd {
	case "layout", "metrics", "report", "exact":
		fs := flag.NewFlagSet(cmd, flag.ContinueOnError)
		fs.SetOutput(stderr)
		var c common
		c.bind(fs)
		out := fs.String("o", "", "output file (default stdout)")
		format := fs.String("format", "svg", "layout: svg | json")
		poly := fs.Bool("polyline", false, "layout: straight segments instead of splines")
		bands := fs.Bool("bands", false, "layout: draw rank bands")
		pos, perr := parseInterleaved(fs, rest)
		if perr != nil {
			return 2
		}
		if len(pos) != 1 {
			return fail(fmt.Errorf("%s needs exactly one input file (or - for stdin)", cmd))
		}
		dg, lg, o, err := loadGraph(pos[0], stdin, &c)
		if err != nil {
			return fail(err)
		}
		var w io.Writer = stdout
		if *out != "" {
			fh, err := os.Create(*out)
			if err != nil {
				return fail(err)
			}
			defer fh.Close()
			w = fh
		}
		switch cmd {
		case "exact":
			return doExact(lg, o, w, stderr)
		case "report":
			html, err := render.Report(dg, lg, o, pos[0])
			if err != nil {
				return fail(err)
			}
			io.WriteString(w, html)
			return 0
		}
		res, err := layout.Layout(lg, o)
		if err != nil {
			return fail(err)
		}
		if cmd == "metrics" {
			printMetrics(w, res)
			return 0
		}
		switch *format {
		case "svg":
			io.WriteString(w, render.SVG(res, render.Options{Directed: dg.Directed, Polyline: *poly, Bands: *bands}))
		case "json":
			enc := json.NewEncoder(w)
			enc.SetIndent("", "  ")
			if err := enc.Encode(res); err != nil {
				return fail(err)
			}
		default:
			return fail(fmt.Errorf("unknown -format %q (svg or json)", *format))
		}
		return 0
	case "gen":
		fs := flag.NewFlagSet("gen", flag.ContinueOnError)
		fs.SetOutput(stderr)
		kind := fs.String("kind", "layered", "layered | dag | cyclic | tree")
		n := fs.Int("n", 30, "number of nodes")
		seed := fs.Int64("seed", 1, "random seed")
		density := fs.Float64("density", 1.4, "edges per node (approx)")
		if err := fs.Parse(rest); err != nil {
			return 2
		}
		s, err := gen.DOT(*kind, *n, *seed, *density)
		if err != nil {
			return fail(err)
		}
		io.WriteString(stdout, s)
		return 0
	}
	fmt.Fprintf(stderr, "tier: unknown command %q\n\n%s\n", cmd, usage)
	return 2
}

func printMetrics(w io.Writer, r *layout.Result) {
	m := r.Metrics
	fmt.Fprintf(w, "nodes        %d\nedges        %d\nlayers       %d\nwidest layer %d\ndummies      %d\ncrossings    %d\nedge length  %.0f\nreversed     %d\nbends        %d\nsize         %.0f x %.0f\n",
		len(r.Nodes), len(r.Edges), m.Layers, m.MaxLayer, m.Dummies, m.Crossings, m.EdgeLength, m.Reversed, m.Bends, m.Width, m.Height)
}

func doExact(lg layout.Graph, o layout.Options, w io.Writer, stderr io.Writer) int {
	res, err := layout.Layout(lg, o)
	if err != nil {
		fmt.Fprintln(stderr, "tier:", err)
		return 1
	}
	best, ok, err := layout.OptimalCrossings(lg, o)
	if err != nil {
		fmt.Fprintln(stderr, "tier:", err)
		return 1
	}
	if !ok {
		fmt.Fprintln(stderr, "tier: graph too large for exact crossing minimisation (layers too wide)")
		return 1
	}
	fmt.Fprintf(w, "heuristic crossings %d\noptimal crossings   %d\ngap                 %d\n", res.Metrics.Crossings, best, res.Metrics.Crossings-best)
	return 0
}

// parseInterleaved parses flags that may appear before or after positional
// arguments ("tier layout g.dot -o g.svg").
func parseInterleaved(fs *flag.FlagSet, args []string) ([]string, error) {
	var pos []string
	for {
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		args = fs.Args()
		if len(args) == 0 {
			return pos, nil
		}
		if args[0] == "-" {
			pos = append(pos, "-")
			args = args[1:]
			continue
		}
		pos = append(pos, args[0])
		args = args[1:]
	}
}
