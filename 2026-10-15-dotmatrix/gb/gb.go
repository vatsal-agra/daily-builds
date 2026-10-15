// Package gb is a Game Boy (DMG) emulator core.
//
// Timing model: the CPU executes whole instructions; after each one the
// peripherals (timer, PPU, DMA, serial, APU) are advanced by the number of
// machine cycles it consumed. The PPU renders a scanline at a time.
package gb

const (
	ScreenW = 160
	ScreenH = 144

	// T-cycles per frame: 154 lines * 456 dots.
	CyclesPerFrame = 70224
	ClockHz        = 4194304
)

// Interrupt bits (IF / IE).
const (
	IntVBlank = 1 << iota
	IntSTAT
	IntTimer
	IntSerial
	IntJoypad
)

// Buttons, as passed to SetButton.
const (
	BtnRight = iota
	BtnLeft
	BtnUp
	BtnDown
	BtnA
	BtnB
	BtnSelect
	BtnStart
)

// GB is a complete machine.
type GB struct {
	CPU
	Cart *Cart

	vram [0x2000]byte
	wram [0x2000]byte
	oam  [0xA0]byte
	hram [0x7F]byte
	io   [0x80]byte // backing store for registers without dedicated logic
	ie   byte
	ifl  byte

	Timer  timer
	PPU    ppu
	Joy    joypad
	APU    *APU
	dma    dmaState
	serial serialState

	// Serial collects every byte the program transmits on the link port.
	Serial []byte

	// Cycles is the total number of T-cycles executed.
	Cycles uint64

	// Frames counts completed frames (VBlank entries).
	Frames uint64

	Dbg *Debugger
}

type dmaState struct {
	active bool
	src    uint16
	idx    int
	start  int // M-cycles of start-up delay left
}

type serialState struct {
	active bool
	left   int // T-cycles remaining
}

// New creates a machine with the cartridge inserted and registers set to the
// state the DMG boot ROM leaves behind.
func New(cart *Cart) *GB {
	g := &GB{Cart: cart}
	g.APU = newAPU()
	g.reset()
	return g
}

func (g *GB) reset() {
	c := &g.CPU
	*c = CPU{}
	c.a, c.f = 0x01, 0xB0
	c.b, c.c = 0x00, 0x13
	c.d, c.e = 0x00, 0xD8
	c.h, c.l = 0x01, 0x4D
	c.sp, c.pc = 0xFFFE, 0x0100
	g.Timer = timer{}
	g.Timer.counter = 0xABCC
	g.PPU = ppu{}
	g.PPU.lcdc = 0x91
	g.PPU.bgp = 0xFC
	g.PPU.obp0, g.PPU.obp1 = 0xFF, 0xFF
	g.PPU.mode = 2
	g.PPU.ly = 0
	g.PPU.dot = 0
	g.ifl = 0xE1
	g.Joy = joypad{keys: 0xFF}
	g.Joy.sel = 0x30
	g.APU.reset()
}

// Step executes one instruction (or one idle HALT slice or interrupt
// dispatch) and advances every peripheral. It returns the T-cycles consumed.
func (g *GB) Step() int {
	m := g.cpuStep() // M-cycles
	t := m * 4
	g.advance(t)
	return t
}

// advance ticks the peripherals by t T-cycles in M-cycle slices.
func (g *GB) advance(t int) {
	for i := 0; i < t; i += 4 {
		g.tickTimer()
		g.tickDMA()
		g.tickSerial()
	}
	g.tickPPU(t)
	g.APU.tick(t)
	g.Cart.tickRTC(t)
	g.Cycles += uint64(t)
}

// RunFrame runs until the next VBlank begins. It returns an error-ish stop
// reason: nil normally, ErrBreak when a debugger breakpoint hit, or the CPU's
// lock-up error.
func (g *GB) RunFrame() error {
	start := g.Frames
	for g.Frames == start {
		if err := g.StepChecked(); err != nil {
			return err
		}
	}
	return nil
}

// RunCycles runs for at least n T-cycles.
func (g *GB) RunCycles(n uint64) error {
	end := g.Cycles + n
	for g.Cycles < end {
		if err := g.StepChecked(); err != nil {
			return err
		}
	}
	return nil
}

// SetButton presses or releases a joypad button.
func (g *GB) SetButton(btn int, down bool) {
	g.joypadSet(btn, down)
}

// Framebuffer returns the current 160x144 frame as shade indices 0..3
// (0 = lightest) after palette mapping.
func (g *GB) Framebuffer() []byte { return g.PPU.front[:] }
