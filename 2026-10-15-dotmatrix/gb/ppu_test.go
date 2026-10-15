package gb

import "testing"

func blank(t testing.TB) *GB {
	g := onlyOp(t, 0x18, 0xFE) // jr -2 : spin
	return g
}

// setTile writes a tile whose pixel (x,y) colour index is f(x,y).
func setTile(g *GB, addr uint16, f func(x, y int) int) {
	for y := 0; y < 8; y++ {
		var lo, hi byte
		for x := 0; x < 8; x++ {
			c := f(x, y)
			lo |= byte(c&1) << uint(7-x)
			hi |= byte(c>>1) << uint(7-x)
		}
		g.Poke(addr+uint16(y*2), lo)
		g.Poke(addr+uint16(y*2)+1, hi)
	}
}

func frame(t testing.TB, g *GB) []byte {
	t.Helper()
	if err := g.RunFrame(); err != nil {
		t.Fatal(err)
	}
	// RunFrame returns at VBlank start; the front buffer holds the frame just drawn.
	return g.Framebuffer()
}

func px(fb []byte, x, y int) byte { return fb[y*ScreenW+x] }

func TestLineTimingAndModes(t *testing.T) {
	g := blank(t)
	g.writeIO(0xFF40, 0)
	g.writeIO(0xFF40, 0x91)
	if g.PPU.ly != 0 || g.PPU.mode != 2 {
		t.Fatalf("after enable ly=%d mode=%d", g.PPU.ly, g.PPU.mode)
	}
	want := func(dots int, ly, mode byte) {
		t.Helper()
		g.tickPPU(dots)
		if g.PPU.ly != ly || g.PPU.mode != mode {
			t.Fatalf("expected ly=%d mode=%d, got ly=%d mode=%d (dot %d)", ly, mode, g.PPU.ly, g.PPU.mode, g.PPU.dot)
		}
	}
	want(79, 0, 2)
	want(1, 0, 3) // dot 80: drawing begins
	want(171, 0, 3)
	want(1, 0, 0)   // dot 252: HBlank
	want(203, 0, 0) // dot 455
	want(1, 1, 2)
	for ly := byte(2); ly <= 143; ly++ {
		want(456, ly, 2)
	}
	want(456, 144, 1)
	want(456*9, 153, 1)
	want(456, 0, 2)
}

func TestVBlankInterruptTiming(t *testing.T) {
	g := blank(t)
	g.ifl = 0
	g.tickPPU(144*456 - 1)
	if g.ifl&IntVBlank != 0 {
		t.Fatal("VBlank flagged early")
	}
	g.tickPPU(1)
	if g.ifl&IntVBlank == 0 || g.Frames != 1 {
		t.Fatalf("VBlank not flagged at line 144: if=%02X frames=%d", g.ifl, g.Frames)
	}
}

func TestSTATInterrupts(t *testing.T) {
	// LYC coincidence
	g := blank(t)
	g.ifl = 0
	g.writeIO(0xFF45, 10)
	g.writeIO(0xFF41, 0x40)
	g.tickPPU(10*456 - 1)
	if g.ifl&IntSTAT != 0 {
		t.Fatal("LYC interrupt early")
	}
	g.tickPPU(1)
	if g.ifl&IntSTAT == 0 {
		t.Fatal("LYC interrupt missing")
	}
	if g.readIO(0xFF41)&4 == 0 {
		t.Error("coincidence flag not set")
	}
	g.ifl = 0
	g.tickPPU(300) // still on line 10: must not re-fire
	if g.ifl&IntSTAT != 0 {
		t.Error("STAT re-fired on the same line")
	}
	g.tickPPU(456)
	if g.readIO(0xFF41)&4 != 0 {
		t.Error("coincidence flag stuck")
	}

	// HBlank (mode 0) source fires once per visible line
	g = blank(t)
	g.ifl = 0
	g.writeIO(0xFF41, 0x08)
	n := 0
	for i := 0; i < 154*456; i++ {
		g.tickPPU(1)
		if g.ifl&IntSTAT != 0 {
			n++
			g.ifl = 0
		}
	}
	if n != 144 {
		t.Errorf("mode-0 STAT fired %d times per frame, want 144", n)
	}

	// VBlank (mode 1) source: once per frame
	g = blank(t)
	g.ifl = 0
	g.writeIO(0xFF41, 0x10)
	n = 0
	for i := 0; i < 154*456; i++ {
		g.tickPPU(1)
		if g.ifl&IntSTAT != 0 {
			n++
			g.ifl = 0
		}
	}
	if n != 1 {
		t.Errorf("mode-1 STAT fired %d times per frame, want 1", n)
	}

	// OAM scan (mode 2) source: 144 visible lines + wrap to line 0 => 144 per frame
	g = blank(t)
	g.ifl = 0
	g.writeIO(0xFF41, 0x20)
	n = 0
	for i := 0; i < 154*456; i++ {
		g.tickPPU(1)
		if g.ifl&IntSTAT != 0 {
			n++
			g.ifl = 0
		}
	}
	if n < 143 || n > 145 {
		t.Errorf("mode-2 STAT fired %d times per frame, want ~144", n)
	}
}

func TestSTATBlocking(t *testing.T) {
	// Mode-0 and mode-1 sources together: HBlank of line 143 flows straight into
	// VBlank with the line still high, so there is no extra edge. 144 edges per frame.
	g := blank(t)
	g.ifl = 0
	g.writeIO(0xFF41, 0x18)
	n := 0
	for i := 0; i < 154*456; i++ {
		g.tickPPU(1)
		if g.ifl&IntSTAT != 0 {
			n++
			g.ifl = 0
		}
	}
	if n != 144 {
		t.Errorf("STAT edges with mode0|mode1 sources: %d, want 144", n)
	}
}

func TestLCDOffBehaviour(t *testing.T) {
	g := blank(t)
	g.tickPPU(1000)
	g.writeIO(0xFF40, 0x11)
	if g.PPU.ly != 0 || g.readIO(0xFF41)&3 != 0 {
		t.Errorf("LCD off: ly=%d mode=%d", g.PPU.ly, g.readIO(0xFF41)&3)
	}
	g.tickPPU(5000)
	if g.PPU.ly != 0 {
		t.Error("LY advanced while LCD off")
	}
	g.write(0x8000, 0x77)
	if g.vram[0] != 0x77 {
		t.Error("VRAM must be writable with LCD off")
	}
	for _, v := range g.Framebuffer() {
		if v != 0 {
			t.Fatal("screen not blank while LCD off")
		}
	}
}

func TestVRAMBlockedDuringDrawing(t *testing.T) {
	g := blank(t)
	g.vram[0] = 0x42
	g.tickPPU(100) // mode 3
	if g.PPU.mode != 3 {
		t.Fatalf("mode %d", g.PPU.mode)
	}
	if g.read(0x8000) != 0xFF {
		t.Error("VRAM readable in mode 3")
	}
	g.write(0x8000, 0x99)
	if g.vram[0] != 0x42 {
		t.Error("VRAM writable in mode 3")
	}
	if g.read(0xFE00) != 0xFF {
		t.Error("OAM readable in mode 3")
	}
	g.tickPPU(300) // HBlank
	if g.read(0x8000) != 0x42 {
		t.Error("VRAM not readable in HBlank")
	}
}

func TestBackgroundRendering(t *testing.T) {
	g := blank(t)
	g.writeIO(0xFF47, 0xE4) // identity palette
	setTile(g, 0x8010, func(x, y int) int { return (x + y) & 3 })
	g.Poke(0x9800, 1)
	g.Poke(0x9801, 1)
	fb := frame(t, g)
	for y := 0; y < 8; y++ {
		for x := 0; x < 16; x++ {
			if want := byte((x%8 + y) & 3); px(fb, x, y) != want {
				t.Fatalf("pixel (%d,%d) = %d want %d", x, y, px(fb, x, y), want)
			}
		}
	}
	if px(fb, 16, 0) != 0 {
		t.Error("tile 0 (blank) should be colour 0")
	}
	// palette mapping: remap colours 0..3 -> 3,2,1,0
	g.writeIO(0xFF47, 0x1B)
	fb = frame(t, g)
	if px(fb, 0, 0) != 3 || px(fb, 3, 0) != 0 || px(fb, 16, 0) != 3 {
		t.Errorf("palette remap wrong: %d %d %d", px(fb, 0, 0), px(fb, 3, 0), px(fb, 16, 0))
	}
}

func TestScrollingWraps(t *testing.T) {
	g := blank(t)
	g.writeIO(0xFF47, 0xE4)
	setTile(g, 0x8010, func(x, y int) int { return x & 3 })
	g.Poke(0x9800+31, 1) // rightmost tile of map row 0
	g.writeIO(0xFF43, 248+3)
	fb := frame(t, g)
	// SCX=251: screen x=0 shows map pixel 251 = tile 31, column 3
	if px(fb, 0, 0) != 3 {
		t.Errorf("scrolled pixel = %d want 3", px(fb, 0, 0))
	}
	if px(fb, 4, 0) != 3-0 && px(fb, 5, 0) != 0 {
		t.Errorf("wrap-around wrong: x4=%d x5=%d", px(fb, 4, 0), px(fb, 5, 0))
	}
	// vertical: SCY=8*3 shows map row 3 at line 0
	g.writeIO(0xFF43, 0)
	g.writeIO(0xFF42, 24)
	g.Poke(0x9800+3*32, 1)
	fb = frame(t, g)
	if px(fb, 0, 0) != 0 || px(fb, 3, 0) != 3 {
		t.Errorf("SCY: %d %d", px(fb, 0, 0), px(fb, 3, 0))
	}
}

func TestTileDataModesAndMapSelect(t *testing.T) {
	g := blank(t)
	g.writeIO(0xFF47, 0xE4)
	// 0x8800 mode: index 0xFF = -1 -> 0x8FF0 ; index 0x80 = -128 -> 0x8800
	setTile(g, 0x8FF0, func(x, y int) int { return 1 })
	setTile(g, 0x8800, func(x, y int) int { return 2 })
	g.Poke(0x9800, 0xFF)
	g.Poke(0x9801, 0x80)
	g.writeIO(0xFF40, 0x81) // BG on, signed tile data
	fb := frame(t, g)
	if px(fb, 0, 0) != 1 || px(fb, 8, 0) != 2 {
		t.Errorf("signed addressing: %d %d", px(fb, 0, 0), px(fb, 8, 0))
	}
	// unsigned: index 0xFF -> 0x8FF0 (same), 0x80 -> 0x8800 (same) -- use index 0 to distinguish
	setTile(g, 0x9000, func(x, y int) int { return 3 }) // tile 0 in signed mode
	g.Poke(0x9802, 0)
	fb = frame(t, g)
	if px(fb, 16, 0) != 3 {
		t.Errorf("signed index 0 should hit 0x9000: %d", px(fb, 16, 0))
	}
	g.writeIO(0xFF40, 0x91) // unsigned
	fb = frame(t, g)
	if px(fb, 16, 0) != 0 {
		t.Errorf("unsigned index 0 should hit 0x8000 (blank): %d", px(fb, 16, 0))
	}
	// second map
	setTile(g, 0x8010, func(x, y int) int { return 2 })
	g.Poke(0x9C00, 1)
	g.writeIO(0xFF40, 0x99)
	fb = frame(t, g)
	if px(fb, 0, 0) != 2 {
		t.Errorf("map 9C00 select failed: %d", px(fb, 0, 0))
	}
}

func TestWindow(t *testing.T) {
	g := blank(t)
	g.writeIO(0xFF47, 0xE4)
	setTile(g, 0x8010, func(x, y int) int { return 3 })
	setTile(g, 0x8020, func(x, y int) int { return 1 })
	for i := 0; i < 32*32; i++ {
		g.Poke(0x9800+uint16(i), 2) // background map: colour 1
		g.Poke(0x9C00+uint16(i), 1) // window map: colour 3
	}
	g.writeIO(0xFF4A, 16)   // WY
	g.writeIO(0xFF4B, 47)   // WX => window starts at x=40
	g.writeIO(0xFF40, 0xF1) // LCD, win map 9C00, win on, BG on
	fb := frame(t, g)
	if px(fb, 39, 20) != 1 || px(fb, 40, 20) != 3 || px(fb, 159, 143) != 3 {
		t.Errorf("window edges: %d %d %d", px(fb, 39, 20), px(fb, 40, 20), px(fb, 159, 143))
	}
	if px(fb, 100, 15) != 1 || px(fb, 100, 16) != 3 {
		t.Errorf("WY: %d %d", px(fb, 100, 15), px(fb, 100, 16))
	}
	// the window uses its own line counter: tile row advances every 8 lines from WY
	g.Poke(0x9C00+32, 2) // window map row 1, col 0 -> colour 1 tile
	fb = frame(t, g)
	if px(fb, 40, 16+7) != 3 || px(fb, 40, 16+8) != 1 {
		t.Errorf("window line counter: %d %d", px(fb, 40, 16+7), px(fb, 40, 16+8))
	}
	// disabling BG bit also disables the window on DMG
	g.writeIO(0xFF40, 0xF0)
	fb = frame(t, g)
	if px(fb, 100, 100) != 0 {
		t.Errorf("window drawn with BG disabled: %d", px(fb, 100, 100))
	}
}

func oamSet(g *GB, i int, y, x, tile, attr byte) {
	g.Poke(0xFE00+uint16(i*4), y)
	g.Poke(0xFE00+uint16(i*4)+1, x)
	g.Poke(0xFE00+uint16(i*4)+2, tile)
	g.Poke(0xFE00+uint16(i*4)+3, attr)
}

func TestSprites(t *testing.T) {
	g := blank(t)
	g.writeIO(0xFF47, 0xE4)
	g.writeIO(0xFF48, 0xE4)
	g.writeIO(0xFF49, 0x1B)
	// tile 1 is deliberately NOT mirror-symmetric so X flips are visible
	setTile(g, 0x8010, func(x, y int) int { return []int{0, 1, 2, 3, 0, 0, 0, 1}[x] })
	g.writeIO(0xFF40, 0x93)         // BG + OBJ on, 8x8
	oamSet(g, 0, 16+10, 8+20, 1, 0) // at (20,10)
	fb := frame(t, g)
	for x := 0; x < 8; x++ {
		want := []int{0, 1, 2, 3, 0, 0, 0, 1}[x]
		if int(px(fb, 20+x, 10)) != want {
			t.Fatalf("sprite px %d = %d want %d", x, px(fb, 20+x, 10), want)
		}
	}
	// X flip + OBP1
	oamSet(g, 0, 16+10, 8+20, 1, 0x20|0x10)
	fb = frame(t, g)
	// mirrored source columns 7..0 = 1,0,0,0,3,2,1,0 ; OBP1 = 0x1B maps colours 1->2, 2->1, 3->0
	for x, want := range []byte{2, 0, 0, 0, 0, 1, 2, 0} {
		if px(fb, 20+x, 10) != want {
			t.Errorf("x-flipped sprite column %d = %d, want %d", x, px(fb, 20+x, 10), want)
		}
	}
	// Y flip: sprite with distinct rows
	setTile(g, 0x8020, func(x, y int) int { return y & 3 })
	oamSet(g, 0, 16+10, 8+30, 2, 0x40)
	fb = frame(t, g)
	if px(fb, 30, 10) != 3 || px(fb, 30, 17) != 0 {
		t.Errorf("yflip: top=%d bottom=%d", px(fb, 30, 10), px(fb, 30, 17))
	}
	// BG priority: BG colour 0 shows sprite, colours 1-3 hide it
	setTile(g, 0x8030, func(x, y int) int { return 2 })
	g.Poke(0x9800+5*32+5, 3) // BG tile at screen (40..47, 40..47)
	setTile(g, 0x8010, func(x, y int) int { return 1 })
	oamSet(g, 0, 16+40, 8+36, 1, 0x80) // spans x 36..43 over BG from x=40
	fb = frame(t, g)
	if px(fb, 38, 40) != 1 || px(fb, 41, 40) != 2 {
		t.Errorf("OBJ-behind-BG priority: %d %d", px(fb, 38, 40), px(fb, 41, 40))
	}
	// off-screen / clipping
	oamSet(g, 0, 16+5, 0, 1, 0) // x=-8 fully hidden
	oamSet(g, 1, 16+5, 4, 1, 0) // x=-4 half visible
	fb = frame(t, g)
	if px(fb, 0, 5) != 1 || px(fb, 3, 5) != 1 {
		t.Errorf("left clipping: %d %d", px(fb, 0, 5), px(fb, 3, 5))
	}
	if px(fb, 4, 5) != 0 {
		t.Errorf("sprite 1 overran: %d", px(fb, 4, 5))
	}
}

func TestSprite8x16(t *testing.T) {
	g := blank(t)
	g.writeIO(0xFF48, 0xE4)
	setTile(g, 0x8020, func(x, y int) int { return 1 })
	setTile(g, 0x8030, func(x, y int) int { return 2 })
	g.writeIO(0xFF40, 0x97)
	oamSet(g, 0, 16+20, 8+20, 3, 0) // tile index LSB ignored: tiles 2 and 3
	fb := frame(t, g)
	if px(fb, 20, 20) != 1 || px(fb, 20, 27) != 1 || px(fb, 20, 28) != 2 || px(fb, 20, 35) != 2 || px(fb, 20, 36) != 0 {
		t.Errorf("8x16: %d %d %d %d %d", px(fb, 20, 20), px(fb, 20, 27), px(fb, 20, 28), px(fb, 20, 35), px(fb, 20, 36))
	}
	oamSet(g, 0, 16+20, 8+20, 2, 0x40) // y-flip swaps the halves
	fb = frame(t, g)
	if px(fb, 20, 20) != 2 || px(fb, 20, 35) != 1 {
		t.Errorf("8x16 yflip: %d %d", px(fb, 20, 20), px(fb, 20, 35))
	}
}

func TestSpritePriorityAndLimit(t *testing.T) {
	g := blank(t)
	g.writeIO(0xFF48, 0xE4)
	setTile(g, 0x8010, func(x, y int) int { return 1 })
	setTile(g, 0x8020, func(x, y int) int { return 2 })
	g.writeIO(0xFF40, 0x93)
	// overlapping: smaller X wins regardless of OAM order
	oamSet(g, 0, 16+10, 8+24, 1, 0) // x=24
	oamSet(g, 1, 16+10, 8+20, 2, 0) // x=20 -> wins on overlap (24..27)
	fb := frame(t, g)
	if px(fb, 24, 10) != 2 {
		t.Errorf("smaller X must win: %d", px(fb, 24, 10))
	}
	if px(fb, 28, 10) != 1 {
		t.Errorf("sprite 0 right part: %d", px(fb, 28, 10))
	}
	// equal X: lower OAM index wins
	oamSet(g, 0, 16+10, 8+20, 1, 0)
	oamSet(g, 1, 16+10, 8+20, 2, 0)
	fb = frame(t, g)
	if px(fb, 20, 10) != 1 {
		t.Errorf("equal X: lower OAM index must win, got %d", px(fb, 20, 10))
	}
	// 10 sprites per line: the 11th is dropped
	for i := 0; i < 40; i++ {
		oamSet(g, i, 0, 0, 0, 0)
	}
	for i := 0; i < 11; i++ {
		oamSet(g, i, 16+50, byte(8+i*12), 1, 0)
	}
	fb = frame(t, g)
	for i := 0; i < 10; i++ {
		if px(fb, i*12, 50) != 1 {
			t.Errorf("sprite %d missing", i)
		}
	}
	if px(fb, 10*12, 50) != 0 {
		t.Errorf("11th sprite on the line was drawn")
	}
	// transparent pixel of a higher-priority sprite doesn't hide a lower one
	setTile(g, 0x8030, func(x, y int) int { return []int{0, 0, 0, 0, 2, 2, 2, 2}[x] })
	for i := 0; i < 40; i++ {
		oamSet(g, i, 0, 0, 0, 0)
	}
	oamSet(g, 0, 16+70, 8+10, 3, 0) // left half transparent, at x=10
	oamSet(g, 1, 16+70, 8+12, 1, 0) // x=12 -- lower priority (larger X)
	fb = frame(t, g)
	if px(fb, 12, 70) != 1 {
		t.Errorf("transparent pixel hid lower-priority sprite: %d", px(fb, 12, 70))
	}
}

func TestOBJDisable(t *testing.T) {
	g := blank(t)
	setTile(g, 0x8010, func(x, y int) int { return 3 })
	oamSet(g, 0, 16, 8, 1, 0)
	g.writeIO(0xFF40, 0x91) // OBJ off
	fb := frame(t, g)
	if px(fb, 0, 0) != 0 {
		t.Error("sprite drawn with OBJ disabled")
	}
}

func TestMidFrameRegisterChangeAppliesPerLine(t *testing.T) {
	// Raster effect: the CPU changes SCX at line 72, so only the lower half shifts.
	g := buildRaw(t, `
	.org 0x100
	jp main
	.org 0x150
main:
	ld a, 0xE4
	ldh [0x47], a
.top:
	xor a
	ldh [0x43], a
.w72:
	ldh a, [0x44]
	cp 72
	jr nz, .w72
	ld a, 4
	ldh [0x43], a
.w144:
	ldh a, [0x44]
	cp 144
	jr nz, .w144
	jr .top
`)
	setTile(g, 0x8010, func(x, y int) int { return x / 2 })
	for i := 0; i < 32*32; i++ {
		g.Poke(0x9800+uint16(i), 1)
	}
	for i := 0; i < 3; i++ {
		frame(t, g)
	}
	fb := g.Framebuffer()
	if px(fb, 0, 10) != 0 || px(fb, 2, 10) != 1 {
		t.Errorf("top half shifted: %d %d", px(fb, 0, 10), px(fb, 2, 10))
	}
	if px(fb, 0, 100) != 2 || px(fb, 2, 100) != 3 {
		t.Errorf("bottom half not shifted by 4: %d %d", px(fb, 0, 100), px(fb, 2, 100))
	}
}

// Regression: with the LCD off no VBlank ever occurs, but RunFrame must still
// return once a frame's worth of time has passed (it used to spin forever).
func TestRunFrameWithLCDOff(t *testing.T) {
	g := buildRaw(t, "\t.org 0x100\n\tjp main\n\t.org 0x150\nmain:\n\txor a\n\tldh [0x40], a\n\tjr $\n")
	before := g.Cycles
	for i := 0; i < 3; i++ {
		if err := g.RunFrame(); err != nil {
			t.Fatal(err)
		}
	}
	if g.Cycles-before > 4*CyclesPerFrame {
		t.Errorf("3 frames with the LCD off took %d cycles", g.Cycles-before)
	}
}
