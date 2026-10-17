// Command kolmo is a lossless compression laboratory.
package main

import (
	"bytes"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"text/tabwriter"
	"time"

	"kolmo/internal/container"
	"kolmo/internal/deflate"
	"kolmo/internal/heat"
)

const usage = `kolmo — a from-scratch lossless compression lab

usage:
  kolmo compress   [-m auto|store|deflate|bwt|cm|rans0|rans1] [-l 1-9] [-f] [-o out] <file|->
  kolmo decompress [-f] [-o out] <file|->        (also reads plain .gz files)
  kolmo inspect    <file.kol>                      print the container header
  kolmo bench      [-l 1-9] <file>...              every method, side by side, verified
  kolmo heat       [-max N] [-o out.html] <file>   per-byte cost map from the CM model
  kolmo gzip       [-l 1-9] <file|->  > out.gz     RFC 1952 output readable by gzip(1)
  kolmo gunzip     <file.gz|->                     decode gzip using our own inflate
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	var err error
	args := os.Args[2:]
	switch os.Args[1] {
	case "compress", "c":
		err = cmdCompress(args)
	case "decompress", "d":
		err = cmdDecompress(args)
	case "inspect", "i":
		err = cmdInspect(args)
	case "bench", "b":
		err = cmdBench(args)
	case "heat", "h":
		err = cmdHeat(args)
	case "gzip":
		err = cmdGzip(args, false)
	case "gunzip":
		err = cmdGzip(args, true)
	case "help", "-h", "--help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "kolmo: unknown command %q\n\n%s", os.Args[1], usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "kolmo:", err)
		os.Exit(1)
	}
}

func newFlags(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	return fs
}

func readInput(path string) ([]byte, error) {
	if path == "-" {
		return io.ReadAll(os.Stdin)
	}
	st, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	if st.IsDir() {
		return nil, fmt.Errorf("%s is a directory", path)
	}
	return os.ReadFile(path)
}

func writeOutput(path string, data []byte, force bool) error {
	if path == "-" || path == "" {
		_, err := os.Stdout.Write(data)
		return err
	}
	flags := os.O_WRONLY | os.O_CREATE | os.O_EXCL
	if force {
		flags = os.O_WRONLY | os.O_CREATE | os.O_TRUNC
	}
	f, err := os.OpenFile(path, flags, 0o644)
	if err != nil {
		if os.IsExist(err) {
			return fmt.Errorf("%s already exists (use -f to overwrite)", path)
		}
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

// parse handles flag errors uniformly and enforces the positional argument count.
func parse(fs *flag.FlagSet, args []string, min, max int) ([]string, error) {
	if err := fs.Parse(reorder(args)); err != nil {
		return nil, err
	}
	if fs.NArg() < min || (max >= 0 && fs.NArg() > max) {
		want := fmt.Sprintf("exactly %d file argument(s)", min)
		switch {
		case max < 0:
			want = fmt.Sprintf("at least %d file argument(s)", min)
		case max != min:
			want = fmt.Sprintf("%d to %d file arguments", min, max)
		}
		return nil, fmt.Errorf("%s: expected %s, got %d (see 'kolmo help')", fs.Name(), want, fs.NArg())
	}
	return fs.Args(), nil
}

// reorder lets flags appear after positional arguments ("kolmo compress file -m cm").
func reorder(args []string) []string {
	var flags, pos []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		if a == "-" || !strings.HasPrefix(a, "-") {
			pos = append(pos, a)
			continue
		}
		flags = append(flags, a)
		if !strings.Contains(a, "=") && (a == "-m" || a == "-l" || a == "-o" || a == "-max") && i+1 < len(args) {
			i++
			flags = append(flags, args[i])
		}
	}
	return append(flags, pos...)
}

func checkLevel(l int) error {
	if l < 1 || l > 9 {
		return fmt.Errorf("level must be 1..9, got %d", l)
	}
	return nil
}

func cmdCompress(args []string) error {
	fs := newFlags("compress")
	method := fs.String("m", "auto", "method: auto, "+methodNames())
	level := fs.Int("l", 9, "deflate level 1-9")
	force := fs.Bool("f", false, "overwrite output")
	out := fs.String("o", "", "output path (default: <file>.kol, or stdout for -)")
	pos, err := parse(fs, args, 1, 1)
	if err != nil {
		return err
	}
	if err := checkLevel(*level); err != nil {
		return err
	}
	var m *container.Method
	if *method != "auto" {
		if m = container.Lookup(*method); m == nil {
			return fmt.Errorf("unknown method %q (have auto, %s)", *method, methodNames())
		}
	}
	src, err := readInput(pos[0])
	if err != nil {
		return err
	}
	var enc []byte
	t0 := time.Now()
	if m == nil {
		var skipped bool
		if enc, m, skipped, err = container.Auto(src, *level); err == nil && skipped {
			fmt.Fprintf(os.Stderr, "note: input over %d MiB, skipped the slow cm model (force it with -m cm)\n", container.SlowLimit>>20)
		}
	} else {
		enc, err = m.Encode(src, *level)
	}
	if err != nil {
		return err
	}
	dst := *out
	if dst == "" && pos[0] != "-" {
		dst = pos[0] + ".kol"
	}
	if err := writeOutput(dst, enc, *force); err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "%s: %d -> %d bytes (%.1f%%) via %s in %v\n", pos[0], len(src), len(enc),
		pct(len(enc), len(src)), m.Name, time.Since(t0).Round(time.Millisecond))
	return nil
}

func cmdDecompress(args []string) error {
	fs := newFlags("decompress")
	force := fs.Bool("f", false, "overwrite output")
	out := fs.String("o", "", "output path")
	pos, err := parse(fs, args, 1, 1)
	if err != nil {
		return err
	}
	data, err := readInput(pos[0])
	if err != nil {
		return err
	}
	plain, info, err := container.Decode(data)
	if err != nil {
		return err
	}
	dst := *out
	if dst == "" {
		switch {
		case pos[0] == "-":
		case strings.HasSuffix(pos[0], ".kol"):
			dst = strings.TrimSuffix(pos[0], ".kol")
		case strings.HasSuffix(pos[0], ".gz"):
			dst = strings.TrimSuffix(pos[0], ".gz")
		default:
			return fmt.Errorf("cannot guess output name for %s; use -o", pos[0])
		}
	}
	if err := writeOutput(dst, plain, *force); err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "%s: %d bytes via %s, CRC-32 %08x verified\n", pos[0], len(plain), info.Method.Name, info.CRC)
	return nil
}

func cmdInspect(args []string) error {
	pos, err := parse(newFlags("inspect"), args, 1, 1)
	if err != nil {
		return err
	}
	data, err := readInput(pos[0])
	if err != nil {
		return err
	}
	info, _, err := container.Inspect(data)
	if err != nil {
		return err
	}
	fmt.Printf("format:    KOL1\nmethod:    %s (%s)\noriginal:  %d bytes\npayload:   %d bytes (%.2f%% of original)\ncrc32:     %08x\n",
		info.Method.Name, info.Method.Desc, info.Original, info.PayloadBytes, pct(info.PayloadBytes, info.Original), info.CRC)
	return nil
}

func cmdBench(args []string) error {
	fs := newFlags("bench")
	level := fs.Int("l", 9, "deflate level")
	pos, err := parse(fs, args, 1, -1)
	if err != nil {
		return err
	}
	if err := checkLevel(*level); err != nil {
		return err
	}
	for _, path := range pos {
		src, err := readInput(path)
		if err != nil {
			return err
		}
		fmt.Printf("\n%s — %d bytes\n", path, len(src))
		tw := tabwriter.NewWriter(os.Stdout, 2, 0, 2, ' ', tabwriter.AlignRight)
		fmt.Fprintln(tw, "method\tbytes\tratio\tbits/B\tenc\tdec\tverified\t")
		for _, m := range container.Methods() {
			t0 := time.Now()
			enc, eerr := m.Encode(src, *level)
			te := time.Since(t0)
			if eerr != nil {
				fmt.Fprintf(tw, "%s\t-\t-\t-\t-\t-\tn/a (%v)\t\n", m.Name, errors.Unwrap(eerr))
				continue
			}
			t0 = time.Now()
			dec, _, derr := container.Decode(enc)
			td := time.Since(t0)
			ok := "yes"
			if derr != nil || !bytes.Equal(dec, src) {
				ok = "FAIL"
			}
			bpb := 0.0
			if len(src) > 0 {
				bpb = float64(len(enc)) * 8 / float64(len(src))
			}
			fmt.Fprintf(tw, "%s\t%d\t%.1f%%\t%.3f\t%v\t%v\t%s\t\n", m.Name, len(enc), pct(len(enc), len(src)), bpb,
				te.Round(time.Millisecond), td.Round(time.Millisecond), ok)
			if ok == "FAIL" {
				tw.Flush()
				return fmt.Errorf("%s failed to round-trip %s", m.Name, path)
			}
		}
		tw.Flush()
	}
	return nil
}

func cmdHeat(args []string) error {
	fs := newFlags("heat")
	max := fs.Int("max", 200000, "analyse at most this many bytes")
	out := fs.String("o", "", "output html (default <file>.heat.html)")
	force := fs.Bool("f", false, "overwrite output")
	pos, err := parse(fs, args, 1, 1)
	if err != nil {
		return err
	}
	if *max < 1 {
		return fmt.Errorf("-max must be positive")
	}
	data, err := readInput(pos[0])
	if err != nil {
		return err
	}
	if len(data) == 0 {
		return fmt.Errorf("%s is empty; nothing to analyse", pos[0])
	}
	dst := *out
	if dst == "" {
		dst = pos[0] + ".heat.html"
	}
	if err := writeOutput(dst, []byte(heat.Render(pos[0], data, *max)), *force); err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "wrote %s\n", dst)
	return nil
}

func cmdGzip(args []string, decode bool) error {
	fs := newFlags("gzip")
	level := fs.Int("l", 6, "level 1-9")
	pos, err := parse(fs, args, 1, 1)
	if err != nil {
		return err
	}
	if err := checkLevel(*level); err != nil {
		return err
	}
	data, err := readInput(pos[0])
	if err != nil {
		return err
	}
	if decode {
		out, err := deflate.Gunzip(data, container.MaxOriginal)
		if err != nil {
			return err
		}
		return writeOutput("-", out, true)
	}
	return writeOutput("-", deflate.Gzip(data, *level), true)
}

func methodNames() string {
	var n []string
	for _, m := range container.Methods() {
		n = append(n, m.Name)
	}
	return strings.Join(n, ", ")
}

func pct(a, b int) float64 {
	if b == 0 {
		return 0
	}
	return 100 * float64(a) / float64(b)
}
