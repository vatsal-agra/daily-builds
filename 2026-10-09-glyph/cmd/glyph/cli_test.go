package main_test

import (
	"bytes"
	"encoding/json"
	"encoding/xml"
	"image/png"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"glyph/ttf"
)

var bin string

func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "glyphbin")
	if err != nil {
		panic(err)
	}
	bin = filepath.Join(dir, "glyph")
	if out, err := exec.Command("go", "build", "-o", bin, ".").CombinedOutput(); err != nil {
		panic(string(out))
	}
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

const lora = "../../testdata/fonts/Lora-Regular.ttf"
const italic = "../../testdata/fonts/Lora-Italic.ttf"

func run(t *testing.T, stdin string, args ...string) (string, string, int) {
	t.Helper()
	cmd := exec.Command(bin, args...)
	cmd.Stdin = strings.NewReader(stdin)
	var so, se bytes.Buffer
	cmd.Stdout, cmd.Stderr = &so, &se
	err := cmd.Run()
	code := 0
	if ee, ok := err.(*exec.ExitError); ok {
		code = ee.ExitCode()
	} else if err != nil {
		t.Fatal(err)
	}
	return so.String(), se.String(), code
}

func mustPNG(t *testing.T, path string) (w, h int) {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	cfg, err := png.DecodeConfig(f)
	if err != nil {
		t.Fatalf("%s: %v", path, err)
	}
	return cfg.Width, cfg.Height
}

func TestInfo(t *testing.T) {
	out, _, code := run(t, "", "info", lora)
	if code != 0 {
		t.Fatal("info failed")
	}
	for _, want := range []string{"family      Lora", "unitsPerEm  1000", "GPOS pair adjustment", "checksums   OK", "glyf"} {
		if !strings.Contains(out, want) {
			t.Errorf("info output missing %q:\n%s", want, out)
		}
	}
}

func TestTextSVGLCDAndStdin(t *testing.T) {
	d := t.TempDir()
	p := filepath.Join(d, "t.png")
	out, _, code := run(t, "", "text", "-font", lora, "-size", "24", "-width", "300", "-align", "justify", "-o", p,
		"The quick brown fox jumps over the lazy dog and keeps running far away.")
	if code != 0 || !strings.Contains(out, "wrote") {
		t.Fatalf("text failed: %s", out)
	}
	if w, h := mustPNG(t, p); w < 300 || h < 60 {
		t.Errorf("png %dx%d", w, h)
	}
	// wider wrap → fewer lines → shorter image
	p2 := filepath.Join(d, "t2.png")
	run(t, "", "text", "-font", lora, "-size", "24", "-width", "900", "-o", p2, "The quick brown fox jumps over the lazy dog and keeps running far away.")
	if _, h2 := mustPNG(t, p2); h2 >= func() int { _, h := mustPNG(t, p); return h }() {
		t.Error("wider wrap did not reduce height")
	}
	// stdin
	p3 := filepath.Join(d, "t3.png")
	if _, e, code := run(t, "from stdin\nsecond line", "text", "-font", lora, "-file", "-", "-o", p3); code != 0 {
		t.Fatal(e)
	}
	if _, h3 := mustPNG(t, p3); h3 < 60 {
		t.Errorf("two stdin lines gave height %d", h3)
	}
	// svg
	sv := filepath.Join(d, "t.svg")
	if _, e, code := run(t, "", "svg", "-font", italic, "-size", "36", "-o", sv, "Vector"); code != 0 {
		t.Fatal(e)
	}
	b, _ := os.ReadFile(sv)
	if err := xml.Unmarshal(b, new(struct{ XMLName xml.Name })); err != nil || strings.Count(string(b), "<path") != 6 {
		t.Errorf("svg invalid (%v) or wrong path count %d", err, strings.Count(string(b), "<path"))
	}
	// lcd
	lc := filepath.Join(d, "l.png")
	if out, _, code := run(t, "", "lcd", "-font", lora, "-o", lc, "LCD"); code != 0 || !strings.Contains(out, "LCD") {
		t.Fatal(out)
	}
	mustPNG(t, lc)
}

func TestGlyphCommand(t *testing.T) {
	d := t.TempDir()
	out, _, code := run(t, "", "glyph", "-font", lora, "-char", "o", "-size", "30", "-ascii", "-o", filepath.Join(d, "o.png"))
	if code != 0 {
		t.Fatal(out)
	}
	if !strings.Contains(out, "2 contours") || !strings.ContainsAny(out, "@#%") {
		t.Errorf("o should have 2 contours and ASCII ink:\n%s", out)
	}
	mustPNG(t, filepath.Join(d, "o.png"))
	// the space glyph is empty: reported, no PNG requested → exit 0
	if out, _, code := run(t, "", "glyph", "-font", lora, "-char", " "); code != 0 || !strings.Contains(out, "empty glyph") {
		t.Errorf("space: %s", out)
	}
	if _, e, code := run(t, "", "glyph", "-font", lora, "-char", " ", "-o", filepath.Join(d, "s.png")); code == 0 || !strings.Contains(e, "no outline") {
		t.Errorf("PNG for an empty glyph must fail clearly: %s", e)
	}
}

func TestSubsetCommandProducesUsableFont(t *testing.T) {
	d := t.TempDir()
	sub := filepath.Join(d, "s.ttf")
	out, e, code := run(t, "", "subset", "-font", lora, "-o", sub, "Glyph AV")
	if code != 0 {
		t.Fatal(e)
	}
	b, _ := os.ReadFile(sub)
	f, err := ttf.Parse(b)
	if err != nil {
		t.Fatal(err)
	}
	if len(b) > 6000 || f.NumGlyphs != 9 || f.Index('G') == 0 || f.Index('z') != 0 || len(f.Verify()) != 0 {
		t.Errorf("subset: %d bytes, %d glyphs\n%s", len(b), f.NumGlyphs, out)
	}
	// the subset is itself a valid input for every other command
	p := filepath.Join(d, "x.png")
	if _, e, code := run(t, "", "text", "-font", sub, "-o", p, "Glyph AV"); code != 0 {
		t.Fatal(e)
	}
	mustPNG(t, p)
}

func TestSDFAndSpecimenCommands(t *testing.T) {
	d := t.TempDir()
	atlas, demo := filepath.Join(d, "a.png"), filepath.Join(d, "demo.png")
	out, e, code := run(t, "", "sdf", "-font", lora, "-o", atlas, "-demo", demo, "-size", "64", "Glyph")
	if code != 0 {
		t.Fatal(e)
	}
	mustPNG(t, atlas)
	mustPNG(t, demo)
	js, err := os.ReadFile(filepath.Join(d, "a.json"))
	if err != nil || !json.Valid(js) || !strings.Contains(out, "5 glyphs") {
		t.Errorf("sdf json: %v %s", err, out)
	}
	html := filepath.Join(d, "s.html")
	if _, e, code := run(t, "", "specimen", "-font", lora, "-o", html, "-max", "40"); code != 0 {
		t.Fatal(e)
	}
	b, _ := os.ReadFile(html)
	if !strings.Contains(string(b), "<figure") || !strings.Contains(string(b), "Lora Regular") {
		t.Error("specimen content wrong")
	}
}

// REVIEW R8 and the CLI misuse matrix: every bad invocation is a one-line error, exit 1, no panic/stack trace.
func TestMisuseMatrix(t *testing.T) {
	d := t.TempDir()
	notFont := filepath.Join(d, "notes.txt")
	os.WriteFile(notFont, []byte("hello, not a font"), 0o644)
	cases := map[string][]string{
		"no args to info":   {"info"},
		"missing file":      {"info", "/nonexistent/font.ttf"},
		"not a font":        {"info", notFont},
		"no text":           {"text", "-font", lora, "-o", filepath.Join(d, "x.png")},
		"no output":         {"text", "-font", lora, "hi"},
		"no font":           {"text", "-o", filepath.Join(d, "x.png"), "hi"},
		"size zero":         {"text", "-font", lora, "-size", "0", "-o", filepath.Join(d, "x.png"), "hi"},
		"size NaN":          {"text", "-font", lora, "-size", "NaN", "-o", filepath.Join(d, "x.png"), "hi"},
		"bad colour":        {"text", "-font", lora, "-fg", "zzz", "-o", filepath.Join(d, "x.png"), "hi"},
		"bad alignment":     {"text", "-font", lora, "-align", "middle", "-o", filepath.Join(d, "x.png"), "hi"},
		"unwritable output": {"text", "-font", lora, "-o", "/no/such/dir/x.png", "hi"},
		"two chars":         {"glyph", "-font", lora, "-char", "AB"},
		"giant glyph":       {"glyph", "-font", lora, "-char", "A", "-size", "99999"},
		"negative width":    {"text", "-font", lora, "-width", "-3", "-o", filepath.Join(d, "x.png"), "hi"},
		"unknown command":   {"frobnicate"},
		"unknown flag":      {"text", "-bogus"},
		"svg no output":     {"svg", "-font", lora, "x"},
		"sdf bad spread":    {"sdf", "-font", lora, "-spread", "0", "-o", filepath.Join(d, "a.png"), "x"},
		"subset no text":    {"subset", "-font", lora, "-o", filepath.Join(d, "s.ttf")},
	}
	for name, args := range cases {
		_, stderr, code := run(t, "", args...)
		if code == 0 {
			t.Errorf("%s: exited 0", name)
		}
		if strings.Contains(stderr, "goroutine") || strings.Contains(stderr, "panic") {
			t.Errorf("%s: crashed:\n%s", name, stderr)
		}
		if name != "unknown flag" && strings.Count(strings.TrimSpace(stderr), "\n") > 0 {
			t.Errorf("%s: error is not one line:\n%s", name, stderr)
		}
	}
	// the exact message from review finding R8
	if _, e, _ := run(t, "", "text", "-font", lora, "-fg", "zzz", "-o", filepath.Join(d, "x.png"), "hi"); !strings.Contains(e, `"zzz"`) {
		t.Errorf("colour error should quote the user's input: %s", e)
	}
	// help works and exits 0
	if out, _, code := run(t, "", "help"); code != 0 || !strings.Contains(out, "usage: glyph") {
		t.Error("help")
	}
	// blank text warns but succeeds
	if _, e, code := run(t, "", "text", "-font", lora, "-o", filepath.Join(d, "blank.png"), " "); code != 0 || !strings.Contains(e, "warning") {
		t.Errorf("blank text: code %d stderr %q", code, e)
	}
}
