// Package cm is a context-mixing compressor in the PAQ/lpaq lineage: hashed context
// models feed adaptive probability counters, a gated logistic mixer combines their
// opinions, and an APM stage refines the result before a binary arithmetic coder.
package cm

// All tables are derived with plain IEEE-754 +,-,*,/ (each product explicitly rounded)
// so that compressor and decompressor agree bit-for-bit on every platform.

var squashTab [4096]int32  // index d+2048, d in [-2048,2047] (stretch domain, 8 fractional bits) -> P(1) in 16 bits
var stretchTab [4096]int32 // index p16>>4 -> d

func expTaylor(x float64) float64 {
	sum, term := 1.0, 1.0
	for k := 1; k < 30; k++ {
		term = float64(term*x) / float64(k)
		sum = float64(sum + term)
	}
	return sum
}

func init() {
	e := expTaylor(1.0 / 256) // e^(1/256)
	// pw[k] = e^(k/256), k = 0..2048
	pw := make([]float64, 2049)
	pw[0] = 1
	for k := 1; k < len(pw); k++ {
		pw[k] = float64(pw[k-1] * e)
	}
	for i := 0; i < 4096; i++ {
		d := i - 2048
		var ex float64 // e^(-d/256)
		if d >= 0 {
			ex = 1 / pw[d]
		} else {
			ex = pw[-d]
		}
		p := 65536 / float64(1+ex)
		v := int32(p + 0.5)
		if v < 16 {
			v = 16
		}
		if v > 65535-16 {
			v = 65535 - 16
		}
		squashTab[i] = v
	}
	pi := int32(0)
	for d := int32(-2047); d <= 2047; d++ {
		v := squashTab[d+2048] >> 4
		for i := pi; i <= v; i++ {
			stretchTab[i] = d
		}
		pi = v + 1
	}
	for i := pi; i < 4096; i++ {
		stretchTab[i] = 2047
	}
}

func squash(d int32) int32 {
	if d > 2047 {
		d = 2047
	}
	if d < -2047 {
		d = -2047
	}
	return squashTab[d+2048]
}

func stretch(p16 int32) int32 { return stretchTab[p16>>4] }
