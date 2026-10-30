// Package qr implements ISO/IEC 18004 QR codes from scratch: GF(256) and
// Reed-Solomon coding, the encoder, and a matrix-level decoder.
package qr

// GF(2^8) with the QR primitive polynomial x^8+x^4+x^3+x^2+1 (0x11D).
var (
	gfExp [512]byte
	gfLog [256]int
)

func init() {
	x := 1
	for i := 0; i < 255; i++ {
		gfExp[i] = byte(x)
		gfLog[x] = i
		x <<= 1
		if x&0x100 != 0 {
			x ^= 0x11D
		}
	}
	for i := 255; i < 512; i++ {
		gfExp[i] = gfExp[i-255]
	}
}

// GFMul multiplies in GF(256).
func GFMul(a, b byte) byte {
	if a == 0 || b == 0 {
		return 0
	}
	return gfExp[gfLog[a]+gfLog[b]]
}

// GFDiv divides a by b; it panics on b == 0.
func GFDiv(a, b byte) byte {
	if b == 0 {
		panic("qr: GF division by zero")
	}
	if a == 0 {
		return 0
	}
	return gfExp[gfLog[a]+255-gfLog[b]]
}

// GFInv returns the multiplicative inverse of a (a != 0).
func GFInv(a byte) byte {
	if a == 0 {
		panic("qr: GF inverse of zero")
	}
	return gfExp[255-gfLog[a]]
}

// GFPow returns alpha^n for any integer n.
func GFPow(n int) byte {
	n %= 255
	if n < 0 {
		n += 255
	}
	return gfExp[n]
}

// polyEval evaluates p (highest-degree coefficient first) at x using Horner.
func polyEval(p []byte, x byte) byte {
	var y byte
	for _, c := range p {
		y = GFMul(y, x) ^ c
	}
	return y
}

// polyMul multiplies two polynomials (highest-degree first).
func polyMul(a, b []byte) []byte {
	out := make([]byte, len(a)+len(b)-1)
	for i, x := range a {
		if x == 0 {
			continue
		}
		for j, y := range b {
			out[i+j] ^= GFMul(x, y)
		}
	}
	return out
}

// generatorPoly returns prod_{i=0}^{degree-1} (x - alpha^i), highest first.
func generatorPoly(degree int) []byte {
	g := []byte{1}
	for i := 0; i < degree; i++ {
		g = polyMul(g, []byte{1, GFPow(i)})
	}
	return g
}
