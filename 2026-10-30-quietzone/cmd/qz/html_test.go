package main

import (
	"encoding/json"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"quietzone/qr"
)

// The explorer's in-browser verdict ("guaranteed to scan") must agree with the
// real Go decoder for arbitrary data-area damage: whenever the page says the
// symbol survives, qr.Decode must actually read it.
func TestExplorerVerdictAgreesWithDecoder(t *testing.T) {
	node, err := exec.LookPath("node")
	if err != nil {
		t.Skip("node not available")
	}
	dir := t.TempDir()
	text := "https://example.com/quietzone/anatomy?id=0123456789"
	for _, lvl := range []qr.ECC{qr.L, qr.Q, qr.H} {
		page, code, err := buildExplorer(text, lvl)
		if err != nil {
			t.Fatal(err)
		}
		ex := code.Explain()
		n := code.Matrix.N
		var pool []int
		for i, m := range ex.Modules {
			if m.Kind == qr.KData && m.CW >= 0 {
				pool = append(pool, i)
			}
		}
		rng := rand.New(rand.NewSource(int64(lvl) + 5))
		var cases [][]int
		for k := 0; k < 120; k++ {
			cnt := 1 + rng.Intn(len(pool)/(3+int(lvl)*2))
			if k%4 == 0 { // clustered damage: a rectangular smear
				cnt = 1 + rng.Intn(12)
			}
			var flips []int
			if k%4 == 0 {
				c := pool[rng.Intn(len(pool))]
				for dy := 0; dy < 1+rng.Intn(5); dy++ {
					for dx := 0; dx < 1+rng.Intn(5); dx++ {
						if x, y := c%n+dx, c/n+dy; x < n && y < n && ex.Modules[y*n+x].Kind == qr.KData && ex.Modules[y*n+x].CW >= 0 {
							flips = append(flips, y*n+x)
						}
					}
				}
			} else {
				for _, i := range rng.Perm(len(pool))[:cnt] {
					flips = append(flips, pool[i])
				}
			}
			cases = append(cases, flips)
		}
		pf, cf := filepath.Join(dir, "p.html"), filepath.Join(dir, "c.json")
		cj, _ := json.Marshal(cases)
		if err := os.WriteFile(pf, []byte(page), 0o644); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(cf, cj, 0o644); err != nil {
			t.Fatal(err)
		}
		cmd := exec.Command(node, "../../tools/check_html.js", pf, cf, filepath.Join(dir, "shot"))
		cmd.Env = append(os.Environ(), "NODE_PATH="+nodePath())
		outb, err := cmd.CombinedOutput()
		if err != nil {
			if strings.Contains(string(outb), "Cannot find module") || strings.Contains(string(outb), "Executable doesn't exist") {
				t.Skipf("headless browser unavailable: %v", err)
			}
			t.Fatalf("browser check failed: %v\n%s", err, outb)
		}
		var res struct {
			Verdicts []bool   `json:"verdicts"`
			Errors   []string `json:"errors"`
			Overflow bool     `json:"overflow"`
		}
		line := outb[strings.LastIndexByte(strings.TrimSpace(string(outb)), '\n')+1:]
		if err := json.Unmarshal(line, &res); err != nil {
			t.Fatalf("bad output: %v\n%s", err, outb)
		}
		if len(res.Errors) > 0 || res.Overflow {
			t.Fatalf("page errors %v overflow=%v", res.Errors, res.Overflow)
		}
		guaranteed, beyond, luck := 0, 0, 0
		for i, flips := range cases {
			m := code.Matrix.Clone()
			for _, f := range flips {
				m.Set(f%n, f/n, !m.Get(f%n, f/n))
			}
			r, derr := qr.Decode(m)
			ok := derr == nil && r.Text == text
			if res.Verdicts[i] {
				guaranteed++
				if !ok {
					t.Fatalf("level %v case %d: page promises recovery but decoder failed (%v)", lvl, i, derr)
				}
			} else {
				beyond++
				if ok {
					luck++
				}
			}
		}
		t.Logf("level %v: %d guaranteed (all decoded), %d beyond budget (%d decoded anyway through luck)", lvl, guaranteed, beyond, luck)
		if guaranteed == 0 || beyond == 0 {
			t.Fatalf("level %v: test did not exercise both outcomes", lvl)
		}
	}
}

func nodePath() string {
	out, err := exec.Command("npm", "root", "-g").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}
