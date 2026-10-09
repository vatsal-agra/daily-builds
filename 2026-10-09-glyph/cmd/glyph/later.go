package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"glyph/render"
	"glyph/ttf"
)

func cmdLCD(args []string) error {
	fs := flag.NewFlagSet("lcd", flag.ContinueOnError)
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
	st.LCD = true
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
	fmt.Printf("wrote %s (%dx%d, %d glyphs, LCD RGB sub-pixel)\n", c.out, cv.W, cv.H, len(res.Glyphs))
	return nil
}

func cmdSubset(args []string) error {
	fs := flag.NewFlagSet("subset", flag.ContinueOnError)
	var font, out, file string
	fs.StringVar(&font, "font", "", "path to a .ttf file")
	fs.StringVar(&out, "o", "", "output .ttf path")
	fs.StringVar(&file, "file", "", "read the characters to keep from a file (- for stdin)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	f, err := loadFont(font)
	if err != nil {
		return err
	}
	txt, err := textInput(file, fs.Args())
	if err != nil {
		return err
	}
	if out == "" {
		return fmt.Errorf("missing -o output path")
	}
	b, err := f.Subset(txt)
	if err != nil {
		return err
	}
	orig, _ := os.Stat(font)
	if err := os.WriteFile(out, b, 0o644); err != nil {
		return err
	}
	sub, _ := ttf.Parse(b)
	fmt.Printf("wrote %s: %d bytes (from %d), %d glyphs, %d mapped characters\n", out, len(b), orig.Size(), sub.NumGlyphs, len(sub.Runes()))
	return nil
}

func cmdSDF(args []string) error {
	fs := flag.NewFlagSet("sdf", flag.ContinueOnError)
	var c common
	var spread int
	var px float64
	var demo string
	c.register(fs)
	fs.IntVar(&spread, "spread", 8, "distance range in pixels (±spread maps to 0..255)")
	fs.Float64Var(&px, "px", 48, "size in pixels the glyph fields are generated at")
	fs.StringVar(&demo, "demo", "", "also draw the text at -size from the atlas alone, to this PNG")
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
	if c.out == "" {
		return fmt.Errorf("missing -o atlas PNG path")
	}
	a, err := render.BuildAtlas(f, txt, px, spread)
	if err != nil {
		return err
	}
	png, err := a.PNG()
	if err != nil {
		return err
	}
	if err := os.WriteFile(c.out, png, 0o644); err != nil {
		return err
	}
	js, err := a.JSON(filepath.Base(c.out))
	if err != nil {
		return err
	}
	jsPath := strings.TrimSuffix(c.out, filepath.Ext(c.out)) + ".json"
	if err := os.WriteFile(jsPath, js, 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%dx%d) and %s (%d glyphs)\n", c.out, a.W, a.H, jsPath, len(a.Glyphs))
	if demo != "" {
		st, err := c.style()
		if err != nil {
			return err
		}
		cv, err := a.Text(txt, c.size, st.FG, st.BG, c.pad)
		if err != nil {
			return err
		}
		dp, err := cv.PNG()
		if err != nil {
			return err
		}
		if err := os.WriteFile(demo, dp, 0o644); err != nil {
			return err
		}
		fmt.Printf("wrote %s (text drawn from the atlas at %.0f px)\n", demo, c.size)
	}
	return nil
}

func cmdSpecimen(args []string) error {
	fs := flag.NewFlagSet("specimen", flag.ContinueOnError)
	var font, out string
	var max int
	fs.StringVar(&font, "font", "", "path to a .ttf file")
	fs.StringVar(&out, "o", "", "output .html path")
	fs.IntVar(&max, "max", 600, "maximum number of glyph cells")
	if err := fs.Parse(args); err != nil {
		return err
	}
	f, err := loadFont(font)
	if err != nil {
		return err
	}
	if out == "" {
		return fmt.Errorf("missing -o output path")
	}
	h, err := render.Specimen(f, max)
	if err != nil {
		return err
	}
	if err := os.WriteFile(out, []byte(h), 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%d KiB)\n", out, len(h)/1024)
	return nil
}
