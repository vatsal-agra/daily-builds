package gb

import (
	"math"
	"testing"
)

// run advances the machine's peripherals by n cycles (multiples of 4).
func runAudio(g *GB, cycles int) []int16 {
	g.APU.Drain()
	for i := 0; i < cycles; i += 4 {
		g.advance(4)
	}
	return g.APU.Drain()
}

// crossings counts rising zero crossings in the left channel.
func crossings(s []int16) int {
	n := 0
	for i := 2; i < len(s); i += 2 {
		if s[i-2] <= 0 && s[i] > 0 {
			n++
		}
	}
	return n
}

func rms(s []int16, ch int) float64 {
	var sum float64
	n := 0
	for i := ch; i < len(s); i += 2 {
		sum += float64(s[i]) * float64(s[i])
		n++
	}
	if n == 0 {
		return 0
	}
	return math.Sqrt(sum / float64(n))
}

func peak(s []int16, ch int) int {
	m := 0
	for i := ch; i < len(s); i += 2 {
		v := int(s[i])
		if v < 0 {
			v = -v
		}
		if v > m {
			m = v
		}
	}
	return m
}

func newAPUMachine(t testing.TB) *GB {
	g := onlyOp(t, 0x18, 0xFE)
	g.writeIO(0xFF26, 0x80)
	g.writeIO(0xFF24, 0x77)
	g.writeIO(0xFF25, 0xFF)
	return g
}

func TestPulseFrequency(t *testing.T) {
	g := newAPUMachine(t)
	// channel 2, 50% duty, full volume, no length, ~440 Hz (x = 1750 = 0x6D6)
	g.writeIO(0xFF16, 0x80)
	g.writeIO(0xFF17, 0xF0)
	g.writeIO(0xFF18, 0xD6)
	g.writeIO(0xFF19, 0x86)
	s := runAudio(g, ClockHz) // one second
	if len(s) < 2*SampleRate-200 || len(s) > 2*SampleRate+200 {
		t.Fatalf("one second produced %d sample pairs, want ~%d", len(s)/2, SampleRate)
	}
	hz := crossings(s)
	want := 131072.0 / (2048 - 1750)
	if math.Abs(float64(hz)-want) > 3 {
		t.Errorf("measured %d Hz, want %.1f Hz", hz, want)
	}
	if peak(s, 0) < 5000 {
		t.Errorf("tone far too quiet: peak %d", peak(s, 0))
	}
}

func TestDutyCycles(t *testing.T) {
	// fraction of time the output is "high" must match the duty setting
	for duty, want := range []float64{0.125, 0.25, 0.5, 0.75} {
		g := newAPUMachine(t)
		g.writeIO(0xFF16, byte(duty<<6))
		g.writeIO(0xFF17, 0xF0)
		g.writeIO(0xFF18, 0x00) // 2048-1536 = 512 -> period 2048 cycles -> ~2 kHz, exact sampling
		g.writeIO(0xFF19, 0x86)
		s := runAudio(g, ClockHz/4)
		// remove DC by thresholding at the signal's midpoint
		mx, mn := -40000, 40000
		for i := 0; i < len(s); i += 2 {
			if int(s[i]) > mx {
				mx = int(s[i])
			}
			if int(s[i]) < mn {
				mn = int(s[i])
			}
		}
		mid := (mx + mn) / 2
		hi := 0
		for i := 0; i < len(s); i += 2 {
			if int(s[i]) > mid {
				hi++
			}
		}
		got := float64(hi) / float64(len(s)/2)
		if math.Abs(got-want) > 0.04 {
			t.Errorf("duty %d: high fraction %.3f want %.3f", duty, got, want)
		}
	}
}

func TestEnvelopeDecays(t *testing.T) {
	g := newAPUMachine(t)
	g.writeIO(0xFF16, 0x80)
	g.writeIO(0xFF17, 0xF1) // vol 15, decrease, period 1 (1/64 s per step)
	g.writeIO(0xFF18, 0xD6)
	g.writeIO(0xFF19, 0x86)
	first := runAudio(g, ClockHz/20)
	g.advance(ClockHz / 2) // let it run down to silence (15 steps = 0.23 s)
	g.APU.Drain()
	late := runAudio(g, ClockHz/20)
	if peak(first, 0) < 4*peak(late, 0)+1 && peak(late, 0) > 500 {
		t.Errorf("envelope did not decay: early peak %d late peak %d", peak(first, 0), peak(late, 0))
	}
	if peak(late, 0) > 800 {
		t.Errorf("not silent at the end of the envelope: %d", peak(late, 0))
	}
	// increasing envelope starts quiet and rises
	g = newAPUMachine(t)
	g.writeIO(0xFF16, 0x80)
	g.writeIO(0xFF17, 0x09) // vol 0, increase, period 1
	g.writeIO(0xFF18, 0xD6)
	g.writeIO(0xFF19, 0x86)
	a := runAudio(g, ClockHz/20)
	g.advance(ClockHz / 2)
	g.APU.Drain()
	b := runAudio(g, ClockHz/20)
	if peak(b, 0) <= peak(a, 0) {
		t.Errorf("rising envelope: %d -> %d", peak(a, 0), peak(b, 0))
	}
}

func TestLengthCutoff(t *testing.T) {
	g := newAPUMachine(t)
	g.writeIO(0xFF16, 0x80|(64-16)) // length counter = 16 -> 16/256 s = 62.5 ms
	g.writeIO(0xFF17, 0xF0)
	g.writeIO(0xFF18, 0xD6)
	g.writeIO(0xFF19, 0xC6) // trigger + length enable
	if g.readIO(0xFF26)&2 == 0 {
		t.Fatal("channel 2 should be on after trigger")
	}
	g.advance(ClockHz / 10) // 100 ms
	if g.readIO(0xFF26)&2 != 0 {
		t.Error("channel 2 should have been cut off by its length counter")
	}
	// without length enable the sound continues
	g = newAPUMachine(t)
	g.writeIO(0xFF16, 0x80|(64-16))
	g.writeIO(0xFF17, 0xF0)
	g.writeIO(0xFF19, 0x86)
	g.advance(ClockHz / 2)
	if g.readIO(0xFF26)&2 == 0 {
		t.Error("channel stopped although length was not enabled")
	}
}

func TestSweepRaisesPitchAndOverflowSilences(t *testing.T) {
	g := newAPUMachine(t)
	g.writeIO(0xFF10, 0x11) // period 1, add, shift 1
	g.writeIO(0xFF11, 0x80)
	g.writeIO(0xFF12, 0xF0)
	g.writeIO(0xFF13, 0x00)
	g.writeIO(0xFF14, 0x84) // freq 0x400
	before := g.APU.ch1.freq
	g.advance(ClockHz / 20)
	if g.APU.ch1.freq <= before {
		t.Errorf("sweep up did not raise the frequency: %d -> %d", before, g.APU.ch1.freq)
	}
	g.advance(ClockHz) // runs into the 2047 ceiling
	if g.readIO(0xFF26)&1 != 0 {
		t.Error("channel 1 should be disabled by sweep overflow")
	}
	// sweep down lowers it
	g = newAPUMachine(t)
	g.writeIO(0xFF10, 0x19) // period 1, subtract, shift 1
	g.writeIO(0xFF11, 0x80)
	g.writeIO(0xFF12, 0xF0)
	g.writeIO(0xFF13, 0x00)
	g.writeIO(0xFF14, 0x85) // freq 0x500
	before = g.APU.ch1.freq
	g.advance(ClockHz / 20)
	if g.APU.ch1.freq >= before {
		t.Errorf("sweep down did not lower the frequency: %d -> %d", before, g.APU.ch1.freq)
	}
}

func TestWaveChannel(t *testing.T) {
	g := newAPUMachine(t)
	// a 32-sample ramp 0..15,15..0 in wave RAM
	for i := 0; i < 16; i++ {
		var hi, lo byte
		for h := 0; h < 2; h++ {
			s := i*2 + h
			v := s
			if s >= 16 {
				v = 31 - s
			}
			if h == 0 {
				hi = byte(v)
			} else {
				lo = byte(v)
			}
		}
		g.writeIO(0xFF30+uint16(i), hi<<4|lo)
	}
	g.writeIO(0xFF1A, 0x80)
	g.writeIO(0xFF1B, 0x00)
	g.writeIO(0xFF1C, 0x20) // 100%
	// 32 samples per cycle; freq = 65536/(2048-x) Hz. x=1792 -> 256 Hz
	g.writeIO(0xFF1D, 0x00)
	g.writeIO(0xFF1E, 0x87)
	s := runAudio(g, ClockHz/2)
	hz := crossings(s) * 2
	if math.Abs(float64(hz)-256) > 6 {
		t.Errorf("wave channel pitch %d Hz, want ~256", hz)
	}
	// mute volume code
	g.writeIO(0xFF1C, 0x00)
	runAudio(g, ClockHz/5) // let the DC blocker settle on the constant "silent" DAC level
	s = runAudio(g, ClockHz/20)
	if peak(s, 0) > 600 {
		t.Errorf("volume code 0 should mute, peak %d", peak(s, 0))
	}
	// quarter volume is quieter than full
	g.writeIO(0xFF1C, 0x20)
	full := peak(runAudio(g, ClockHz/20), 0)
	g.writeIO(0xFF1C, 0x40)
	half := peak(runAudio(g, ClockHz/20), 0)
	g.writeIO(0xFF1C, 0x60)
	quarter := peak(runAudio(g, ClockHz/20), 0)
	if r := float64(half) / float64(full); r < 0.4 || r > 0.6 {
		t.Errorf("50%% volume code gives %.2f of full amplitude", r)
	}
	if r := float64(quarter) / float64(full); r < 0.15 || r > 0.35 {
		t.Errorf("25%% volume code gives %.2f of full amplitude", r)
	}
	// DAC off turns the channel off
	g.writeIO(0xFF1A, 0x00)
	if g.readIO(0xFF26)&4 != 0 {
		t.Error("disabling the DAC should switch the channel off")
	}
}

func TestNoiseChannel(t *testing.T) {
	g := newAPUMachine(t)
	g.writeIO(0xFF21, 0xF0)
	g.writeIO(0xFF22, 0x33) // shift 3, 15-bit, divisor 3
	g.writeIO(0xFF23, 0x80)
	s := runAudio(g, ClockHz/10)
	if rms(s, 0) < 1000 {
		t.Errorf("noise too quiet: rms %.0f", rms(s, 0))
	}
	// the 15-bit and 7-bit LFSR modes must produce different sequences
	a := newAPUMachine(t)
	b := newAPUMachine(t)
	for _, m := range []struct {
		g    *GB
		mode byte
	}{{a, 0x03}, {b, 0x0B}} {
		m.g.writeIO(0xFF21, 0xF0)
		m.g.writeIO(0xFF22, m.mode)
		m.g.writeIO(0xFF23, 0x80)
	}
	sa := runAudio(a, ClockHz/20)
	sb := runAudio(b, ClockHz/20)
	same := true
	for i := range sa {
		if i < len(sb) && sa[i] != sb[i] {
			same = false
			break
		}
	}
	if same {
		t.Error("7-bit LFSR mode sounds identical to 15-bit mode")
	}
	// Drive the real channel and observe its LFSR: 7-bit mode must repeat every 127 steps, 15-bit every 32767.
	period := func(mode byte, limit int) int {
		m := newAPUMachine(t)
		m.writeIO(0xFF21, 0xF0)
		m.writeIO(0xFF22, mode) // shift 0, divisor code from mode
		m.writeIO(0xFF23, 0x80)
		c := &m.APU.ch4
		step := noiseDivisor[mode&7] << (mode >> 4)
		for i := 0; i < 40; i++ { // flush the all-ones start state into the real cycle
			m.APU.advanceChannels(step)
		}
		start := c.lfsr
		for i := 1; i <= limit; i++ {
			m.APU.advanceChannels(step)
			if c.lfsr == start {
				return i
			}
		}
		return -1
	}
	if p := period(0x08, 400); p != 127 {
		t.Errorf("7-bit LFSR period %d, want 127", p)
	}
	if p := period(0x00, 40000); p != 32767 {
		t.Errorf("15-bit LFSR period %d, want 32767", p)
	}
}

func TestPanningAndMasterVolume(t *testing.T) {
	g := newAPUMachine(t)
	g.writeIO(0xFF16, 0x80)
	g.writeIO(0xFF17, 0xF0)
	g.writeIO(0xFF18, 0xD6)
	g.writeIO(0xFF19, 0x86)
	g.writeIO(0xFF25, 0x20) // channel 2 -> left only
	s := runAudio(g, ClockHz/10)
	if peak(s, 0) < 3000 || peak(s, 1) > 100 {
		t.Errorf("left-only pan: L=%d R=%d", peak(s, 0), peak(s, 1))
	}
	g.writeIO(0xFF25, 0x02) // right only
	s = runAudio(g, ClockHz/10)
	if peak(s, 1) < 3000 || peak(s, 0) > 100 {
		t.Errorf("right-only pan: L=%d R=%d", peak(s, 0), peak(s, 1))
	}
	g.writeIO(0xFF25, 0xFF)
	g.writeIO(0xFF24, 0x77)
	loud := peak(runAudio(g, ClockHz/10), 0)
	g.writeIO(0xFF24, 0x22)
	quiet := peak(runAudio(g, ClockHz/10), 0)
	if !(quiet < loud/2) {
		t.Errorf("master volume: 7 -> %d, 2 -> %d", loud, quiet)
	}
}

func TestPowerControl(t *testing.T) {
	g := newAPUMachine(t)
	g.writeIO(0xFF17, 0xF0)
	g.writeIO(0xFF19, 0x86)
	if g.readIO(0xFF26) != 0xF2 {
		t.Errorf("NR52 = %02X, want F2", g.readIO(0xFF26))
	}
	g.writeIO(0xFF26, 0x00) // power off
	if g.readIO(0xFF26)&0x8F != 0 {
		t.Errorf("NR52 after power-off = %02X", g.readIO(0xFF26))
	}
	g.writeIO(0xFF17, 0xAB) // ignored while off
	g.writeIO(0xFF26, 0x80)
	if g.readIO(0xFF17) != 0 {
		t.Errorf("registers must be cleared and read-only while off; NR22=%02X", g.readIO(0xFF17))
	}
	s := runAudio(g, ClockHz/20)
	if peak(s, 0) > 10 {
		t.Errorf("sound while no channel is enabled: %d", peak(s, 0))
	}
	// wave RAM survives power cycling
	g.writeIO(0xFF30, 0x5A)
	g.writeIO(0xFF26, 0x00)
	g.writeIO(0xFF26, 0x80)
	if g.readIO(0xFF30) != 0x5A {
		t.Error("wave RAM was cleared by power cycle")
	}
	// read masks
	g.writeIO(0xFF11, 0x80)
	if g.readIO(0xFF11) != 0xBF {
		t.Errorf("NR11 read mask: %02X", g.readIO(0xFF11))
	}
	if g.readIO(0xFF13) != 0xFF {
		t.Errorf("NR13 is write-only: %02X", g.readIO(0xFF13))
	}
	if g.readIO(0xFF27) != 0xFF {
		t.Errorf("unused APU register: %02X", g.readIO(0xFF27))
	}
}

func TestDACOffSilencesChannel(t *testing.T) {
	g := newAPUMachine(t)
	g.writeIO(0xFF17, 0xF0)
	g.writeIO(0xFF19, 0x86)
	g.writeIO(0xFF17, 0x00) // DAC off
	if g.readIO(0xFF26)&2 != 0 {
		t.Error("channel should switch off when its DAC is disabled")
	}
	g.writeIO(0xFF19, 0x86) // trigger with DAC off must not start it
	if g.readIO(0xFF26)&2 != 0 {
		t.Error("trigger with DAC off turned the channel on")
	}
}

func TestWAVExport(t *testing.T) {
	g := newAPUMachine(t)
	g.APU.StartRecording()
	g.writeIO(0xFF17, 0xF0)
	g.writeIO(0xFF19, 0x86)
	g.advance(ClockHz / 10)
	w := g.APU.WAV()
	if string(w[0:4]) != "RIFF" || string(w[8:12]) != "WAVE" || string(w[36:40]) != "data" {
		t.Fatalf("bad WAV header: %q", w[:44])
	}
	dataLen := int(w[40]) | int(w[41])<<8 | int(w[42])<<16 | int(w[43])<<24
	if dataLen != len(w)-44 {
		t.Errorf("data chunk says %d bytes, file has %d", dataLen, len(w)-44)
	}
	if dataLen/4 < SampleRate/10-100 {
		t.Errorf("0.1 s recorded as only %d frames", dataLen/4)
	}
}
