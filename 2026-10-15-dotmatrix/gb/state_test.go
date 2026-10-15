package gb

import (
	"bytes"
	"crypto/sha256"
	"os"
	"strings"
	"testing"

	"dotmatrix/asm"
)

func loadRomFile(t testing.TB, name string) *GB {
	t.Helper()
	src, err := os.ReadFile("../roms/" + name)
	if err != nil {
		t.Fatal(err)
	}
	r, err := asm.Assemble(name, string(src), asm.Options{Include: asm.FileInclude("../roms")})
	if err != nil {
		t.Fatal(err)
	}
	c, err := NewCart(r.ROM)
	if err != nil {
		t.Fatal(err)
	}
	return New(c)
}

func fingerprint(g *GB) [32]byte {
	h := sha256.New()
	h.Write(g.Framebuffer())
	h.Write(g.wram[:])
	h.Write(g.vram[:])
	h.Write(g.oam[:])
	return [32]byte(h.Sum(nil))
}

func runFrames(t testing.TB, g *GB, n int, keys map[int]string) {
	t.Helper()
	for i := 0; i < n; i++ {
		if k, ok := keys[i]; ok {
			switch k {
			case "start":
				g.SetButton(BtnStart, true)
			case "-start":
				g.SetButton(BtnStart, false)
			case "down":
				g.SetButton(BtnDown, true)
			}
		}
		if err := g.RunFrame(); err != nil {
			t.Fatal(err)
		}
	}
}

func TestSaveStateRoundTripIsDeterministic(t *testing.T) {
	g := loadRomFile(t, "snake.asm")
	runFrames(t, g, 30, map[int]string{5: "start", 6: "-start"})
	state := g.SaveState()
	runFrames(t, g, 120, map[int]string{20: "down"})
	want := fingerprint(g)
	wantCycles, wantFrames := g.Cycles, g.Frames

	// keep running (state diverges), then restore and replay the same inputs
	runFrames(t, g, 50, nil)
	if err := g.LoadState(state); err != nil {
		t.Fatal(err)
	}
	runFrames(t, g, 120, map[int]string{20: "down"})
	if fingerprint(g) != want || g.Cycles != wantCycles || g.Frames != wantFrames {
		t.Fatal("restored machine diverged from the original run")
	}

	// and a brand-new machine can load it too (this is the "reopen the emulator" case)
	g2 := loadRomFile(t, "snake.asm")
	if err := g2.LoadState(state); err != nil {
		t.Fatal(err)
	}
	runFrames(t, g2, 120, map[int]string{20: "down"})
	if fingerprint(g2) != want {
		t.Fatal("fresh machine restored from state diverged")
	}
}

func TestSaveStateKeepsCartridgeRAMAndBanking(t *testing.T) {
	c := markedROM(t, 0x13, 8, 3)
	g := New(c)
	c.WriteReg(0x0000, 0x0A)
	c.WriteReg(0x2000, 5)
	c.WriteReg(0x4000, 2)
	c.WriteRAM(0xA123, 0x77)
	st := g.SaveState()
	c.WriteReg(0x2000, 3)
	c.WriteReg(0x4000, 0)
	c.WriteRAM(0xA123, 0x11)
	if err := g.LoadState(st); err != nil {
		t.Fatal(err)
	}
	if c.ReadROM(0x4000) != 5 || c.ReadRAM(0xA123) != 0x77 {
		t.Errorf("bank=%d ram=%02X", c.ReadROM(0x4000), c.ReadRAM(0xA123))
	}
}

func TestSaveStateRejectsBadInput(t *testing.T) {
	g := loadRomFile(t, "snake.asm")
	runFrames(t, g, 5, nil)
	st := g.SaveState()
	before := fingerprint(g)
	cases := map[string][]byte{
		"empty":     nil,
		"bad magic": append([]byte("XXXX"), st[4:]...),
		"truncated": st[:len(st)/2],
		"trailing":  append(append([]byte{}, st...), 1, 2, 3),
		"version":   append(append([]byte{}, st[:4]...), append([]byte{99}, st[5:]...)...),
	}
	for name, data := range cases {
		if err := g.LoadState(data); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
	if fingerprint(g) != before {
		t.Error("a rejected state modified the machine")
	}
	other := loadRomFile(t, "cputest.asm")
	if err := other.LoadState(st); err == nil || !strings.Contains(err.Error(), "different cartridge") {
		t.Errorf("state from another ROM accepted: %v", err)
	}
	// determinism of the encoding itself
	if !bytes.Equal(g.SaveState(), g.SaveState()) {
		t.Error("SaveState is not deterministic")
	}
}
