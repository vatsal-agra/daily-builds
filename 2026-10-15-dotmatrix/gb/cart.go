package gb

import (
	"errors"
	"fmt"
	"strings"
)

// Cart is a parsed cartridge with its memory bank controller.
type Cart struct {
	ROM  []byte
	RAM  []byte
	Info Header

	mbc        int // 0 none, 1, 3, 5
	hasBattery bool
	hasRTC     bool

	ramEnable bool
	romBank   int // selected switchable bank (meaning depends on mbc)
	ramBank   int // RAM bank or RTC register select
	mode      int // MBC1 banking mode
	romMask   int // number of ROM banks - 1 (power of two)

	// MBC3 real-time clock
	rtc       [5]byte // S M H DL DH
	rtcLatch  [5]byte
	latchPrev byte
	rtcCycles uint64
}

// Header holds the cartridge header fields.
type Header struct {
	Title          string
	Type           byte
	TypeName       string
	ROMSize        int
	RAMSize        int
	HeaderChecksum byte
	HeaderOK       bool
	GlobalChecksum uint16
	GlobalOK       bool
	CGBFlag        byte
}

var typeNames = map[byte]string{
	0x00: "ROM ONLY", 0x01: "MBC1", 0x02: "MBC1+RAM", 0x03: "MBC1+RAM+BATTERY",
	0x0F: "MBC3+TIMER+BATTERY", 0x10: "MBC3+TIMER+RAM+BATTERY", 0x11: "MBC3",
	0x12: "MBC3+RAM", 0x13: "MBC3+RAM+BATTERY",
	0x19: "MBC5", 0x1A: "MBC5+RAM", 0x1B: "MBC5+RAM+BATTERY",
}

var ramSizes = map[byte]int{0: 0, 1: 2048, 2: 8192, 3: 32768, 4: 131072, 5: 65536}

// ParseHeader decodes the header of a ROM image.
func ParseHeader(rom []byte) (Header, error) {
	var h Header
	if len(rom) < 0x150 {
		return h, errors.New("ROM too small to contain a header (need at least 0x150 bytes)")
	}
	t := rom[0x134:0x144]
	n := 0
	for n < len(t) && t[n] != 0 {
		n++
	}
	h.Title = strings.Map(func(r rune) rune {
		if r < 32 || r > 126 {
			return '?'
		}
		return r
	}, string(t[:n]))
	h.Type = rom[0x147]
	h.TypeName = typeNames[h.Type]
	if h.TypeName == "" {
		h.TypeName = fmt.Sprintf("UNKNOWN(0x%02X)", h.Type)
	}
	if rom[0x148] > 8 {
		return h, fmt.Errorf("invalid ROM size code 0x%02X", rom[0x148])
	}
	h.ROMSize = 0x8000 << rom[0x148]
	h.RAMSize = ramSizes[rom[0x149]]
	h.CGBFlag = rom[0x143]
	h.HeaderChecksum = rom[0x14D]
	var x byte
	for i := 0x134; i <= 0x14C; i++ {
		x = x - rom[i] - 1
	}
	h.HeaderOK = x == h.HeaderChecksum
	h.GlobalChecksum = uint16(rom[0x14E])<<8 | uint16(rom[0x14F])
	var sum uint16
	for i, b := range rom {
		if i == 0x14E || i == 0x14F {
			continue
		}
		sum += uint16(b)
	}
	h.GlobalOK = sum == h.GlobalChecksum
	return h, nil
}

// HeaderChecksumOf computes the header checksum for a ROM image.
func HeaderChecksumOf(rom []byte) byte {
	var x byte
	for i := 0x134; i <= 0x14C; i++ {
		x = x - rom[i] - 1
	}
	return x
}

// NewCart builds a cartridge from a ROM image. The image is padded up to the
// size declared in its header so bank masks behave like real hardware.
func NewCart(rom []byte) (*Cart, error) {
	h, err := ParseHeader(rom)
	if err != nil {
		return nil, err
	}
	c := &Cart{Info: h}
	switch h.Type {
	case 0x00:
		c.mbc = 0
	case 0x01, 0x02, 0x03:
		c.mbc = 1
	case 0x0F, 0x10, 0x11, 0x12, 0x13:
		c.mbc = 3
	case 0x19, 0x1A, 0x1B:
		c.mbc = 5
	default:
		return nil, fmt.Errorf("unsupported cartridge type 0x%02X (%s)", h.Type, h.TypeName)
	}
	c.hasBattery = h.Type == 0x03 || h.Type == 0x0F || h.Type == 0x10 || h.Type == 0x13 || h.Type == 0x1B
	c.hasRTC = h.Type == 0x0F || h.Type == 0x10
	size := h.ROMSize
	if len(rom) > size {
		size = len(rom)
	}
	// round up to a power of two number of 16 KiB banks
	banks := 2
	for banks*0x4000 < size {
		banks <<= 1
	}
	c.ROM = make([]byte, banks*0x4000)
	for i := range c.ROM {
		c.ROM[i] = 0xFF
	}
	copy(c.ROM, rom)
	c.romMask = banks - 1
	c.RAM = make([]byte, h.RAMSize)
	c.romBank = 1
	return c, nil
}

func (c *Cart) bankFor0000() int {
	if c.mbc == 1 && c.mode == 1 {
		return (c.ramBank << 5) & c.romMask
	}
	return 0
}

func (c *Cart) bankFor4000() int {
	switch c.mbc {
	case 1:
		b := c.romBank & 0x1F
		if b == 0 {
			b = 1
		}
		return (b | c.ramBank<<5) & c.romMask
	case 3:
		b := c.romBank & 0x7F
		if b == 0 {
			b = 1
		}
		return b & c.romMask
	case 5:
		return c.romBank & c.romMask
	}
	return 1 & c.romMask
}

// ReadROM reads 0x0000-0x7FFF.
func (c *Cart) ReadROM(addr uint16) byte {
	if addr < 0x4000 {
		return c.ROM[c.bankFor0000()*0x4000+int(addr)]
	}
	return c.ROM[c.bankFor4000()*0x4000+int(addr-0x4000)]
}

func (c *Cart) ramIndex(addr uint16) int {
	if len(c.RAM) == 0 {
		return -1
	}
	bank := 0
	switch c.mbc {
	case 1:
		if c.mode == 1 {
			bank = c.ramBank & 3
		}
	case 3:
		bank = c.ramBank & 3
	case 5:
		bank = c.ramBank & 0xF
	}
	i := bank*0x2000 + int(addr-0xA000)
	if len(c.RAM) <= 0x2000 { // 2 KiB / 8 KiB chips mirror within themselves
		i = int(addr-0xA000) % len(c.RAM)
	} else {
		i %= len(c.RAM)
	}
	return i
}

// ReadRAM reads 0xA000-0xBFFF.
func (c *Cart) ReadRAM(addr uint16) byte {
	if !c.ramEnable {
		return 0xFF
	}
	if c.mbc == 3 && c.ramBank >= 8 && c.ramBank <= 0xC {
		if c.hasRTC {
			return c.rtcLatch[c.ramBank-8]
		}
		return 0xFF
	}
	i := c.ramIndex(addr)
	if i < 0 {
		return 0xFF
	}
	return c.RAM[i]
}

// WriteRAM writes 0xA000-0xBFFF.
func (c *Cart) WriteRAM(addr uint16, v byte) {
	if !c.ramEnable {
		return
	}
	if c.mbc == 3 && c.ramBank >= 8 && c.ramBank <= 0xC {
		if c.hasRTC {
			c.rtc[c.ramBank-8] = v
		}
		return
	}
	if i := c.ramIndex(addr); i >= 0 {
		c.RAM[i] = v
	}
}

// WriteReg handles writes to 0x0000-0x7FFF (MBC control registers).
func (c *Cart) WriteReg(addr uint16, v byte) {
	switch c.mbc {
	case 1:
		switch {
		case addr < 0x2000:
			c.ramEnable = v&0x0F == 0x0A
		case addr < 0x4000:
			c.romBank = int(v & 0x1F)
		case addr < 0x6000:
			c.ramBank = int(v & 3)
		default:
			c.mode = int(v & 1)
		}
	case 3:
		switch {
		case addr < 0x2000:
			c.ramEnable = v&0x0F == 0x0A
		case addr < 0x4000:
			c.romBank = int(v & 0x7F)
		case addr < 0x6000:
			c.ramBank = int(v)
		default:
			if c.latchPrev == 0 && v == 1 {
				c.rtcLatch = c.rtc
			}
			c.latchPrev = v
		}
	case 5:
		switch {
		case addr < 0x2000:
			c.ramEnable = v&0x0F == 0x0A
		case addr < 0x3000:
			c.romBank = c.romBank&0x100 | int(v)
		case addr < 0x4000:
			c.romBank = c.romBank&0xFF | int(v&1)<<8
		case addr < 0x6000:
			c.ramBank = int(v & 0xF)
		}
	}
}

// tickRTC advances the MBC3 clock by the given number of T-cycles.
func (c *Cart) tickRTC(cycles int) {
	if !c.hasRTC || c.rtc[4]&0x40 != 0 { // halted
		return
	}
	c.rtcCycles += uint64(cycles)
	for c.rtcCycles >= 4194304 {
		c.rtcCycles -= 4194304
		c.rtc[0]++
		if c.rtc[0] < 60 {
			continue
		}
		c.rtc[0] = 0
		c.rtc[1]++
		if c.rtc[1] < 60 {
			continue
		}
		c.rtc[1] = 0
		c.rtc[2]++
		if c.rtc[2] < 24 {
			continue
		}
		c.rtc[2] = 0
		days := int(c.rtc[3]) | int(c.rtc[4]&1)<<8
		days++
		if days > 511 {
			days = 0
			c.rtc[4] |= 0x80
		}
		c.rtc[3] = byte(days)
		c.rtc[4] = c.rtc[4]&^1 | byte(days>>8)
	}
}

// Battery reports whether the cartridge has battery-backed RAM.
func (c *Cart) Battery() bool { return c.hasBattery && len(c.RAM) > 0 }
