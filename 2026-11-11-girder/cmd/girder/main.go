// Command girder is a finite-element structural-mechanics lab.
package main

import (
	"flag"
	"fmt"
	"os"
	"time"

	"girder/fem"
)

const usage = `girder — finite-element structural mechanics lab

usage:
  girder solve <model.fem> [-o report.html] [-solver direct|cg-jacobi|cg-ic0]
  girder mesh  <model.fem>                 print mesh statistics
  girder validate [-o report.html]         run the closed-form verification suite
  girder topopt [flags]                    SIMP topology optimisation (-h for flags)
  girder modal  <model.fem> [-n 6]         natural frequencies
  girder heat   <model.fem>                steady heat conduction (see README)
`

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "girder:", err)
	os.Exit(1)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	var err error
	switch cmd {
	case "solve":
		err = cmdSolve(args)
	case "mesh":
		err = cmdMesh(args)
	case "validate":
		err = cmdValidate(args)
	case "topopt":
		err = cmdTopopt(args)
	case "modal":
		err = cmdModal(args)
	case "heat":
		err = cmdHeat(args)
	case "-h", "--help", "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "girder: unknown command %q\n%s", cmd, usage)
		os.Exit(2)
	}
	if err != nil {
		fatal(err)
	}
}

func loadModel(path string) (*fem.Input, error) {
	src, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	in, err := fem.Parse(string(src))
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return in, nil
}

func splitArgs(fs *flag.FlagSet, args []string) (pos []string, err error) {
	// allow flags before or after the positional file argument
	for len(args) > 0 {
		if err = fs.Parse(args); err != nil {
			return nil, err
		}
		if fs.NArg() == 0 {
			break
		}
		pos = append(pos, fs.Arg(0))
		args = fs.Args()[1:]
	}
	return pos, nil
}

func cmdSolve(args []string) error {
	fs := flag.NewFlagSet("solve", flag.ContinueOnError)
	out := fs.String("o", "", "write an HTML report to this path")
	solver := fs.String("solver", "", "override solver: direct, cg-jacobi, cg-ic0")
	pos, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return fmt.Errorf("solve needs exactly one model file")
	}
	in, err := loadModel(pos[0])
	if err != nil {
		return err
	}
	if *solver != "" {
		switch k := fem.SolverKind(*solver); k {
		case fem.SolverDirect, fem.SolverCGJacobi, fem.SolverCGIC0:
			in.Solver = k
		default:
			return fmt.Errorf("unknown solver %q", *solver)
		}
	}
	t0 := time.Now()
	var page string
	if in.Frame != nil {
		sol, err := in.Frame.Solve()
		if err != nil {
			return err
		}
		fmt.Printf("frame: %d nodes, %d members  (%.1f ms)\n", len(in.Frame.X), len(in.Frame.Members), time.Since(t0).Seconds()*1000)
		for i, m := range in.Frame.Members {
			ef := sol.EndForces[i]
			fmt.Printf("  member %d (%d-%d): N=%.5g  V1=%.5g  M1=%.5g  M2=%.5g\n", i, m.N1, m.N2, in.Frame.AxialForce(sol, i), ef[1], ef[2], ef[5])
		}
		for n := range in.Frame.X {
			fmt.Printf("  node %d: u=(%.6g, %.6g) θ=%.6g\n", n, sol.U[3*n], sol.U[3*n+1], sol.U[3*n+2])
		}
		page = fem.FrameReport(in, sol)
	} else {
		md := in.Solid
		sol, err := md.Solve(in.Solver)
		if err != nil {
			return err
		}
		res, err := fem.Post(md, sol)
		if err != nil {
			return err
		}
		vm, _ := res.NodalField(fem.FieldVonMises)
		vmax, at := fem.MaxField(vm)
		d, _ := res.NodalField(fem.FieldDispMag)
		dmax, _ := fem.MaxField(d)
		fmt.Printf("solid: %d nodes, %d %s elements, %d free DOFs  solver=%s  (%.1f ms)\n", md.Mesh.NumNodes(), md.Mesh.NumElems(), md.Mesh.Type, sol.Info.FreeDOFs, sol.Info.Solver, time.Since(t0).Seconds()*1000)
		fmt.Printf("  max von Mises = %.6g at node %d (%.4g, %.4g)\n  max |u| = %.6g\n  strain energy = %.6g\n  force balance residual = (%.2e, %.2e)\n", vmax, at, md.Mesh.X[at], md.Mesh.Y[at], dmax, res.Energy, res.Equilib[0], res.Equilib[1])
		if loadless(md) {
			fmt.Println("  warning: the model carries no loads or prescribed displacements — all results are zero")
		}
		page, err = fem.SolidReport(in, res)
		if err != nil {
			return err
		}
	}
	if *out != "" {
		if err := os.WriteFile(*out, []byte(page), 0o644); err != nil {
			return err
		}
		fmt.Println("report written to", *out)
	}
	return nil
}

func cmdMesh(args []string) error {
	if len(args) != 1 {
		return fmt.Errorf("mesh needs one model file")
	}
	in, err := loadModel(args[0])
	if err != nil {
		return err
	}
	if in.Solid == nil {
		return fmt.Errorf("model is a frame: no continuum mesh")
	}
	m := in.Solid.Mesh
	if err := m.Validate(); err != nil {
		return err
	}
	x0, y0, x1, y1 := m.Bounds()
	fmt.Printf("%d nodes, %d %s elements, area %.6g, bounds [%.4g,%.4g]x[%.4g,%.4g], %d boundary edges, %d fixed dofs\n",
		m.NumNodes(), m.NumElems(), m.Type, m.Area(), x0, x1, y0, y1, len(m.BoundaryEdges()), len(in.Solid.Fixed))
	return nil
}

func loadless(md *fem.Model) bool {
	for _, f := range md.F {
		if f != 0 {
			return false
		}
	}
	for _, v := range md.Fixed {
		if v != 0 {
			return false
		}
	}
	return true
}
