package scan

import (
	"image"
	"image/color"
	"math/rand"
	"testing"
	"time"

	"quietzone/qr"
)

func TestProbeInverted(t *testing.T) {
	c := enc(t, "inverted colours", qr.M)
	g := c.Matrix.Image(6, 4)
	for i := range g.Pix {
		g.Pix[i] = 255 - g.Pix[i]
	}
	ds, err := Scan(g, Options{})
	if err != nil || ds[0].Result.Text != "inverted colours" {
		t.Fatalf("%v", err)
	}
}

func TestProbeNoQuietZone(t *testing.T) {
	c := enc(t, "no quiet zone at all", qr.Q)
	g := c.Matrix.Image(6, 0)
	if ds, err := Scan(g, Options{}); err != nil || ds[0].Result.Text != "no quiet zone at all" {
		t.Fatalf("border-flush: %v", err)
	}
}

func TestProbeTwoCodes(t *testing.T) {
	a, b := enc(t, "first code", qr.M), enc(t, "second code is longer 1234567890", qr.Q)
	ia, ib := a.Matrix.Image(6, 4), b.Matrix.Image(6, 4)
	w := ia.Bounds().Dx() + ib.Bounds().Dx() + 20
	h := max(ia.Bounds().Dy(), ib.Bounds().Dy()) + 30
	canvas := image.NewGray(image.Rect(0, 0, w, h))
	for i := range canvas.Pix {
		canvas.Pix[i] = 255
	}
	put := func(src *image.Gray, ox, oy int) {
		for y := 0; y < src.Bounds().Dy(); y++ {
			for x := 0; x < src.Bounds().Dx(); x++ {
				canvas.SetGray(ox+x, oy+y, src.GrayAt(x, y))
			}
		}
	}
	put(ia, 5, 5)
	put(ib, ia.Bounds().Dx()+15, 20)
	ds, err := Scan(canvas, Options{})
	if err != nil || len(ds) != 2 {
		t.Fatalf("want 2 codes, got %d (%v)", len(ds), err)
	}
}

func TestProbeLargeBlankIsFast(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	for _, noisy := range []bool{false, true} {
		g := image.NewGray(image.Rect(0, 0, 3000, 2000))
		for i := range g.Pix {
			g.Pix[i] = 255
			if noisy {
				g.Pix[i] = uint8(rng.Intn(256))
			}
		}
		start := time.Now()
		_, err := Scan(g, Options{})
		if err != ErrNotFound {
			t.Fatalf("noisy=%v: %v", noisy, err)
		}
		if d := time.Since(start); d > 20*time.Second {
			t.Fatalf("noisy=%v took %v", noisy, d)
		}
		t.Logf("noisy=%v: %v", noisy, time.Since(start))
	}
}

func TestProbeAlpha(t *testing.T) {
	c := enc(t, "transparent bg", qr.M)
	g := c.Matrix.Image(6, 4)
	img := image.NewNRGBA(g.Bounds())
	for y := 0; y < g.Bounds().Dy(); y++ {
		for x := 0; x < g.Bounds().Dx(); x++ {
			if g.GrayAt(x, y).Y < 128 {
				img.SetNRGBA(x, y, color.NRGBA{0, 0, 0, 255})
			} // else fully transparent
		}
	}
	if ds, err := Scan(img, Options{}); err != nil || ds[0].Result.Text != "transparent bg" {
		t.Fatalf("%v", err)
	}
}

func TestProbeTinyImages(t *testing.T) {
	for _, d := range [][2]int{{0, 0}, {1, 1}, {20, 20}, {21, 5}, {5, 400}} {
		g := image.NewGray(image.Rect(0, 0, d[0], d[1]))
		if _, err := Scan(g, Options{}); err == nil {
			t.Fatalf("%v: no error", d)
		}
	}
}

func TestProbeTwoPixelModules(t *testing.T) {
	c := enc(t, "2px", qr.L)
	if _, err := Scan(c.Matrix.Image(2, 4), Options{}); err != nil {
		t.Fatalf("2px/module v%d: %v", c.Version, err)
	}
}

func TestProbeCroppedSymbolFailsCleanly(t *testing.T) {
	c := enc(t, "cropped symbol should not be decodable", qr.M)
	g := c.Matrix.Image(6, 4)
	b := g.Bounds()
	crop := g.SubImage(image.Rect(0, 0, b.Dx()*2/3, b.Dy()))
	if _, err := Scan(crop, Options{}); err == nil {
		t.Fatal("decoded a symbol with a missing third")
	}
}

func TestProbeSubImageOffset(t *testing.T) {
	c := enc(t, "subimage with non-zero origin", qr.M)
	g := c.Matrix.Image(6, 4)
	canvas := image.NewGray(image.Rect(0, 0, g.Bounds().Dx()+60, g.Bounds().Dy()+60))
	for i := range canvas.Pix {
		canvas.Pix[i] = 255
	}
	for y := 0; y < g.Bounds().Dy(); y++ {
		for x := 0; x < g.Bounds().Dx(); x++ {
			canvas.SetGray(x+30, y+30, g.GrayAt(x, y))
		}
	}
	sub := canvas.SubImage(image.Rect(20, 20, canvas.Bounds().Dx()-10, canvas.Bounds().Dy()-10))
	if ds, err := Scan(sub, Options{}); err != nil || ds[0].Result.Text != "subimage with non-zero origin" {
		t.Fatalf("%v", err)
	}
}
