package gb

type ppu struct {
	lcdc, stat, scy, scx, ly, lyc byte
	bgp, obp0, obp1, wy, wx       byte

	mode      byte
	dot       int // dot within the current line (0..455)
	mode3Len  int
	winLine   int  // window internal line counter
	winActive bool // window was drawn this line
	statLine  bool // previous STAT interrupt line level
	skipFrame bool // first frame after LCD enable is blank

	back  [ScreenW * ScreenH]byte // being drawn
	front [ScreenW * ScreenH]byte // last completed frame
	bgRaw [ScreenW]byte           // BG colour index (pre-palette) of the current line, for sprite priority
}

func (p *ppu) lcdOn() bool { return p.lcdc&0x80 != 0 }

func (p *ppu) readStat() byte {
	m := p.mode
	if !p.lcdOn() {
		m = 0
	}
	v := p.stat&0x78 | 0x80 | m
	if p.lcdOn() && p.ly == p.lyc {
		v |= 4
	}
	return v
}

func (p *ppu) writeStat(g *GB, v byte) {
	p.stat = v & 0x78
	p.updateStatLine(g)
}

func (p *ppu) writeLCDC(g *GB, v byte) {
	was := p.lcdOn()
	p.lcdc = v
	if was && !p.lcdOn() {
		p.ly = 0
		p.dot = 0
		p.mode = 0
		p.winLine = 0
		p.statLine = false
		// the screen goes blank (white) while the LCD is off
		for i := range p.front {
			p.front[i] = 0
		}
	} else if !was && p.lcdOn() {
		p.ly = 0
		p.dot = 0
		p.mode = 2
		p.skipFrame = true
		p.updateStatLine(g)
	}
}

func (p *ppu) updateLYC(g *GB) { p.updateStatLine(g) }

// updateStatLine recomputes the STAT interrupt line and raises IF on a rising edge.
func (p *ppu) updateStatLine(g *GB) {
	if !p.lcdOn() {
		p.statLine = false
		return
	}
	line := false
	switch p.mode {
	case 0:
		line = p.stat&0x08 != 0
	case 1:
		line = p.stat&0x10 != 0
	case 2:
		line = p.stat&0x20 != 0
	}
	if p.ly == p.lyc && p.stat&0x40 != 0 {
		line = true
	}
	if line && !p.statLine {
		g.ifl |= IntSTAT
	}
	p.statLine = line
}

func (p *ppu) setMode(g *GB, m byte) {
	p.mode = m
	p.updateStatLine(g)
}

// tickPPU advances the PPU by t T-cycles.
func (g *GB) tickPPU(t int) {
	p := &g.PPU
	if !p.lcdOn() {
		return
	}
	for ; t > 0; t-- {
		p.dot++
		switch {
		case p.ly < 144:
			switch {
			case p.dot == 80:
				p.mode3Len = p.computeMode3Len(g)
				p.setMode(g, 3)
			case p.dot == 80+p.mode3Len && p.mode == 3:
				p.renderLine(g)
				p.setMode(g, 0)
			}
		}
		if p.dot == 456 {
			p.dot = 0
			if p.winActive {
				p.winLine++
				p.winActive = false
			}
			p.ly++
			switch {
			case p.ly == 144:
				g.Frames++
				if p.skipFrame {
					p.skipFrame = false
				} else {
					p.front = p.back
				}
				g.ifl |= IntVBlank
				p.setMode(g, 1)
			case p.ly == 154:
				p.ly = 0
				p.winLine = 0
				p.setMode(g, 2)
			case p.ly < 144:
				p.setMode(g, 2)
			}
			p.updateStatLine(g)
		}
		// STAT/LYC coincidence changes with LY
		if p.dot == 0 {
			p.updateStatLine(g)
		}
	}
	_ = g
}

// computeMode3Len approximates the variable length of the drawing phase:
// 172 dots plus SCX fine-scroll, window and per-sprite fetch penalties.
func (p *ppu) computeMode3Len(g *GB) int {
	n := 172 + int(p.scx&7) + 6*len(p.lineSprites(g))
	if p.lcdc&0x20 != 0 && p.ly >= p.wy && p.wx <= 166 {
		n += 6
	}
	return n
}
