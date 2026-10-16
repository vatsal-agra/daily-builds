package fuzz

import (
	"fmt"
	"math/rand"
	"strings"

	"dominion/backend"
	"dominion/front"
	"dominion/ir"
	"dominion/opt"
)

// Failure describes a miscompile or compiler crash.
type Failure struct {
	Seed   int64
	Src    string
	Stage  string
	Detail string
}

func (f *Failure) Error() string {
	return fmt.Sprintf("seed %d: [%s] %s", f.Seed, f.Stage, f.Detail)
}

// Config controls one differential check.
type Config struct {
	Regs       []int // register-file sizes to compile for
	Fuel       int64
	ChaosOrder bool // also run random pass orders
}

var DefaultConfig = Config{Regs: []int{4, 6, 12}, Fuel: 3_000_000, ChaosOrder: true}

// Outcome of a seed.
type Outcome struct {
	Skipped bool // baseline ran out of fuel / stack
	Trapped bool // baseline trapped (and every configuration agreed)
	Fail    *Failure
}

func safe(stage string, seed int64, src string, fn func() *Failure) (fail *Failure) {
	defer func() {
		if r := recover(); r != nil {
			fail = &Failure{seed, src, stage, fmt.Sprintf("compiler panic: %v", r)}
		}
	}()
	return fn()
}

// Check runs one seed through every configuration.
func Check(seed int64, cfg Config) Outcome { return CheckSource(seed, Generate(seed), cfg) }

// CheckSource is Check for an explicit program text.
func CheckSource(seed int64, src string, cfg Config) Outcome {
	var out Outcome
	base, err := front.Compile(src)
	if err != nil {
		out.Fail = &Failure{seed, src, "frontend", err.Error()}
		return out
	}
	want := base.Run(cfg.Fuel)
	if want.Trap == ir.TrapFuel || want.Trap == ir.TrapStack {
		out.Skipped = true
		return out
	}
	out.Trapped = want.Trap != ""
	compare := func(stage string, got ir.Result) *Failure {
		if !got.Same(want) {
			return &Failure{seed, src, stage, fmt.Sprintf("got %v, want %v", got, want)}
		}
		return nil
	}
	compileOpt := func(passes []string) (*ir.Module, *Failure) {
		m, _ := front.Compile(src)
		var f *Failure
		f = safe("optimize "+strings.Join(passes, ","), seed, src, func() *Failure {
			if _, err := opt.Run(m, passes, opt.Options{Verify: true}); err != nil {
				return &Failure{seed, src, "optimize " + strings.Join(passes, ","), err.Error()}
			}
			return nil
		})
		return m, f
	}
	runVM := func(stage string, m *ir.Module, regs int) *Failure {
		return safe(stage, seed, src, func() *Failure {
			o, err := backend.Compile(m, backend.Config{NumRegs: regs})
			if err != nil {
				return &Failure{seed, src, stage, err.Error()}
			}
			got, _ := o.Prog.Run(cfg.Fuel * 4)
			if got.Trap == ir.TrapFuel {
				return &Failure{seed, src, stage, "vm ran out of fuel but the interpreter did not"}
			}
			return compare(stage, got)
		})
	}
	// 1. unoptimised IR through the backend (exercises allocas + spills)
	for _, regs := range cfg.Regs {
		if f := runVM(fmt.Sprintf("vm -O0 regs=%d", regs), base, regs); f != nil {
			out.Fail = f
			return out
		}
	}
	// 2. every level
	for lvl := 1; lvl <= 3; lvl++ {
		passes := opt.Level(lvl)
		m, f := compileOpt(passes)
		if f != nil {
			out.Fail = f
			return out
		}
		if f := safe(fmt.Sprintf("interp -O%d", lvl), seed, src, func() *Failure { return compare(fmt.Sprintf("interp -O%d", lvl), m.Run(cfg.Fuel*4)) }); f != nil {
			out.Fail = f
			return out
		}
		// text round trip must be lossless
		if f := safe("roundtrip", seed, src, func() *Failure {
			m2, err := ir.Parse(m.String())
			if err != nil {
				return &Failure{seed, src, "roundtrip", err.Error()}
			}
			if err := m2.Verify(); err != nil {
				return &Failure{seed, src, "roundtrip", err.Error()}
			}
			return compare("roundtrip", m2.Run(cfg.Fuel*4))
		}); f != nil {
			out.Fail = f
			return out
		}
		for _, regs := range cfg.Regs {
			if f := runVM(fmt.Sprintf("vm -O%d regs=%d", lvl, regs), m, regs); f != nil {
				out.Fail = f
				return out
			}
		}
	}
	// 3. random pass orders
	if cfg.ChaosOrder {
		r := rand.New(rand.NewSource(seed ^ 0x5eed))
		names := opt.PassNames()
		for trial := 0; trial < 3; trial++ {
			passes := []string{"simplifycfg"}
			if r.Intn(5) != 0 {
				passes = append(passes, "mem2reg")
			}
			for i := 0; i < 4+r.Intn(10); i++ {
				passes = append(passes, names[r.Intn(len(names))])
			}
			m, f := compileOpt(passes)
			if f != nil {
				out.Fail = f
				return out
			}
			stage := "chaos " + strings.Join(passes, ",")
			if f := safe(stage, seed, src, func() *Failure { return compare(stage, m.Run(cfg.Fuel*4)) }); f != nil {
				out.Fail = f
				return out
			}
			if f := runVM("vm "+stage, m, cfg.Regs[r.Intn(len(cfg.Regs))]); f != nil {
				out.Fail = f
				return out
			}
		}
	}
	return out
}

// Reduce shrinks a failing program by deleting lines and balanced blocks while the failure persists.
func Reduce(f *Failure, cfg Config) string {
	return ReduceWith(f.Src, func(src string) bool {
		o := CheckSource(f.Seed, src, cfg)
		return o.Fail != nil && o.Fail.Stage != "frontend" && stageKind(o.Fail.Stage) == stageKind(f.Stage)
	})
}

// ReduceWith shrinks src (deleting balanced blocks, then single lines, to a fixed point) while
// failsLike keeps returning true.
func ReduceWith(src string, failsLike func(src string) bool) string {
	lines := strings.Split(strings.TrimRight(src, "\n"), "\n")
	try := func(cand []string) bool { return failsLike(strings.Join(cand, "\n") + "\n") }
	for changed := true; changed; {
		changed = false
		// remove balanced blocks first, then single lines
		for i := 0; i < len(lines); i++ {
			j := blockEnd(lines, i)
			if j <= i {
				continue
			}
			cand := append(append([]string(nil), lines[:i]...), lines[j+1:]...)
			if try(cand) {
				lines, changed = cand, true
				i--
			}
		}
		for i := 0; i < len(lines); i++ {
			if strings.HasPrefix(strings.TrimSpace(lines[i]), "fn ") || strings.TrimSpace(lines[i]) == "}" {
				continue
			}
			cand := append(append([]string(nil), lines[:i]...), lines[i+1:]...)
			if try(cand) {
				lines, changed = cand, true
				i--
			}
		}
	}
	return strings.Join(lines, "\n") + "\n"
}

func stageKind(s string) string {
	if i := strings.IndexAny(s, " "); i > 0 {
		return s[:i]
	}
	return s
}

// blockEnd returns the index of the line closing the block opened on line i (or -1).
func blockEnd(lines []string, i int) int {
	t := strings.TrimSpace(lines[i])
	if !strings.HasSuffix(t, "{") || strings.HasPrefix(t, "fn ") {
		return -1
	}
	depth := 0
	for j := i; j < len(lines); j++ {
		t := strings.TrimSpace(lines[j])
		if strings.HasSuffix(t, "{") {
			depth++
		}
		if strings.HasPrefix(t, "}") {
			depth--
			if depth == 0 {
				return j
			}
			if strings.HasSuffix(t, "{") { // "} else {"
				depth++
			}
		}
	}
	return -1
}
