package gb

import (
	"fmt"
	"testing"
)

func TestEIDelayAndISR(t *testing.T) {
	g := buildRaw(t, `
	.org 0x40
	ld e, c        ; record C at ISR entry
	ld d, b
	reti
	.org 0x100
	jp main
	.org 0x150
main:
	ld sp, 0xDFF0
	ld a, 1
	ldh [0xFF], a  ; IE = VBlank
	ldh [0x0F], a  ; IF = VBlank (pending)
	ld b, 0
	ld c, 0
	ei
	inc b          ; must execute before the interrupt
	inc c          ; must not execute before the ISR runs
	di
	halt
`)
	runUntilHalt(t, g, 100000)
	if g.d != 1 || g.e != 0 {
		t.Fatalf("at ISR entry B=%d C=%d, want B=1 C=0", g.d, g.e)
	}
	if g.c != 1 {
		t.Fatalf("after RETI C=%d", g.c)
	}
}

func TestEIThenDINoInterrupt(t *testing.T) {
	g := buildRaw(t, `
	.org 0x40
	ld d, 0xEE
	reti
	.org 0x100
	jp main
	.org 0x150
main:
	ld sp, 0xDFF0
	ld a, 1
	ldh [0xFF], a
	ldh [0x0F], a
	ei
	di
	nop
	nop
	xor a
	ldh [0x0F], a
	halt
`)
	runUntilHalt(t, g, 100000)
	if g.d == 0xEE {
		t.Fatal("interrupt was serviced although DI immediately followed EI")
	}
}

func TestInterruptPriorityAndVectors(t *testing.T) {
	for bit := 0; bit < 5; bit++ {
		g := buildRaw(t, fmt.Sprintf(`
	.org 0x%02X
	ld a, %d
	halt
	.org 0x100
	jp main
	.org 0x150
main:
	ld sp, 0xDFF0
	ld a, 0x1F
	ldh [0xFF], a
	ldh [0x0F], a   ; all five pending: lowest bit must win
	ei
	nop
	halt
`, 0x40+8*bit, 100+bit))
		_ = g
		// above: all five pending => always vector 0x40. Build single-source variant:
		g = buildRaw(t, fmt.Sprintf(`
	.org 0x%02X
	ld b, %d
	halt
	.org 0x100
	jp main
	.org 0x150
main:
	ld sp, 0xDFF0
	ld a, 0x1F
	ldh [0xFF], a
	ld a, %d
	ldh [0x0F], a
	ei
	nop
	halt
`, 0x40+8*bit, 10+bit, 1<<bit))
		runUntilHalt(t, g, 100000)
		g.Step() // ensure settled
		if int(g.b) != 10+bit {
			t.Errorf("interrupt bit %d: B=%d, vector not taken", bit, g.b)
		}
	}
	// priority: VBlank (bit0) before Timer (bit2); the other stays pending.
	g := buildRaw(t, `
	.org 0x40
	ld b, 1
	reti
	.org 0x50
	ld c, 1
	reti
	.org 0x100
	jp main
	.org 0x150
main:
	ld sp, 0xDFF0
	ld a, 5
	ldh [0xFF], a
	ldh [0x0F], a
	ei
	nop
	nop
	nop
	di
	halt
`)
	runUntilHalt(t, g, 100000)
	if g.b != 1 || g.c != 1 {
		t.Errorf("both interrupts should run, B=%d C=%d", g.b, g.c)
	}
	if g.ifl&0x1F != 0 {
		t.Errorf("IF not cleared: %02X", g.ifl)
	}
}

func TestInterruptDispatchCost(t *testing.T) {
	g := onlyOp(t, 0x00)
	g.sp = 0xDFF0
	g.ime = true
	g.ie, g.ifl = 1, 1
	if m := g.cpuStep(); m != 5 {
		t.Errorf("dispatch took %d M-cycles, want 5", m)
	}
	if g.pc != 0x40 || g.sp != 0xDFEE || g.ime || g.ifl&1 != 0 {
		t.Errorf("after dispatch pc=%04X sp=%04X ime=%v if=%02X", g.pc, g.sp, g.ime, g.ifl)
	}
	if lo, hi := g.peek(0xDFEE), g.peek(0xDFEF); uint16(hi)<<8|uint16(lo) != 0x150 {
		t.Errorf("pushed return address %02X%02X", hi, lo)
	}
}

func TestHaltBehaviours(t *testing.T) {
	// IME off, interrupt pending at HALT time -> HALT bug: next byte read twice.
	g := buildRaw(t, `
	.org 0x100
	jp main
	.org 0x150
main:
	ld a, 1
	ldh [0xFF], a
	ldh [0x0F], a
	ld b, 0
	halt
	inc b
	nop
	ld c, 0x77
	stop
`)
	stepN(t, g, 3+1+1+1+3)
	if g.b != 2 {
		t.Errorf("HALT bug: INC B ran %d times, want 2", g.b)
	}

	// IME off, nothing pending: HALT sleeps until an enabled interrupt is flagged, then resumes without ISR.
	g = buildRaw(t, `
	.org 0x100
	jp main
	.org 0x150
main:
	ld a, 4        ; enable timer interrupt
	ldh [0xFF], a
	ld a, 0xF0
	ldh [0x05], a  ; TIMA = F0: ~256 cycles to overflow
	ld a, 5
	ldh [0x07], a  ; TAC enable, 16-cycle
	xor a
	ldh [0x0F], a
	halt
	ld b, 0x42
	stop
`)
	for i := 0; i < 2000 && g.b != 0x42; i++ {
		g.Step()
	}
	if g.b != 0x42 {
		t.Fatal("HALT never woke on timer interrupt")
	}
	if g.pc < 0x150 {
		t.Errorf("pc=%04X: should have continued inline (IME=0)", g.pc)
	}
}

func TestTimerRates(t *testing.T) {
	for tac, period := range map[byte]int{4: 1024, 5: 16, 6: 64, 7: 256} {
		g := onlyOp(t, 0)
		g.writeIO(0xFF04, 0) // reset divider for a deterministic phase
		g.writeIO(0xFF05, 0)
		g.writeIO(0xFF07, tac)
		g.advance(period * 10)
		if g.Timer.tima != 10 {
			t.Errorf("TAC=%d: TIMA=%d after 10 periods, want 10", tac, g.Timer.tima)
		}
	}
	// disabled
	g := onlyOp(t, 0)
	g.writeIO(0xFF07, 1)
	g.advance(1000)
	if g.Timer.tima != 0 {
		t.Errorf("timer ran while disabled")
	}
}

func TestTimerOverflowReload(t *testing.T) {
	g := onlyOp(t, 0)
	g.writeIO(0xFF04, 0)
	g.ifl = 0
	g.writeIO(0xFF06, 0xAB)
	g.writeIO(0xFF05, 0xFF)
	g.writeIO(0xFF07, 5)
	g.advance(16) // overflow: TIMA reads 0 for one M-cycle, no IF yet
	if g.Timer.tima != 0 || g.ifl&IntTimer != 0 {
		t.Fatalf("right after overflow: TIMA=%02X IF=%02X", g.Timer.tima, g.ifl)
	}
	g.advance(4)
	if g.Timer.tima != 0xAB || g.ifl&IntTimer == 0 {
		t.Fatalf("after reload: TIMA=%02X IF=%02X", g.Timer.tima, g.ifl)
	}
	// Writing TIMA during the delay cancels the reload and interrupt.
	g.ifl = 0
	g.writeIO(0xFF04, 0)
	g.writeIO(0xFF05, 0xFF)
	g.advance(16)
	g.writeIO(0xFF05, 0x10)
	g.advance(8)
	if g.Timer.tima != 0x10 || g.ifl&IntTimer != 0 {
		t.Errorf("cancel: TIMA=%02X IF=%02X", g.Timer.tima, g.ifl)
	}
}

func TestDivBehaviour(t *testing.T) {
	g := onlyOp(t, 0)
	g.writeIO(0xFF04, 0)
	g.advance(252)
	if g.readIO(0xFF04) != 0 {
		t.Errorf("DIV after 252 cycles = %d", g.readIO(0xFF04))
	}
	g.advance(4)
	if g.readIO(0xFF04) != 1 {
		t.Errorf("DIV after 256 cycles = %d", g.readIO(0xFF04))
	}
	g.writeIO(0xFF04, 0x99)
	if g.readIO(0xFF04) != 0 {
		t.Errorf("DIV write must reset to 0")
	}
	// falling edge: resetting DIV while the selected bit is high ticks TIMA
	g.writeIO(0xFF07, 5) // bit 3
	g.Timer.counter = 0x0008
	g.Timer.tima = 3
	g.writeIO(0xFF04, 0)
	if g.Timer.tima != 4 {
		t.Errorf("DIV reset falling edge: TIMA=%d want 4", g.Timer.tima)
	}
}

func TestOAMDMA(t *testing.T) {
	g := buildRaw(t, `
	.org 0x100
	jp main
	.org 0x150
main:
	ld sp, 0xDFF0
	; fill 0xC000..0xC09F with i
	ld hl, 0xC000
	ld b, 160
	xor a
.fill:
	ld [hl+], a
	inc a
	dec b
	jr nz, .fill
	; copy DMA routine into HRAM
	ld hl, dmacode
	ld de, 0xFF80
	ld b, dmaend - dmacode
.cp:
	ld a, [hl+]
	ld [de], a
	inc de
	dec b
	jr nz, .cp
	call 0xFF80
	halt
dmacode:
	ld a, 0xC0
	ldh [0x46], a
	ld a, 40
.w:
	dec a
	jr nz, .w
	ret
dmaend:
`)
	runUntilHalt(t, g, 1_000_000)
	for i := 0; i < 0xA0; i++ {
		if g.oam[i] != byte(i) {
			t.Fatalf("OAM[%d]=%02X want %02X", i, g.oam[i], i)
		}
	}
}

func TestDMABlocksCPUAccess(t *testing.T) {
	g := onlyOp(t, 0)
	g.wram[0] = 0x55
	g.write(0xFF46, 0xC0)
	g.advance(8) // past the start-up delay, DMA in flight
	if got := g.read(0xC000); got != 0xFF {
		t.Errorf("WRAM read during DMA = %02X, want FF", got)
	}
	g.write(0xFF80, 0x12)
	if g.read(0xFF80) != 0x12 {
		t.Errorf("HRAM must stay accessible during DMA")
	}
	g.advance(4 * 170)
	if got := g.read(0xC000); got != 0x55 {
		t.Errorf("WRAM read after DMA = %02X", got)
	}
}

func TestJoypad(t *testing.T) {
	g := onlyOp(t, 0)
	g.ifl = 0
	g.writeIO(0xFF00, 0x20) // select d-pad
	if g.readIO(0xFF00)&0x0F != 0x0F {
		t.Fatal("nothing pressed should read 1111")
	}
	g.SetButton(BtnDown, true)
	if v := g.readIO(0xFF00); v&0x0F != 0x07 {
		t.Errorf("down pressed: P1=%02X", v)
	}
	if g.ifl&IntJoypad == 0 {
		t.Errorf("joypad interrupt not raised on press")
	}
	g.writeIO(0xFF00, 0x10) // select buttons
	if g.readIO(0xFF00)&0x0F != 0x0F {
		t.Errorf("dpad leaked into button group")
	}
	g.SetButton(BtnA, true)
	g.SetButton(BtnStart, true)
	if v := g.readIO(0xFF00) & 0x0F; v != 0x06 {
		t.Errorf("A+Start: low nibble %X want 6", v)
	}
	g.writeIO(0xFF00, 0x30) // none selected
	if g.readIO(0xFF00)&0x0F != 0x0F {
		t.Errorf("no group selected should read 1111")
	}
	g.SetButton(BtnA, false)
	g.SetButton(BtnStart, false)
	g.SetButton(BtnDown, false)
}

func TestMemoryMap(t *testing.T) {
	g := onlyOp(t, 0)
	g.write(0xC123, 0x5A)
	if g.read(0xE123) != 0x5A {
		t.Errorf("echo RAM should mirror WRAM")
	}
	g.write(0xE456, 0xA5)
	if g.read(0xC456) != 0xA5 {
		t.Errorf("write through echo")
	}
	if g.read(0xFEA5) != 0xFF {
		t.Errorf("prohibited area should read FF")
	}
	g.write(0xFFFF, 0x1F)
	if g.read(0xFFFF) != 0x1F {
		t.Errorf("IE")
	}
	g.write(0xFF0F, 0xFF)
	if g.read(0xFF0F) != 0xFF {
		t.Errorf("IF upper bits read as 1: %02X", g.read(0xFF0F))
	}
	g.write(0xFF80, 7)
	if g.read(0xFF80) != 7 {
		t.Errorf("HRAM")
	}
	// ROM is read-only
	before := g.read(0x0150)
	g.write(0x0150, ^before)
	if g.read(0x0150) != before {
		t.Errorf("ROM write modified ROM")
	}
}
