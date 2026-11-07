package sable

import "fmt"

// Config selects how a module is compiled.
type Config struct {
	OptLevel int
	Regs     int
	Alg      Alg
	NoInline bool
	Verify   bool
}

// Compiled bundles every stage of one compilation for inspection.
type Compiled struct {
	AST    *Program
	SSA    *Module // after mem2reg, before optimisation
	Opt    *Module // after the optimiser
	Prog   *Image
	Passes Stats
}

// Compile runs the whole pipeline on source text.
func Compile(src string, cfg Config) (*Compiled, error) {
	ast, err := Parse(src)
	if err != nil {
		return nil, err
	}
	return CompileAST(ast, cfg)
}

func CompileAST(ast *Program, cfg Config) (*Compiled, error) {
	m := Lower(ast)
	if err := VerifyModule(m, false); err != nil {
		return nil, err
	}
	if err := BuildSSA(m); err != nil {
		return nil, err
	}
	c := &Compiled{AST: ast, SSA: m.Clone()}
	st, err := Optimize(m, Options{Level: cfg.OptLevel, Verify: cfg.Verify, NoInline: cfg.NoInline})
	if err != nil {
		return nil, err
	}
	c.Opt, c.Passes = m, st
	prog, err := Backend(m, cfg.Regs, cfg.Alg)
	if err != nil {
		return nil, err
	}
	c.Prog = prog
	return c, nil
}

// Backend lowers optimised SSA to allocated machine code.
func Backend(m *Module, k int, alg Alg) (*Image, error) {
	if k < 2 {
		return nil, fmt.Errorf("need at least 2 registers, got %d", k)
	}
	t := NewTarget(k)
	p := &Image{ByName: map[string]*MFunc{}, Target: t, Alg: alg, Stats: map[string]AllocStats{}}
	for _, f := range m.Funcs {
		mf := Select(f)
		p.Stats[f.Name] = Allocate(mf, t, alg)
		if err := CheckAllocated(mf, t); err != nil {
			return nil, err
		}
		p.Funcs = append(p.Funcs, mf)
		p.ByName[mf.Name] = mf
	}
	return p, nil
}

// CheckAllocated verifies that no virtual register survives allocation and every
// physical register operand is in range.
func CheckAllocated(mf *MFunc, t Target) error {
	for _, b := range mf.Blocks {
		for i := range b.Instrs {
			in := &b.Instrs[i]
			ops := append(in.uses(), in.def())
			for _, o := range ops {
				if o == nil {
					continue
				}
				if o.K == OVReg {
					return fmt.Errorf("%s: virtual register %s survived allocation in %q", mf.Name, o, in.Format(nil))
				}
				if o.K == OReg && (o.V < 0 || int(o.V) >= t.NumPhys()) {
					return fmt.Errorf("%s: register r%d out of range", mf.Name, o.V)
				}
			}
		}
	}
	return nil
}
