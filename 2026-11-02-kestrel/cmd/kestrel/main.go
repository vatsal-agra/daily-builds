// Command kestrel is the CLI front end for the Kestrel tracking laboratory.
package main

import (
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"

	"kestrel/lab"
	"kestrel/sim"
	"kestrel/tracker"
)

const usage = `kestrel — multi-target radar tracking laboratory

usage:
  kestrel scenarios                         list built-in scenarios
  kestrel run     [-scenario S] [-filter F] [-assoc A] [-seed N] [-tracks]
  kestrel compare [-scenario S] [-seed N] [-seeds K]     filters x association table
  kestrel consistency [-filter F] [-sensor X] [-runs N] [-steps N] [-mismatch Q]
  kestrel report  [-scenario S] [-filter F] [-assoc A] [-seed N] [-o file.html]

filters: ekf ukf imm-ekf imm-ukf (tracker)   kf ekf ukf (consistency)
assoc:   gnn jpda        sensors: cartesian radar
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "scenarios":
		cmdScenarios()
	case "run":
		err = cmdRun(os.Args[2:])
	case "compare":
		err = cmdCompare(os.Args[2:])
	case "consistency":
		err = cmdConsistency(os.Args[2:])
	case "report":
		err = cmdReport(os.Args[2:])
	case "-h", "--help", "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s", os.Args[1], usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func cmdScenarios() {
	for _, s := range sim.Scenarios() {
		fmt.Printf("%-11s %3d targets  Pd=%.2f  clutter=%4.1f/scan  %s\n", s.Name, len(s.Targets), s.Radar.Pd, s.Radar.ClutterMean, s.Desc)
	}
}

func setup(fs *flag.FlagSet) (*string, *string, *string, *int64) {
	return fs.String("scenario", "cruise", "scenario name"),
		fs.String("filter", "ekf", "ekf|ukf|imm-ekf|imm-ukf"),
		fs.String("assoc", "gnn", "gnn|jpda"),
		fs.Int64("seed", 1, "random seed")
}

func execute(scn, fl, as string, seed int64) (*tracker.Run, error) {
	sc, err := sim.Lookup(scn)
	if err != nil {
		return nil, err
	}
	o := tracker.DefaultOptions()
	o.Filter, o.Assoc = fl, as
	cfg, err := tracker.ForScenario(sc, o)
	if err != nil {
		return nil, err
	}
	frames, err := sc.Run(seed)
	if err != nil {
		return nil, err
	}
	return tracker.RunFrames(sc, frames, cfg)
}

func cmdRun(args []string) error {
	fs := flag.NewFlagSet("run", flag.ContinueOnError)
	scn, fl, as, seed := setup(fs)
	showTracks := fs.Bool("tracks", false, "list every confirmed track")
	if err := fs.Parse(args); err != nil {
		return err
	}
	r, err := execute(*scn, *fl, *as, *seed)
	if err != nil {
		return err
	}
	s := r.Score
	nd, nc := 0, 0
	for _, f := range r.Frames {
		for _, d := range f.Dets {
			nd++
			if d.Source == 0 {
				nc++
			}
		}
	}
	fmt.Printf("scenario %s · %s/%s · seed %d · %d scans · %d detections (%d clutter)\n",
		*scn, *fl, *as, *seed, len(r.Frames), nd, nc)
	fmt.Printf("  mean OSPA      %7.1f m   (loc %.1f, card %.1f)\n", s.MeanOSPA, s.MeanLoc, s.MeanCard)
	fmt.Printf("  position RMSE  %7.1f m\n", s.PosRMSE)
	fmt.Printf("  coverage       %7.1f %%   (%d of %d truth-scans have a track)\n", 100*s.Coverage, s.TruthScans-s.MissedScans, s.TruthScans)
	fmt.Printf("  ID switches    %7d\n  false-track scans %d\n  distinct tracks   %d (truth: %d)\n",
		s.IDSwitches, s.FalseTrackScans, s.Tracks, len(r.Scenario.Targets))
	if *showTracks {
		all := r.Tracker.AllTracks()
		sort.Slice(all, func(i, j int) bool { return all[i].ID < all[j].ID })
		fmt.Println("\n  id  status     born   hits  last-update  note")
		for _, t := range all {
			if t.Hits < 3 {
				continue
			}
			note := t.DeathReason
			fmt.Printf("  %-3d %-9s %5.0f  %5d  %10.0f  %s\n", t.ID, t.Status, t.Born, t.Hits, t.History[len(t.History)-1].T, note)
		}
	}
	return nil
}

func cmdCompare(args []string) error {
	fs := flag.NewFlagSet("compare", flag.ContinueOnError)
	scn := fs.String("scenario", "manoeuvre", "scenario name")
	seed := fs.Int64("seed", 1, "first seed")
	seeds := fs.Int("seeds", 5, "number of seeds to average")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *seeds < 1 {
		return fmt.Errorf("-seeds must be >= 1")
	}
	fmt.Printf("scenario %s, mean over %d seeds\n\n%-9s %-5s %9s %9s %7s %7s %7s\n", *scn, *seeds, "filter", "assoc", "OSPA(m)", "RMSE(m)", "switch", "false", "cov%")
	for _, fl := range []string{"ekf", "ukf", "imm-ekf", "imm-ukf"} {
		for _, as := range []string{"gnn", "jpda"} {
			if strings.HasPrefix(fl, "imm") && as == "jpda" {
				continue
			}
			var o, rm, cv float64
			var sw, fa int
			for k := 0; k < *seeds; k++ {
				r, err := execute(*scn, fl, as, *seed+int64(k))
				if err != nil {
					return err
				}
				o += r.Score.MeanOSPA
				rm += r.Score.PosRMSE
				cv += r.Score.Coverage
				sw += r.Score.IDSwitches
				fa += r.Score.FalseTrackScans
			}
			n := float64(*seeds)
			fmt.Printf("%-9s %-5s %9.1f %9.1f %7d %7d %7.1f\n", fl, as, o/n, rm/n, sw, fa, 100*cv/n)
		}
	}
	return nil
}

func cmdConsistency(args []string) error {
	fs := flag.NewFlagSet("consistency", flag.ContinueOnError)
	fl := fs.String("filter", "kf", "kf|ekf|ukf")
	sensor := fs.String("sensor", "cartesian", "cartesian|radar")
	runs := fs.Int("runs", 400, "Monte-Carlo runs")
	steps := fs.Int("steps", 40, "scans per run")
	mismatch := fs.Float64("mismatch", 0, "give the filter this wrong process noise")
	seed := fs.Int64("seed", 1, "random seed")
	if err := fs.Parse(args); err != nil {
		return err
	}
	rep, err := lab.Consistency(lab.Config{Filter: *fl, Sensor: *sensor, Runs: *runs, Steps: *steps,
		Dt: 2, Q: 0.5, Seed: *seed, MismatchQ: *mismatch})
	if err != nil {
		return err
	}
	verdict := func(ok bool) string {
		if ok {
			return "CONSISTENT"
		}
		return "INCONSISTENT"
	}
	fmt.Printf("%s on %s measurements · %d runs x %d scans (95%% two-sided test)\n", strings.ToUpper(*fl), *sensor, *runs, *steps)
	fmt.Printf("  NEES  mean %.3f  expected 4 · accept [%.3f, %.3f] · %s · %.0f%% of scans pass\n",
		rep.NEES.Mean, rep.NEES.Lo, rep.NEES.Hi, verdict(rep.NEES.Consistent), 100*rep.NEESFrac)
	fmt.Printf("  NIS   mean %.3f  expected 2 · accept [%.3f, %.3f] · %s · %.0f%% of scans pass\n",
		rep.NIS.Mean, rep.NIS.Lo, rep.NIS.Hi, verdict(rep.NIS.Consistent), 100*rep.NISFrac)
	fmt.Printf("  position RMSE %.1f m\n", rep.PosRMSE)
	return nil
}

func cmdReport(args []string) error {
	return fmt.Errorf("report: not yet implemented")
}
