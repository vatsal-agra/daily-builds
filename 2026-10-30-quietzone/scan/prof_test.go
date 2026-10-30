package scan

import (
	"fmt"
	"image"
	"math/rand"
	"testing"
	"time"
)

func TestProf(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	g := image.NewGray(image.Rect(0, 0, 3000, 2000))
	for i := range g.Pix {
		g.Pix[i] = uint8(rng.Intn(256))
	}
	t0 := time.Now()
	gg := FromImage(g)
	fmt.Println("fromimage", time.Since(t0))
	for _, st := range Strategies()[:7] {
		t0 = time.Now()
		b := gg.Binarize(st)
		t1 := time.Now()
		fs := FindFinders(b)
		t2 := time.Now()
		for i := range fs {
			fs[i].Module = CoreModule(b, fs[i].C, fs[i].Module)
		}
		t3 := time.Now()
		trs := rankTriples(fs)
		n := 0
		for _, tr := range trs {
			if _, err := decodeTriple(b, fs[tr.a], fs[tr.b], fs[tr.c]); err == nil {
				n++
			}
		}
		fmt.Println(st.Name, "bin", t1.Sub(t0), "find", t2.Sub(t1), len(fs), "core", t3.Sub(t2), "triples", len(trs), time.Since(t3))
	}
}
