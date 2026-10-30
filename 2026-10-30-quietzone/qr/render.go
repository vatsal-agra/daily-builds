package qr

import (
	"bytes"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"strings"
)

// Text renders the matrix with a quiet zone using Unicode half blocks
// (two module rows per text row). invert swaps dark/light for dark terminals.
func (m *Matrix) Text(quiet int, invert bool) string {
	get := func(x, y int) bool {
		if x < 0 || y < 0 || x >= m.N || y >= m.N {
			return false
		}
		return m.Get(x, y) != invert
	}
	var sb strings.Builder
	for y := -quiet; y < m.N+quiet; y += 2 {
		for x := -quiet; x < m.N+quiet; x++ {
			top, bot := get(x, y), get(x, y+1)
			switch {
			case top && bot:
				sb.WriteString("█")
			case top:
				sb.WriteString("▀")
			case bot:
				sb.WriteString("▄")
			default:
				sb.WriteString(" ")
			}
		}
		sb.WriteString("\n")
	}
	return sb.String()
}

// SVG renders a crisp vector image.
func (m *Matrix) SVG(quiet int) string {
	n := m.N + 2*quiet
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges"><rect width="%d" height="%d" fill="#fff"/><path fill="#000" d="`, n, n, n, n)
	for y := 0; y < m.N; y++ {
		for x := 0; x < m.N; x++ {
			if m.Get(x, y) {
				fmt.Fprintf(&sb, "M%d %dh1v1h-1z", x+quiet, y+quiet)
			}
		}
	}
	sb.WriteString(`"/></svg>`)
	return sb.String()
}

// Image rasterises the matrix with `scale` pixels per module.
func (m *Matrix) Image(scale, quiet int) *image.Gray {
	n := (m.N + 2*quiet) * scale
	img := image.NewGray(image.Rect(0, 0, n, n))
	for i := range img.Pix {
		img.Pix[i] = 255
	}
	for y := 0; y < m.N; y++ {
		for x := 0; x < m.N; x++ {
			if !m.Get(x, y) {
				continue
			}
			for dy := 0; dy < scale; dy++ {
				for dx := 0; dx < scale; dx++ {
					img.SetGray((x+quiet)*scale+dx, (y+quiet)*scale+dy, color.Gray{0})
				}
			}
		}
	}
	return img
}

// PNG encodes the matrix as a grayscale PNG.
func (m *Matrix) PNG(scale, quiet int) ([]byte, error) {
	var buf bytes.Buffer
	if err := png.Encode(&buf, m.Image(scale, quiet)); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// ParseText reads the half-block / '#' text form produced by Text (or a
// plain grid of '#' and '.') back into a matrix, ignoring the quiet zone.
func ParseText(s string) (*Matrix, error) {
	lines := strings.Split(strings.TrimRight(s, "\n"), "\n")
	var rows [][]bool
	for _, ln := range lines {
		var top, bot []bool
		for _, r := range ln {
			switch r {
			case '█':
				top, bot = append(top, true), append(bot, true)
			case '▀':
				top, bot = append(top, true), append(bot, false)
			case '▄':
				top, bot = append(top, false), append(bot, true)
			default:
				top, bot = append(top, false), append(bot, false)
			}
		}
		rows = append(rows, top, bot)
	}
	minX, minY, maxX, maxY := 1<<30, 1<<30, -1, -1
	for y, r := range rows {
		for x, v := range r {
			if v {
				minX, maxX = min(minX, x), max(maxX, x)
				minY, maxY = min(minY, y), max(maxY, y)
			}
		}
	}
	if maxX < 0 {
		return nil, fmt.Errorf("qr: no dark modules in text")
	}
	w, h := maxX-minX+1, maxY-minY+1
	if w != h {
		return nil, fmt.Errorf("qr: text bounding box %dx%d is not square", w, h)
	}
	m := NewMatrix(w)
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			if y+minY < len(rows) && x+minX < len(rows[y+minY]) {
				m.Set(x, y, rows[y+minY][x+minX])
			}
		}
	}
	return m, nil
}
