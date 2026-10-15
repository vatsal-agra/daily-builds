package gb

import (
	"bytes"
	"encoding/binary"
)

// SampleRate is the audio output rate of the APU mixer.
const SampleRate = 44100

const oversample = 4 // sub-samples averaged into each output sample (box filter)

var dutyTable = [4][8]uint8{
	{0, 0, 0, 0, 0, 0, 0, 1}, // 12.5%
	{1, 0, 0, 0, 0, 0, 0, 1}, // 25%
	{1, 0, 0, 0, 0, 1, 1, 1}, // 50%
	{0, 1, 1, 1, 1, 1, 1, 0}, // 75%
}

var noiseDivisor = [8]int{8, 16, 32, 48, 64, 80, 96, 112}

// Read masks: bits that always read back as 1 for NR10..NR52.
var apuReadMask = [0x17]uint8{
	0x80, 0x3F, 0x00, 0xFF, 0xBF, // NR10-NR14
	0xFF, 0x3F, 0x00, 0xFF, 0xBF, // FF15 (unused), NR21-NR24
	0x7F, 0xFF, 0x9F, 0xFF, 0xBF, // NR30-NR34
	0xFF, 0xFF, 0x00, 0x00, 0xBF, // FF1F (unused), NR41-NR44
	0x00, 0x00, 0x70, // NR50-NR52
}

type pulse struct {
	on        bool
	dac       bool
	duty      uint8
	pos       uint8
	timer     int // T-cycles until the next duty step
	freq      int
	length    int
	lenEnable bool
	vol       uint8
	envInit   uint8
	envAdd    bool
	envPeriod uint8
	envTimer  uint8
	// sweep (channel 1 only)
	sweepPeriod uint8
	sweepNeg    bool
	sweepShift  uint8
	sweepTimer  uint8
	sweepOn     bool
	shadow      int
}

type waveCh struct {
	on        bool
	dac       bool
	timer     int
	freq      int
	pos       uint8
	length    int
	lenEnable bool
	volCode   uint8
}

type noiseCh struct {
	on        bool
	dac       bool
	timer     int
	lfsr      uint16
	shift     uint8
	narrow    bool
	divCode   uint8
	length    int
	lenEnable bool
	vol       uint8
	envInit   uint8
	envAdd    bool
	envPeriod uint8
	envTimer  uint8
}

// APU is the four-channel sound unit.
type APU struct {
	regs    [0x30]byte // raw register bytes FF10..FF3F (wave RAM lives at 0x20..0x2F)
	power   bool
	ch1     pulse
	ch2     pulse
	ch3     waveCh
	ch4     noiseCh
	fsTimer int
	fsStep  int

	left, right uint8 // NR50 volumes 0..7
	pan         uint8 // NR51

	sampleAcc  int
	subCount   int
	subSum     [2]float64
	pending    []int16 `state:"-"` // interleaved L,R since last Drain
	recording  bool    `state:"-"`
	recorded   []int16 `state:"-"`
	hpL, hpR   float64 // DC-blocking filter state
	prevL      float64
	prevR      float64
	maxPending int `state:"-"`
}

func newAPU() *APU {
	a := &APU{maxPending: SampleRate * 2 * 2} // ~2 s of stereo samples
	a.reset()
	return a
}

func (a *APU) reset() {
	pend, rec, recording, maxp := a.pending[:0], a.recorded, a.recording, a.maxPending
	wave := a.regs[0x20:0x30]
	saved := append([]byte(nil), wave...)
	*a = APU{pending: pend, recorded: rec, recording: recording, maxPending: maxp}
	copy(a.regs[0x20:0x30], saved)
	// DMG post-boot state: powered on, channel 1 had just played the boot "ding" but is silent.
	a.power = true
	a.writeReg(0xFF26, 0x80)
	a.writeReg(0xFF24, 0x77)
	a.writeReg(0xFF25, 0xF3)
	a.regs[0x02] = 0xF3 // NR12 (envelope left as the boot ROM leaves it)
	a.regs[0x01] = 0xBF
	a.ch1.dac = true
}

// ---- register interface ----------------------------------------------------

func (a *APU) read(addr uint16) byte {
	i := int(addr - 0xFF10)
	switch {
	case i >= 0x20: // wave RAM
		if a.ch3.on {
			// while playing, the CPU sees the byte the channel is reading
			return a.regs[0x20+int(a.ch3.pos>>1)]
		}
		return a.regs[i]
	case i == 0x16: // NR52
		v := uint8(0x70)
		if a.power {
			v |= 0x80
		}
		if a.ch1.on {
			v |= 1
		}
		if a.ch2.on {
			v |= 2
		}
		if a.ch3.on {
			v |= 4
		}
		if a.ch4.on {
			v |= 8
		}
		return v
	case i > 0x16:
		return 0xFF // unused FF27-FF2F
	}
	return a.regs[i] | apuReadMask[i]
}

func (a *APU) write(addr uint16, v byte) { a.writeReg(addr, v) }

func (a *APU) writeReg(addr uint16, v byte) {
	i := int(addr - 0xFF10)
	if i >= 0x20 { // wave RAM
		if a.ch3.on {
			a.regs[0x20+int(a.ch3.pos>>1)] = v
		} else {
			a.regs[i] = v
		}
		return
	}
	if i == 0x16 { // NR52
		on := v&0x80 != 0
		if a.power && !on {
			for r := 0; r < 0x16; r++ { // power off clears every register
				a.regs[r] = 0
			}
			a.ch1, a.ch2, a.ch3, a.ch4 = pulse{}, pulse{}, waveCh{}, noiseCh{}
			a.left, a.right, a.pan = 0, 0, 0
			a.power = false
		} else if !a.power && on {
			a.power = true
			a.fsStep = 0
		}
		return
	}
	if i > 0x16 {
		return
	}
	if !a.power {
		return // registers are read-only while the APU is off
	}
	a.regs[i] = v
	switch addr {
	case 0xFF10:
		a.ch1.sweepPeriod = v >> 4 & 7
		a.ch1.sweepNeg = v&8 != 0
		a.ch1.sweepShift = v & 7
	case 0xFF11:
		a.ch1.duty = v >> 6
		a.ch1.length = 64 - int(v&0x3F)
	case 0xFF12:
		a.setEnv(&a.ch1, v)
	case 0xFF13:
		a.ch1.freq = a.ch1.freq&0x700 | int(v)
	case 0xFF14:
		a.ch1.freq = a.ch1.freq&0xFF | int(v&7)<<8
		a.ch1.lenEnable = v&0x40 != 0
		if v&0x80 != 0 {
			a.triggerPulse(&a.ch1, true)
		}
	case 0xFF16:
		a.ch2.duty = v >> 6
		a.ch2.length = 64 - int(v&0x3F)
	case 0xFF17:
		a.setEnv(&a.ch2, v)
	case 0xFF18:
		a.ch2.freq = a.ch2.freq&0x700 | int(v)
	case 0xFF19:
		a.ch2.freq = a.ch2.freq&0xFF | int(v&7)<<8
		a.ch2.lenEnable = v&0x40 != 0
		if v&0x80 != 0 {
			a.triggerPulse(&a.ch2, false)
		}
	case 0xFF1A:
		a.ch3.dac = v&0x80 != 0
		if !a.ch3.dac {
			a.ch3.on = false
		}
	case 0xFF1B:
		a.ch3.length = 256 - int(v)
	case 0xFF1C:
		a.ch3.volCode = v >> 5 & 3
	case 0xFF1D:
		a.ch3.freq = a.ch3.freq&0x700 | int(v)
	case 0xFF1E:
		a.ch3.freq = a.ch3.freq&0xFF | int(v&7)<<8
		a.ch3.lenEnable = v&0x40 != 0
		if v&0x80 != 0 {
			a.triggerWave()
		}
	case 0xFF20:
		a.ch4.length = 64 - int(v&0x3F)
	case 0xFF21:
		c := &a.ch4
		c.envInit, c.envAdd, c.envPeriod = v>>4, v&8 != 0, v&7
		c.dac = v&0xF8 != 0
		if !c.dac {
			c.on = false
		}
	case 0xFF22:
		a.ch4.shift = v >> 4
		a.ch4.narrow = v&8 != 0
		a.ch4.divCode = v & 7
	case 0xFF23:
		a.ch4.lenEnable = v&0x40 != 0
		if v&0x80 != 0 {
			a.triggerNoise()
		}
	case 0xFF24:
		a.left, a.right = v>>4&7, v&7
	case 0xFF25:
		a.pan = v
	}
}

func (a *APU) setEnv(c *pulse, v byte) {
	c.envInit, c.envAdd, c.envPeriod = v>>4, v&8 != 0, v&7
	c.dac = v&0xF8 != 0
	if !c.dac {
		c.on = false
	}
}

func (a *APU) triggerPulse(c *pulse, sweep bool) {
	if !c.dac {
		return
	}
	c.on = true
	if c.length == 0 {
		c.length = 64
	}
	c.timer = (2048 - c.freq) * 4
	c.vol = c.envInit
	c.envTimer = c.envPeriod
	if c.envTimer == 0 {
		c.envTimer = 8
	}
	if sweep {
		c.shadow = c.freq
		c.sweepTimer = c.sweepPeriod
		if c.sweepTimer == 0 {
			c.sweepTimer = 8
		}
		c.sweepOn = c.sweepPeriod != 0 || c.sweepShift != 0
		if c.sweepShift != 0 {
			if _, ovf := a.sweepCalc(c); ovf {
				c.on = false
			}
		}
	}
}

func (a *APU) triggerWave() {
	c := &a.ch3
	if !c.dac {
		return
	}
	c.on = true
	if c.length == 0 {
		c.length = 256
	}
	c.timer = (2048 - c.freq) * 2
	c.pos = 0
}

func (a *APU) triggerNoise() {
	c := &a.ch4
	if !c.dac {
		return
	}
	c.on = true
	if c.length == 0 {
		c.length = 64
	}
	c.timer = noiseDivisor[c.divCode] << c.shift
	c.lfsr = 0x7FFF
	c.vol = c.envInit
	c.envTimer = c.envPeriod
	if c.envTimer == 0 {
		c.envTimer = 8
	}
}

func (a *APU) sweepCalc(c *pulse) (int, bool) {
	d := c.shadow >> c.sweepShift
	n := c.shadow + d
	if c.sweepNeg {
		n = c.shadow - d
	}
	return n, n > 2047
}

// ---- timing ----------------------------------------------------------------

// tick advances the APU by t T-cycles, generating output samples. Each output
// sample is the average of `oversample` evenly spaced mixer snapshots, which
// removes most of the aliasing a plain nearest-sample pick would add to the
// high-pitched square waves.
func (a *APU) tick(t int) {
	if !a.power {
		a.emitSilence(t) // keep audio in step with video even while powered off
		return
	}
	const sub = ClockHz / (SampleRate * oversample) // ~23 cycles per sub-sample
	for t > 0 {
		step := t
		if step > sub {
			step = sub
		}
		a.advanceChannels(step)
		t -= step
		a.sampleAcc += step * SampleRate * oversample
		for a.sampleAcc >= ClockHz {
			a.sampleAcc -= ClockHz
			l, r := a.mix()
			a.subSum[0] += l
			a.subSum[1] += r
			a.subCount++
			if a.subCount == oversample {
				a.outputSample(a.subSum[0]/oversample, a.subSum[1]/oversample)
				a.subSum = [2]float64{}
				a.subCount = 0
			}
		}
	}
}

func (a *APU) emitSilence(t int) {
	a.sampleAcc += t * SampleRate
	for a.sampleAcc >= ClockHz {
		a.sampleAcc -= ClockHz
		a.outputSample(0, 0)
	}
}

func (a *APU) advanceChannels(t int) {
	// frame sequencer: 512 Hz = every 8192 T-cycles
	a.fsTimer += t
	for a.fsTimer >= 8192 {
		a.fsTimer -= 8192
		a.frameStep()
	}
	for _, c := range []*pulse{&a.ch1, &a.ch2} {
		if !c.on {
			continue
		}
		c.timer -= t
		for c.timer <= 0 {
			period := (2048 - c.freq) * 4
			if period <= 0 {
				period = 4
			}
			c.timer += period
			c.pos = (c.pos + 1) & 7
		}
	}
	if a.ch3.on {
		c := &a.ch3
		c.timer -= t
		for c.timer <= 0 {
			period := (2048 - c.freq) * 2
			if period <= 0 {
				period = 2
			}
			c.timer += period
			c.pos = (c.pos + 1) & 31
		}
	}
	if a.ch4.on {
		c := &a.ch4
		c.timer -= t
		for c.timer <= 0 {
			c.timer += noiseDivisor[c.divCode] << c.shift
			x := (c.lfsr ^ c.lfsr>>1) & 1
			c.lfsr = c.lfsr>>1 | x<<14
			if c.narrow {
				c.lfsr = c.lfsr&^(1<<6) | x<<6
			}
		}
	}
}

func (a *APU) frameStep() {
	s := a.fsStep
	a.fsStep = (a.fsStep + 1) & 7
	if s&1 == 0 { // length: steps 0,2,4,6
		a.clockLength(&a.ch1.length, a.ch1.lenEnable, &a.ch1.on)
		a.clockLength(&a.ch2.length, a.ch2.lenEnable, &a.ch2.on)
		a.clockLength(&a.ch3.length, a.ch3.lenEnable, &a.ch3.on)
		a.clockLength(&a.ch4.length, a.ch4.lenEnable, &a.ch4.on)
	}
	if s == 2 || s == 6 { // sweep
		c := &a.ch1
		if c.sweepTimer > 0 {
			c.sweepTimer--
		}
		if c.sweepTimer == 0 {
			c.sweepTimer = c.sweepPeriod
			if c.sweepTimer == 0 {
				c.sweepTimer = 8
			}
			if c.sweepOn && c.sweepPeriod > 0 {
				n, ovf := a.sweepCalc(c)
				if ovf {
					c.on = false
				} else if c.sweepShift > 0 {
					c.shadow, c.freq = n, n
					a.regs[0x03] = byte(n)
					a.regs[0x04] = a.regs[0x04]&^7 | byte(n>>8)
					if _, ovf2 := a.sweepCalc(c); ovf2 {
						c.on = false
					}
				}
			}
		}
	}
	if s == 7 { // envelope
		a.clockEnv(&a.ch1.vol, a.ch1.envAdd, a.ch1.envPeriod, &a.ch1.envTimer, a.ch1.on)
		a.clockEnv(&a.ch2.vol, a.ch2.envAdd, a.ch2.envPeriod, &a.ch2.envTimer, a.ch2.on)
		a.clockEnv(&a.ch4.vol, a.ch4.envAdd, a.ch4.envPeriod, &a.ch4.envTimer, a.ch4.on)
	}
}

func (a *APU) clockLength(n *int, enabled bool, on *bool) {
	if !enabled || *n == 0 {
		return
	}
	*n--
	if *n == 0 {
		*on = false
	}
}

func (a *APU) clockEnv(vol *uint8, add bool, period uint8, timer *uint8, on bool) {
	if !on || period == 0 {
		return
	}
	if *timer > 0 {
		*timer--
	}
	if *timer != 0 {
		return
	}
	*timer = period
	if add && *vol < 15 {
		*vol++
	} else if !add && *vol > 0 {
		*vol--
	}
}

// ---- mixing ------------------------------------------------------------------

// chOut returns a channel's current analog level in -1..1 (0 when silent).
func (a *APU) chOut(i int) float64 {
	var digital float64
	switch i {
	case 0, 1:
		c := &a.ch1
		if i == 1 {
			c = &a.ch2
		}
		if !c.on || !c.dac {
			return 0
		}
		digital = float64(dutyTable[c.duty][c.pos] * c.vol)
	case 2:
		c := &a.ch3
		if !c.on || !c.dac {
			return 0
		}
		b := a.regs[0x20+int(c.pos>>1)]
		s := b >> 4
		if c.pos&1 == 1 {
			s = b & 0xF
		}
		switch c.volCode {
		case 0:
			s = 0
		case 2:
			s >>= 1
		case 3:
			s >>= 2
		}
		digital = float64(s)
	default:
		c := &a.ch4
		if !c.on || !c.dac {
			return 0
		}
		if c.lfsr&1 == 0 {
			digital = float64(c.vol)
		}
	}
	return digital/7.5 - 1
}

func (a *APU) mix() (l, r float64) {
	for i := 0; i < 4; i++ {
		v := a.chOut(i)
		if a.pan&(1<<uint(4+i)) != 0 {
			l += v
		}
		if a.pan&(1<<uint(i)) != 0 {
			r += v
		}
	}
	l *= float64(a.left+1) / 8 / 4
	r *= float64(a.right+1) / 8 / 4
	return
}

func (a *APU) outputSample(l, r float64) {
	// one-pole DC blocker (hardware has a capacitor doing the same)
	const k = 0.999
	ol := l - a.prevL + k*a.hpL
	or := r - a.prevR + k*a.hpR
	a.prevL, a.prevR, a.hpL, a.hpR = l, r, ol, or
	sl, sr := toS16(ol), toS16(or)
	if len(a.pending) < a.maxPending {
		a.pending = append(a.pending, sl, sr)
	}
	if a.recording {
		a.recorded = append(a.recorded, sl, sr)
	}
}

func toS16(v float64) int16 {
	v *= 32767 * 0.9
	if v > 32767 {
		return 32767
	}
	if v < -32768 {
		return -32768
	}
	return int16(v)
}

// Drain returns (and clears) the interleaved stereo samples produced since the last call.
func (a *APU) Drain() []int16 {
	out := make([]int16, len(a.pending))
	copy(out, a.pending)
	a.pending = a.pending[:0]
	return out
}

// StartRecording keeps every sample for WAV export.
func (a *APU) StartRecording() { a.recording = true }

// WAV encodes everything recorded so far as a 16-bit stereo PCM WAV file.
func (a *APU) WAV() []byte {
	var b bytes.Buffer
	data := len(a.recorded) * 2
	w := func(v any) { binary.Write(&b, binary.LittleEndian, v) }
	b.WriteString("RIFF")
	w(uint32(36 + data))
	b.WriteString("WAVEfmt ")
	w(uint32(16))
	w(uint16(1)) // PCM
	w(uint16(2)) // channels
	w(uint32(SampleRate))
	w(uint32(SampleRate * 4))
	w(uint16(4))
	w(uint16(16))
	b.WriteString("data")
	w(uint32(data))
	w(a.recorded)
	return b.Bytes()
}

// Status reports which channels are currently sounding (for the UI).
func (a *APU) Status() [4]bool { return [4]bool{a.ch1.on, a.ch2.on, a.ch3.on, a.ch4.on} }
