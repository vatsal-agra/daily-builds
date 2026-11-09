// Command chime is the CLI for the Chime perceptual audio codec.
package main

import (
	"flag"
	"fmt"
	"os"
	"strings"

	"chime/codec"
)

const usage = `chime — perceptual audio codec (MDCT + psychoacoustics + range coding)

usage:
  chime gen    -signal NAME [-seconds 8] [-rate 44100] [-seed 1] -o out.wav
  chime encode [-b KBPS | -q DB] [-nomS] [-nf] [-flat] [-noswitch] in.wav out.chm
  chime decode in.chm out.wav
  chime info   file.chm
  chime eval   [-b KBPS] [-nf] in.wav          perceptual vs flat baseline at equal bitrate
  chime report [-b KBPS] [-o report.html] in.wav
signals: ` + "%s\n"

func die(err error) {
	fmt.Fprintln(os.Stderr, "chime:", err)
	os.Exit(1)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, usage, strings.Join(codec.SignalNames, ", "))
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	var err error
	switch cmd {
	case "gen":
		err = cmdGen(args)
	case "encode":
		err = cmdEncode(args)
	case "decode":
		err = cmdDecode(args)
	case "info":
		err = cmdInfo(args)
	case "eval":
		err = cmdEval(args)
	case "report":
		err = cmdReport(args)
	case "help", "-h", "--help":
		fmt.Printf(usage, strings.Join(codec.SignalNames, ", "))
	default:
		fmt.Fprintf(os.Stderr, "chime: unknown command %q\n", cmd)
		fmt.Fprintf(os.Stderr, usage, strings.Join(codec.SignalNames, ", "))
		os.Exit(2)
	}
	if err != nil {
		die(err)
	}
}

func cmdGen(args []string) error {
	fs := flag.NewFlagSet("gen", flag.ContinueOnError)
	sig := fs.String("signal", "mix", "signal name")
	sec := fs.Float64("seconds", 8, "duration")
	rate := fs.Int("rate", 44100, "sample rate")
	seed := fs.Int64("seed", 1, "seed")
	out := fs.String("o", "", "output wav")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *out == "" {
		return fmt.Errorf("gen: -o is required")
	}
	a, err := codec.Generate(*sig, *sec, *rate, *seed)
	if err != nil {
		return err
	}
	return writeWAV(*out, a)
}

func writeWAV(path string, a *codec.Audio) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	if err := codec.WriteWAV(f, a); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

func readWAV(path string) (*codec.Audio, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	a, err := codec.ReadWAV(b)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return a, nil
}

type encFlags struct {
	b        float64
	q        float64
	noMS     bool
	nf       bool
	flat     bool
	noSwitch bool
}

func addEncFlags(fs *flag.FlagSet, e *encFlags) {
	fs.Float64Var(&e.b, "b", 0, "target bitrate in kbps (default 128 unless -q given)")
	fs.Float64Var(&e.q, "q", 0, "fixed quality: dB offset on the masking threshold (higher = finer)")
	fs.BoolVar(&e.noMS, "noms", false, "disable adaptive M/S stereo")
	fs.BoolVar(&e.nf, "nf", false, "enable noise filling")
	fs.BoolVar(&e.flat, "flat", false, "baseline: flat quantiser, no psychoacoustics")
	fs.BoolVar(&e.noSwitch, "noswitch", false, "disable block switching")
}

func (e *encFlags) params(qSet bool) codec.Params {
	p := codec.DefaultParams()
	if qSet {
		p.Kbps, p.Quality = 0, e.q
	} else if e.b != 0 {
		p.Kbps = e.b // invalid values are rejected by codec.Encode
	}
	p.MS = !e.noMS
	p.NoiseFill = e.nf
	p.Flat = e.flat
	p.Transient = !e.noSwitch
	return p
}

func cmdEncode(args []string) error {
	fs := flag.NewFlagSet("encode", flag.ContinueOnError)
	var e encFlags
	addEncFlags(fs, &e)
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 2 {
		return fmt.Errorf("encode: need in.wav out.chm")
	}
	qSet := false
	fs.Visit(func(f *flag.Flag) {
		if f.Name == "q" {
			qSet = true
		}
	})
	if qSet && e.b > 0 {
		return fmt.Errorf("encode: -b and -q are mutually exclusive")
	}
	a, err := readWAV(fs.Arg(0))
	if err != nil {
		return err
	}
	file, st, err := codec.Encode(a, e.params(qSet))
	if err != nil {
		return err
	}
	if err := os.WriteFile(fs.Arg(1), file, 0o644); err != nil {
		return err
	}
	fmt.Printf("%s → %s: %d bytes, %.1f kbps (offset %+.2f dB, %d frames, %d short, %d M/S)\n",
		fs.Arg(0), fs.Arg(1), st.Bytes, st.Kbps, st.Offset, st.Frames, st.ShortFrames, st.MSFrames)
	if st.Capped {
		fmt.Fprintf(os.Stderr, "note: %.0f kbps is more than this signal can use; encoded at the finest setting (%.1f kbps)\n", e.b, st.Kbps)
	}
	if st.Overshoot {
		fmt.Fprintln(os.Stderr, "warning: target bitrate could not be reached; this is the lowest the codec can go")
	}
	return nil
}

func cmdDecode(args []string) error {
	if len(args) != 2 {
		return fmt.Errorf("decode: need in.chm out.wav")
	}
	b, err := os.ReadFile(args[0])
	if err != nil {
		return err
	}
	a, err := codec.Decode(b)
	if err != nil {
		return fmt.Errorf("%s: %w", args[0], err)
	}
	return writeWAV(args[1], a)
}
