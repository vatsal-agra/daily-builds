package gb

type timer struct {
	counter     uint16 // internal 16-bit system counter; DIV is its high byte
	tima, tma   byte
	tac         byte
	overflowing bool // TIMA overflowed last M-cycle; reload is pending
}

var timerBits = [4]uint{9, 3, 5, 7}

func (t *timer) signal() bool {
	return t.tac&4 != 0 && t.counter&(1<<timerBits[t.tac&3]) != 0
}

func (g *GB) timerIncrement() {
	t := &g.Timer
	t.tima++
	if t.tima == 0 {
		t.overflowing = true
	}
}

// tickTimer advances the timer by one M-cycle (4 T-cycles).
func (g *GB) tickTimer() {
	t := &g.Timer
	if t.overflowing {
		t.overflowing = false
		t.tima = t.tma
		g.ifl |= IntTimer
	}
	old := t.signal()
	t.counter += 4
	if old && !t.signal() {
		g.timerIncrement()
	}
}

func (g *GB) timerWriteDiv() {
	t := &g.Timer
	old := t.signal()
	t.counter = 0
	if old && !t.signal() {
		g.timerIncrement()
	}
}

func (g *GB) timerWriteTima(v byte) {
	t := &g.Timer
	// Writing during the overflow delay cancels the reload.
	t.overflowing = false
	t.tima = v
}

func (g *GB) timerWriteTac(v byte) {
	t := &g.Timer
	old := t.signal()
	t.tac = v & 7
	if old && !t.signal() {
		g.timerIncrement()
	}
}
