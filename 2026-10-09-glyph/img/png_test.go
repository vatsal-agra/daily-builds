package img_test

import (
	"bytes"
	"compress/zlib"
	"encoding/binary"
	"hash/crc32"
	"image"
	"image/color"
	"image/png"
	"io"
	"math/rand"
	"testing"

	"glyph/img"
	"glyph/raster"
)

// The stdlib decoder is the independent oracle for our hand-written encoder.
func TestPNGRoundTripAllShapes(t *testing.T) {
	rng := rand.New(rand.NewSource(7))
	for _, ch := range []int{1, 3, 4} {
		for _, dim := range [][2]int{{1, 1}, {2, 3}, {17, 5}, {64, 64}, {5, 130}} {
			w, h := dim[0], dim[1]
			pix := make([]byte, w*h*ch)
			for i := range pix {
				switch (i / (w * ch)) % 4 { // rows alternate noise / gradient / flat / sparse so every filter gets exercised
				case 0:
					pix[i] = byte(rng.Intn(256))
				case 1:
					pix[i] = byte(i)
				case 2:
					pix[i] = 200
				default:
					if rng.Intn(9) == 0 {
						pix[i] = 255
					}
				}
			}
			var b bytes.Buffer
			if err := img.EncodePNG(&b, w, h, ch, pix); err != nil {
				t.Fatal(err)
			}
			m, err := png.Decode(&b)
			if err != nil {
				t.Fatalf("ch=%d %dx%d: stdlib cannot decode: %v", ch, w, h, err)
			}
			if m.Bounds() != image.Rect(0, 0, w, h) {
				t.Fatalf("bounds %v", m.Bounds())
			}
			for y := 0; y < h; y++ {
				for x := 0; x < w; x++ {
					o := (y*w + x) * ch
					var want color.Color
					switch ch {
					case 1:
						want = color.Gray{Y: pix[o]}
					case 3:
						want = color.NRGBA{pix[o], pix[o+1], pix[o+2], 255}
					default:
						want = color.NRGBA{pix[o], pix[o+1], pix[o+2], pix[o+3]}
					}
					wr, wg, wb, wa := want.RGBA()
					gr, gg, gb, ga := m.At(x, y).RGBA()
					if wr != gr || wg != gg || wb != gb || wa != ga {
						t.Fatalf("ch=%d %dx%d pixel (%d,%d): got %v want %v", ch, w, h, x, y, m.At(x, y), want)
					}
				}
			}
		}
	}
}

// Every one of the five scanline filters must be selected by some input and still round-trip.
func TestAllFilterTypesExercised(t *testing.T) {
	rng := rand.New(rand.NewSource(3))
	const w, h = 40, 30
	mk := map[string]func(x, y int) byte{
		"identical rows (Up)":        func(x, y int) byte { return byte(x * 37 % 251) },
		"horizontal ramp (Sub)":      func(x, y int) byte { return byte(x * 6) },
		"smooth 2D ramp (Avg/Paeth)": func(x, y int) byte { return byte(x*3 + y*5) },
		"noise (None)":               func(x, y int) byte { return byte(rng.Intn(256)) },
		"diagonal edges (Paeth)": func(x, y int) byte {
			if (x+y)%17 < 8 {
				return 30
			}
			return 220
		},
	}
	seen := map[byte]bool{}
	for name, f := range mk {
		pix := make([]byte, w*h)
		for y := 0; y < h; y++ {
			for x := 0; x < w; x++ {
				pix[y*w+x] = f(x, y)
			}
		}
		var b bytes.Buffer
		if err := img.EncodePNG(&b, w, h, 1, pix); err != nil {
			t.Fatal(err)
		}
		raw := b.Bytes()
		// find IDAT, inflate, read the filter byte at the start of each row
		off := 8
		var idat []byte
		for off < len(raw) {
			n := int(binary.BigEndian.Uint32(raw[off:]))
			if string(raw[off+4:off+8]) == "IDAT" {
				idat = raw[off+8 : off+8+n]
			}
			off += 12 + n
		}
		zr, err := zlib.NewReader(bytes.NewReader(idat))
		if err != nil {
			t.Fatal(err)
		}
		data, _ := io.ReadAll(zr)
		for y := 0; y < h; y++ {
			seen[data[y*(w+1)]] = true
		}
		m, err := png.Decode(bytes.NewReader(raw))
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		for y := 0; y < h; y++ {
			for x := 0; x < w; x++ {
				if m.(*image.Gray).GrayAt(x, y).Y != pix[y*w+x] {
					t.Fatalf("%s: pixel (%d,%d) corrupted", name, x, y)
				}
			}
		}
	}
	for ft := byte(0); ft < 5; ft++ {
		if !seen[ft] {
			t.Errorf("filter type %d never selected by any test image", ft)
		}
	}
}

func TestPNGStructure(t *testing.T) {
	var b bytes.Buffer
	if err := img.EncodePNG(&b, 3, 2, 3, make([]byte, 18)); err != nil {
		t.Fatal(err)
	}
	d := b.Bytes()
	if string(d[:8]) != "\x89PNG\r\n\x1a\n" {
		t.Fatal("bad signature")
	}
	off, seen := 8, []string{}
	for off < len(d) {
		n := int(binary.BigEndian.Uint32(d[off:]))
		typ := string(d[off+4 : off+8])
		body := d[off+8 : off+8+n]
		crc := binary.BigEndian.Uint32(d[off+8+n:])
		if crc != crc32.ChecksumIEEE(d[off+4:off+8+n]) {
			t.Errorf("chunk %s has a bad CRC", typ)
		}
		if typ == "IHDR" && (binary.BigEndian.Uint32(body) != 3 || binary.BigEndian.Uint32(body[4:]) != 2 || body[8] != 8 || body[9] != 2) {
			t.Errorf("IHDR wrong: %v", body)
		}
		seen = append(seen, typ)
		off += 12 + n
	}
	if len(seen) != 3 || seen[0] != "IHDR" || seen[1] != "IDAT" || seen[2] != "IEND" {
		t.Errorf("chunks %v", seen)
	}
}

func TestPNGRejectsBadInput(t *testing.T) {
	var b bytes.Buffer
	for name, f := range map[string]func() error{
		"channels": func() error { return img.EncodePNG(&b, 2, 2, 2, make([]byte, 8)) },
		"size":     func() error { return img.EncodePNG(&b, 0, 2, 3, nil) },
		"buffer":   func() error { return img.EncodePNG(&b, 2, 2, 3, make([]byte, 5)) },
		"negative": func() error { return img.EncodePNG(&b, -1, 2, 1, nil) },
	} {
		if f() == nil {
			t.Errorf("%s accepted", name)
		}
	}
}

func TestCanvasBlending(t *testing.T) {
	bm := &raster.Bitmap{W: 3, H: 1, Pix: []float32{0, 0.5, 1}}
	white, black := img.RGB{R: 255, G: 255, B: 255}, img.RGB{}
	c := img.NewCanvas(3, 1, white)
	c.Blend(bm, 0, 0, black, false)
	if c.Pix[0] != 255 || c.Pix[3] != 128 || c.Pix[6] != 0 {
		t.Errorf("sRGB blend: %v", c.Pix)
	}
	g := img.NewCanvas(3, 1, white)
	g.Blend(bm, 0, 0, black, true)
	// 50% black over white in linear light is ≈ sRGB 188, brighter than naive 128
	if g.Pix[3] < 180 || g.Pix[3] > 195 || g.Pix[0] != 255 || g.Pix[6] != 0 {
		t.Errorf("linear blend: %v", g.Pix)
	}
	// light on dark: 50% white over black → ≈ 188 as well (symmetry of linear light)
	d := img.NewCanvas(3, 1, black)
	d.Blend(bm, 0, 0, white, true)
	if d.Pix[3] < 180 || d.Pix[3] > 195 {
		t.Errorf("light-on-dark: %v", d.Pix)
	}
	// offsets, clipping and out-of-range coverage never panic or corrupt neighbours
	e := img.NewCanvas(2, 2, white)
	e.Blend(&raster.Bitmap{W: 2, H: 2, X0: -1, Y0: -1, Pix: []float32{1, 1, 1, 7}}, 0, 0, black, false)
	if e.Pix[0] != 0 || e.Pix[3] != 255 {
		t.Errorf("clipped blend: %v", e.Pix)
	}
	e.MixChannel(-5, 0, 0, 0, 1, false) // out of range: ignored
	e.MixChannel(0, 9, 0, 0, 1, false)
	if _, err := c.PNG(); err != nil {
		t.Error(err)
	}
}

func TestGrayPNG(t *testing.T) {
	b, err := img.GrayPNG(&raster.Bitmap{W: 2, H: 1, Pix: []float32{0, 1}})
	if err != nil {
		t.Fatal(err)
	}
	m, err := png.Decode(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if g := m.At(0, 0).(color.Gray).Y; g != 255 {
		t.Errorf("no ink should be white, got %d", g)
	}
	if g := m.At(1, 0).(color.Gray).Y; g != 0 {
		t.Errorf("full ink should be black, got %d", g)
	}
	if _, err := img.GrayPNG(&raster.Bitmap{}); err == nil {
		t.Error("empty bitmap should be an error, not an invalid PNG")
	}
}
