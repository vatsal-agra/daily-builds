package ttf_test

import (
	"math/rand"
	"os"
	"path/filepath"
	"testing"
	"time"

	"glyph/ttf"
)

// exercise drives every public entry point of a parsed font.
func exercise(f *ttf.Font) {
	f.Name(1)
	f.Verify()
	f.CmapInfo()
	f.HasKerning()
	rs := f.Runes()
	n := f.NumGlyphs
	if n > 400 {
		n = 400
	}
	for g := 0; g < n; g++ {
		f.Glyph(uint16(g))
		f.Advance(uint16(g))
		f.Kerning(uint16(g), uint16((g*7)%n))
	}
	for i, r := range rs {
		if i > 300 {
			break
		}
		f.Index(r)
	}
	f.Index(0x1F600)
	f.Index(-1)
}

func TestMalformedNeverPanicsOrHangs(t *testing.T) {
	files, _ := filepath.Glob("../testdata/fonts/*.ttf")
	if len(files) == 0 {
		t.Skip("no fonts")
	}
	rng := rand.New(rand.NewSource(1))
	deadline := time.Now().Add(20 * time.Second)
	cases := 0
	for _, p := range files {
		orig, _ := os.ReadFile(p)
		for i := 0; i < 150 && time.Now().Before(deadline); i++ {
			b := append([]byte(nil), orig...)
			switch i % 3 {
			case 0: // truncate
				b = b[:rng.Intn(len(b))]
			case 1: // flip bytes anywhere
				for k := 0; k < 1+rng.Intn(20); k++ {
					b[rng.Intn(len(b))] ^= byte(1 << rng.Intn(8))
				}
			default: // smash bytes in the first 2 KB (directory + small tables)
				for k := 0; k < 1+rng.Intn(8); k++ {
					b[rng.Intn(min(2048, len(b)))] = byte(rng.Intn(256))
				}
			}
			done := make(chan struct{})
			go func() {
				defer close(done)
				defer func() {
					if r := recover(); r != nil {
						t.Errorf("%s case %d: panic %v", filepath.Base(p), i, r)
					}
				}()
				if f, err := ttf.Parse(b); err == nil {
					exercise(f)
				}
			}()
			select {
			case <-done:
			case <-time.After(5 * time.Second):
				t.Fatalf("%s case %d: hang", filepath.Base(p), i)
			}
			cases++
		}
	}
	t.Logf("%d mutated fonts survived", cases)
}
