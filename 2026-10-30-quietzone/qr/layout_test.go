package qr

import "testing"

func TestCapacitiesKnown(t *testing.T) {
	cases := []struct {
		v    int
		want [4]int // L M Q H data codewords
	}{
		{1, [4]int{19, 16, 13, 9}}, {2, [4]int{34, 28, 22, 16}}, {5, [4]int{108, 86, 62, 46}},
		{7, [4]int{156, 124, 88, 66}}, {10, [4]int{274, 216, 154, 122}},
		{25, [4]int{1276, 1000, 718, 538}}, {32, [4]int{1955, 1541, 1115, 845}},
		{40, [4]int{2956, 2334, 1666, 1276}},
	}
	for _, c := range cases {
		for e := L; e <= H; e++ {
			if got := DataCodewords(c.v, e); got != c.want[e] {
				t.Errorf("v%d-%v: %d want %d", c.v, e, got, c.want[e])
			}
		}
	}
}

func TestTableConsistency(t *testing.T) {
	for v := 1; v <= 40; v++ {
		l := NewLayout(v)
		order := l.DataOrder()
		if len(order) != rawModules(v) {
			t.Fatalf("v%d: %d data modules, expected %d", v, len(order), rawModules(v))
		}
		seen := map[[2]int]bool{}
		for _, p := range order {
			if seen[p] || l.IsFunction(p[0], p[1]) {
				t.Fatalf("v%d: bad/duplicate position %v", v, p)
			}
			seen[p] = true
		}
		for e := L; e <= H; e++ {
			lens, ecc := blockLayout(v, e)
			sum := 0
			for _, d := range lens {
				sum += d + ecc
			}
			if sum != RawCodewords(v) {
				t.Fatalf("v%d-%v block layout sums to %d", v, e, sum)
			}
			// monotone capacity in level
			if e > L && DataCodewords(v, e) >= DataCodewords(v, e-1) {
				t.Fatalf("v%d: capacity not decreasing at %v", v, e)
			}
		}
		if v > 1 && DataCodewords(v, M) <= DataCodewords(v-1, M) {
			t.Fatalf("capacity not increasing at v%d", v)
		}
	}
}

func TestFormatAndVersionCodes(t *testing.T) {
	// ISO 18004 Annex C: level M, mask 5 => 100000011001110.
	if got := formatCode(M, 5); got != 0b100000011001110 {
		t.Fatalf("format M/5 = %015b", got)
	}
	// Annex D: version 7 => 000111110010010100.
	if got := versionCode(7); got != 0b000111110010010100 {
		t.Fatalf("version 7 = %018b", got)
	}
	// minimum distance of the BCH(15,5) code is 7
	for a := 0; a < 32; a++ {
		for b := a + 1; b < 32; b++ {
			if d := popcount(formatCode(ECC(a>>3), a&7) ^ formatCode(ECC(b>>3), b&7)); d < 7 && a != b {
				// levels indexed L..H map to distinct bit pairs, so every pair must be >= 8 apart
				t.Fatalf("format distance %d between %d,%d", d, a, b)
			}
		}
	}
}

func TestAlignPositions(t *testing.T) {
	want := map[int][]int{2: {6, 18}, 7: {6, 22, 38}, 14: {6, 26, 46, 66}, 32: {6, 34, 60, 86, 112, 138}, 40: {6, 30, 58, 86, 114, 142, 170}}
	for v, w := range want {
		got := alignPositions(v)
		if len(got) != len(w) {
			t.Fatalf("v%d: %v want %v", v, got, w)
		}
		for i := range w {
			if got[i] != w[i] {
				t.Fatalf("v%d: %v want %v", v, got, w)
			}
		}
	}
}
