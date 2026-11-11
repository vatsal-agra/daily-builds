package main

import (
	"flag"
	"fmt"
	"os"

	"girder/fem"
)

func cmdModal(args []string) error {
	fs := flag.NewFlagSet("modal", flag.ContinueOnError)
	n := fs.Int("n", 0, "number of modes (default: `modes n=` in the file, else 6)")
	out := fs.String("o", "", "write an HTML report")
	pos, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return fmt.Errorf("modal needs exactly one model file")
	}
	in, err := loadModel(pos[0])
	if err != nil {
		return err
	}
	nm := *n
	if nm == 0 {
		nm = in.Modes
	}
	if nm == 0 {
		nm = 6
	}
	var ms *fem.ModeSet
	var free []int
	if in.Frame != nil {
		ms, free, err = in.Frame.FrameModes(nm)
	} else {
		ms, free, err = in.Solid.SolidModes(nm)
	}
	if err != nil {
		return err
	}
	for i := range ms.Omega2 {
		fmt.Printf("mode %2d: %12.6g Hz   (omega^2 = %.8g)\n", i+1, ms.Freq(i), ms.Omega2[i])
	}
	if *out != "" {
		t := in.Title
		if t == "" {
			t = "Girder modal analysis"
		}
		return os.WriteFile(*out, []byte(fem.ModalReport(t, in.Solid, in.Frame, ms, free)), 0o644)
	}
	return nil
}

func cmdHeat(args []string) error {
	fs := flag.NewFlagSet("heat", flag.ContinueOnError)
	out := fs.String("o", "", "write an HTML report")
	pos, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return fmt.Errorf("heat needs exactly one model file")
	}
	in, err := loadModel(pos[0])
	if err != nil {
		return err
	}
	if in.Heat == nil {
		return fmt.Errorf("model has no thermal directives (temp / flux / source)")
	}
	T, err := in.Heat.Solve(in.Solver)
	if err != nil {
		return err
	}
	lo, hi := T[0], T[0]
	for _, v := range T {
		if v < lo {
			lo = v
		}
		if v > hi {
			hi = v
		}
	}
	fmt.Printf("heat: %d nodes, T in [%.6g, %.6g]\n", len(T), lo, hi)
	if *out != "" {
		t := in.Title
		if t == "" {
			t = "Girder heat conduction"
		}
		return os.WriteFile(*out, []byte(fem.HeatReport(t, in.Heat, T)), 0o644)
	}
	return nil
}
