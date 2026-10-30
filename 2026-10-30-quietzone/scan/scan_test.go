package scan

import (
	"math/rand"
	"strings"
	"testing"

	"quietzone/qr"
	"quietzone/sim"
)

func enc(t *testing.T, s string, e qr.ECC) *qr.Code {
	t.Helper()
	c, err := qr.EncodeText(s, qr.Options{ECC: e, Mask: -1})
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestCleanImageAllScalesAndVersions(t *testing.T) {
	for _, tc := range []struct {
		text  string
		scale int
	}{{"hi", 4}, {"https://example.com/quietzone", 6}, {strings.Repeat("v7+ ", 40), 5}, {strings.Repeat("big payload 0123 ", 90), 3}} {
		c := enc(t, tc.text, qr.M)
		img := c.Matrix.Image(tc.scale, 4)
		ds, err := Scan(img, Options{})
		if err != nil || len(ds) != 1 || ds[0].Result.Text != tc.text {
			t.Fatalf("v%d scale %d: %v", c.Version, tc.scale, err)
		}
	}
}

func TestRotationAndPerspective(t *testing.T) {
	c := enc(t, "rotate me — ünïcode ✓", qr.Q)
	base := c.Matrix.Image(8, 4)
	for _, p := range []sim.Pose{
		{Roll: 0}, {Roll: 17}, {Roll: 45}, {Roll: 90}, {Roll: 133}, {Roll: 180}, {Roll: -77},
		{Roll: 10, TiltX: 30}, {Roll: -20, TiltY: 35}, {Roll: 33, TiltX: 25, TiltY: -25, Margin: 0.2},
		{Mirror: true, Roll: 12},
	} {
		img := sim.Warp(base, p, 255)
		ds, err := Scan(img, Options{})
		if err != nil || ds[0].Result.Text != "rotate me — ünïcode ✓" {
			t.Fatalf("pose %+v: %v", p, err)
		}
	}
}

func TestNoiseBlurLighting(t *testing.T) {
	c := enc(t, "degraded capture 123456", qr.Q)
	rng := rand.New(rand.NewSource(3))
	img := sim.Warp(c.Matrix.Image(8, 4), sim.Pose{Roll: 11, TiltX: 15, Margin: 0.1}, 235)
	img = sim.Blur(img, 1.4)
	img = sim.Noise(img, 14, 0.004, rng)
	img = sim.Lighting(img, 0.5, 0.3, 40)
	ds, err := Scan(img, Options{})
	if err != nil || ds[0].Result.Text != "degraded capture 123456" {
		t.Fatalf("%v", err)
	}
}

func TestNothingToFind(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	blank := sim.Noise(sim.Warp(qr.NewMatrix(21).Image(4, 4), sim.Pose{}, 255), 30, 0.02, rng)
	if _, err := Scan(blank, Options{}); err != ErrNotFound {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}
