// Command qz is the Quietzone command-line front end.
package main

import (
	"flag"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"os"
	"strings"

	"quietzone/qr"
	"quietzone/scan"
)

const usage = `qz — a QR code laboratory

  qz encode  [-ecc L|M|Q|H] [-v N] [-mask N] [-o out.png|out.svg|-] [-scale N] [-border N] [-noeci] TEXT
  qz decode  IMAGE|-         decode a QR code from a PNG/JPEG/GIF (or ASCII art with -text)
  qz scan    IMAGE           like decode but lists every symbol, geometry and error-correction stats
  qz rs      ...             Reed–Solomon workbench (encode / corrupt / decode)
  qz damage  ...             flip modules in a generated symbol and watch the error budget
  qz explain TEXT            anatomy of a symbol: version, blocks, codeword map
  qz html    TEXT -o f.html  interactive anatomy explorer
  qz distort IN OUT ...      apply camera-style degradation to an image
  qz bench                   scanner accuracy benchmark under distortion

Run "qz <command> -h" for options.
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	var err error
	switch cmd {
	case "encode":
		err = cmdEncode(args)
	case "decode":
		err = cmdDecode(args, false)
	case "scan":
		err = cmdDecode(args, true)
	case "rs":
		err = cmdRS(args)
	case "damage":
		err = cmdDamage(args)
	case "explain":
		err = cmdExplain(args)
	case "html":
		err = cmdHTML(args)
	case "distort":
		err = cmdDistort(args)
	case "bench":
		err = cmdBench(args)
	case "-h", "--help", "help":
		fmt.Print(usage)
		return
	default:
		fmt.Fprintf(os.Stderr, "qz: unknown command %q\n\n%s", cmd, usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "qz:", err)
		os.Exit(1)
	}
}

func fail(fs *flag.FlagSet, msg string) error {
	fs.Usage()
	return fmt.Errorf("%s", msg)
}

func textArg(fs *flag.FlagSet) (string, error) {
	if fs.NArg() == 1 && fs.Arg(0) == "-" {
		b, err := io.ReadAll(os.Stdin)
		return strings.TrimRight(string(b), "\n"), err
	}
	if fs.NArg() < 1 {
		return "", fail(fs, "missing TEXT (use - to read stdin)")
	}
	return strings.Join(fs.Args(), " "), nil
}

func cmdEncode(args []string) error {
	fs := flag.NewFlagSet("encode", flag.ContinueOnError)
	eccS := fs.String("ecc", "M", "error correction level L|M|Q|H")
	ver := fs.Int("v", 0, "force version 1-40 (0 = smallest that fits)")
	mask := fs.Int("mask", -1, "force data mask 0-7 (-1 = best by penalty)")
	out := fs.String("o", "-", "output file (.png, .svg, .txt) or - for terminal art")
	scale := fs.Int("scale", 8, "pixels per module for PNG")
	border := fs.Int("border", 4, "quiet-zone width in modules")
	noeci := fs.Bool("noeci", false, "never emit an ECI header")
	boost := fs.Bool("boost", false, "raise the ECC level for free when the version allows")
	info := fs.Bool("info", false, "print the encoding summary to stderr")
	invert := fs.Bool("invert", false, "invert terminal art for dark backgrounds")
	if err := fs.Parse(args); err != nil {
		return err
	}
	e, ok := qr.ParseECC(*eccS)
	if !ok {
		return fmt.Errorf("bad -ecc %q (want L, M, Q or H)", *eccS)
	}
	text, err := textArg(fs)
	if err != nil {
		return err
	}
	if *scale < 1 || *scale > 64 || *border < 0 || *border > 64 {
		return fmt.Errorf("-scale must be 1..64 and -border 0..64")
	}
	if *mask < -1 || *mask > 7 {
		return fmt.Errorf("-mask must be -1 (auto) or 0..7")
	}
	opt := qr.Options{ECC: e, NoECI: *noeci, BoostECC: *boost}
	if *mask >= 0 {
		opt.Mask = qr.ForceMask(*mask)
	}
	if *ver != 0 {
		opt.MinVersion, opt.MaxVersion = *ver, *ver
	}
	code, err := qr.EncodeText(text, opt)
	if err != nil {
		return err
	}
	if *info {
		fmt.Fprintf(os.Stderr, "version %d (%dx%d)  ecc %v  mask %d  penalty %d  segments:", code.Version, code.Matrix.N, code.Matrix.N, code.ECC, code.Mask, code.Penalty)
		for _, s := range code.Segments {
			if s.Mode == qr.ModeECI {
				fmt.Fprintf(os.Stderr, " eci(%d)", s.ECI)
			} else {
				fmt.Fprintf(os.Stderr, " %v[%d]", s.Mode, s.Chars)
			}
		}
		fmt.Fprintln(os.Stderr)
	}
	switch {
	case *out == "-" || strings.HasSuffix(*out, ".txt"):
		art := code.Matrix.Text(*border, *invert)
		if *out == "-" {
			fmt.Print(art)
			return nil
		}
		return os.WriteFile(*out, []byte(art), 0o644)
	case strings.HasSuffix(*out, ".svg"):
		return os.WriteFile(*out, []byte(code.Matrix.SVG(*border)), 0o644)
	case strings.HasSuffix(*out, ".png"):
		b, err := code.Matrix.PNG(*scale, *border)
		if err != nil {
			return err
		}
		return os.WriteFile(*out, b, 0o644)
	}
	return fmt.Errorf("unknown output type %q (use .png, .svg, .txt or -)", *out)
}

func loadImage(path string) (image.Image, error) {
	var r io.Reader = os.Stdin
	if path != "-" {
		f, err := os.Open(path)
		if err != nil {
			return nil, err
		}
		defer f.Close()
		r = f
	}
	img, _, err := image.Decode(r)
	if err != nil {
		return nil, fmt.Errorf("cannot read image: %w", err)
	}
	return img, nil
}

func cmdDecode(args []string, verbose bool) error {
	name := "decode"
	if verbose {
		name = "scan"
	}
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	asText := fs.Bool("text", false, "input is ASCII/half-block art of the module grid, not an image")
	all := fs.Bool("all", false, "print every symbol found (decode prints the first only)")
	debug := fs.Bool("debug", false, "trace scanner strategies")
	raw := fs.Bool("raw", false, "write the payload bytes verbatim (binary-safe, no newline)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 1 {
		return fail(fs, "need exactly one IMAGE (or - for stdin)")
	}
	if *asText {
		var b []byte
		var err error
		if fs.Arg(0) == "-" {
			b, err = io.ReadAll(os.Stdin)
		} else {
			b, err = os.ReadFile(fs.Arg(0))
		}
		if err != nil {
			return err
		}
		m, err := qr.ParseText(string(b))
		if err != nil {
			return err
		}
		r, err := qr.Decode(m)
		if err != nil {
			return err
		}
		printOut(r, verbose, *raw)
		return nil
	}
	img, err := loadImage(fs.Arg(0))
	if err != nil {
		return err
	}
	opt := scan.Options{}
	if !*all && !verbose {
		opt.MaxCodes = 1
	}
	if *debug {
		opt.Debug = func(s string) { fmt.Fprintln(os.Stderr, "scan:", s) }
	}
	ds, err := scan.Scan(img, opt)
	if err != nil {
		return err
	}
	for i, d := range ds {
		if verbose || *all {
			c := d.Corners
			fmt.Printf("symbol %d/%d  strategy=%s  module≈%.1fpx  alignment-refined=%d\n", i+1, len(ds), d.Strategy, d.Module, d.Aligns)
			fmt.Printf("  corners TL(%.0f,%.0f) TR(%.0f,%.0f) BR(%.0f,%.0f) BL(%.0f,%.0f)\n", c[0].X, c[0].Y, c[1].X, c[1].Y, c[2].X, c[2].Y, c[3].X, c[3].Y)
		}
		printOut(d.Result, verbose, *raw)
	}
	return nil
}

func printOut(r *qr.Result, verbose, raw bool) {
	if raw && !verbose {
		os.Stdout.Write(r.Bytes)
		return
	}
	printResult(r, verbose)
}

func printResult(r *qr.Result, verbose bool) {
	if !verbose {
		fmt.Println(r.Text)
		return
	}
	fmt.Printf("  version %d  ecc %v  mask %d  segments:", r.Version, r.ECC, r.Mask)
	for _, s := range r.Segments {
		if s.Mode == qr.ModeECI {
			fmt.Printf(" eci(%d)", s.ECI)
		} else {
			fmt.Printf(" %v[%d]", s.Mode, s.Chars)
		}
	}
	fmt.Printf("\n  error correction: %d codeword(s) repaired (per-block budget %d)", r.ByteErrors, r.Budget)
	if r.ErasuresUsed > 0 {
		fmt.Printf(", %d erasures", r.ErasuresUsed)
	}
	if r.FormatDistance > 0 {
		fmt.Printf(", format info %d bit(s) off", r.FormatDistance)
	}
	if r.FormatBruteForced {
		fmt.Print(" (recovered by brute force)")
	}
	if r.Transposed {
		fmt.Print(", mirrored capture fixed")
	}
	fmt.Printf("\n  text: %s\n", r.Text)
}
