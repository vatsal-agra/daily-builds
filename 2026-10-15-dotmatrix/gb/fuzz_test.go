package gb

import (
	"math/rand"
	"testing"
)

// Random programs, random IO traffic and random cartridge types must never
// panic the core, no matter how nonsensical the machine state gets.
func TestRandomROMsDoNotPanic(t *testing.T) {
	types := []byte{0x00, 0x01, 0x02, 0x03, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x19, 0x1A, 0x1B}
	for seed := int64(0); seed < 60; seed++ {
		r := rand.New(rand.NewSource(seed))
		size := 0x8000 << uint(r.Intn(4))
		rom := make([]byte, size)
		r.Read(rom)
		illegal := map[byte]bool{0xD3: true, 0xDB: true, 0xDD: true, 0xE3: true, 0xE4: true, 0xEB: true, 0xEC: true, 0xED: true, 0xF4: true, 0xFC: true, 0xFD: true}
		for i, b := range rom {
			if illegal[b] {
				rom[i] = 0x00 // keep the random stream running instead of locking up
			}
		}
		rom[0x147] = types[r.Intn(len(types))]
		rom[0x148] = byte(map[int]int{0x8000: 0, 0x10000: 1, 0x20000: 2, 0x40000: 3}[size])
		rom[0x149] = byte(r.Intn(6))
		rom[0x14D] = HeaderChecksumOf(rom)
		cart, err := NewCart(rom)
		if err != nil {
			t.Fatal(err)
		}
		g := New(cart)
		func() {
			defer func() {
				if e := recover(); e != nil {
					t.Fatalf("seed %d: panic: %v (pc=%04X)", seed, e, g.pc)
				}
			}()
			for i := 0; i < 300000; i++ {
				if i%97 == 0 {
					g.writeIO(0xFF00+uint16(r.Intn(0x80)), byte(r.Intn(256)))
					g.write(uint16(r.Intn(0x10000)), byte(r.Intn(256)))
					g.SetButton(r.Intn(8), r.Intn(2) == 0)
				}
				if err := g.StepChecked(); err != nil {
					g.locked, g.pc, g.halted = false, 0x100, false // restart after a lock-up
				}
			}
		}()
	}
}

func TestRandomPPUStateDoesNotPanic(t *testing.T) {
	r := rand.New(rand.NewSource(7))
	g := onlyOp(t, 0x18, 0xFE)
	for i := 0; i < 400; i++ {
		for a := 0; a < 8; a++ {
			g.writeIO(0xFF40+uint16(r.Intn(12)), byte(r.Intn(256)))
		}
		for j := 0; j < 0xA0; j++ {
			g.oam[j] = byte(r.Intn(256))
		}
		for j := 0; j < 0x2000; j += 3 {
			g.vram[j] = byte(r.Intn(256))
		}
		g.tickPPU(70224 / 4)
	}
}
