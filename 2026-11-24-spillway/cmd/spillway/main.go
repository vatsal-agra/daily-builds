// Command spillway is a register-allocation laboratory.
package main

import (
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"

	"spillway/sp"
)

const usage = `spillway — register-allocation laboratory

usage:
  spillway interp  <prog.ir> [-args 1,2]                 run the reference interpreter
  spillway run     <prog.ir> -k 6 [-alloc color|linear|naive] [-args 1,2] [-nocoalesce] [-nopost]
                                                         allocate, print machine code, execute, verify
  spillway compare <prog.ir> -k 6 [-args ...]            all allocators side by side
  spillway sweep   <prog.ir> [-kmin 3 -kmax 16]          cycles/spills as K grows
  spillway live    <prog.ir>                             liveness, loop depth, live intervals
  spillway gen     [-seed 1 -vars 10 -depth 3 -shuffle]  print a random program
  spillway fuzz    [-n 200 -seed 1 -vars 14]             differential fuzzing of every allocator
  spillway report  <prog.ir> -o report.html [-k 6]       self-contained HTML report
  -args accepts several input vectors separated by ';' (e.g. -args "5;10;20").`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, usage)
		os.Exit(2)
	}
	cmd, rest := os.Args[1], os.Args[2:]
	var err error
	switch cmd {
	case "interp":
		err = cmdInterp(rest)
	case "run":
		err = cmdRun(rest)
	case "compare":
		err = cmdCompare(rest)
	case "sweep":
		err = cmdSweep(rest)
	case "live":
		err = cmdLive(rest)
	case "gen":
		err = cmdGen(rest)
	case "fuzz":
		err = cmdFuzz(rest)
	case "report":
		err = cmdReport(rest)
	case "help", "-h", "--help":
		fmt.Println(usage)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s\n", cmd, usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

// splitArgs separates the program path (first non-flag arg) from flags so the
// path may appear before or after the flags.
func parseFlags(fs *flag.FlagSet, args []string, wantFile bool) (string, error) {
	var file string
	var flags []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		if strings.HasPrefix(a, "-") {
			flags = append(flags, a)
			name := strings.TrimLeft(a, "-")
			if !strings.Contains(name, "=") {
				if f := fs.Lookup(name); f != nil {
					if _, isBool := f.Value.(interface{ IsBoolFlag() bool }); !isBool && i+1 < len(args) {
						i++
						flags = append(flags, args[i])
					}
				}
			}
		} else if file == "" {
			file = a
		} else {
			return "", fmt.Errorf("unexpected argument %q", a)
		}
	}
	if err := fs.Parse(flags); err != nil {
		return "", err
	}
	if wantFile && file == "" {
		return "", fmt.Errorf("missing program file (see `spillway help`)")
	}
	return file, nil
}

func load(path string) (*sp.Function, error) {
	src, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	f, err := sp.Parse(string(src))
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if err := f.Validate(); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return f, nil
}

func parseInputs(s string) ([][]int64, error) {
	if strings.TrimSpace(s) == "" {
		return [][]int64{nil}, nil
	}
	var out [][]int64
	for _, vec := range strings.Split(s, ";") {
		var v []int64
		for _, p := range strings.Split(vec, ",") {
			p = strings.TrimSpace(p)
			if p == "" {
				continue
			}
			n, err := strconv.ParseInt(p, 0, 64)
			if err != nil {
				return nil, fmt.Errorf("bad -args value %q", p)
			}
			v = append(v, n)
		}
		out = append(out, v)
	}
	return out, nil
}

func cmdInterp(args []string) error {
	fs := flag.NewFlagSet("interp", flag.ContinueOnError)
	a := fs.String("args", "", "input vector(s)")
	file, err := parseFlags(fs, args, true)
	if err != nil {
		return err
	}
	f, err := load(file)
	if err != nil {
		return err
	}
	ins, err := parseInputs(*a)
	if err != nil {
		return err
	}
	for _, in := range ins {
		r, err := sp.Run(f, in, sp.StepBudget)
		if err != nil {
			return fmt.Errorf("input %v: %w", in, err)
		}
		fmt.Printf("input %v: ret=%d output=%v steps=%d cycles=%d\n", in, r.Ret, r.Output, r.Stats.Steps, r.Stats.Cycles)
	}
	return nil
}

func cmdRun(args []string) error {
	fs := flag.NewFlagSet("run", flag.ContinueOnError)
	k := fs.Int("k", 6, "number of physical registers")
	al := fs.String("alloc", "color", "allocator: color, linear, naive")
	a := fs.String("args", "", "input vector(s)")
	noco := fs.Bool("nocoalesce", false, "disable coalescing (color only)")
	nopost := fs.Bool("nopost", false, "skip post-allocation clean-up (forwarding, dead stores, slot sharing)")
	file, err := parseFlags(fs, args, true)
	if err != nil {
		return err
	}
	f, err := load(file)
	if err != nil {
		return err
	}
	ins, err := parseInputs(*a)
	if err != nil {
		return err
	}
	if err := sp.CheckTerminates(f, ins); err != nil {
		return err
	}
	al2, err := sp.Allocate(f, *al, *k, sp.Options{Coalesce: !*noco, NoPost: *nopost})
	if err != nil {
		return err
	}
	fmt.Printf("; %s on %d registers — %d allocation round(s), %d variable(s) spilled, %d move(s) eliminated\n",
		al2.Allocator, al2.K, al2.Rounds, al2.SpilledVars, al2.Coalesced)
	if !*nopost {
		p := al2.Post
		fmt.Printf("; post-pass: %d reload(s) dropped, %d turned into moves, %d dead store(s) removed, stack slots %d -> %d\n",
			p.LoadsDropped, p.LoadsToMoves, p.DeadStores, p.SlotsBefore, p.SlotsAfter)
	}
	fmt.Print(sp.FormatMachine(al2.Machine))
	if _, err := sp.Verify(f, al2, ins); err != nil {
		return err
	}
	for _, in := range ins {
		ref, _ := sp.Run(f, in, sp.StepBudget)
		got, _ := sp.Run(al2.Machine, in, sp.StepBudget*8)
		fmt.Printf("; input %v: ret=%d output=%v (machine == reference ✓) cycles=%d (ref %d) spill ld/st=%d/%d\n",
			in, got.Ret, got.Output, got.Stats.Cycles, ref.Stats.Cycles, got.Stats.SpillLoads, got.Stats.SpillStores)
	}
	return nil
}

func cmdCompare(args []string) error {
	fs := flag.NewFlagSet("compare", flag.ContinueOnError)
	k := fs.Int("k", 6, "number of physical registers")
	a := fs.String("args", "", "input vector(s)")
	noco := fs.Bool("nocoalesce", false, "disable coalescing")
	nopost := fs.Bool("nopost", false, "skip post-allocation clean-up")
	file, err := parseFlags(fs, args, true)
	if err != nil {
		return err
	}
	f, err := load(file)
	if err != nil {
		return err
	}
	ins, err := parseInputs(*a)
	if err != nil {
		return err
	}
	if err := sp.CheckTerminates(f, ins); err != nil {
		return err
	}
	fmt.Printf("%s: %d vregs, %d blocks, %d instrs; K=%d\n", f.Name, f.NumRegs, len(f.Blocks), f.NumInstrs(), *k)
	rows := sp.CompareOpt(f, *k, ins, sp.Options{Coalesce: !*noco, NoPost: *nopost})
	fmt.Print(sp.FormatTable(rows))
	for _, r := range rows {
		if r.Err != nil {
			return fmt.Errorf("%s: %w", r.Allocator, r.Err)
		}
	}
	return nil
}

func cmdSweep(args []string) error {
	fs := flag.NewFlagSet("sweep", flag.ContinueOnError)
	kmin := fs.Int("kmin", sp.MinK, "smallest K")
	kmax := fs.Int("kmax", 16, "largest K")
	a := fs.String("args", "", "input vector(s)")
	file, err := parseFlags(fs, args, true)
	if err != nil {
		return err
	}
	if *kmin < sp.MinK || *kmax < *kmin {
		return fmt.Errorf("need %d <= kmin <= kmax", sp.MinK)
	}
	f, err := load(file)
	if err != nil {
		return err
	}
	ins, err := parseInputs(*a)
	if err != nil {
		return err
	}
	if err := sp.CheckTerminates(f, ins); err != nil {
		return err
	}
	fmt.Print(sp.FormatSweep(sp.Sweep(f, *kmin, *kmax, ins, true)))
	return nil
}

func cmdLive(args []string) error {
	fs := flag.NewFlagSet("live", flag.ContinueOnError)
	file, err := parseFlags(fs, args, true)
	if err != nil {
		return err
	}
	f, err := load(file)
	if err != nil {
		return err
	}
	fmt.Print(sp.FormatLiveness(f))
	return nil
}
