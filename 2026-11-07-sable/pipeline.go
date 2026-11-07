package sable

import (
	"fmt"
	"strings"
)

// Pass is one optimisation over a function.
type Pass struct {
	Name string
	Run  func(f *Func) bool
}

var (
	PassSimplifyCFG = Pass{"simplifycfg", SimplifyCFG}
	PassSCCP        = Pass{"sccp", SCCP}
	PassInstCombine = Pass{"instcombine", InstCombine}
	PassGVN         = Pass{"gvn", GVN}
	PassLICM        = Pass{"licm", LICM}
	PassDCE         = Pass{"dce", DCE}
)

// PassByName looks up a pass for the CLI.
func PassByName(n string) (Pass, bool) {
	for _, p := range []Pass{PassSimplifyCFG, PassSCCP, PassInstCombine, PassGVN, PassLICM, PassDCE} {
		if p.Name == n {
			return p, true
		}
	}
	return Pass{}, false
}

// PassStat records the effect of one pass application on one function.
type PassStat struct {
	Round         int
	Pass, Func    string
	Before, After int // instruction counts
	Changed       bool
}

// Options controls Optimize.
type Options struct {
	Level    int  // 0 = SSA only, 1 = scalar cleanups, 2 = + GVN, LICM, inlining
	Verify   bool // verify the SSA invariants after every pass
	Inline   bool // overrides Level>=2 default when InlineSet
	NoInline bool
	// Hook is called after every pass application with the whole module
	// (used by the pass bisector and the HTML report).
	Hook func(round int, pass, fn string, m *Module)
	// Only restricts the pipeline to a list of pass names (empty = all).
	Only []string
	// MaxPasses stops after that many pass applications (0 = unlimited); used for bisection.
	MaxPasses int
}

type Stats struct {
	Rows    []PassStat
	Rounds  int
	Applied int
}

func (o Options) allowed(name string) bool {
	if len(o.Only) == 0 {
		return true
	}
	for _, n := range o.Only {
		if n == name {
			return true
		}
	}
	return false
}

// BuildSSA converts a lowered module to SSA form in place.
func BuildSSA(m *Module) error {
	for _, f := range m.Funcs {
		Mem2Reg(f)
	}
	return VerifyModule(m, true)
}

// Optimize runs the pass pipeline to a fixpoint (bounded).
func Optimize(m *Module, opt Options) (Stats, error) {
	var st Stats
	var pipeline []Pass
	switch {
	case opt.Level <= 0:
	case opt.Level == 1:
		pipeline = []Pass{PassSimplifyCFG, PassSCCP, PassInstCombine, PassDCE}
	default:
		pipeline = []Pass{PassSimplifyCFG, PassSCCP, PassInstCombine, PassGVN, PassLICM, PassDCE}
	}
	if opt.Level >= 2 && !opt.NoInline && opt.allowed("inline") {
		if opt.MaxPasses > 0 && st.Applied >= opt.MaxPasses {
			return st, nil
		}
		before := totalInstrs(m)
		n := Inline(m)
		st.Applied++
		st.Rows = append(st.Rows, PassStat{Pass: "inline", Func: "*", Before: before, After: totalInstrs(m), Changed: n > 0})
		if err := VerifyModule(m, true); err != nil {
			return st, fmt.Errorf("after inline: %w", err)
		}
		if opt.Hook != nil {
			opt.Hook(0, "inline", "*", m)
		}
	}
	for round := 1; round <= 8; round++ {
		any := false
		for _, f := range m.Funcs {
			for _, p := range pipeline {
				if !opt.allowed(p.Name) {
					continue
				}
				if opt.MaxPasses > 0 && st.Applied >= opt.MaxPasses {
					return st, nil
				}
				before := f.NumInstrs()
				ch := p.Run(f)
				st.Applied++
				st.Rows = append(st.Rows, PassStat{round, p.Name, f.Name, before, f.NumInstrs(), ch})
				if ch {
					any = true
				}
				if opt.Verify {
					if err := Verify(f, true); err != nil {
						return st, fmt.Errorf("after %s: %w\n%s", p.Name, err, f)
					}
				}
				if opt.Hook != nil {
					opt.Hook(round, p.Name, f.Name, m)
				}
			}
		}
		st.Rounds = round
		if !any {
			break
		}
	}
	for _, f := range m.Funcs {
		f.renumber()
	}
	return st, VerifyModule(m, true)
}

func totalInstrs(m *Module) int {
	n := 0
	for _, f := range m.Funcs {
		n += f.NumInstrs()
	}
	return n
}

// Summary renders the per-pass table.
func (s Stats) Summary() string {
	type agg struct{ runs, changed, delta int }
	order := []string{}
	m := map[string]*agg{}
	for _, r := range s.Rows {
		a := m[r.Pass]
		if a == nil {
			a = &agg{}
			m[r.Pass] = a
			order = append(order, r.Pass)
		}
		a.runs++
		if r.Changed {
			a.changed++
		}
		a.delta += r.After - r.Before
	}
	var sb strings.Builder
	fmt.Fprintf(&sb, "%-12s %5s %8s %10s\n", "pass", "runs", "changed", "Δ instrs")
	for _, n := range order {
		a := m[n]
		fmt.Fprintf(&sb, "%-12s %5d %8d %+10d\n", n, a.runs, a.changed, a.delta)
	}
	return sb.String()
}
