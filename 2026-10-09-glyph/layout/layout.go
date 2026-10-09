// Package layout positions glyphs: cmap lookup, advances, kerning, wrapping, alignment.
package layout

import (
	"fmt"
	"strings"

	"glyph/ttf"
)

type Align int

const (
	Left Align = iota
	Center
	Right
	Justify
)

// ParseAlign parses "left", "center", "right" or "justify".
func ParseAlign(s string) (Align, error) {
	switch strings.ToLower(s) {
	case "", "left":
		return Left, nil
	case "center", "centre":
		return Center, nil
	case "right":
		return Right, nil
	case "justify":
		return Justify, nil
	}
	return Left, fmt.Errorf("unknown alignment %q (want left, center, right or justify)", s)
}

// Options controls layout. Size is the em size in pixels.
type Options struct {
	Size          float64
	Width         float64 // wrap width in px; 0 = no wrapping
	Align         Align
	LineHeight    float64 // multiplier of the font's natural line height; 0 = 1
	NoKerning     bool
	LetterSpacing float64 // extra px after every glyph
	TabSpaces     int     // tab advance in space widths; 0 = 4
}

// Placed is one positioned glyph; X,Y is the pen origin on the baseline (px).
type Placed struct {
	Rune rune
	GID  uint16
	X, Y float64
	Line int
}

// Line summarises one laid-out line.
type Line struct {
	Start, End int     // glyph index range [Start,End) in Result.Glyphs
	Width      float64 // ink advance width without trailing spaces
	Baseline   float64
}

// Result is a laid-out text block.
type Result struct {
	Glyphs                []Placed
	Lines                 []Line
	Width, Height         float64
	Ascent, Descent, Step float64 // px; Step is the line pitch
}

type item struct {
	r     rune
	gid   uint16
	adv   float64
	space bool
}

// Layout shapes text with the given font. It never fails on odd text: unmapped
// runes use .notdef, control characters (other than \n and \t) are dropped.
func Layout(f *ttf.Font, text string, o Options) (*Result, error) {
	if !(o.Size > 0) || o.Size > 10000 {
		return nil, fmt.Errorf("font size must be in (0, 10000], got %v", o.Size)
	}
	if o.Width < 0 {
		return nil, fmt.Errorf("wrap width must be >= 0")
	}
	scale := o.Size / float64(f.UnitsPerEm)
	lh := o.LineHeight
	if lh == 0 {
		lh = 1
	}
	res := &Result{
		Ascent:  float64(f.Ascent) * scale,
		Descent: float64(-f.Descent) * scale,
	}
	res.Step = float64(f.Ascent-f.Descent+f.LineGap) * scale * lh
	spaceGID := f.Index(' ')
	spaceAdv := float64(f.UnitsPerEm) / 4 * scale
	if spaceGID != 0 {
		spaceAdv = float64(f.Advance(spaceGID)) * scale
	}
	tabN := o.TabSpaces
	if tabN <= 0 {
		tabN = 4
	}

	text = strings.ReplaceAll(strings.ReplaceAll(text, "\r\n", "\n"), "\r", "\n")
	lineNo := 0
	y := res.Ascent
	for _, para := range strings.Split(text, "\n") {
		items := shape(f, para, scale, spaceAdv, tabN, o)
		lines := breakLines(f, items, o, scale)
		if len(lines) == 0 {
			lines = [][2]int{{0, 0}}
		}
		for li, ln := range lines {
			seg := items[ln[0]:ln[1]]
			last := li == len(lines)-1
			start := len(res.Glyphs)
			// trim trailing spaces for width/alignment
			end := len(seg)
			for end > 0 && seg[end-1].space {
				end--
			}
			xs := penPositions(f, seg, scale, o)
			width := 0.0
			if end > 0 {
				width = xs[end-1] + seg[end-1].adv
			}
			x0, extra := 0.0, 0.0
			switch o.Align {
			case Center:
				if o.Width > 0 {
					x0 = (o.Width - width) / 2
				}
			case Right:
				if o.Width > 0 {
					x0 = o.Width - width
				}
			case Justify:
				if o.Width > 0 && !last && width < o.Width {
					gaps := 0
					for _, it := range seg[:end] {
						if it.space {
							gaps++
						}
					}
					if gaps > 0 {
						extra = (o.Width - width) / float64(gaps)
					}
				}
			}
			shift := 0.0
			for i, it := range seg {
				res.Glyphs = append(res.Glyphs, Placed{Rune: it.r, GID: it.gid, X: x0 + xs[i] + shift, Y: y, Line: lineNo})
				if it.space && i < end {
					shift += extra // justification widens interior spaces
				}
			}
			if extra > 0 {
				width = o.Width
			}
			res.Lines = append(res.Lines, Line{Start: start, End: len(res.Glyphs), Width: width, Baseline: y})
			res.Width = max(res.Width, x0+width)
			lineNo++
			y += res.Step
		}
	}
	res.Height = res.Ascent + res.Descent + res.Step*float64(max(lineNo-1, 0))
	return res, nil
}

func shape(f *ttf.Font, s string, scale, spaceAdv float64, tabN int, o Options) []item {
	var items []item
	for _, r := range s {
		switch {
		case r == '\t':
			items = append(items, item{r: r, gid: f.Index(' '), adv: spaceAdv * float64(tabN), space: true})
		case r < 0x20 || (r >= 0x7f && r < 0xa0) || r == 0x200b || r == 0xfeff || r == 0x200c || r == 0x200d:
			continue
		default:
			g := f.Index(r)
			items = append(items, item{r: r, gid: g, adv: float64(f.Advance(g))*scale + o.LetterSpacing, space: r == ' '})
		}
	}
	return items
}

// penPositions returns the x of each item within a line (kerning applied
// between adjacent non-tab items).
func penPositions(f *ttf.Font, seg []item, scale float64, o Options) []float64 {
	xs := make([]float64, len(seg))
	x := 0.0
	for i, it := range seg {
		xs[i] = x
		x += it.adv
		if !o.NoKerning && i+1 < len(seg) && it.r != '\t' && seg[i+1].r != '\t' {
			x += float64(f.Kerning(it.gid, seg[i+1].gid)) * scale
		}
	}
	return xs
}

// breakLines greedily wraps items at spaces/hyphens, hard-splitting words
// wider than the wrap width. Returns [start,end) item ranges.
func breakLines(f *ttf.Font, items []item, o Options, scale float64) [][2]int {
	if len(items) == 0 {
		return nil
	}
	if o.Width <= 0 {
		return [][2]int{{0, len(items)}}
	}
	// break opportunity = index i such that a line may end before item i
	canBreakBefore := func(i int) bool {
		return i > 0 && i < len(items) && (items[i-1].space && !items[i].space || items[i-1].r == '-' && !items[i].space && items[i-1].r != items[i].r)
	}
	widthOf := func(a, b int) float64 { // ink width of items[a:b], trailing spaces excluded
		for b > a && items[b-1].space {
			b--
		}
		if b <= a {
			return 0
		}
		xs := penPositions(f, items[a:b], scale, o)
		return xs[len(xs)-1] + items[b-1].adv
	}
	var lines [][2]int
	n := len(items)
	for a := 0; a < n; {
		best := -1
		for c := a + 1; c <= n; c++ {
			if c != n && !canBreakBefore(c) {
				continue
			}
			if widthOf(a, c) > o.Width {
				break
			}
			best = c
		}
		if best < 0 { // first word alone is too wide: split it by character
			best = a + 1
			for best < n && widthOf(a, best+1) <= o.Width {
				best++
			}
		}
		lines = append(lines, [2]int{a, best})
		a = best
	}
	return lines
}
