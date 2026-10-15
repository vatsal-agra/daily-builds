package gb

// read is a CPU-visible read: honours PPU access blocking and OAM DMA.
func (g *GB) read(addr uint16) byte {
	if g.Dbg != nil {
		g.Dbg.noteRead(g, addr)
	}
	if g.dma.active && g.dma.start == 0 && addr < 0xFF00 {
		// While OAM DMA runs the CPU only sees HRAM and IO; everything else floats high.
		return 0xFF
	}
	switch {
	case addr >= 0x8000 && addr < 0xA000:
		if g.PPU.lcdOn() && g.PPU.mode == 3 {
			return 0xFF
		}
	case addr >= 0xFE00 && addr < 0xFEA0:
		if g.dma.active || (g.PPU.lcdOn() && g.PPU.mode >= 2) {
			return 0xFF
		}
	}
	return g.peek(addr)
}

// peek reads without any blocking or side effects (debugger / DMA / PPU).
func (g *GB) peek(addr uint16) byte {
	switch {
	case addr < 0x8000:
		return g.Cart.ReadROM(addr)
	case addr < 0xA000:
		return g.vram[addr-0x8000]
	case addr < 0xC000:
		return g.Cart.ReadRAM(addr)
	case addr < 0xE000:
		return g.wram[addr-0xC000]
	case addr < 0xFE00:
		return g.wram[addr-0xE000]
	case addr < 0xFEA0:
		return g.oam[addr-0xFE00]
	case addr < 0xFF00:
		return 0xFF // prohibited area
	case addr < 0xFF80:
		return g.readIO(addr)
	case addr < 0xFFFF:
		return g.hram[addr-0xFF80]
	}
	return g.ie
}

func (g *GB) write(addr uint16, v byte) {
	if g.Dbg != nil {
		g.Dbg.noteWrite(g, addr, v)
	}
	if g.dma.active && g.dma.start == 0 && addr < 0xFF00 {
		return
	}
	switch {
	case addr < 0x8000:
		g.Cart.WriteReg(addr, v)
	case addr < 0xA000:
		if g.PPU.lcdOn() && g.PPU.mode == 3 {
			return
		}
		g.vram[addr-0x8000] = v
	case addr < 0xC000:
		g.Cart.WriteRAM(addr, v)
	case addr < 0xE000:
		g.wram[addr-0xC000] = v
	case addr < 0xFE00:
		g.wram[addr-0xE000] = v
	case addr < 0xFEA0:
		if g.dma.active || (g.PPU.lcdOn() && g.PPU.mode >= 2) {
			return
		}
		g.oam[addr-0xFE00] = v
	case addr < 0xFF00:
		// prohibited
	case addr < 0xFF80:
		g.writeIO(addr, v)
	case addr < 0xFFFF:
		g.hram[addr-0xFF80] = v
	default:
		g.ie = v
	}
}

func (g *GB) readIO(addr uint16) byte {
	switch addr {
	case 0xFF00:
		return g.joypadRead()
	case 0xFF01:
		return g.io[1]
	case 0xFF02:
		return g.io[2] | 0x7E
	case 0xFF04:
		return byte(g.Timer.counter >> 8)
	case 0xFF05:
		return g.Timer.tima
	case 0xFF06:
		return g.Timer.tma
	case 0xFF07:
		return g.Timer.tac | 0xF8
	case 0xFF0F:
		return g.ifl | 0xE0
	case 0xFF40:
		return g.PPU.lcdc
	case 0xFF41:
		return g.PPU.readStat()
	case 0xFF42:
		return g.PPU.scy
	case 0xFF43:
		return g.PPU.scx
	case 0xFF44:
		return g.PPU.ly
	case 0xFF45:
		return g.PPU.lyc
	case 0xFF46:
		return g.dma.srcReg()
	case 0xFF47:
		return g.PPU.bgp
	case 0xFF48:
		return g.PPU.obp0
	case 0xFF49:
		return g.PPU.obp1
	case 0xFF4A:
		return g.PPU.wy
	case 0xFF4B:
		return g.PPU.wx
	}
	if addr >= 0xFF10 && addr <= 0xFF3F {
		return g.APU.read(addr)
	}
	return 0xFF
}

func (d *dmaState) srcReg() byte { return byte(d.src >> 8) }

func (g *GB) writeIO(addr uint16, v byte) {
	switch addr {
	case 0xFF00:
		g.joypadWrite(v)
	case 0xFF01:
		g.io[1] = v
	case 0xFF02:
		g.io[2] = v
		if v&0x81 == 0x81 {
			g.serial.active = true
			g.serial.left = 8 * 512 // 8 bits at 8192 Hz
		}
	case 0xFF04:
		g.timerWriteDiv()
	case 0xFF05:
		g.timerWriteTima(v)
	case 0xFF06:
		g.Timer.tma = v
	case 0xFF07:
		g.timerWriteTac(v)
	case 0xFF0F:
		g.ifl = v & 0x1F
	case 0xFF40:
		g.PPU.writeLCDC(g, v)
	case 0xFF41:
		g.PPU.writeStat(g, v)
	case 0xFF42:
		g.PPU.scy = v
	case 0xFF43:
		g.PPU.scx = v
	case 0xFF44:
		// read-only
	case 0xFF45:
		g.PPU.lyc = v
		g.PPU.updateLYC(g)
	case 0xFF46:
		g.dma.active = true
		g.dma.src = uint16(v) << 8
		g.dma.idx = 0
		g.dma.start = 1
	case 0xFF47:
		g.PPU.bgp = v
	case 0xFF48:
		g.PPU.obp0 = v
	case 0xFF49:
		g.PPU.obp1 = v
	case 0xFF4A:
		g.PPU.wy = v
	case 0xFF4B:
		g.PPU.wx = v
	default:
		if addr >= 0xFF10 && addr <= 0xFF3F {
			g.APU.write(addr, v)
		}
	}
}

// tickDMA advances OAM DMA by one M-cycle.
func (g *GB) tickDMA() {
	if !g.dma.active {
		return
	}
	if g.dma.start > 0 {
		g.dma.start--
		return
	}
	src := g.dma.src
	if src >= 0xE000 { // sources above DFFF mirror WRAM
		src -= 0x2000
	}
	g.oam[g.dma.idx] = g.peek(src + uint16(g.dma.idx))
	g.dma.idx++
	if g.dma.idx >= 0xA0 {
		g.dma.active = false
	}
}

func (g *GB) tickSerial() {
	if !g.serial.active {
		return
	}
	g.serial.left -= 4
	if g.serial.left <= 0 {
		g.serial.active = false
		g.Serial = append(g.Serial, g.io[1])
		g.io[1] = 0xFF // nothing connected: receive all ones
		g.io[2] &^= 0x80
		g.ifl |= IntSerial
	}
}

// Peek exposes side-effect-free memory reads to tools.
func (g *GB) Peek(addr uint16) byte { return g.peek(addr) }

// Poke writes memory directly, bypassing PPU/DMA blocking (debugger use).
func (g *GB) Poke(addr uint16, v byte) {
	switch {
	case addr >= 0x8000 && addr < 0xA000:
		g.vram[addr-0x8000] = v
	case addr >= 0xFE00 && addr < 0xFEA0:
		g.oam[addr-0xFE00] = v
	default:
		g.write(addr, v)
	}
}
