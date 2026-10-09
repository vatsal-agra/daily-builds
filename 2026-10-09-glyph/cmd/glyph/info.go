package main

import (
	"flag"
	"fmt"
	"os"
	"strings"
	"unicode/utf8"

	"glyph/img"
	"glyph/raster"
	"glyph/ttf"
)

func cmdInfo(args []string) error {
	fs := flag.NewFlagSet("info", flag.ContinueOnError)
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 1 {
		return fmt.Errorf("usage: glyph info <font.ttf>")
	}
	f, err := loadFont(fs.Arg(0))
	if err != nil {
		return err
	}
	fmt.Printf("family      %s\n", f.Name(1))
	fmt.Printf("style       %s\n", f.Name(2))
	fmt.Printf("full name   %s\n", f.Name(4))
	if v := f.Name(5); v != "" {
		fmt.Printf("version     %s\n", v)
	}
	fmt.Printf("unitsPerEm  %d\n", f.UnitsPerEm)
	fmt.Printf("glyphs      %d\n", f.NumGlyphs)
	fmt.Printf("ascent      %d   descent %d   lineGap %d\n", f.Ascent, f.Descent, f.LineGap)
	fmt.Printf("bbox        (%d,%d)-(%d,%d)\n", f.XMin, f.YMin, f.XMax, f.YMax)
	if f.WeightClass != 0 {
		fmt.Printf("weight      %d\n", f.WeightClass)
	}
	p, e, fm := f.CmapInfo()
	fmt.Printf("cmap        platform %d encoding %d format %d, %d mapped characters\n", p, e, fm, len(f.Runes()))
	src := "none"
	switch {
	case f.HasTable("GPOS") && f.HasKerning() && len(f.KernPairs()) == 0:
		src = "GPOS pair adjustment"
	case len(f.KernPairs()) > 0:
		src = fmt.Sprintf("kern table (%d pairs)", len(f.KernPairs()))
	}
	fmt.Printf("kerning     %s\n", src)
	fmt.Printf("tables      %s\n", strings.Join(f.Tables(), " "))
	if bad := f.Verify(); len(bad) == 0 {
		fmt.Println("checksums   OK")
	} else {
		fmt.Println("checksums   PROBLEMS")
		for _, b := range bad {
			fmt.Println("  -", b)
		}
	}
	return nil
}

const ramp = " .:-=+*#%@"

func cmdGlyph(args []string) error {
	fs := flag.NewFlagSet("glyph", flag.ContinueOnError)
	var font, ch, out string
	var size float64
	var ascii bool
	var samples int
	fs.StringVar(&font, "font", "", "path to a .ttf file")
	fs.StringVar(&ch, "char", "", "character to render")
	fs.StringVar(&out, "o", "", "write grayscale coverage PNG here")
	fs.Float64Var(&size, "size", 64, "size in pixels")
	fs.BoolVar(&ascii, "ascii", false, "print ASCII art to stdout")
	fs.IntVar(&samples, "samples", 0, "vertical sub-scanlines per pixel")
	if err := fs.Parse(args); err != nil {
		return err
	}
	f, err := loadFont(font)
	if err != nil {
		return err
	}
	if utf8.RuneCountInString(ch) != 1 {
		return fmt.Errorf("-char must be exactly one character, got %q", ch)
	}
	if !(size >= 1 && size <= 4000) {
		return fmt.Errorf("-size must be in [1, 4000]")
	}
	r, _ := utf8.DecodeRuneInString(ch)
	gid := f.Index(r)
	o, err := f.Glyph(gid)
	if err != nil {
		return err
	}
	scale := size / float64(f.UnitsPerEm)
	bm := raster.Render(raster.Flatten(o, raster.Scale(scale, 0, 0, 0), 0), samples)
	fmt.Printf("%q → glyph %d, advance %d units, %d contours, %d points, bitmap %dx%d\n",
		r, gid, f.Advance(gid), len(o.Contours), o.NumPoints(), bm.W, bm.H)
	if bm.W == 0 {
		fmt.Println("(empty glyph: nothing to draw)")
	}
	if ascii {
		for y := 0; y < bm.H; y++ {
			var sb strings.Builder
			for x := 0; x < bm.W; x++ {
				sb.WriteByte(ramp[int(bm.At(x, y)*float32(len(ramp)-1)+0.5)])
			}
			fmt.Println(strings.TrimRight(sb.String(), " "))
		}
	}
	if out != "" {
		if bm.W == 0 {
			return fmt.Errorf("glyph has no outline; no PNG written")
		}
		png, err := img.GrayPNG(bm)
		if err != nil {
			return err
		}
		return os.WriteFile(out, png, 0o644)
	}
	return nil
}

var _ = ttf.Parse
