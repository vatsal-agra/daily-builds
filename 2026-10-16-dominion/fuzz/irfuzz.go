package fuzz

import (
	"fmt"
	"math/rand"
	"regexp"
	"strings"

	"dominion/backend"
	"dominion/front"
	"dominion/ir"
	"dominion/opt"
)

var (
	nameRe   = regexp.MustCompile(`%[av]?\d+`)
	constRe  = regexp.MustCompile(`(^|[ ,\[])(-?\d+)([,\]]|$)`)
	binOpRe  = regexp.MustCompile(`= (add|sub|mul|and|or|xor|shl|shr|eq|ne|lt|le|gt|ge) `)
	binNames = []string{"add", "sub", "mul", "and", "or", "xor", "shl", "shr", "eq", "ne", "lt", "le", "gt", "ge"}
)

// MutateIR returns a mutated copy of IR text (1-3 random edits). The result may be invalid IR.
func MutateIR(text string, r *rand.Rand) string {
	lines := strings.Split(text, "\n")
	var blocks []string
	var names []string
	for _, l := range lines {
		t := strings.TrimSpace(l)
		if strings.HasSuffix(t, ":") && !strings.Contains(t, " ") {
			blocks = append(blocks, strings.TrimSuffix(t, ":"))
		}
	}
	for _, m := range nameRe.FindAllString(text, -1) {
		names = append(names, m)
	}
	want := 1 + r.Intn(3)
	for attempts := 0; want > 0 && attempts < 60; attempts++ {
		before := strings.Join(lines, "\n")
		mutateOnce(&lines, blocks, names, r)
		if strings.Join(lines, "\n") != before {
			want--
		}
	}
	return strings.Join(lines, "\n")
}

// mutateOnce applies one random edit (which may turn out to be a no-op).
func mutateOnce(lp *[]string, blocks, names []string, r *rand.Rand) {
	lines := *lp
	defer func() { *lp = lines }()
	{
		i := r.Intn(len(lines))
		l := lines[i]
		t := strings.TrimSpace(l)
		if t == "" || strings.HasPrefix(t, "func") || t == "}" || strings.HasSuffix(t, ":") {
			return
		}
		switch r.Intn(7) {
		case 0: // swap two operands of a binary op
			if loc := binOpRe.FindStringIndex(l); loc != nil {
				head := l[:loc[1]]
				ops := strings.Split(strings.TrimSpace(l[loc[1]:]), ",")
				if len(ops) == 2 {
					lines[i] = head + strings.TrimSpace(ops[1]) + ", " + strings.TrimSpace(ops[0])
				}
			}
		case 1: // change the operator
			if binOpRe.MatchString(l) {
				lines[i] = binOpRe.ReplaceAllString(l, "= "+binNames[r.Intn(len(binNames))]+" ")
			}
		case 2: // perturb a constant
			if m := constRe.FindStringSubmatchIndex(l); m != nil {
				v := []string{"0", "1", "-1", "2", "7", "63", "64", "255"}[r.Intn(8)]
				lines[i] = l[:m[4]] + v + l[m[5]:]
			}
		case 3: // retarget a branch
			if (strings.HasPrefix(t, "br ") || strings.HasPrefix(t, "condbr ")) && len(blocks) > 0 {
				f := strings.Fields(strings.ReplaceAll(t, ",", " "))
				tgt := f[len(f)-1]
				lines[i] = strings.Replace(l, tgt, blocks[r.Intn(len(blocks))], 1)
			}
		case 4: // use a different value as an operand
			if ms := nameRe.FindAllStringIndex(l, -1); len(ms) > 0 && len(names) > 0 && !strings.Contains(l, "phi") {
				m := ms[r.Intn(len(ms))]
				if m[0] > strings.Index(l, "=") && strings.Contains(l, "=") || !strings.Contains(l, "=") {
					rep := names[r.Intn(len(names))]
					if r.Intn(4) == 0 {
						rep = fmt.Sprint(r.Intn(9) - 2)
					}
					lines[i] = l[:m[0]] + rep + l[m[1]:]
				}
			}
		case 5: // delete an instruction
			if !strings.HasPrefix(t, "br ") && !strings.HasPrefix(t, "condbr ") && !strings.HasPrefix(t, "ret ") {
				lines = append(lines[:i], lines[i+1:]...)
			}
		case 6: // swap condbr targets
			if strings.HasPrefix(t, "condbr ") {
				p := strings.Split(t, ",")
				if len(p) == 3 {
					lines[i] = "  " + p[0] + ", " + strings.TrimSpace(p[2]) + ", " + strings.TrimSpace(p[1])
				}
			}
		}
	}
}

// CheckIRText differentially tests an arbitrary (verified) IR module: interpreter vs every
// optimisation level, random pass orders, and the backend at several register counts.
func CheckIRText(seed int64, text string, cfg Config) Outcome {
	var out Outcome
	fail := func(stage, detail string) Outcome {
		out.Fail = &Failure{seed, text, "ir:" + stage, detail}
		return out
	}
	load := func() *ir.Module {
		m, err := ir.Parse(text)
		if err != nil || m.Verify() != nil {
			return nil
		}
		return m
	}
	base := load()
	if base == nil {
		out.Skipped = true
		return out
	}
	var want ir.Result
	if f := safe("baseline", seed, text, func() *Failure { want = base.Run(cfg.Fuel); return nil }); f != nil {
		return fail("baseline", f.Detail) // the reference interpreter itself must never crash
	}
	switch want.Trap {
	case ir.TrapFuel, ir.TrapStack, ir.TrapOOB, ir.TrapOutput, "no parameterless function @main":
		out.Skipped = true // non-terminating, or undefined behaviour (out-of-bounds)
		return out
	}
	check := func(stage string, got ir.Result) *Outcome {
		if !got.Same(want) {
			o := fail(stage, fmt.Sprintf("got %v, want %v", got, want))
			return &o
		}
		return nil
	}
	r := rand.New(rand.NewSource(seed))
	var configs [][]string
	for lvl := 1; lvl <= 3; lvl++ {
		configs = append(configs, opt.Level(lvl))
	}
	names := opt.PassNames()
	for t := 0; t < 3; t++ {
		var p []string
		for i := 0; i < 3+r.Intn(10); i++ {
			p = append(p, names[r.Intn(len(names))])
		}
		configs = append(configs, p)
	}
	for _, passes := range configs {
		stage := strings.Join(passes, ",")
		m := load()
		var res *Outcome
		if f := safe(stage, seed, text, func() *Failure {
			if _, err := opt.Run(m, passes, opt.Options{Verify: true}); err != nil {
				return &Failure{seed, text, stage, err.Error()}
			}
			res = check(stage, m.Run(cfg.Fuel*4))
			return nil
		}); f != nil {
			return fail(stage, f.Detail)
		}
		if res != nil {
			return *res
		}
		regs := cfg.Regs[r.Intn(len(cfg.Regs))]
		if f := safe("vm "+stage, seed, text, func() *Failure {
			o, err := backend.Compile(m, backend.Config{NumRegs: regs})
			if err != nil {
				return &Failure{seed, text, stage, err.Error()}
			}
			got, _ := o.Prog.Run(cfg.Fuel * 4)
			if got.Trap == ir.TrapFuel {
				return &Failure{seed, text, stage, "vm out of fuel"}
			}
			res = check(fmt.Sprintf("vm regs=%d %s", regs, stage), got)
			return nil
		}); f != nil {
			return fail("vm "+stage, f.Detail)
		}
		if res != nil {
			return *res
		}
	}
	return out
}

// CheckMutant builds a program from the seed, optimises it lightly (so phis/selects exist),
// mutates the IR text and runs CheckIRText on the result.
func CheckMutant(seed int64, cfg Config) Outcome {
	src := Generate(seed)
	m, err := front.Compile(src)
	if err != nil {
		return Outcome{Fail: &Failure{seed, src, "frontend", err.Error()}}
	}
	if _, err := opt.Optimize(m, 1+int(seed%2), false); err != nil {
		return Outcome{Fail: &Failure{seed, src, "optimize", err.Error()}}
	}
	r := rand.New(rand.NewSource(seed * 7919))
	return CheckIRText(seed, MutateIR(m.String(), r), cfg)
}
