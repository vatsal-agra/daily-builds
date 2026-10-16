package opt

import (
	"fmt"
	"sort"
	"strings"

	"dominion/ir"
)

// Stats counts transformations per pass.
type Stats map[string]int

func (s Stats) String() string {
	var ks []string
	for k := range s {
		ks = append(ks, k)
	}
	sort.Strings(ks)
	var parts []string
	for _, k := range ks {
		parts = append(parts, fmt.Sprintf("%s=%d", k, s[k]))
	}
	return strings.Join(parts, " ")
}

type passFn struct {
	fn     func(f *ir.Func) int
	module func(m *ir.Module) int
}

var registry = map[string]passFn{
	"simplifycfg": {fn: SimplifyCFG},
	"mem2reg":     {fn: Mem2Reg},
	"instcombine": {fn: InstCombine},
	"sccp":        {fn: SCCP},
	"gvn":         {fn: GVN},
	"memopt":      {fn: MemOpt},
	"licm":        {fn: LICM},
	"dce":         {fn: DCE},
	"tre":         {fn: TailRecursionElim},
	"inline":      {module: func(m *ir.Module) int { return Inline(m, DefaultInline) }},
}

// PassNames lists registered passes.
func PassNames() []string {
	var n []string
	for k := range registry {
		n = append(n, k)
	}
	sort.Strings(n)
	return n
}

// Level returns the pass list for -O0/-O1/-O2/-O3.
func Level(o int) []string {
	switch o {
	case 0:
		return nil
	case 1:
		return strings.Fields("simplifycfg mem2reg instcombine sccp dce simplifycfg")
	case 2:
		return strings.Fields("simplifycfg mem2reg instcombine sccp simplifycfg dce " +
			"inline simplifycfg mem2reg instcombine sccp gvn memopt licm instcombine dce simplifycfg " +
			"gvn instcombine sccp dce simplifycfg")
	default:
		return strings.Fields("simplifycfg mem2reg instcombine sccp simplifycfg dce " +
			"inline tre simplifycfg mem2reg instcombine sccp gvn memopt licm instcombine dce simplifycfg " +
			"simplifycfg instcombine sccp gvn memopt licm dce simplifycfg " +
			"gvn instcombine sccp dce simplifycfg")
	}
}

// Options controls Run.
type Options struct {
	Verify bool                                         // verify the module after every pass
	Hook   func(pass string, m *ir.Module, changes int) // called after each pass (tracing)
}

// Run executes the named passes over the module.
func Run(m *ir.Module, passes []string, opts Options) (Stats, error) {
	st := Stats{}
	for _, name := range passes {
		p, ok := registry[name]
		if !ok {
			return st, fmt.Errorf("unknown pass %q (available: %s)", name, strings.Join(PassNames(), ", "))
		}
		n := 0
		if p.module != nil {
			n = p.module(m)
		} else {
			for _, f := range m.Funcs {
				n += p.fn(f)
			}
		}
		st[name] += n
		if opts.Verify {
			if err := m.Verify(); err != nil {
				return st, fmt.Errorf("after pass %s: %w", name, err)
			}
		}
		if opts.Hook != nil {
			opts.Hook(name, m, n)
		}
	}
	return st, nil
}

// Optimize runs the standard pipeline for an optimisation level.
func Optimize(m *ir.Module, level int, verify bool) (Stats, error) {
	return Run(m, Level(level), Options{Verify: verify})
}
