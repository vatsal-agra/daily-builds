package report

import (
	"encoding/json"
	"math"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"bayou/internal/bn"
	"bayou/internal/graph"
	"bayou/internal/infer"
	"bayou/internal/parse"
)

func load(t testing.TB, name string) *bn.Network {
	t.Helper()
	src, err := os.ReadFile(filepath.Join("..", "..", "examples", name))
	if err != nil {
		t.Fatal(err)
	}
	n, err := parse.ParseBN(name, string(src))
	if err != nil {
		t.Fatal(err)
	}
	return n
}

func TestLayoutIsLayeredAndNonOverlapping(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	for trial := 0; trial < 100; trial++ {
		n := bn.Random(rng, bn.RandomOpts{Vars: 1 + rng.Intn(30), MaxParents: 3, MaxCard: 5, EdgeProb: rng.Float64()})
		boxes := Layout(n)
		for v, x := range n.Vars {
			for _, p := range x.Parents {
				if !(boxes[p].Y+boxes[p].H < boxes[v].Y) {
					t.Fatalf("parent %d is not strictly above child %d", p, v)
				}
			}
			if boxes[v].H != NodeHeight(n.Card(v)) || boxes[v].X < 0 || boxes[v].Y < 0 {
				t.Fatalf("bad box %v", boxes[v])
			}
		}
		for i := range boxes {
			for j := i + 1; j < len(boxes); j++ {
				a, b := boxes[i], boxes[j]
				if a.X < b.X+b.W && b.X < a.X+a.W && a.Y < b.Y+b.H && b.Y < a.Y+a.H {
					t.Fatalf("nodes %d and %d overlap: %v %v", i, j, a, b)
				}
			}
		}
	}
}

func TestBuildEscapesHostileNames(t *testing.T) {
	n := bn.New(`</script><img src=x onerror=alert(1)>&"'`)
	n.AddVar(`</script><script>alert(2)</script>`, []string{`<b>x</b>`, "y z"})
	page, err := Build(n, nil)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(page, "<img src=x") || strings.Contains(page, "<script>alert(2)") {
		t.Fatal("unescaped markup reached the page")
	}
	// exactly the template's own script blocks: data, engine, app
	if c := strings.Count(page, "</script>"); c != 3 {
		t.Fatalf("expected 3 closing script tags, found %d", c)
	}
	if strings.Contains(page, " ") {
		t.Fatal("raw U+2028 inside inline script")
	}
}

func TestBuildLimits(t *testing.T) {
	big := bn.Random(rand.New(rand.NewSource(1)), bn.RandomOpts{Vars: MaxVars + 1, MaxParents: 1, MaxCard: 2})
	if _, err := Build(big, nil); err == nil {
		t.Fatal("oversized network accepted")
	}
	dense := bn.Random(rand.New(rand.NewSource(2)), bn.RandomOpts{Vars: 60, MaxParents: 5, MaxCard: 3, EdgeProb: 0.9})
	if _, err := Build(dense, nil); err == nil {
		t.Fatal("intractable network accepted")
	}
	if _, err := Build(load(t, "asia.bn"), bn.Evidence{0: 1}); err != nil {
		t.Fatal(err)
	}
}

// The browser engine must agree with the Go junction tree on every marginal,
// on log P(evidence), on impossible evidence, and with Go's d-separation.
func TestBrowserEngineMatchesGo(t *testing.T) {
	node, err := exec.LookPath("node")
	if err != nil {
		t.Skip("node not installed; browser-engine check skipped")
	}
	type caseT struct {
		Evidence   map[int]int `json:"evidence"`
		Impossible bool        `json:"impossible"`
		Marginals  [][]float64 `json:"marginals"`
		LogPe      float64     `json:"logPe"`
		Start      int         `json:"start"`
		Reach      []int       `json:"reach"`
	}
	type netCase struct {
		Net   jsData  `json:"net"`
		Cases []caseT `json:"cases"`
	}
	var all []netCase
	rng := rand.New(rand.NewSource(42))
	nets := []*bn.Network{load(t, "asia.bn"), load(t, "student.bn"), load(t, "car.bn"), load(t, "burglar.bn")}
	for i := 0; i < 12; i++ {
		nets = append(nets, bn.Random(rng, bn.RandomOpts{Vars: 3 + rng.Intn(8), MaxParents: 3, MaxCard: 4, ZeroProb: 0.15}))
	}
	for _, n := range nets {
		jt, err := infer.NewJT(n)
		if err != nil {
			t.Fatal(err)
		}
		nc := netCase{Net: jsData{Name: n.Name}}
		for _, v := range n.Vars {
			nc.Net.Vars = append(nc.Net.Vars, jsVar{v.Name, v.States, nonNil(v.Parents), v.CPT})
		}
		for k := 0; k < 12; k++ {
			ev := bn.Evidence{}
			for v := range n.Vars {
				if rng.Float64() < 0.3 {
					ev[v] = rng.Intn(n.Card(v))
				}
			}
			c := caseT{Evidence: map[int]int(ev), Start: rng.Intn(len(n.Vars))}
			ms, lpe, err := jt.Marginals(ev)
			if err == infer.ErrImpossible {
				c.Impossible = true
			} else if err != nil {
				t.Fatal(err)
			} else {
				c.LogPe = lpe
				for _, f := range ms {
					c.Marginals = append(c.Marginals, f.Probs())
				}
			}
			var obs []int
			for v := range ev {
				obs = append(obs, v)
			}
			for v := range graph.Reachable(n, []int{c.Start}, obs) {
				c.Reach = append(c.Reach, v)
			}
			nc.Cases = append(nc.Cases, c)
		}
		all = append(all, nc)
	}
	dir := t.TempDir()
	raw, _ := json.Marshal(all)
	os.WriteFile(filepath.Join(dir, "cases.json"), raw, 0o644)
	os.WriteFile(filepath.Join(dir, "engine.js"), []byte(engineJS), 0o644)
	script := `
const E = require('./engine.js'); const all = require('./cases.json');
let checked = 0, imp = 0;
for (const nc of all) for (const c of nc.cases) {
  const r = E.marginals(nc.net, c.evidence);
  if (c.impossible) { if (r !== null) { console.log('expected impossible'); process.exit(1); } imp++; continue; }
  if (r === null) { console.log('engine says impossible but Go does not', nc.net.name, JSON.stringify(c.evidence)); process.exit(1); }
  if (Math.abs(r.logEvidence - c.logPe) > 1e-9) { console.log('logPe', r.logEvidence, c.logPe); process.exit(1); }
  c.marginals.forEach((m, v) => m.forEach((p, s) => { if (Math.abs(p - r.marginals[v][s]) > 1e-9) { console.log('marginal mismatch', nc.net.name, v, s, p, r.marginals[v][s]); process.exit(1); } }));
  const reach = Array.from(E.dConnected(nc.net, c.start, Object.keys(c.evidence).map(Number))).sort((a,b)=>a-b);
  const want = c.reach.slice().sort((a,b)=>a-b);
  if (JSON.stringify(reach) !== JSON.stringify(want)) { console.log('d-connected mismatch', reach, want); process.exit(1); }
  checked++;
}
console.log('OK ' + checked + ' feasible, ' + imp + ' impossible');
`
	os.WriteFile(filepath.Join(dir, "check.js"), []byte(script), 0o644)
	cmd := exec.Command(node, "check.js")
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("browser engine disagrees with Go:\n%s", out)
	}
	t.Log(strings.TrimSpace(string(out)))
	if !strings.HasPrefix(string(out), "OK") || math.IsNaN(0) {
		t.Fatal(string(out))
	}
}
