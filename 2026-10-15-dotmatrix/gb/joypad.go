package gb

type joypad struct {
	keys uint8 // bit set = released. low nibble: right,left,up,down  high nibble: a,b,select,start
	sel  uint8 // P1 bits 4/5 (0 = group selected)
}

func (j *joypad) lines() uint8 {
	v := uint8(0x0F)
	if j.sel&0x10 == 0 { // d-pad
		v &= j.keys & 0x0F
	}
	if j.sel&0x20 == 0 { // buttons
		v &= j.keys >> 4
	}
	return v
}

func (g *GB) joypadRead() byte {
	return 0xC0 | g.Joy.sel | g.Joy.lines()
}

func (g *GB) joypadWrite(v byte) {
	before := g.Joy.lines()
	g.Joy.sel = v & 0x30
	if before&^g.Joy.lines() != 0 {
		g.ifl |= IntJoypad
	}
}

func (g *GB) joypadSet(btn int, down bool) {
	if btn < 0 || btn > 7 {
		return
	}
	before := g.Joy.lines()
	if down {
		g.Joy.keys &^= 1 << uint(btn)
	} else {
		g.Joy.keys |= 1 << uint(btn)
	}
	if before&^g.Joy.lines() != 0 {
		g.ifl |= IntJoypad
	}
}
