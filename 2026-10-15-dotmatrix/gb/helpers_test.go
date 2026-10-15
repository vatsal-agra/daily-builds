package gb

import (
	"testing"

	"dotmatrix/asm"
)

// build assembles `body` as the program at 0x150 behind a standard entry stub.
func build(t testing.TB, body string) *GB {
	t.Helper()
	src := "\t.org 0x100\n\tnop\n\tjp main\n\t.org 0x150\nmain:\n" + body + "\n"
	return buildRaw(t, src)
}

func buildRaw(t testing.TB, src string) *GB {
	t.Helper()
	r, err := asm.Assemble("test.s", src, asm.Options{})
	if err != nil {
		t.Fatalf("assemble: %v", err)
	}
	cart, err := NewCart(r.ROM)
	if err != nil {
		t.Fatalf("cart: %v", err)
	}
	return New(cart)
}

// runUntilHalt runs until the CPU executes HALT with interrupts disabled
// (the idiom the test programs use to finish) or maxCycles elapse.
func runUntilHalt(t testing.TB, g *GB, maxCycles uint64) {
	t.Helper()
	end := g.Cycles + maxCycles
	for g.Cycles < end {
		if err := g.StepChecked(); err != nil {
			t.Fatalf("cpu error: %v", err)
		}
		if g.halted && !g.ime {
			return
		}
	}
	t.Fatalf("program did not halt within %d cycles (pc=%04X)", maxCycles, g.pc)
}

// stepN executes n instructions.
func stepN(t testing.TB, g *GB, n int) {
	t.Helper()
	for i := 0; i < n; i++ {
		if err := g.StepChecked(); err != nil {
			t.Fatalf("cpu error: %v", err)
		}
	}
}

// onlyOp creates a machine whose program at 0x150 is the given raw bytes.
func onlyOp(t testing.TB, bytes ...byte) *GB {
	t.Helper()
	src := "\t.org 0x100\n\tjp 0x150\n\t.org 0x150\n\t.db "
	for i, b := range bytes {
		if i > 0 {
			src += ","
		}
		src += itoa(int(b))
	}
	src += "\n"
	g := buildRaw(t, src)
	g.pc = 0x150
	return g
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	s := ""
	for n > 0 {
		s = string(rune('0'+n%10)) + s
		n /= 10
	}
	return s
}
