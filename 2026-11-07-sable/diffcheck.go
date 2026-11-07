package sable

import "fmt"

// CheckRow is one executor's result in a differential check.
type CheckRow struct {
	Name    string
	Outcome Outcome
	Match   bool
	Skipped string
}

type CheckResult struct {
	Oracle Outcome
	Rows   []CheckRow
}

const checkFuel = 200_000_000

// CheckAll runs one program through every executor in the toolchain and
// compares each against the AST oracle: lowered IR, SSA, every optimisation
// level, and machine code for both allocators over a range of register counts.
func CheckAll(src string) (*CheckResult, error) {
	ast, err := Parse(src)
	if err != nil {
		return nil, err
	}
	return CheckAST(ast)
}

func CheckAST(ast *Program) (*CheckResult, error) {
	res := &CheckResult{Oracle: RunAST(ast, checkFuel)}
	add := func(name string, o Outcome) {
		row := CheckRow{Name: name, Outcome: o}
		switch {
		case res.Oracle.Resource():
			row.Skipped = "oracle hit " + res.Oracle.Trap
		case o.Resource():
			row.Skipped = "executor hit " + o.Trap
		default:
			row.Match = o.Same(res.Oracle)
		}
		res.Rows = append(res.Rows, row)
	}
	lowered := Lower(ast)
	if err := VerifyModule(lowered, false); err != nil {
		return nil, err
	}
	add("IR (slots, pre-SSA)", RunIR(lowered, checkFuel*20))
	for level := 0; level <= 2; level++ {
		m := Lower(ast)
		if err := BuildSSA(m); err != nil {
			return nil, err
		}
		if _, err := Optimize(m, Options{Level: level, Verify: true}); err != nil {
			return nil, err
		}
		add(fmt.Sprintf("SSA -O%d (IR interpreter)", level), RunIR(m, checkFuel*20))
		if level == 2 {
			m2 := m
			for _, alg := range []Alg{LinearScan, GraphColor} {
				for _, k := range []int{2, 3, 4, 6, 8, 16} {
					img, err := Backend(m2, k, alg)
					if err != nil {
						return nil, err
					}
					o, _ := RunProgram(img, checkFuel*20)
					add(fmt.Sprintf("VM -O2 %v K=%d", alg, k), o)
				}
			}
		}
	}
	return res, nil
}
