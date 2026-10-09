// Command glyph is a CLI front-end for the Glyph TrueType engine.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"glyph/img"
	"glyph/layout"
	"glyph/render"
	"glyph/ttf"
)

const usage = `glyph — a from-scratch TrueType font engine

usage: glyph <command> [flags]

commands:
  info    <font.ttf>                  print metrics, tables, cmap, kerning and checksum status
  text    -font F -o out.png TEXT...  lay out and rasterize text (anti-aliased PNG)
  glyph   -font F -char A [-ascii]    render one glyph large, as PNG and/or ASCII art
  svg     -font F -o out.svg TEXT...  export exact vector outlines as SVG
  sdf     -font F -o out.png TEXT...  signed-distance-field atlas of the glyphs in TEXT
  subset  -font F -o out.ttf TEXT...  write a new TTF containing only the glyphs in TEXT
  lcd     -font F -o out.png TEXT...  LCD sub-pixel rendered text
  specimen -font F -o out.html        HTML specimen sheet of the whole font

Text may come from arguments, -file PATH, or stdin ("-file -").`

func main() {
	if len(os.Args) < 2 || os.Args[1] == "-h" || os.Args[1] == "--help" || os.Args[1] == "help" {
		fmt.Println(usage)
		return
	}
	cmd, args := os.Args[1], os.Args[2:]
	var err error
	switch cmd {
	case "info":
		err = cmdInfo(args)
	case "text":
		err = cmdText(args)
	case "glyph":
		err = cmdGlyph(args)
	case "svg":
		err = cmdSVG(args)
	case "sdf":
		err = cmdSDF(args)
	case "subset":
		err = cmdSubset(args)
	case "lcd":
		err = cmdLCD(args)
	case "specimen":
		err = cmdSpecimen(args)
	default:
		err = fmt.Errorf("unknown command %q (try `glyph help`)", cmd)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "glyph:", err)
		os.Exit(1)
	}
}

func loadFont(path string) (*ttf.Font, error) {
	if path == "" {
		return nil, fmt.Errorf("missing -font")
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	f, err := ttf.Parse(b)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return f, nil
}

func parseColor(s string) (img.RGB, error) {
	s = strings.TrimPrefix(s, "#")
	if len(s) == 3 {
		s = string([]byte{s[0], s[0], s[1], s[1], s[2], s[2]})
	}
	var r, g, b uint8
	if len(s) != 6 {
		return img.RGB{}, fmt.Errorf("bad colour %q (want #rgb or #rrggbb)", s)
	}
	if _, err := fmt.Sscanf(s, "%02x%02x%02x", &r, &g, &b); err != nil {
		return img.RGB{}, fmt.Errorf("bad colour %q (want #rgb or #rrggbb)", s)
	}
	return img.RGB{R: r, G: g, B: b}, nil
}

// textInput resolves the text to render from -file or positional args.
func textInput(file string, rest []string) (string, error) {
	switch {
	case file == "-":
		b, err := io.ReadAll(os.Stdin)
		return string(b), err
	case file != "":
		b, err := os.ReadFile(file)
		return string(b), err
	case len(rest) > 0:
		return strings.Join(rest, " "), nil
	}
	return "", fmt.Errorf("no text given (pass it as arguments, or use -file)")
}

type common struct {
	font, out, file, fg, bg, align     string
	size, width, lineH, spacing, slant float64
	pad                                int
	noKern, noGamma                    bool
	samples                            int
}

func (c *common) register(fs *flag.FlagSet) {
	fs.StringVar(&c.font, "font", "", "path to a .ttf file")
	fs.StringVar(&c.out, "o", "", "output path")
	fs.StringVar(&c.file, "file", "", "read text from file (- for stdin)")
	fs.StringVar(&c.fg, "fg", "#111111", "text colour")
	fs.StringVar(&c.bg, "bg", "#ffffff", "background colour")
	fs.StringVar(&c.align, "align", "left", "left|center|right|justify")
	fs.Float64Var(&c.size, "size", 32, "font size in pixels")
	fs.Float64Var(&c.width, "width", 0, "wrap width in pixels (0 = no wrap)")
	fs.Float64Var(&c.lineH, "line-height", 1, "line height multiplier")
	fs.Float64Var(&c.spacing, "spacing", 0, "extra letter spacing in pixels")
	fs.Float64Var(&c.slant, "slant", 0, "synthetic oblique shear (0.2 ≈ 11°)")
	fs.IntVar(&c.pad, "pad", 8, "padding in pixels")
	fs.BoolVar(&c.noKern, "no-kern", false, "disable kerning")
	fs.BoolVar(&c.noGamma, "no-gamma", false, "blend in sRGB instead of linear light")
	fs.IntVar(&c.samples, "samples", 0, "vertical sub-scanlines per pixel (default 32)")
}

func (c *common) style() (render.Style, error) {
	fg, err := parseColor(c.fg)
	if err != nil {
		return render.Style{}, err
	}
	bg, err := parseColor(c.bg)
	if err != nil {
		return render.Style{}, err
	}
	al, err := layout.ParseAlign(c.align)
	if err != nil {
		return render.Style{}, err
	}
	return render.Style{
		Options: layout.Options{Size: c.size, Width: c.width, Align: al, LineHeight: c.lineH,
			NoKerning: c.noKern, LetterSpacing: c.spacing},
		FG: fg, BG: bg, Padding: c.pad, Gamma: !c.noGamma, Slant: c.slant, Samples: c.samples,
	}, nil
}

func cmdText(args []string) error {
	fs := flag.NewFlagSet("text", flag.ContinueOnError)
	var c common
	c.register(fs)
	if err := fs.Parse(args); err != nil {
		return err
	}
	f, err := loadFont(c.font)
	if err != nil {
		return err
	}
	txt, err := textInput(c.file, fs.Args())
	if err != nil {
		return err
	}
	st, err := c.style()
	if err != nil {
		return err
	}
	if c.out == "" {
		return fmt.Errorf("missing -o output path")
	}
	cv, res, err := render.Text(f, txt, st)
	if err != nil {
		return err
	}
	png, err := cv.PNG()
	if err != nil {
		return err
	}
	if err := os.WriteFile(c.out, png, 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%dx%d, %d glyphs, %d lines)\n", c.out, cv.W, cv.H, len(res.Glyphs), len(res.Lines))
	return nil
}

func cmdSVG(args []string) error {
	fs := flag.NewFlagSet("svg", flag.ContinueOnError)
	var c common
	c.register(fs)
	if err := fs.Parse(args); err != nil {
		return err
	}
	f, err := loadFont(c.font)
	if err != nil {
		return err
	}
	txt, err := textInput(c.file, fs.Args())
	if err != nil {
		return err
	}
	st, err := c.style()
	if err != nil {
		return err
	}
	if c.out == "" {
		return fmt.Errorf("missing -o output path")
	}
	s, err := render.SVG(f, txt, st)
	if err != nil {
		return err
	}
	if err := os.WriteFile(c.out, []byte(s), 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%d bytes)\n", c.out, len(s))
	return nil
}
