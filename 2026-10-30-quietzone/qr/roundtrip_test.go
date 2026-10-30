package qr

import (
	"bytes"
	"strings"
	"testing"
)

func mustEncode(t *testing.T, s string, e ECC) *Code {
	t.Helper()
	opt := DefaultOptions()
	opt.ECC = e
	opt.BoostECC = false
	c, err := EncodeText(s, opt)
	if err != nil {
		t.Fatalf("encode %q: %v", s, err)
	}
	return c
}

func TestRoundTripAllVersionsAndLevels(t *testing.T) {
	for v := 1; v <= 40; v++ {
		for e := L; e <= H; e++ {
			n := DataCodewords(v, e) - 4
			if n < 1 {
				n = 1
			}
			payload := bytes.Repeat([]byte("quietzone-"), n/10+1)[:n]
			c, err := EncodeSegments([]Segment{{Mode: ModeByte, Chars: len(payload), Data: payload}}, v, Options{ECC: e, Mask: -1})
			if err != nil {
				// payload may overflow for tiny v; shrink
				payload = payload[:max(1, len(payload)-6)]
				c, err = EncodeSegments([]Segment{{Mode: ModeByte, Chars: len(payload), Data: payload}}, v, Options{ECC: e, Mask: -1})
				if err != nil {
					t.Fatalf("v%d-%v: %v", v, e, err)
				}
			}
			r, err := Decode(c.Matrix)
			if err != nil {
				t.Fatalf("v%d-%v: %v", v, e, err)
			}
			if r.Version != v || r.ECC != e || r.Mask != c.Mask || !bytes.Equal(r.Bytes, payload) || r.ByteErrors != 0 {
				t.Fatalf("v%d-%v: mismatch %+v", v, e, r)
			}
		}
	}
}

func TestEveryMaskDecodes(t *testing.T) {
	for mk := 0; mk < 8; mk++ {
		opt := Options{ECC: Q, Mask: mk}
		c, _ := EncodeText("MASK TEST 12345 mixed Case", opt)
		r, err := Decode(c.Matrix)
		if err != nil || r.Mask != mk || r.Text != "MASK TEST 12345 mixed Case" {
			t.Fatalf("mask %d: %v %+v", mk, err, r)
		}
	}
}

func TestModesAndUnicode(t *testing.T) {
	for _, s := range []string{"0", "00", "000", "0001234567890", "A", "AB", "ABC", "HELLO WORLD $%*+-./:", "mixed ABC 123 def 4567890123456789",
		"héllo wörld ✓ 日本語 🎉", strings.Repeat("a", 500), "line1\nline2\ttab\x00nul"} {
		c := mustEncode(t, s, M)
		r, err := Decode(c.Matrix)
		if err != nil || r.Text != s {
			t.Fatalf("%q -> %q (%v)", s, r.Text, err)
		}
	}
	c := mustEncode(t, "日本", L)
	if c.Segments[0].Mode != ModeECI {
		t.Fatal("expected ECI for non-ASCII")
	}
	c2, _ := EncodeText("日本", Options{ECC: L, Mask: -1, NoECI: true})
	if c2.Segments[0].Mode == ModeECI {
		t.Fatal("NoECI ignored")
	}
}

func TestFormatInfoDamage(t *testing.T) {
	c := mustEncode(t, "format damage", Q)
	m := c.Matrix.Clone()
	// flip 3 bits of the first format copy: still BCH-correctable
	for _, i := range []int{0, 5, 11} {
		x, y := formatPos1(i)
		m.Set(x, y, !m.Get(x, y))
		x, y = formatPos2(i+1, m.N)
		m.Set(x, y, !m.Get(x, y))
	}
	r, err := Decode(m)
	if err != nil || r.Text != "format damage" || r.FormatDistance != 3 || r.FormatBruteForced {
		t.Fatalf("%v %+v", err, r)
	}
	// destroy BOTH copies entirely: brute force over the 32 (level,mask) pairs
	for i := 0; i < 15; i++ {
		x, y := formatPos1(i)
		m.Set(x, y, i%2 == 0)
		x, y = formatPos2(i, m.N)
		m.Set(x, y, i%3 == 0)
	}
	r, err = Decode(m)
	if err != nil || r.Text != "format damage" || !r.FormatBruteForced {
		t.Fatalf("brute force: %v %+v", err, r)
	}
}

func TestMirroredMatrixIsRecovered(t *testing.T) {
	c := mustEncode(t, "mirror me", M)
	tr := NewMatrix(c.Matrix.N)
	for y := 0; y < tr.N; y++ {
		for x := 0; x < tr.N; x++ {
			tr.Set(x, y, c.Matrix.Get(y, x))
		}
	}
	r, err := Decode(tr)
	if err != nil || !r.Transposed || r.Text != "mirror me" {
		t.Fatalf("%v %+v", err, r)
	}
	if _, err := DecodeWith(tr, DecodeOptions{NoTranspose: true}); err == nil {
		t.Fatal("NoTranspose ignored")
	}
}

func TestDataDamageWithinBudget(t *testing.T) {
	r0 := newRand(5)
	for trial := 0; trial < 60; trial++ {
		e := ECC(r0.Intn(4))
		c := mustEncode(t, strings.Repeat("resilient payload ", 6), e)
		l := NewLayout(c.Version)
		order := l.DataOrder()
		lens, eccLen := blockLayout(c.Version, e)
		// damage up to the budget in every block: flip whole codewords
		m := c.Matrix.Clone()
		perBlock := map[int]int{}
		for k := 0; k < 200; k++ {
			cwi := r0.Intn(len(c.Codewords))
			// find which block this codeword belongs to
			blk := blockOf(cwi, lens, eccLen)
			if perBlock[blk] >= eccLen/2 {
				continue
			}
			perBlock[blk]++
			for b := 0; b < 8; b++ {
				p := order[cwi*8+b]
				m.Set(p[0], p[1], !m.Get(p[0], p[1]))
			}
		}
		res, err := Decode(m)
		if err != nil || res.Text != strings.Repeat("resilient payload ", 6) {
			t.Fatalf("trial %d: %v", trial, err)
		}
	}
}

func blockOf(cw int, lens []int, eccLen int) int {
	nb := len(lens)
	maxData := lens[nb-1]
	pos := 0
	dataPos := map[int]int{}
	for i := 0; i < maxData; i++ {
		for b := 0; b < nb; b++ {
			if i < lens[b] {
				dataPos[pos] = b
				pos++
			}
		}
	}
	if b, ok := dataPos[cw]; ok {
		return b
	}
	return (cw - pos) % nb
}

func TestTextRenderRoundTrip(t *testing.T) {
	c := mustEncode(t, "text render", M)
	m, err := ParseText(c.Matrix.Text(4, false))
	if err != nil {
		t.Fatal(err)
	}
	r, err := Decode(m)
	if err != nil || r.Text != "text render" {
		t.Fatal(err)
	}
	if _, err := ParseText("   \n  "); err == nil {
		t.Fatal("empty accepted")
	}
}

func TestDecodeRejectsGarbage(t *testing.T) {
	if _, err := Decode(NewMatrix(20)); err == nil {
		t.Fatal("bad size accepted")
	}
	r := newRand(9)
	m := NewMatrix(25)
	for y := 0; y < 25; y++ {
		for x := 0; x < 25; x++ {
			m.Set(x, y, r.Intn(2) == 0)
		}
	}
	if _, err := Decode(m); err == nil {
		t.Fatal("noise decoded")
	}
}
