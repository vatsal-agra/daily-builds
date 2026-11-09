package codec

import (
	"errors"
	"math"
)

// The bitstream syntax. Everything here runs identically in encode and decode
// mode (see RC): in encode mode the passed-in values are written, in decode
// mode they are overwritten with what was read.

const (
	SFMin   = -8
	SFMax   = 90
	NFMax   = 22
	maxQ    = 1 << 22
	nCtx    = 11
	magUn   = 14
	sfUnary = 20
)

// Step returns the quantiser step for scalefactor s.
func Step(s int) float64 { return math.Exp2(float64(s) / 4) }

// NoiseRMS returns the noise-filling rms for level n (1..NFMax).
func NoiseRMS(n int) float64 { return 0.25 * math.Exp2(float64(n-1)) }

// BlockQ is one quantised block (a long frame has one, a short frame eight).
type BlockQ struct {
	Q  []int32
	SF []int
	NZ []bool
	NF []int
}

func newBlockQ(l *Layout) BlockQ {
	nb := l.NB()
	return BlockQ{Q: make([]int32, l.M), SF: make([]int, nb), NZ: make([]bool, nb), NF: make([]int, nb)}
}

// FrameQ is one quantised frame.
type FrameQ struct {
	MS     bool
	Blocks [2][]BlockQ
}

type deltaModels struct {
	zero Prob
	sign Prob
	mag  [sfUnary]Prob
}

func newDelta() deltaModels {
	d := deltaModels{zero: NewProb(), sign: NewProb()}
	for i := range d.mag {
		d.mag[i] = NewProb()
	}
	return d
}

// Syntax holds the adaptive models and inter-block context of one stream.
type Syntax struct {
	rc        *RC
	rate, nch int
	nfill     bool

	shortP [2]Prob
	msP    [2]Prob
	bandNZ [2][2][2][2]Prob  // [ch][short][prevBand][prevBlock]
	sfD    [2][2]deltaModels // [ch][first]
	nfNZ   [2][2]Prob        // [ch][prev band had fill]
	nfD    [2]deltaModels
	cZero  [2][2][nCtx]Prob
	cMag   [2][2][nCtx][magUn]Prob

	prevMag [2][]int32
	prevM   [2]int
	lastSF  [2]int
	lastNF  [2]int
	prevMS  int
	prevSh  int

	// statistics (encode mode with Track)
	BandBits  [2][]float64 // [short][band] coefficient+sf+flag bits
	BlockCnt  [2]int
	SFBits    float64
	FlagBits  float64
	CoefBits  float64
	NoiseBits float64
}

func NewSyntax(rc *RC, rate, nch int, nfill bool) *Syntax {
	s := &Syntax{rc: rc, rate: rate, nch: nch, nfill: nfill}
	for i := range s.shortP {
		s.shortP[i], s.msP[i] = NewProb(), NewProb()
	}
	for c := 0; c < 2; c++ {
		for a := 0; a < 2; a++ {
			s.sfD[c][a] = newDelta()
			s.nfNZ[c][a] = NewProb()
			for sh := 0; sh < 2; sh++ {
				for x := 0; x < 2; x++ {
					for y := 0; y < 2; y++ {
						s.bandNZ[c][sh][x][y] = NewProb()
					}
				}
				for k := 0; k < nCtx; k++ {
					s.cZero[c][sh][k] = NewProb()
					for m := 0; m < magUn; m++ {
						s.cMag[c][sh][k][m] = NewProb()
					}
				}
			}
		}
		s.nfD[c] = newDelta()
		s.lastSF[c] = 40
		s.lastNF[c] = 8
	}
	s.BandBits[0] = make([]float64, LayoutFor(LongM, rate).NB())
	s.BandBits[1] = make([]float64, LayoutFor(ShortM, rate).NB())
	return s
}

// Flags codes the per-frame block-type flags (short/long).
func (s *Syntax) Flags(short []bool) {
	prev := 0
	for f := range short {
		v := s.rc.Bit(&s.shortP[prev], b2i(short[f]))
		short[f] = v == 1
		prev = v
	}
}

func (s *Syntax) signed(m *deltaModels, v int) int {
	rc := s.rc
	if rc.Bit(&m.zero, b2i(v != 0)) == 0 {
		return 0
	}
	neg := rc.Bit(&m.sign, b2i(v < 0))
	mag := v
	if mag < 0 {
		mag = -mag
	}
	n := 1
	for n <= sfUnary {
		if rc.Bit(&m.mag[n-1], b2i(mag > n)) == 0 {
			break
		}
		n++
	}
	if n > sfUnary {
		n = sfUnary + 1 + int(rc.ExpGolomb(uint32(mag-sfUnary-1)))
	}
	if n > 4096 {
		n = 4096
		if rc.Decoding() && rc.Err == nil {
			rc.Err = errors.New("corrupt delta")
		}
	}
	if neg == 1 {
		return -n
	}
	return n
}

func ctxOf(t int32) int {
	switch {
	case t < 5:
		return int(t)
	case t < 7:
		return 5
	case t < 9:
		return 6
	case t < 12:
		return 7
	case t < 16:
		return 8
	case t < 23:
		return 9
	}
	return 10
}

// mapMag resamples a previous block's magnitudes to resolution m.
func mapMag(prev []int32, m int) []int32 {
	out := make([]int32, m)
	pm := len(prev)
	switch {
	case pm == 0:
	case pm == m:
		copy(out, prev)
	case pm < m: // short → long
		r := m / pm
		for k := range out {
			out[k] = prev[k/r]
		}
	default: // long → short: max over the group
		r := pm / m
		for k := range out {
			var mx int32
			for j := 0; j < r; j++ {
				if v := prev[k*r+j]; v > mx {
					mx = v
				}
			}
			out[k] = mx
		}
	}
	return out
}

// Block codes one quantised block of channel ch.
func (s *Syntax) Block(ch int, b *BlockQ, short bool) {
	rc := s.rc
	sh := b2i(short)
	lay := LayoutFor(len(b.Q), s.rate)
	pm := mapMag(s.prevMag[ch], lay.M)
	prevBand := 0
	ref := -1000
	prevNF := 0
	curGroup, groupLevel := -1, 0
	s.BlockCnt[sh]++
	for bd := 0; bd < lay.NB(); bd++ {
		lo, hi := lay.Edges[bd], lay.Edges[bd+1]
		c0 := rc.Cost
		pb := 0
		for k := lo; k < hi; k++ {
			if pm[k] > 0 {
				pb = 1
				break
			}
		}
		nz := rc.Bit(&s.bandNZ[ch][sh][prevBand][pb], b2i(b.NZ[bd])) == 1
		b.NZ[bd] = nz
		s.FlagBits += rc.Cost - c0
		prevBand = b2i(nz)
		if !nz {
			if s.nfill {
				g := bd / lay.NFGroup()
				if g != curGroup { // first zero band of a noise-fill group carries the level
					curGroup = g
					cn := rc.Cost
					on := rc.Bit(&s.nfNZ[ch][prevNF], b2i(b.NF[bd] > 0)) == 1
					groupLevel = 0
					if on {
						d := s.signed(&s.nfD[ch], b.NF[bd]-s.lastNF[ch])
						v := s.lastNF[ch] + d
						if v < 1 || v > NFMax {
							if rc.Decoding() && rc.Err == nil {
								rc.Err = errors.New("noise level out of range")
							}
							v = 1
						}
						groupLevel = v
						s.lastNF[ch] = v
					}
					prevNF = b2i(on)
					s.NoiseBits += rc.Cost - cn
				}
				b.NF[bd] = groupLevel
			} else {
				b.NF[bd] = 0
			}
			for k := lo; k < hi; k++ {
				b.Q[k] = 0
			}
			s.BandBits[sh][bd] += rc.Cost - c0
			continue
		}
		prevNF = 0
		// scalefactor
		c1 := rc.Cost
		r := ref
		first := 0
		if r == -1000 {
			r = s.lastSF[ch]
			first = 1
		}
		d := s.signed(&s.sfD[ch][first], b.SF[bd]-r)
		v := r + d
		if v < SFMin || v > SFMax {
			if rc.Decoding() && rc.Err == nil {
				rc.Err = errors.New("scalefactor out of range")
			}
			v = SFMin
		}
		b.SF[bd] = v
		ref = v
		s.lastSF[ch] = v
		s.SFBits += rc.Cost - c1
		// coefficients
		c2 := rc.Cost
		for k := lo; k < hi; k++ {
			var a1, a2 int32
			if k > 0 {
				a1 = abs32(b.Q[k-1])
			}
			if k > 1 {
				a2 = abs32(b.Q[k-2])
			}
			pl, pr := pm[k], pm[k]
			if k > 0 {
				pl = pm[k-1]
			}
			if k+1 < lay.M {
				pr = pm[k+1]
			}
			t := 2*a1 + a2 + (pl+2*pm[k]+pr+1)/2
			cx := ctxOf(t)
			q := b.Q[k]
			if rc.Bit(&s.cZero[ch][sh][cx], b2i(q != 0)) == 0 {
				b.Q[k] = 0
				continue
			}
			neg := rc.Bypass(b2i(q < 0))
			mag := q
			if mag < 0 {
				mag = -mag
			}
			n := int32(1)
			for n <= magUn {
				if rc.Bit(&s.cMag[ch][sh][cx][n-1], b2i(mag > n)) == 0 {
					break
				}
				n++
			}
			if n > magUn {
				n = magUn + 1 + int32(rc.ExpGolomb(uint32(mag-magUn-1)))
				if n > maxQ {
					n = maxQ
					if rc.Decoding() && rc.Err == nil {
						rc.Err = errors.New("coefficient out of range")
					}
				}
			}
			if neg == 1 {
				n = -n
			}
			b.Q[k] = n
		}
		s.CoefBits += rc.Cost - c2
		s.BandBits[sh][bd] += rc.Cost - c0
	}
	mag := make([]int32, lay.M)
	for k, q := range b.Q {
		mag[k] = abs32(q)
	}
	s.prevMag[ch] = mag
	s.prevM[ch] = lay.M
}

func abs32(v int32) int32 {
	if v < 0 {
		return -v
	}
	return v
}

// Frame codes a whole frame; fr must be pre-sized for decoding (see AllocFrame).
func (s *Syntax) Frame(fr *FrameQ, short bool) {
	if s.nch == 2 {
		fr.MS = s.rc.Bit(&s.msP[s.prevMS], b2i(fr.MS)) == 1
		s.prevMS = b2i(fr.MS)
	}
	for c := 0; c < s.nch; c++ {
		for i := range fr.Blocks[c] {
			s.Block(c, &fr.Blocks[c][i], short)
		}
	}
}

// AllocFrame allocates an empty frame for decoding.
func AllocFrame(nch, rate int, short bool) *FrameQ {
	fr := &FrameQ{}
	for c := 0; c < nch; c++ {
		if short {
			l := LayoutFor(ShortM, rate)
			fr.Blocks[c] = make([]BlockQ, NumShort)
			for i := range fr.Blocks[c] {
				fr.Blocks[c][i] = newBlockQ(l)
			}
		} else {
			fr.Blocks[c] = []BlockQ{newBlockQ(LayoutFor(LongM, rate))}
		}
	}
	return fr
}
