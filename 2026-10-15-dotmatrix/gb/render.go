package gb

import "sort"

type sprite struct {
	x, y     int // screen position of top-left (may be negative)
	tile     byte
	attr     byte
	oamIndex int
}

// lineSprites returns the (up to 10) sprites that intersect the current line,
// in OAM order, exactly as the hardware's OAM scan selects them.
func (p *ppu) lineSprites(g *GB) []sprite {
	h := 8
	if p.lcdc&4 != 0 {
		h = 16
	}
	var out []sprite
	ly := int(p.ly)
	for i := 0; i < 40 && len(out) < 10; i++ {
		y := int(g.oam[i*4]) - 16
		if ly >= y && ly < y+h {
			out = append(out, sprite{
				x: int(g.oam[i*4+1]) - 8, y: y,
				tile: g.oam[i*4+2], attr: g.oam[i*4+3], oamIndex: i,
			})
		}
	}
	return out
}

func (g *GB) tileRowBits(addr int, row int) (lo, hi byte) {
	a := (addr + row*2) & 0x1FFF
	return g.vram[a], g.vram[(a+1)&0x1FFF]
}

// renderLine draws the current scanline into the back buffer.
func (p *ppu) renderLine(g *GB) {
	ly := int(p.ly)
	row := p.back[ly*ScreenW : (ly+1)*ScreenW]

	bgOn := p.lcdc&1 != 0
	winOn := bgOn && p.lcdc&0x20 != 0 && ly >= int(p.wy) && int(p.wx) <= 166
	winX := int(p.wx) - 7

	for x := 0; x < ScreenW; x++ {
		var ci byte
		if bgOn {
			var mapBase, px, py int
			if winOn && x >= winX {
				mapBase = 0x1800
				if p.lcdc&0x40 != 0 {
					mapBase = 0x1C00
				}
				px = x - winX
				py = p.winLine
				p.winActive = true
			} else {
				mapBase = 0x1800
				if p.lcdc&0x08 != 0 {
					mapBase = 0x1C00
				}
				px = (x + int(p.scx)) & 0xFF
				py = (ly + int(p.scy)) & 0xFF
			}
			idx := g.vram[mapBase+(py>>3)*32+(px>>3)]
			var base int
			if p.lcdc&0x10 != 0 {
				base = int(idx) * 16
			} else {
				base = 0x1000 + int(int8(idx))*16
			}
			lo, hi := g.tileRowBits(base, py&7)
			bit := uint(7 - px&7)
			ci = (lo>>bit)&1 | ((hi>>bit)&1)<<1
		}
		p.bgRaw[x] = ci
		row[x] = (p.bgp >> (ci * 2)) & 3
	}

	if p.lcdc&2 != 0 {
		p.drawSprites(g, row)
	}
}

func (p *ppu) drawSprites(g *GB, row []byte) {
	sp := p.lineSprites(g)
	if len(sp) == 0 {
		return
	}
	// DMG priority: smaller X wins; ties go to the lower OAM index.
	sort.SliceStable(sp, func(i, j int) bool {
		if sp[i].x != sp[j].x {
			return sp[i].x < sp[j].x
		}
		return sp[i].oamIndex < sp[j].oamIndex
	})
	h := 8
	if p.lcdc&4 != 0 {
		h = 16
	}
	var claimed [ScreenW]bool
	ly := int(p.ly)
	for _, s := range sp {
		line := ly - s.y
		if s.attr&0x40 != 0 { // Y flip
			line = h - 1 - line
		}
		tile := int(s.tile)
		if h == 16 {
			tile &= 0xFE
		}
		lo, hi := g.tileRowBits(tile*16, line)
		pal := p.obp0
		if s.attr&0x10 != 0 {
			pal = p.obp1
		}
		for i := 0; i < 8; i++ {
			x := s.x + i
			if x < 0 || x >= ScreenW || claimed[x] {
				continue
			}
			bit := uint(7 - i)
			if s.attr&0x20 != 0 { // X flip
				bit = uint(i)
			}
			ci := (lo>>bit)&1 | ((hi>>bit)&1)<<1
			if ci == 0 {
				continue
			}
			claimed[x] = true
			if s.attr&0x80 != 0 && p.bgRaw[x] != 0 {
				continue
			}
			row[x] = (pal >> (ci * 2)) & 3
		}
	}
}
