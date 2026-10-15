package gb

import (
	"fmt"
	"strings"
	"testing"

	"dotmatrix/asm"
)

// markedROM builds a cartridge of n 16 KiB banks where byte 0 and 0x3FFF of each bank hold the bank number (low byte) / high byte.
func markedROM(t testing.TB, typ, banks, ramCode int) *Cart {
	t.Helper()
	var sb strings.Builder
	fmt.Fprintf(&sb, "\t.cart %d\n\t.ramsize %d\n\t.org 0x100\n\tnop\n\tjp 0x150\n\t.org 0x150\n\tnop\n", typ, ramCode)
	for b := 1; b < banks; b++ {
		fmt.Fprintf(&sb, "\t.bank %d\n\t.db %d, %d\n", b, b&0xFF, b>>8)
	}
	r, err := asm.Assemble("m.s", sb.String(), asm.Options{})
	if err != nil {
		t.Fatal(err)
	}
	// header size code is derived from content; force the declared size for bank-count tests
	rom := make([]byte, banks*0x4000)
	copy(rom, r.ROM)
	for b := 1; b < banks; b++ {
		rom[b*0x4000] = byte(b)
		rom[b*0x4000+1] = byte(b >> 8)
	}
	rom[0x148] = 0
	for 0x8000<<rom[0x148] < len(rom) {
		rom[0x148]++
	}
	rom[0x14D] = HeaderChecksumOf(rom)
	c, err := NewCart(rom)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestHeaderParsing(t *testing.T) {
	r, err := asm.Assemble("h.s", ".title \"TESTCART\"\n.cart 3\n.ramsize 2\n.org 0x150\nnop\n", asm.Options{})
	if err != nil {
		t.Fatal(err)
	}
	h, err := ParseHeader(r.ROM)
	if err != nil {
		t.Fatal(err)
	}
	if h.Title != "TESTCART" || h.Type != 3 || h.TypeName != "MBC1+RAM+BATTERY" || h.RAMSize != 8192 || h.ROMSize != 0x8000 {
		t.Errorf("header: %+v", h)
	}
	if !h.HeaderOK || !h.GlobalOK {
		t.Errorf("checksums should validate: %+v", h)
	}
	bad := append([]byte{}, r.ROM...)
	bad[0x134] ^= 0xFF
	h, _ = ParseHeader(bad)
	if h.HeaderOK {
		t.Error("corrupted header accepted")
	}
	bad = append([]byte{}, r.ROM...)
	bad[0x200] ^= 1
	h, _ = ParseHeader(bad)
	if h.GlobalOK {
		t.Error("corrupted body accepted by global checksum")
	}
	if _, err := ParseHeader(make([]byte, 0x100)); err == nil {
		t.Error("tiny ROM accepted")
	}
	bad = append([]byte{}, r.ROM...)
	bad[0x148] = 0x20
	if _, err := ParseHeader(bad); err == nil {
		t.Error("bad ROM size code accepted")
	}
	bad = append([]byte{}, r.ROM...)
	bad[0x147] = 0xFC // pocket camera
	if _, err := NewCart(bad); err == nil || !strings.Contains(err.Error(), "unsupported") {
		t.Errorf("unsupported mapper: %v", err)
	}
}

func TestMBC1RomBanking(t *testing.T) {
	c := markedROM(t, 1, 8, 0)
	if c.ReadROM(0x4000) != 1 {
		t.Fatalf("power-on bank = %d", c.ReadROM(0x4000))
	}
	for _, n := range []int{2, 3, 7} {
		c.WriteReg(0x2000, byte(n))
		if got := c.ReadROM(0x4000); int(got) != n {
			t.Errorf("select %d -> bank %d", n, got)
		}
	}
	c.WriteReg(0x2000, 0)
	if c.ReadROM(0x4000) != 1 {
		t.Error("bank 0 must map to bank 1")
	}
	c.WriteReg(0x2000, 9) // only 8 banks: mask wraps to 1
	if c.ReadROM(0x4000) != 1 {
		t.Errorf("out-of-range bank 9 should wrap to 1, got %d", c.ReadROM(0x4000))
	}
	c.WriteReg(0x2000, 0x22)
	if got := c.ReadROM(0x4000); got != 2 {
		t.Errorf("only the low 5 bits count: bank %d", got)
	}
}

func TestMBC1LargeRomAndMode(t *testing.T) {
	c := markedROM(t, 1, 64, 0) // 1 MiB
	c.WriteReg(0x2000, 1)
	c.WriteReg(0x4000, 1) // upper bits = 1 -> banks 32..63
	if got := c.ReadROM(0x4000); got != 33 {
		t.Errorf("upper bits: bank %d want 33", got)
	}
	if c.ReadROM(0x0000) != 0 {
		t.Error("mode 0: bank 0 area fixed")
	}
	c.WriteReg(0x6000, 1) // mode 1
	if got := c.ReadROM(0x0000); got != 32 {
		t.Errorf("mode 1 remaps 0000-3FFF to bank 32, got marker %d", got)
	}
	c.WriteReg(0x2000, 0) // the 0->1 quirk applies on the low 5 bits only
	if got := c.ReadROM(0x4000); got != 33 {
		t.Errorf("bank 0x20 quirk: %d want 33", got)
	}
}

func TestMBC1RAM(t *testing.T) {
	c := markedROM(t, 3, 4, 3) // 32 KiB RAM
	c.WriteRAM(0xA000, 0x12)
	if c.ReadRAM(0xA000) != 0xFF {
		t.Error("RAM disabled should read FF")
	}
	c.WriteReg(0x0000, 0x0A)
	c.WriteRAM(0xA000, 0x12)
	if c.ReadRAM(0xA000) != 0x12 {
		t.Error("RAM write lost")
	}
	// mode 0 uses bank 0 only
	c.WriteReg(0x4000, 1)
	if c.ReadRAM(0xA000) != 0x12 {
		t.Error("mode 0 must ignore RAM bank")
	}
	c.WriteReg(0x6000, 1)
	if c.ReadRAM(0xA000) == 0x12 {
		t.Error("mode 1 RAM bank 1 should differ")
	}
	c.WriteRAM(0xA000, 0x34)
	c.WriteReg(0x4000, 0)
	if c.ReadRAM(0xA000) != 0x12 {
		t.Error("bank 0 clobbered")
	}
	c.WriteReg(0x0000, 0x00)
	if c.ReadRAM(0xA000) != 0xFF {
		t.Error("RAM disable ignored")
	}
	if !c.Battery() {
		t.Error("type 3 has a battery")
	}
}

func TestMBC3(t *testing.T) {
	c := markedROM(t, 0x10, 128, 3)
	c.WriteReg(0x2000, 0x7F)
	if c.ReadROM(0x4000) != 0x7F {
		t.Errorf("bank 127 -> %d", c.ReadROM(0x4000))
	}
	c.WriteReg(0x2000, 0)
	if c.ReadROM(0x4000) != 1 {
		t.Error("bank 0 -> 1")
	}
	c.WriteReg(0x0000, 0x0A)
	for b := 0; b < 4; b++ {
		c.WriteReg(0x4000, byte(b))
		c.WriteRAM(0xA000, byte(0x50+b))
	}
	for b := 0; b < 4; b++ {
		c.WriteReg(0x4000, byte(b))
		if c.ReadRAM(0xA000) != byte(0x50+b) {
			t.Errorf("RAM bank %d", b)
		}
	}
	// RTC: select seconds, tick 5 seconds, latch, read
	c.WriteReg(0x4000, 0x08)
	c.WriteRAM(0xA000, 0)
	c.tickRTC(5 * 4194304)
	if c.ReadRAM(0xA000) != 0 {
		t.Error("RTC visible before latch")
	}
	c.WriteReg(0x6000, 0)
	c.WriteReg(0x6000, 1)
	if c.ReadRAM(0xA000) != 5 {
		t.Errorf("RTC seconds = %d", c.ReadRAM(0xA000))
	}
	// roll over to minutes
	c.tickRTC(56 * 4194304)
	c.WriteReg(0x6000, 0)
	c.WriteReg(0x6000, 1)
	c.WriteReg(0x4000, 0x09)
	if c.ReadRAM(0xA000) != 1 {
		t.Errorf("RTC minutes = %d", c.ReadRAM(0xA000))
	}
	c.WriteReg(0x4000, 0x08)
	if c.ReadRAM(0xA000) != 1 {
		t.Errorf("RTC seconds after rollover = %d", c.ReadRAM(0xA000))
	}
	// halt flag stops the clock
	c.WriteReg(0x4000, 0x0C)
	c.WriteRAM(0xA000, 0x40)
	c.tickRTC(10 * 4194304)
	c.WriteReg(0x6000, 0)
	c.WriteReg(0x6000, 1)
	c.WriteReg(0x4000, 0x08)
	if c.ReadRAM(0xA000) != 1 {
		t.Errorf("halted RTC advanced: %d", c.ReadRAM(0xA000))
	}
}

func TestMBC5(t *testing.T) {
	c := markedROM(t, 0x19, 512, 0)
	c.WriteReg(0x2000, 0xFF)
	c.WriteReg(0x3000, 1)
	if c.ReadROM(0x4000) != 0xFF || c.ReadROM(0x4001) != 1 {
		t.Errorf("9-bit bank 0x1FF: %d,%d", c.ReadROM(0x4000), c.ReadROM(0x4001))
	}
	c.WriteReg(0x2000, 0)
	c.WriteReg(0x3000, 0)
	if c.ReadROM(0x4000) != 0 && c.ReadROM(0x4001) != 0 {
		// MBC5 can map bank 0 into the switchable window
		t.Errorf("bank 0 in window: %d", c.ReadROM(0x4000))
	}
}

func TestROMOnlyIgnoresWrites(t *testing.T) {
	c := markedROM(t, 0, 2, 0)
	c.WriteReg(0x2000, 5)
	if c.ReadROM(0x4000) != 1 {
		t.Error("ROM ONLY bank changed")
	}
	if c.ReadRAM(0xA000) != 0xFF {
		t.Error("no RAM should read FF")
	}
}
