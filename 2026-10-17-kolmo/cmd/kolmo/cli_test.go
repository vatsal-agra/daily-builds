package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

var bin string

func TestMain(m *testing.M) {
	dir, _ := os.MkdirTemp("", "kolmo-cli")
	bin = filepath.Join(dir, "kolmo")
	if out, err := exec.Command("go", "build", "-o", bin, ".").CombinedOutput(); err != nil {
		println(string(out))
		os.Exit(1)
	}
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

func run(t *testing.T, stdin []byte, args ...string) (string, string, error) {
	t.Helper()
	cmd := exec.Command(bin, args...)
	cmd.Stdin = bytes.NewReader(stdin)
	var o, e bytes.Buffer
	cmd.Stdout, cmd.Stderr = &o, &e
	err := cmd.Run()
	return o.String(), e.String(), err
}

func TestCompressDecompressAllMethods(t *testing.T) {
	d := t.TempDir()
	src := bytes.Repeat([]byte("kolmo cli round trip, with a little variety 0123456789\n"), 400)
	in := filepath.Join(d, "in.txt")
	os.WriteFile(in, src, 0o644)
	for _, m := range []string{"auto", "store", "deflate", "bwt", "cm", "rans0", "rans1"} {
		out := filepath.Join(d, "in."+m)
		if _, e, err := run(t, nil, "compress", "-m", m, in, "-o", out); err != nil {
			t.Fatalf("%s compress: %v %s", m, err, e)
		}
		back := filepath.Join(d, "back."+m)
		if _, e, err := run(t, nil, "decompress", out, "-o", back); err != nil {
			t.Fatalf("%s decompress: %v %s", m, err, e)
		}
		got, _ := os.ReadFile(back)
		if !bytes.Equal(got, src) {
			t.Fatalf("%s: content differs", m)
		}
	}
}

func TestOverwriteProtectionAndForce(t *testing.T) {
	d := t.TempDir()
	in := filepath.Join(d, "a")
	os.WriteFile(in, []byte("hello hello hello"), 0o644)
	run(t, nil, "compress", in)
	if _, e, err := run(t, nil, "compress", in); err == nil || !strings.Contains(e, "already exists") {
		t.Fatalf("second compress should refuse: %v %q", err, e)
	}
	if _, _, err := run(t, nil, "compress", "-f", in); err != nil {
		t.Fatal(err)
	}
}

func TestStdinStdout(t *testing.T) {
	src := []byte(strings.Repeat("pipe me ", 500))
	enc, _, err := run(t, src, "compress", "-m", "bwt", "-")
	if err != nil {
		t.Fatal(err)
	}
	dec, _, err := run(t, []byte(enc), "decompress", "-")
	if err != nil || dec != string(src) {
		t.Fatalf("pipe round trip failed: %v", err)
	}
}

func TestGzipInteropViaCLI(t *testing.T) {
	if _, err := exec.LookPath("gzip"); err != nil {
		t.Skip("no gzip")
	}
	src := []byte(strings.Repeat("interop with the real gzip tool\n", 1000))
	gz, _, err := run(t, src, "gzip", "-l", "9", "-")
	if err != nil {
		t.Fatal(err)
	}
	c := exec.Command("gzip", "-dc")
	c.Stdin = strings.NewReader(gz)
	out, err := c.Output()
	if err != nil || !bytes.Equal(out, src) {
		t.Fatalf("system gzip could not read our output: %v", err)
	}
}

func TestErrorsAreFriendly(t *testing.T) {
	d := t.TempDir()
	bad := filepath.Join(d, "bad.kol")
	os.WriteFile(bad, []byte("this is not a kolmo file"), 0o644)
	cases := []struct {
		args []string
		want string
	}{
		{[]string{"compress", filepath.Join(d, "missing")}, "no such file"},
		{[]string{"compress", d}, "is a directory"},
		{[]string{"compress", "-m", "zstd", bad}, "unknown method"},
		{[]string{"compress", "-l", "0", bad}, "level must be"},
		{[]string{"decompress", bad}, "not a valid KOL1"},
		{[]string{"bench"}, "at least 1 file"},
		{[]string{"inspect", bad}, "not a valid KOL1"},
		{[]string{"frobnicate"}, "unknown command"},
	}
	for _, c := range cases {
		_, e, err := run(t, nil, c.args...)
		if err == nil || !strings.Contains(e, c.want) || strings.Contains(e, "kolmo: kolmo:") {
			t.Errorf("%v: err=%v stderr=%q (want %q)", c.args, err, e, c.want)
		}
	}
}

func TestInspectAndBenchAndHeat(t *testing.T) {
	d := t.TempDir()
	in := filepath.Join(d, "t.txt")
	os.WriteFile(in, []byte(strings.Repeat("inspect bench heat ", 300)), 0o644)
	run(t, nil, "compress", "-m", "deflate", in)
	o, _, err := run(t, nil, "inspect", in+".kol")
	if err != nil || !strings.Contains(o, "method:    deflate") || !strings.Contains(o, "5700 bytes") {
		t.Fatalf("inspect: %v %q", err, o)
	}
	o, _, err = run(t, nil, "bench", in)
	if err != nil || strings.Contains(o, "FAIL") || strings.Count(o, "yes") != 6 {
		t.Fatalf("bench: %v %q", err, o)
	}
	if _, _, err = run(t, nil, "heat", in); err != nil {
		t.Fatal(err)
	}
	h, _ := os.ReadFile(in + ".heat.html")
	if !strings.Contains(string(h), "<!doctype html>") {
		t.Fatal("heat report missing")
	}
}

func TestCorruptedFileDetected(t *testing.T) {
	d := t.TempDir()
	in := filepath.Join(d, "c.txt")
	os.WriteFile(in, []byte(strings.Repeat("integrity matters ", 200)), 0o644)
	run(t, nil, "compress", "-m", "cm", in)
	b, _ := os.ReadFile(in + ".kol")
	b[len(b)/2] ^= 0x10
	os.WriteFile(in+".kol", b, 0o644)
	if _, _, err := run(t, nil, "decompress", "-f", in+".kol", "-o", filepath.Join(d, "o")); err == nil {
		t.Fatal("corruption not detected")
	}
	if _, err := os.Stat(filepath.Join(d, "o")); err == nil {
		t.Fatal("wrote output despite corruption")
	}
}
