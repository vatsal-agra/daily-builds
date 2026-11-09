package main

import (
	"flag"
	"fmt"
	"os"

	"chime/codec"
)

func cmdInfo(args []string) error {
	if len(args) != 1 {
		return fmt.Errorf("info: need file.chm")
	}
	b, err := os.ReadFile(args[0])
	if err != nil {
		return err
	}
	h, err := codec.ParseContainer(b)
	if err != nil {
		return fmt.Errorf("%s: %w", args[0], err)
	}
	dur := float64(h.Samples) / float64(h.Rate)
	fmt.Printf("%s: CHM1  %d ch  %d Hz  %d samples (%.2f s)  noise-fill=%v\n", args[0], h.Channels, h.Rate, h.Samples, dur, h.NoiseFill)
	fmt.Printf("  payload %d bytes → %.1f kbps\n", len(h.Payload), float64(len(b))*8/dur/1000)
	return nil
}

func printRow(r *codec.Result) {
	m := r.M
	fmt.Printf("  %-7s %6.1f kbps  SNR %6.2f  segSNR %6.2f | noise over mask: %5.1f%% of bands, mean excess %5.2f dB, p95 NMR %+6.2f dB | mean NMR %+6.2f dB\n",
		r.Name, r.Stats.Kbps, m.SNR, m.SegSNR, 100*m.AudibleFrac, m.MeanExcess, m.P95NMR, m.MeanNMR)
}

func cmdEval(args []string) error {
	fs := flag.NewFlagSet("eval", flag.ContinueOnError)
	var e encFlags
	addEncFlags(fs, &e)
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 1 {
		return fmt.Errorf("eval: need in.wav")
	}
	a, err := readWAV(fs.Arg(0))
	if err != nil {
		return err
	}
	p := e.params(false)
	if p.Kbps == 0 {
		p.Kbps = 128
	}
	per, flat, err := codec.Shootout(a, p)
	if err != nil {
		return err
	}
	fmt.Printf("%s  (%d ch, %d Hz, %.1f s)\n", fs.Arg(0), len(a.Ch), a.Rate, float64(a.Frames())/float64(a.Rate))
	printRow(per)
	printRow(flat)
	fmt.Printf("  → audible excess %.2f → %.2f dB, p95 NMR %+.1f → %+.1f dB, SNR cost %.1f dB\n",
		flat.M.MeanExcess, per.M.MeanExcess, flat.M.P95NMR, per.M.P95NMR, flat.M.SNR-per.M.SNR)
	return nil
}

func cmdReport(args []string) error { return fmt.Errorf("todo") }
