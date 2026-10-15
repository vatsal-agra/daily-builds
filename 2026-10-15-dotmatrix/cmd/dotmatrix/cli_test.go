package main

import (
	"bytes"
	"image/png"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"dotmatrix/gb"
)

const roms = "../../roms/"

func TestParseKeys(t *testing.T) {
	evs, err := parseKeys("10:start, 12:-start,30:right")
	if err != nil || len(evs) != 3 {
		t.Fatalf("%v %v", evs, err)
	}
	if evs[0] != (keyEvent{10, gb.BtnStart, true}) || evs[1] != (keyEvent{12, gb.BtnStart, false}) || evs[2].btn != gb.BtnRight {
		t.Errorf("parsed %+v", evs)
	}
	for _, bad := range []string{"start", "x:start", "5:fire", "-3:a", "5:"} {
		if _, err := parseKeys(bad); err == nil {
			t.Errorf("%q accepted", bad)
		}
	}
	if evs, err := parseKeys(""); err != nil || evs != nil {
		t.Errorf("empty spec: %v %v", evs, err)
	}
}

func TestParseAddr(t *testing.T) {
	good := map[string]int{"0x150": 0x150, "$FF40": 0xFF40, "100": 100, "ff": 255, "0": 0, "0xFFFF": 0xFFFF}
	for s, want := range good {
		if got, err := parseAddr(s); err != nil || got != want {
			t.Errorf("%q: %d %v", s, got, err)
		}
	}
	for _, s := range []string{"", "zz", "0x10000", "-1", "0x"} {
		if _, err := parseAddr(s); err == nil {
			t.Errorf("%q accepted", s)
		}
	}
}

func TestRunWritesPNGWAVAndStates(t *testing.T) {
	dir := t.TempDir()
	pngPath, wavPath, st := filepath.Join(dir, "o.png"), filepath.Join(dir, "o.wav"), filepath.Join(dir, "o.dmst")
	err := cmdRun([]string{roms + "snake.asm", "-frames", "60", "-keys", "5:start,6:-start", "-png", pngPath, "-scale", "2", "-wav", wavPath, "-savestate", st})
	if err != nil {
		t.Fatal(err)
	}
	f, _ := os.Open(pngPath)
	img, err := png.Decode(f)
	f.Close()
	if err != nil || img.Bounds().Dx() != 320 || img.Bounds().Dy() != 288 {
		t.Fatalf("png: %v %v", img, err)
	}
	// the game board is on screen: both light and dark pixels exist
	seen := map[uint32]bool{}
	for y := 0; y < 288; y += 3 {
		for x := 0; x < 320; x += 3 {
			r, _, _, _ := img.At(x, y).RGBA()
			seen[r] = true
		}
	}
	if len(seen) < 2 {
		t.Errorf("screenshot has %d distinct shades (want light + dark)", len(seen))
	}
	w, _ := os.ReadFile(wavPath)
	if len(w) < 44+44100*4/2 || string(w[:4]) != "RIFF" {
		t.Errorf("wav: %d bytes", len(w))
	}
	// resume from the state and run a little more
	if err := cmdRun([]string{roms + "snake.asm", "-frames", "5", "-loadstate", st}); err != nil {
		t.Fatal(err)
	}
	if err := cmdRun([]string{roms + "cputest.asm", "-frames", "1", "-loadstate", st}); err == nil || !strings.Contains(err.Error(), "different cartridge") {
		t.Errorf("state loaded into the wrong ROM: %v", err)
	}
}

func TestRunErrors(t *testing.T) {
	cases := [][]string{
		{},
		{"/nonexistent.gb"},
		{roms + "snake.asm", "-frames", "-1"},
		{roms + "snake.asm", "-scale", "99"},
		{roms + "snake.asm", "-keys", "nonsense"},
		{roms + "snake.asm", "-loadstate", "/nonexistent.dmst"},
		{roms + "snake.asm", roms + "cputest.asm"},
	}
	for _, c := range cases {
		if err := cmdRun(c); err == nil {
			t.Errorf("cmdRun(%v) succeeded", c)
		}
	}
}

func TestTestCommandVerdicts(t *testing.T) {
	if err := cmdTest([]string{roms + "cputest.asm", "-frames", "3000"}); err != nil {
		t.Errorf("cputest should pass: %v", err)
	}
	if err := cmdTest([]string{roms + "mbc1test.asm", "-frames", "300"}); err != nil {
		t.Errorf("mbc1test should pass: %v", err)
	}
	if err := cmdTest([]string{roms + "snake.asm", "-frames", "20"}); err == nil || !strings.Contains(err.Error(), "no PASS/FAIL") {
		t.Errorf("snake has no verdict: %v", err)
	}
}

func TestAsmDisInfoRoundTrip(t *testing.T) {
	dir := t.TempDir()
	rom, sym := filepath.Join(dir, "s.gb"), filepath.Join(dir, "s.sym")
	if err := cmdAsm([]string{roms + "snake.asm", "-o", rom, "-sym", sym}); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(rom)
	if len(b) != 0x8000 {
		t.Errorf("rom is %d bytes", len(b))
	}
	s, _ := os.ReadFile(sym)
	if !strings.Contains(string(s), "put_text") || !strings.Contains(string(s), "step") {
		t.Errorf("symbol file lacks labels:\n%.200s", s)
	}
	if err := cmdInfo([]string{rom}); err != nil {
		t.Errorf("info: %v", err)
	}
	if err := cmdDis([]string{rom, "-from", "0x150", "-len", "16"}); err != nil {
		t.Errorf("dis: %v", err)
	}
	// a ROM with a corrupted header must make info fail
	b[0x134] ^= 0xFF
	bad := filepath.Join(dir, "bad.gb")
	os.WriteFile(bad, b, 0o644)
	if err := cmdInfo([]string{bad}); err == nil {
		t.Error("info accepted a corrupted header")
	}
	if err := cmdDis([]string{rom, "-from", "0x9000"}); err == nil {
		t.Error("dis accepted an address past the ROM")
	}
}

// ---- debugger REPL --------------------------------------------------------

func runScript(t *testing.T, rom, script string) string {
	t.Helper()
	g, res, err := openMachine(rom)
	if err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	if err := runDebugger(g, res.Symbols, strings.NewReader(script), &out, false); err != nil {
		t.Fatal(err)
	}
	return out.String()
}

func TestDebuggerBreakpointsAndInspection(t *testing.T) {
	out := runScript(t, roms+"cputest.asm", strings.Join([]string{
		"b t_alu8", "c", "r", "u t_alu8 3", "x 0xC000 4", "bl", "d 1", "bl", "hist 2", "ppu", "io", "q",
	}, "\n"))
	must := []string{"breakpoint 1 at", "** breakpoint 1 at", "t_alu8:", "ld a, $3C", "1: break", "LCDC=91", "SP="}
	for _, w := range must {
		if !strings.Contains(out, w) {
			t.Errorf("output lacks %q:\n%s", w, out)
		}
	}
	if strings.Count(out, "1: break") != 1 {
		t.Errorf("breakpoint should be listed once and gone after delete:\n%s", out)
	}
}

func TestDebuggerConditionalAndWatch(t *testing.T) {
	// break in print_char only when A == 'P' (the PASS verdict), watch the check counter
	out := runScript(t, roms+"cputest.asm", strings.Join([]string{
		"b print_char if a == 0x50", "c 3000", "r", "q"}, "\n"))
	if !strings.Contains(out, "** breakpoint 1") || !strings.Contains(out, "AF=50") {
		t.Errorf("conditional breakpoint:\n%s", out)
	}
	out = runScript(t, roms+"cputest.asm", strings.Join([]string{"w total", "c", "c", "bl", "q"}, "\n"))
	if strings.Count(out, "** watchpoint 1: write") != 2 || !strings.Contains(out, "watch write C000 (hit 2)") {
		t.Errorf("write watchpoint:\n%s", out)
	}
	out = runScript(t, roms+"cputest.asm", "b 0x150 if bogus == 1\nb 0x150 if a ==\nb nosuchsymbol\nq")
	if strings.Count(out, "unknown register") != 1 || !strings.Contains(out, "bad value") || !strings.Contains(out, "not an address or known symbol") {
		t.Errorf("bad conditions should each be rejected with a message:\n%s", out)
	}
}

func TestDebuggerStepOverFinishUntil(t *testing.T) {
	// start: ... call t_loads ... ; `n` on a CALL must run the whole callee and stop right after it
	g, res, err := openMachine(roms + "cputest.asm")
	if err != nil {
		t.Fatal(err)
	}
	callAddr := uint16(res.Symbols["start"])
	var out bytes.Buffer
	// find the first CALL in start by single-stepping with the debugger API
	d := gb.NewDebugger()
	g.Dbg = d
	for i := 0; i < 20; i++ {
		if g.Peek(g.Regs().PC) == 0xCD && g.Regs().PC > callAddr {
			break
		}
		g.Dbg.ResumeFromStop()
		g.StepChecked()
	}
	pc := g.Regs().PC
	if g.Peek(pc) != 0xCD {
		t.Fatalf("no CALL found near start (pc=%04X)", pc)
	}
	runDebuggerOn := func(g *gb.GB, cmds string) string {
		out.Reset()
		if err := runDebugger(g, res.Symbols, strings.NewReader(cmds), &out, false); err != nil {
			t.Fatal(err)
		}
		return out.String()
	}
	o := runDebuggerOn(g, "n\nr\nq")
	// after stepping over, PC is the instruction following the CALL (3 bytes later) and the stack is balanced
	if !strings.Contains(o, "PC="+hex4(pc+3)) {
		t.Errorf("step over did not land after the call (want PC=%04X):\n%s", pc+3, o)
	}
	// finish from inside a subroutine
	g2, res2, _ := openMachine(roms + "cputest.asm")
	var out2 bytes.Buffer
	runDebugger(g2, res2.Symbols, strings.NewReader("b print_hex8\nc\nd 1\nfinish\nr\nq"), &out2, false)
	if !strings.Contains(out2.String(), "SP=") || strings.Contains(out2.String(), "gave up") {
		t.Errorf("finish:\n%s", out2.String())
	}
	if g2.Regs().PC == uint16(res2.Symbols["print_hex8"]) {
		t.Errorf("finish did not leave print_hex8")
	}
	o3 := runScript(t, roms+"cputest.asm", "until t_daa\nr\nq")
	if !strings.Contains(o3, "PC="+hex4(uint16(res.Symbols["t_daa"]))) {
		t.Errorf("until:\n%s", o3)
	}
}

func hex4(v uint16) string {
	const d = "0123456789ABCDEF"
	return string([]byte{d[v>>12], d[v>>8&15], d[v>>4&15], d[v&15]})
}

func TestDebuggerEditing(t *testing.T) {
	dir := t.TempDir()
	st := filepath.Join(dir, "x.dmst")
	out := runScript(t, roms+"cputest.asm", strings.Join([]string{
		"set a 0x42", "set hl 0xC123", "poke 0xC123 0x99", "x 0xC123 1", "set a 0x1FF", "set zz 1", "poke 0xC000 300",
		"save " + st, "set a 0", "load " + st, "r", "key start", "key bogus", "bogus", "sym t_a", "q"}, "\n"))
	for _, w := range []string{"AF=42", "HL=C123", "C123  99", "8-bit", "unknown register", "bad byte value", "AF=42", "unknown button", "unknown command", "t_alu8"} {
		if !strings.Contains(out, w) {
			t.Errorf("output lacks %q:\n%s", w, out)
		}
	}
}
