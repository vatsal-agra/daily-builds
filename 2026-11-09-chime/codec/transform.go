package codec

import "math"

// Block-switched lapped transform.
//
// Frame f covers original samples [(f-1)N, (f+1)N) (2N = 2048 window). A long
// frame is one 1024-coefficient MDCT; a short frame is eight 128-coefficient
// MDCTs whose 256-sample windows start at shortStart+128j inside the frame.
// Slopes of a long window adapt to the neighbours (start/stop windows) so that
// the Princen–Bradley condition holds across every frame boundary.

var (
	longSlope  = sineSlope(LongM)
	shortSlope = sineSlope(ShortM)
	mdctLong   = NewMDCT(LongM)
	mdctShort  = NewMDCT(ShortM)
)

// sineSlope returns the rising half of a sine window with n samples.
func sineSlope(n int) []float64 {
	w := make([]float64, n)
	for i := range w {
		w[i] = math.Sin(math.Pi * (float64(i) + 0.5) / float64(2*n))
	}
	return w
}

// NumFrames is the number of frames needed to cover n samples.
func NumFrames(n int) int { return (n+FrameN-1)/FrameN + 1 }

// longWindow builds the 2048-sample window for a long frame whose previous /
// next neighbours are short (or not).
func longWindow(prevShort, nextShort bool) []float64 {
	w := make([]float64, 2*FrameN)
	for i := 0; i < FrameN; i++ {
		if !prevShort {
			w[i] = longSlope[i]
		} else if i >= shortStart && i < shortStart+ShortM {
			w[i] = shortSlope[i-shortStart]
		} else if i >= shortStart+ShortM {
			w[i] = 1
		}
		j := 2*FrameN - 1 - i
		if !nextShort {
			w[j] = longSlope[i]
		} else if i >= shortStart && i < shortStart+ShortM {
			w[j] = shortSlope[i-shortStart]
		} else if i >= shortStart+ShortM {
			w[j] = 1
		}
	}
	return w
}

type windowSet struct{ w [2][2][]float64 }

var windows = func() *windowSet {
	ws := &windowSet{}
	for a := 0; a < 2; a++ {
		for b := 0; b < 2; b++ {
			ws.w[a][b] = longWindow(a == 1, b == 1)
		}
	}
	return ws
}()

func b2i(b bool) int {
	if b {
		return 1
	}
	return 0
}

func isShort(short []bool, f int) bool { return f >= 0 && f < len(short) && short[f] }

// frameSegment copies the 2048 samples of frame f (zero outside the signal).
func frameSegment(x []float64, f int, dst []float64) {
	start := (f - 1) * FrameN
	for i := range dst {
		j := start + i
		if j >= 0 && j < len(x) {
			dst[i] = x[j]
		} else {
			dst[i] = 0
		}
	}
}

// AnalyzeFrame returns the MDCT blocks (1×1024 or 8×128) of frame f.
func AnalyzeFrame(x []float64, f int, short []bool) [][]float64 {
	seg := make([]float64, 2*FrameN)
	frameSegment(x, f, seg)
	if !short[f] {
		w := windows.w[b2i(isShort(short, f-1))][b2i(isShort(short, f+1))]
		for i := range seg {
			seg[i] *= w[i]
		}
		out := make([]float64, LongM)
		mdctLong.Forward(seg, out)
		return [][]float64{out}
	}
	blocks := make([][]float64, NumShort)
	buf := make([]float64, 2*ShortM)
	for j := 0; j < NumShort; j++ {
		o := shortStart + j*ShortM
		for i := 0; i < ShortM; i++ {
			buf[i] = seg[o+i] * shortSlope[i]
			buf[2*ShortM-1-i] = seg[o+2*ShortM-1-i] * shortSlope[i]
		}
		blocks[j] = make([]float64, ShortM)
		mdctShort.Forward(buf, blocks[j])
	}
	return blocks
}

// SynthesizeFrame inverse-transforms blocks and overlap-adds into out, which is
// indexed like the original signal (samples outside [0,len(out)) are dropped).
func SynthesizeFrame(blocks [][]float64, f int, short []bool, out []float64) {
	seg := make([]float64, 2*FrameN)
	if !short[f] {
		tmp := make([]float64, 2*FrameN)
		mdctLong.Inverse(blocks[0], tmp)
		w := windows.w[b2i(isShort(short, f-1))][b2i(isShort(short, f+1))]
		for i := range seg {
			seg[i] = tmp[i] * w[i]
		}
	} else {
		tmp := make([]float64, 2*ShortM)
		for j := 0; j < NumShort; j++ {
			mdctShort.Inverse(blocks[j], tmp)
			o := shortStart + j*ShortM
			for i := 0; i < ShortM; i++ {
				seg[o+i] += tmp[i] * shortSlope[i]
				seg[o+2*ShortM-1-i] += tmp[2*ShortM-1-i] * shortSlope[i]
			}
		}
	}
	start := (f - 1) * FrameN
	for i, v := range seg {
		if j := start + i; j >= 0 && j < len(out) {
			out[j] += v
		}
	}
}

// DetectTransients marks frames that should use short blocks.
func DetectTransients(ch [][]float64) []bool {
	n := len(ch[0])
	nf := NumFrames(n)
	short := make([]bool, nf)
	const sub = ShortM
	nsub := (n + sub - 1) / sub
	attack := make([]bool, nsub)
	for _, x := range ch {
		// first-difference high-pass, per-sub-block energy
		e := make([]float64, nsub)
		for i := 1; i < n; i++ {
			d := x[i] - x[i-1]
			e[i/sub] += d * d
		}
		for i := range e {
			e[i] /= sub
		}
		for i := 1; i < nsub; i++ {
			lo := i - 6
			if lo < 0 {
				lo = 0
			}
			var avg float64
			for j := lo; j < i; j++ {
				avg += e[j]
			}
			avg /= float64(i - lo)
			if e[i] > 9*avg+2000 && e[i] > 1e4 {
				attack[i] = true
			}
		}
	}
	for f := 0; f < nf; f++ {
		a := (f-1)*FrameN + 512
		for s := a / sub; s < (a+1024)/sub; s++ {
			if s >= 0 && s < nsub && attack[s] {
				short[f] = true
			}
		}
	}
	return short
}
