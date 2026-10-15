package gb

import (
	"os"
	"testing"

	"dotmatrix/asm"
)

// snakeRig drives the real snake ROM with a bot, reading the game's own
// variables through the assembler's symbol table.
type snakeRig struct {
	t    *testing.T
	g    *GB
	sym  map[string]int
	held int // currently held direction button, -1 if none
}

func newSnakeRig(t *testing.T) *snakeRig {
	src, err := os.ReadFile("../roms/snake.asm")
	if err != nil {
		t.Fatal(err)
	}
	r, err := asm.Assemble("snake.asm", string(src), asm.Options{Include: asm.FileInclude("../roms")})
	if err != nil {
		t.Fatal(err)
	}
	c, err := NewCart(r.ROM)
	if err != nil {
		t.Fatal(err)
	}
	return &snakeRig{t: t, g: New(c), sym: r.Symbols, held: -1}
}

func (s *snakeRig) v(name string) int { return int(s.g.Peek(uint16(s.sym[name]))) }

func (s *snakeRig) frames(n int) {
	for i := 0; i < n; i++ {
		if err := s.g.RunFrame(); err != nil {
			s.t.Fatal(err)
		}
	}
}

func (s *snakeRig) tap(btn int) {
	s.g.SetButton(btn, true)
	s.frames(2)
	s.g.SetButton(btn, false)
	s.frames(1)
}

func (s *snakeRig) tile(x, y int) byte { return s.g.Peek(uint16(0x9800 + y*32 + x)) }

// text reads a run of characters from the BG map (letters and digits) back as a string.
func (s *snakeRig) text(x, y, n int) string {
	out := make([]byte, n)
	for i := range out {
		t := s.tile(x+i, y)
		switch {
		case t == 0:
			out[i] = ' '
		case t >= 0x10 && t <= 0x19:
			out[i] = '0' + t - 0x10
		case t >= 0x20 && t <= 0x39:
			out[i] = 'A' + t - 0x20
		default:
			out[i] = '?'
		}
	}
	return string(out)
}

func (s *snakeRig) startGame() {
	s.frames(10)
	if got := s.text(7, 5, 5); got != "SNAKE" {
		s.t.Fatalf("title screen shows %q", got)
	}
	s.tap(BtnStart)
	s.frames(3)
}

// steer picks the direction that closes in on the food without reversing or hitting a wall/body.
func (s *snakeRig) steer() {
	hx, hy := s.v("hx"), s.v("hy")
	dir := s.v("dir")
	// locate the food by scanning the map (the game draws it as tile 4)
	fxx, fyy := -1, -1
	for y := 1; y < 18 && fxx < 0; y++ {
		for x := 1; x < 19; x++ {
			if s.tile(x, y) == 4 {
				fxx, fyy = x, y
				break
			}
		}
	}
	type cand struct {
		btn, nd, dx, dy int
	}
	cs := []cand{{BtnRight, 0, 1, 0}, {BtnLeft, 1, -1, 0}, {BtnUp, 2, 0, -1}, {BtnDown, 3, 0, 1}}
	best, bestD := -1, 1<<30
	for _, c := range cs {
		if (dir == 0 && c.nd == 1) || (dir == 1 && c.nd == 0) || (dir == 2 && c.nd == 3) || (dir == 3 && c.nd == 2) {
			continue
		}
		nx, ny := hx+c.dx, hy+c.dy
		if tl := s.tile(nx, ny); tl != 0 && tl != 4 {
			continue
		}
		d := abs(nx-fxx) + abs(ny-fyy)
		if d < bestD {
			best, bestD = c.btn, d
		}
	}
	if s.held >= 0 {
		s.g.SetButton(s.held, false)
		s.held = -1
	}
	if best >= 0 {
		s.g.SetButton(best, true)
		s.held = best
	}
}

func abs(a int) int {
	if a < 0 {
		return -a
	}
	return a
}

func TestSnakeBotEatsFoodAndGrows(t *testing.T) {
	s := newSnakeRig(t)
	s.startGame()
	if s.v("len") != 3 || s.v("score") != 0 {
		t.Fatalf("new game: len=%d score=%d", s.v("len"), s.v("score"))
	}
	for i := 0; i < 2500 && s.v("score") < 8; i++ {
		s.steer()
		s.frames(1)
		if s.text(5, 8, 9) == "GAME OVER" {
			t.Fatalf("bot died at frame %d with score %d", i, s.v("score"))
		}
	}
	if s.v("score") < 8 {
		t.Fatalf("bot only reached score %d", s.v("score"))
	}
	if s.v("len") != 3+s.v("score") {
		t.Errorf("length %d does not match score %d", s.v("len"), s.v("score"))
	}
	// speed-up kicked in after 4 points
	if s.v("period") >= 12 {
		t.Errorf("snake did not speed up: period=%d", s.v("period"))
	}
	// the HUD shows the score, and the map holds exactly len snake cells + 1 food
	if got := s.text(8, 0, 3); got != "00"+string(rune('0'+s.v("score"))) {
		t.Errorf("HUD shows %q, score is %d", got, s.v("score"))
	}
	body, food := 0, 0
	for y := 1; y < 17; y++ {
		for x := 1; x < 19; x++ {
			switch s.tile(x, y) {
			case 2, 3:
				body++
			case 4:
				food++
			}
		}
	}
	if body != s.v("len") || food != 1 {
		t.Errorf("map has %d snake cells (len %d) and %d food", body, s.v("len"), food)
	}
}

func TestSnakeDiesOnWallKeepsBodyAndRestarts(t *testing.T) {
	s := newSnakeRig(t)
	s.startGame()
	for i := 0; i < 300 && s.text(5, 8, 9) != "GAME OVER"; i++ {
		s.frames(1)
	}
	if s.text(5, 8, 9) != "GAME OVER" {
		t.Fatal("snake never died heading into the wall")
	}
	// regression for REVIEW #8: all three segments must still be on screen
	cells := 0
	for y := 1; y < 17; y++ {
		for x := 1; x < 19; x++ {
			if tl := s.tile(x, y); tl == 2 || tl == 3 {
				cells++
			}
		}
	}
	if cells != 3 {
		t.Errorf("dead snake shows %d cells, want 3", cells)
	}
	// the death jingle was programmed: channel 1 sweep + noise envelope registers hold the sfx_die values
	if s.g.Peek(0xFF21) != 0xF3 {
		t.Errorf("death noise envelope NR42=%02X, want F3", s.g.Peek(0xFF21))
	}
	// START restarts with a fresh snake
	s.tap(BtnStart)
	s.frames(3)
	if s.v("len") != 3 || s.v("score") != 0 || s.text(5, 8, 9) == "GAME OVER" {
		t.Errorf("restart: len=%d score=%d", s.v("len"), s.v("score"))
	}
}

func TestSnakeReverseTurnIsIgnored(t *testing.T) {
	s := newSnakeRig(t)
	s.startGame()
	// heading right: pressing left must not turn the snake into itself
	s.g.SetButton(BtnLeft, true)
	s.frames(40)
	s.g.SetButton(BtnLeft, false)
	if s.v("dir") != 0 {
		t.Errorf("snake reversed: dir=%d", s.v("dir"))
	}
	if s.text(5, 8, 9) == "GAME OVER" {
		t.Error("snake died although the reverse turn should be ignored")
	}
}

// setSnake overwrites the running game's state with a snake occupying cells
// (tail first) and heading dir, clears the field and drops one food far away.
func (s *snakeRig) setSnake(cells [][2]int, dir int) {
	g := s.g
	for y := 1; y < 17; y++ {
		for x := 1; x < 19; x++ {
			g.Poke(uint16(0x9800+y*32+x), 0)
		}
	}
	ring := s.sym["ring"]
	for i, c := range cells {
		g.Poke(uint16(ring+2*i), byte(c[0]))
		g.Poke(uint16(ring+2*i+1), byte(c[1]))
		tile := byte(2)
		if i == len(cells)-1 {
			tile = 3
		}
		g.Poke(uint16(0x9800+c[1]*32+c[0]), tile)
	}
	head := cells[len(cells)-1]
	set := func(name string, v int) { g.Poke(uint16(s.sym[name]), byte(v)) }
	set("headidx", len(cells))
	set("tailidx", 0)
	set("len", len(cells))
	set("hx", head[0])
	set("hy", head[1])
	set("dir", dir)
	set("ndir", dir)
	set("period", 3)
	set("timer", 1)
	g.Poke(0x9800+15*32+17, 4) // food in a far corner
}

func (s *snakeRig) gameOver() bool { return s.text(5, 8, 9) == "GAME OVER" }

func TestSnakeSelfCollisionIsFatal(t *testing.T) {
	s := newSnakeRig(t)
	s.startGame()
	// U-shape: head (6,6) heading left-turned-up will run into (6,5), a body cell that is not the tail
	s.setSnake([][2]int{{5, 5}, {6, 5}, {7, 5}, {7, 6}, {6, 6}}, 2) // heading up
	s.frames(8)
	if !s.gameOver() {
		t.Fatal("snake ran into its own body and survived")
	}
}

func TestSnakeMayChaseItsOwnTail(t *testing.T) {
	s := newSnakeRig(t)
	s.startGame()
	// 2x2 loop, head directly below the tail heading up: the tail cell is vacated as the head enters it.
	s.setSnake([][2]int{{5, 5}, {6, 5}, {6, 6}, {5, 6}}, 2)
	s.frames(1) // first move: straight up into the cell the tail is vacating
	if s.gameOver() {
		t.Fatal("moving into the vacating tail cell was fatal")
	}
	turns := []int{BtnRight, BtnDown, BtnLeft, BtnUp}
	for lap := 0; lap < 3; lap++ {
		for _, b := range turns {
			s.g.SetButton(b, true)
			s.frames(3) // exactly one move per 3 frames at period 3
			s.g.SetButton(b, false)
			if s.gameOver() {
				t.Fatalf("lap %d: tail chase wrongly fatal (button %d)", lap, b)
			}
		}
	}
	if s.v("len") != 4 {
		t.Errorf("length changed during tail chase: %d", s.v("len"))
	}
}
