package cm

const (
	nCtx    = 8 // hashed context models
	nInputs = nCtx*2 + 2 + 1
	apmN    = 33
)

// counter: high 22 bits probability, low 10 bits observation count (adaptive learning rate).
var recip [1024]int64

func init() {
	for n := range recip {
		recip[n] = int64(65536 * 2 / (2*n + 3)) // 1/(n+1.5)
	}
}

func counterP16(e uint32) int32 { return int32(e >> 16) }

func counterUpdate(e *uint32, y int, limit uint32) {
	p := int64(*e >> 10)
	n := *e & 1023
	target := int64(y) << 22
	p += (target - p) * recip[n] >> 16
	if p < 0 {
		p = 0
	}
	if p > 1<<22-1 {
		p = 1<<22 - 1
	}
	if n < limit {
		n++
	}
	*e = uint32(p)<<10 | n
}

type mixer struct {
	w   []int32
	n   int
	sel int
	pr  int32 // last output probability (16 bit)
	dot int32
}

func newMixer(sets int) *mixer {
	m := &mixer{w: make([]int32, sets*nInputs), n: nInputs}
	for i := range m.w {
		m.w[i] = 1 << 14
	}
	return m
}

func (m *mixer) mix(in []int32, sel int) int32 {
	m.sel = sel * m.n
	w := m.w[m.sel : m.sel+m.n]
	var sum int64
	for i, x := range in {
		sum += int64(x) * int64(w[i])
	}
	d := int32(sum >> 16)
	if d > 2047 {
		d = 2047
	}
	if d < -2047 {
		d = -2047
	}
	m.dot = d
	m.pr = squash(d)
	return d
}

func (m *mixer) update(in []int32, y int, rate int32) {
	err := (int32(y<<16) - m.pr) >> 4 * rate
	w := m.w[m.sel : m.sel+m.n]
	for i, x := range in {
		w[i] += (x*err + 0x2000) >> 14
	}
}

// apm refines a probability given a small context, interpolating between 33 buckets.
type apm struct {
	t   []int32
	idx int
}

func newAPM(n int) *apm {
	a := &apm{t: make([]int32, n*apmN)}
	for c := 0; c < n; c++ {
		for j := 0; j < apmN; j++ {
			a.t[c*apmN+j] = squash(int32((j - 16) * 128))
		}
	}
	return a
}

func (a *apm) refine(p16 int32, cx int) int32 {
	s := stretch(p16) + 2048
	lo, w := int(s>>7), s&127
	a.idx = cx*apmN + lo
	if w >= 64 {
		a.idx++
	}
	i := cx*apmN + lo
	return (a.t[i]*(128-w) + a.t[i+1]*w) >> 7
}

func (a *apm) update(y int, rate uint) {
	target := int32(y) * 65535
	a.t[a.idx] += (target - a.t[a.idx]) >> rate
}

// Model predicts one bit at a time. Call P() for P(next bit = 1), then Update(bit).
type Model struct {
	tbits  uint
	tab    [nCtx][]uint32
	limits [nCtx]uint32
	hash   [nCtx]uint32 // per-byte context hashes
	idx    [nCtx]int    // slot used for the current bit
	in     [nInputs]int32

	c0     uint32 // partial byte with leading 1
	c4, c8 uint32 // previous bytes
	bitPos uint
	word   uint32

	buf      []byte // history for the match model
	mtab     []int32
	mptr     int
	mlen     int
	mbyte    int // predicted byte, or -1 once the prediction failed this byte
	mcnt     [64 * 2]uint32
	mIdx     int
	mixers   [3]*mixer
	apm1     *apm
	apm2     *apm
	pr       int32
	prMix    int32
	mixerOut int32
}

// NewModel sizes hash tables for an input of about n bytes.
func NewModel(n int) *Model {
	m := &Model{}
	m.tbits = 16
	for m.tbits < 22 && (1<<m.tbits) < n*4 {
		m.tbits++
	}
	for i := range m.tab {
		m.tab[i] = make([]uint32, 1<<m.tbits)
		for j := range m.tab[i] {
			m.tab[i][j] = 1 << 31 // p = 0.5, n = 0
		}
		m.limits[i] = 255
	}
	m.limits[3], m.limits[4], m.limits[5] = 30, 16, 16
	m.limits[6], m.limits[7] = 127, 127
	for i := range m.mcnt {
		m.mcnt[i] = 1 << 31
	}
	mb := uint(16)
	for mb < 22 && (1<<mb) < n {
		mb++
	}
	m.mtab = make([]int32, 1<<mb)
	m.buf = make([]byte, 0, n)
	m.mixers[0] = newMixer(256)
	m.mixers[1] = newMixer(256)
	m.mixers[2] = newMixer(64 * 8)
	m.apm1 = newAPM(256)
	m.apm2 = newAPM(1 << 16)
	m.c0 = 1
	m.mbyte = -1
	m.byteUpdate()
	m.predict()
	return m
}

func hash32(a, b uint32) uint32 {
	h := a*0x9E3779B1 ^ b*0x85EBCA6B
	h ^= h >> 15
	h *= 0xC2B2AE35
	return h ^ h>>13
}

// byteUpdate recomputes context hashes at a byte boundary.
func (m *Model) byteUpdate() {
	c4, c8 := m.c4, m.c8
	m.hash[0] = 0
	m.hash[1] = hash32(1, c4&0xff)
	m.hash[2] = hash32(2, c4&0xffff)
	m.hash[3] = hash32(3, c4&0xffffff)
	m.hash[4] = hash32(4, c4)
	m.hash[5] = hash32(5, hash32(c4, c8&0xffff))
	m.hash[6] = hash32(6, m.word<<8|c4&0xff)
	m.hash[7] = hash32(7, c4&0xff00ff00)

	// match model: extend or re-find the longest recent repeat of the last bytes
	n := len(m.buf)
	if m.mlen > 0 && m.mptr < n && m.buf[m.mptr] == m.buf[n-1] {
		m.mlen++
		m.mptr++
	} else {
		m.mlen = 0
	}
	const minLen = 5
	if n >= minLen {
		h := hash32(c4, uint32(m.buf[n-minLen])) >> (32 - uint(log2(len(m.mtab))))
		if m.mlen == 0 {
			cand := int(m.mtab[h])
			if cand > 0 {
				l := 0
				for l < 32 && cand-1-l >= 0 && m.buf[cand-1-l] == m.buf[n-1-l] {
					l++
				}
				if l >= minLen {
					m.mlen, m.mptr = l, cand
				}
			}
		}
		m.mtab[h] = int32(n)
	}
	m.mbyte = -1
	if m.mlen > 0 && m.mptr < n {
		m.mbyte = int(m.buf[m.mptr])
	} else {
		m.mlen = 0
	}
}

func log2(n int) int {
	l := 0
	for 1<<uint(l+1) <= n {
		l++
	}
	return l
}

func (m *Model) predict() {
	shift := 32 - m.tbits
	k := 0
	for i := 0; i < nCtx; i++ {
		ix := int((m.hash[i] + m.c0*0x9E3779B1) * 0x85EBCA6B >> shift)
		m.idx[i] = ix
		e := m.tab[i][ix]
		p := counterP16(e)
		m.in[k] = stretch(p)
		m.in[k+1] = (p - 32768) >> 4
		k += 2
	}
	// match model inputs
	m.mIdx = -1
	m.in[k], m.in[k+1] = 0, 0
	lenBucket := 0
	if m.mbyte >= 0 && uint32(m.mbyte|256)>>(8-m.bitPos) == m.c0 {
		bit := (m.mbyte >> (7 - m.bitPos)) & 1
		l := m.mlen
		if l > 63 {
			l = 63
		}
		m.mIdx = l*2 + bit
		p := counterP16(m.mcnt[m.mIdx])
		m.in[k] = stretch(p)
		if bit == 1 {
			m.in[k+1] = int32(l) * 32
		} else {
			m.in[k+1] = -int32(l) * 32
		}
		lenBucket = 1 + min(l/4, 6)
	}
	m.in[k+2] = 256
	c1 := int(m.c4 & 0xff)
	d0 := m.mixers[0].mix(m.in[:], int(m.c0))
	d1 := m.mixers[1].mix(m.in[:], c1)
	d2 := m.mixers[2].mix(m.in[:], lenBucket*64+int(m.bitPos)*8+min(int(m.c0&7), 7))
	d := (d0 + d1 + d2) / 3
	m.mixerOut = d
	p := squash(d)
	m.prMix = p
	a1 := m.apm1.refine(p, int(m.c0))
	a2 := m.apm2.refine(p, int(hash32(m.c4&0xffff, m.c0)>>16))
	pf := (2*p + a1 + a2*5) >> 3
	if pf < 32 {
		pf = 32
	}
	if pf > 65535-32 {
		pf = 65535 - 32
	}
	m.pr = pf
}

// P returns P(next bit = 1) as a 16-bit probability in [32, 65503].
func (m *Model) P() uint32 { return uint32(m.pr) }

// Update trains the model with the actual bit and prepares the next prediction.
func (m *Model) Update(y int) {
	for i := 0; i < nCtx; i++ {
		counterUpdate(&m.tab[i][m.idx[i]], y, m.limits[i])
	}
	if m.mIdx >= 0 {
		counterUpdate(&m.mcnt[m.mIdx], y, 255)
	}
	m.mixers[0].update(m.in[:], y, 4)
	m.mixers[1].update(m.in[:], y, 4)
	m.mixers[2].update(m.in[:], y, 4)
	m.apm1.update(y, 6)
	m.apm2.update(y, 6)

	m.c0 = m.c0<<1 | uint32(y)
	m.bitPos++
	if m.bitPos == 8 {
		b := byte(m.c0)
		m.buf = append(m.buf, b)
		m.c8 = m.c8<<8 | m.c4>>24
		m.c4 = m.c4<<8 | uint32(b)
		if b|0x20 >= 'a' && b|0x20 <= 'z' || b >= 0x80 {
			m.word = hash32(m.word, uint32(b|0x20))
		} else {
			m.word = 0
		}
		m.c0, m.bitPos = 1, 0
		m.byteUpdate()
	}
	m.predict()
}
