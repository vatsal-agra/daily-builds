package opt_test

import (
	"fmt"
	"math/rand"
	"os"
	"strconv"
	"strings"
	"testing"

	"dominion/backend"
	"dominion/ir"
	"dominion/opt"
)

type irCase struct {
	name, text string
	out        string
	ret        int64
	hasRet     bool
}

func loadCases(t *testing.T) []irCase {
	b, err := os.ReadFile("../testdata/cases.ir.txt")
	if err != nil {
		t.Fatal(err)
	}
	var cases []irCase
	var cur *irCase
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(line, "===") {
			parts := strings.Split(strings.TrimPrefix(line, "==="), "|")
			c := irCase{name: strings.TrimSpace(parts[0])}
			c.out = strings.ReplaceAll(strings.TrimSpace(parts[1]), `\n`, "\n")
			if r := strings.TrimSpace(parts[2]); r != "" {
				c.ret, _ = strconv.ParseInt(r, 10, 64)
				c.hasRet = true
			}
			cases = append(cases, c)
			cur = &cases[len(cases)-1]
			continue
		}
		if cur != nil && !strings.HasPrefix(line, ";;") {
			cur.text += line + "\n"
		}
	}
	return cases
}

func TestHandWrittenIR(t *testing.T) {
	rng := rand.New(rand.NewSource(7))
	for _, c := range loadCases(t) {
		parse := func() *ir.Module {
			m, err := ir.Parse(c.text)
			if err != nil {
				t.Fatalf("%s: parse: %v", c.name, err)
			}
			if err := m.Verify(); err != nil {
				t.Fatalf("%s: verify: %v", c.name, err)
			}
			return m
		}
		want := parse().Run(fuel)
		// the expectation in the file pins the oracle itself
		if want.Out != c.out || (c.hasRet && want.Ret != c.ret) {
			t.Fatalf("%s: interpreter gives %v, case file expects out=%q ret=%d", c.name, want, c.out, c.ret)
		}
		check := func(stage string, got ir.Result) {
			if !got.Same(want) {
				t.Errorf("%s [%s]: got %v want %v", c.name, stage, got, want)
			}
		}
		var configs [][]string
		for l := 1; l <= 3; l++ {
			configs = append(configs, opt.Level(l))
		}
		configs = append(configs,
			[]string{"inline"},
			[]string{"inline", "simplifycfg", "mem2reg", "sccp", "dce"},
			[]string{"inline", "gvn", "memopt", "licm", "dce"},
			[]string{"mem2reg", "inline", "mem2reg", "gvn", "dce"},
			[]string{"simplifycfg", "mem2reg", "ifconv", "simplifycfg", "instcombine", "dce"},
		)
		names := opt.PassNames()
		for k := 0; k < 12; k++ {
			var p []string
			for i := 0; i < 2+rng.Intn(8); i++ {
				p = append(p, names[rng.Intn(len(names))])
			}
			configs = append(configs, p)
		}
		for _, passes := range configs {
			m := parse()
			if _, err := opt.Run(m, passes, opt.Options{Verify: true}); err != nil {
				t.Errorf("%s %v: %v", c.name, passes, err)
				continue
			}
			check(fmt.Sprint(passes), m.Run(fuel))
			for _, regs := range []int{4, 5, 7, 12} {
				o, err := backend.Compile(m, backend.Config{NumRegs: regs})
				if err != nil {
					t.Errorf("%s %v regs=%d: %v", c.name, passes, regs, err)
					continue
				}
				got, _ := o.Prog.Run(fuel)
				check(fmt.Sprintf("vm regs=%d %v", regs, passes), got)
			}
		}
		// unoptimised IR through the backend too
		for _, regs := range []int{4, 5, 7, 12} {
			o, err := backend.Compile(parse(), backend.Config{NumRegs: regs})
			if err != nil {
				t.Errorf("%s -O0 regs=%d: %v", c.name, regs, err)
				continue
			}
			got, _ := o.Prog.Run(fuel)
			check(fmt.Sprintf("vm -O0 regs=%d", regs), got)
		}
	}
}
