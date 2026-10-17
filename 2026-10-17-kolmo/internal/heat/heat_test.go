package heat

import (
	"strings"
	"testing"
)

func TestRenderEscapesAndReports(t *testing.T) {
	data := []byte("say \"hi\" & <script>alert(1)</script>\n\x00\xff tail\n")
	out := Render("evil\"name<.txt", data, 0)
	if strings.Contains(out, "<script>alert") || strings.Contains(out, `evil"name<`) {
		t.Fatal("unescaped input reached the HTML")
	}
	for _, want := range []string{"bits / byte", "data-costs=", "Most surprising lines"} {
		if !strings.Contains(out, want) {
			t.Fatalf("missing %q", want)
		}
	}
}

func TestRenderTruncates(t *testing.T) {
	out := Render("x", []byte(strings.Repeat("abc ", 1000)), 100)
	if !strings.Contains(out, "truncated") || !strings.Contains(out, ">100<") {
		t.Fatal("truncation not reported")
	}
}
