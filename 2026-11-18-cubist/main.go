// Command cubist is a Rubik's Cube toolkit: solve, scramble, analyze, verify, render, bench, serve.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"math/rand"
	"net/http"
	"os"
	"sort"
	"strings"
	"time"

	"cubist/cube"
	"cubist/web"
)

const usage = `cubist — Rubik's Cube toolkit (Kociemba two-phase solver)

usage: cubist <command> [flags] [args]

  solve     solve a cube given --scramble "R U F'" or --facelets <54 letters>   [--json]
  scramble  print a scramble: --state (random-state, default) or --moves N
  analyze   order, cycles and parity of an algorithm:  cubist analyze "R U R' U'"
  verify    validate a facelet string and explain why it is unsolvable
  show      print the facelet net of a scramble or facelet string
  simplify  cancel/merge moves:  cubist simplify "R R U U' L"
  invert    invert an algorithm:  cubist invert "R U R' U'"
  render    write a self-contained animated 3-D HTML player: -o file.html
  bench     solve N random states and print length / time statistics
  serve     interactive web UI + JSON API on --addr (default :8080)

run "cubist <command> -h" for flags.
`

func die(format string, a ...any) {
	fmt.Fprintf(os.Stderr, "error: "+format+"\n", a...)
	os.Exit(1)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Print(usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	switch cmd {
	case "solve":
		cmdSolve(args)
	case "scramble":
		cmdScramble(args)
	case "analyze":
		cmdAnalyze(args)
	case "verify":
		cmdVerify(args)
	case "show":
		cmdShow(args)
	case "simplify", "invert":
		cmdSeq(cmd, args)
	case "render":
		cmdRender(args)
	case "bench":
		cmdBench(args)
	case "serve":
		cmdServe(args)
	case "-h", "--help", "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s", cmd, usage)
		os.Exit(2)
	}
}

type inputFlags struct {
	scramble, facelets *string
	fs                 *flag.FlagSet
}

// looksLikeFacelets: 54 letters, exactly nine of each of U R F D L B. A real 54-move scramble
// written without spaces *and* with that exact letter census is vanishingly unlikely.
func looksLikeFacelets(s string) bool {
	s = strings.ToUpper(s)
	if len(s) != 54 {
		return false
	}
	for _, f := range "URFDLB" {
		if strings.Count(s, string(f)) != 9 {
			return false
		}
	}
	return true
}

func addInput(fs *flag.FlagSet) inputFlags {
	return inputFlags{
		scramble: fs.String("scramble", "", "scramble in face-turn notation"),
		facelets: fs.String("facelets", "", "54-letter facelet string (U R F D L B)"),
		fs:       fs,
	}
}

// cubeFrom builds the cube from flags, positional args, or errors out helpfully.
func cubeFrom(in inputFlags, rest []string) (cube.Cube, string) {
	scr := *in.scramble
	given := false
	in.fs.Visit(func(f *flag.Flag) {
		if f.Name == "scramble" {
			given = true
		}
	})
	if !given && *in.facelets == "" && len(rest) > 0 {
		joined := strings.Join(rest, " ")
		if looksLikeFacelets(joined) {
			*in.facelets = joined
		} else {
			scr, given = joined, true
		}
	}
	switch {
	case *in.facelets != "" && given:
		die("give either --scramble or --facelets, not both")
	case *in.facelets != "":
		c, err := cube.ParseFacelets(*in.facelets)
		if err != nil {
			die("%v", err)
		}
		return c, ""
	case given:
		ms, err := cube.ParseMoves(scr)
		if err != nil {
			die("%v", err)
		}
		return cube.FromMoves(ms), cube.FormatMoves(ms)
	}
	die("no cube given: use --scramble \"R U F'\" or --facelets <54 letters>")
	return cube.Cube{}, ""
}

func solveFlags(fs *flag.FlagSet, defTime time.Duration) (*int, *int, *time.Duration) {
	return fs.Int("target", 20, "stop once a solution this short is found"),
		fs.Int("max", 30, "never return more moves than this"),
		fs.Duration("time", defTime, "keep searching for shorter solutions this long")
}

func checkSolveFlags(target, maxl int, tl time.Duration) {
	if target < 1 || maxl < 1 || tl <= 0 {
		die("--target and --max must be >= 1 and --time must be positive")
	}
}

func cmdSolve(args []string) {
	fs := flag.NewFlagSet("solve", flag.ExitOnError)
	in := addInput(fs)
	target, maxl, tl := solveFlags(fs, 2*time.Second)
	asJSON := fs.Bool("json", false, "machine-readable output")
	fs.Parse(args)
	checkSolveFlags(*target, *maxl, *tl)
	c, scr := cubeFrom(in, fs.Args())
	sol, err := web.BuildSolution(c, scr, cube.Options{Target: *target, MaxLen: *maxl, TimeLimit: *tl})
	if err != nil {
		die("%v", err)
	}
	if sol.Final != cube.SolvedFacelets {
		die("internal error: physical simulation disagrees with solver")
	}
	if *asJSON {
		json.NewEncoder(os.Stdout).Encode(sol)
		return
	}
	if len(sol.Moves) == 0 {
		fmt.Println("already solved (0 moves)")
		return
	}
	if sol.Phase1 < 0 {
		fmt.Printf("solution (%d moves; the scramble reversed is shorter than the solver's answer):\n", len(sol.Moves))
		fmt.Println(strings.Join(sol.Moves, " "))
	} else {
		fmt.Printf("solution (%d moves; phase 1: %d, phase 2: %d; %.1f ms):\n", len(sol.Moves), sol.Phase1, len(sol.Moves)-sol.Phase1, sol.Ms)
		fmt.Println(strings.Join(sol.Moves[:sol.Phase1], " ") + "  .  " + strings.Join(sol.Moves[sol.Phase1:], " "))
	}
	fmt.Println("verified by independent 3-D sticker simulation: solved ✔")
}

func cmdScramble(args []string) {
	fs := flag.NewFlagSet("scramble", flag.ExitOnError)
	n := fs.Int("moves", 0, "random-move scramble of N moves instead of a random state")
	seed := fs.Int64("seed", 0, "random seed (default: time)")
	count := fs.Int("n", 1, "number of scrambles")
	fs.Parse(args)
	if *seed == 0 {
		*seed = time.Now().UnixNano()
	}
	if *count < 1 || *count > 1000 {
		die("-n must be 1..1000")
	}
	if *n < 0 || *n > 1000 {
		die("-moves must be 0..1000")
	}
	r := rand.New(rand.NewSource(*seed))
	for i := 0; i < *count; i++ {
		if *n > 0 {
			fmt.Println(cube.FormatMoves(cube.RandomMoves(r, *n)))
			continue
		}
		c := cube.RandomState(r)
		res, err := cube.Solve(c, cube.Options{Target: 22, TimeLimit: 500 * time.Millisecond})
		if err != nil {
			die("%v", err)
		}
		fmt.Println(cube.FormatMoves(cube.InvertSeq(res.Moves)))
	}
}

func cmdAnalyze(args []string) {
	if len(args) == 0 {
		die(`usage: cubist analyze "R U R' U'"`)
	}
	ms, err := cube.ParseMoves(strings.Join(args, " "))
	if err != nil {
		die("%v", err)
	}
	fmt.Print(cube.Analyze(ms))
}

func cmdVerify(args []string) {
	fs := flag.NewFlagSet("verify", flag.ExitOnError)
	f := fs.String("facelets", "", "54-letter facelet string")
	fs.Parse(args)
	s := *f
	if s == "" {
		s = strings.Join(fs.Args(), "")
	}
	if s == "" {
		die("usage: cubist verify --facelets <54 letters>")
	}
	c, err := cube.ParseFacelets(s)
	if err != nil {
		fmt.Println("INVALID:", err)
		os.Exit(1)
	}
	fmt.Println("VALID: solvable cube", map[bool]string{true: "(already solved)", false: ""}[c.IsSolved()])
}

var ansi = map[byte]string{'U': "47;30", 'R': "41;97", 'F': "42;30", 'D': "43;30", 'L': "45;97", 'B': "44;97"}

func cmdShow(args []string) {
	fs := flag.NewFlagSet("show", flag.ExitOnError)
	in := addInput(fs)
	color := fs.Bool("color", false, "use ANSI colors")
	fs.Parse(args)
	c, _ := cubeFrom(in, fs.Args())
	f := c.Facelets()
	cell := func(i int) string {
		if *color {
			return fmt.Sprintf("\x1b[%sm %c \x1b[0m", ansi[f[i]], f[i])
		}
		return fmt.Sprintf(" %c", f[i])
	}
	row := func(face, r int) string {
		var sb strings.Builder
		for k := 0; k < 3; k++ {
			sb.WriteString(cell(face*9 + r*3 + k))
		}
		return sb.String()
	}
	pad := strings.Repeat(" ", map[bool]int{true: 9, false: 6}[*color])
	for r := 0; r < 3; r++ {
		fmt.Println(pad + row(0, r))
	}
	for r := 0; r < 3; r++ {
		fmt.Println(row(4, r) + row(2, r) + row(1, r) + row(5, r))
	}
	for r := 0; r < 3; r++ {
		fmt.Println(pad + row(3, r))
	}
}

func cmdSeq(cmd string, args []string) {
	if len(args) == 0 {
		die(`usage: cubist %s "R U R' U'"`, cmd)
	}
	ms, err := cube.ParseMoves(strings.Join(args, " "))
	if err != nil {
		die("%v", err)
	}
	if cmd == "invert" {
		fmt.Println(cube.FormatMoves(cube.InvertSeq(ms)))
		return
	}
	fmt.Println(cube.FormatMoves(cube.Simplify(ms)))
}

func cmdRender(args []string) {
	fs := flag.NewFlagSet("render", flag.ExitOnError)
	in := addInput(fs)
	target, maxl, tl := solveFlags(fs, 2*time.Second)
	out := fs.String("o", "cubist.html", "output HTML file")
	fs.Parse(args)
	checkSolveFlags(*target, *maxl, *tl)
	c, scr := cubeFrom(in, fs.Args())
	sol, err := web.BuildSolution(c, scr, cube.Options{Target: *target, MaxLen: *maxl, TimeLimit: *tl})
	if err != nil {
		die("%v", err)
	}
	page, err := web.RenderHTML(sol, false)
	if err != nil {
		die("%v", err)
	}
	if err := os.WriteFile(*out, []byte(page), 0o644); err != nil {
		die("%v", err)
	}
	fmt.Printf("wrote %s (%d-move solution)\n", *out, len(sol.Moves))
}

func cmdBench(args []string) {
	fs := flag.NewFlagSet("bench", flag.ExitOnError)
	n := fs.Int("n", 100, "number of random states")
	seed := fs.Int64("seed", 1, "random seed")
	target, maxl, tl := solveFlags(fs, 150*time.Millisecond)
	fs.Parse(args)
	checkSolveFlags(*target, *maxl, *tl)
	if *n < 1 || *n > 100000 {
		die("-n must be 1..100000")
	}
	t0 := time.Now()
	cube.GetTables()
	fmt.Printf("tables built in %v\n", time.Since(t0).Round(time.Millisecond))
	r := rand.New(rand.NewSource(*seed))
	hist := map[int]int{}
	var total int
	var times []time.Duration
	t1 := time.Now()
	for i := 0; i < *n; i++ {
		c := cube.RandomState(r)
		res, err := cube.Solve(c, cube.Options{Target: *target, MaxLen: *maxl, TimeLimit: *tl})
		if err != nil {
			die("%v", err)
		}
		if cube.PhysicalFaceletsFrom(c.Facelets(), res.Moves) != cube.SolvedFacelets {
			die("physical check failed on state %d", i)
		}
		hist[len(res.Moves)]++
		total += len(res.Moves)
		times = append(times, res.Elapsed)
	}
	sort.Slice(times, func(i, j int) bool { return times[i] < times[j] })
	var keys []int
	for k := range hist {
		keys = append(keys, k)
	}
	sort.Ints(keys)
	fmt.Printf("%d random states, target %d, every solution re-verified physically\n", *n, *target)
	for _, k := range keys {
		fmt.Printf("  %2d moves  %5d  %s\n", k, hist[k], strings.Repeat("█", (hist[k]*50+*n-1)/(*n)))
	}
	fmt.Printf("mean %.2f moves   median time %v   p95 %v   max %v   total %v\n",
		float64(total)/float64(*n), times[len(times)/2].Round(time.Microsecond),
		times[len(times)*95/100].Round(time.Microsecond), times[len(times)-1].Round(time.Microsecond),
		time.Since(t1).Round(time.Millisecond))
}

func cmdServe(args []string) {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	addr := fs.String("addr", ":8080", "listen address")
	target, maxl, tl := solveFlags(fs, 2*time.Second)
	fs.Parse(args)
	checkSolveFlags(*target, *maxl, *tl)
	cube.GetTables()
	fmt.Printf("cubist serving on http://localhost%s\n", *addr)
	srv := &http.Server{Addr: *addr, Handler: web.Handler(cube.Options{Target: *target, MaxLen: *maxl, TimeLimit: *tl}), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second}
	die("%v", srv.ListenAndServe())
}
