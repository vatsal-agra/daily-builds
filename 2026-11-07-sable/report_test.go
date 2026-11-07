package sable

import (
	"strings"
	"testing"
)

func TestReportRenders(t *testing.T) {
	src := "// <b>tag</b> & stuff\nfunc g(x) { if x > 2 { return x * 2; } return x; }\nfunc main() { var s = 0; for var i = 0; i < 6; i = i + 1 { s = s + g(i); } print(s); return s; }\n"
	page, err := Report("t<est>.sb", src, Config{OptLevel: 2, Regs: 4, Alg: LinearScan})
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"<svg class=\"cfg\"", "<svg class=\"ivl\"", "<svg class=\"chart\"", "all 14 configurations agree", "phi", "t&lt;est&gt;.sb", "&lt;b&gt;tag&lt;/b&gt;"} {
		if !strings.Contains(page, want) {
			t.Errorf("report lacks %q", want)
		}
	}
	if strings.Contains(page, "<b>tag</b>") || strings.Contains(page, "http://") && !strings.Contains(page, "w3.org") {
		t.Error("unescaped HTML or external reference in report")
	}
	if _, err := Report("x", "func main() { while 1 { } }", Config{OptLevel: 2, Regs: 4}); err == nil {
		t.Error("report of a non-terminating program must fail cleanly")
	}
}
