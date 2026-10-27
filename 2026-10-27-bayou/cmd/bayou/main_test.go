package main

import (
	"bytes"
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func ex(name string) string { return filepath.Join("..", "..", "examples", name) }

func bayou(t *testing.T, args ...string) (string, string, int) {
	t.Helper()
	var o, e bytes.Buffer
	rc := run(args, &o, &e)
	return o.String(), e.String(), rc
}

func mustOK(t *testing.T, args ...string) string {
	t.Helper()
	o, e, rc := bayou(t, args...)
	if rc != 0 {
		t.Fatalf("bayou %v: exit %d\n%s%s", args, rc, o, e)
	}
	return o
}

func TestQueryAsiaGoldenNumbers(t *testing.T) {
	var out struct {
		PEvidence float64 `json:"p_evidence"`
		Table     []struct {
			Assignment map[string]string `json:"assignment"`
			P          float64           `json:"p"`
		} `json:"table"`
	}
	js := mustOK(t, "query", ex("asia.bn"), "-q", "Tuberculosis", "-e", "XRay=abnormal,Smoking=yes", "--json")
	if err := json.Unmarshal([]byte(js), &out); err != nil {
		t.Fatal(err)
	}
	// Independently computed (enumeration over the 256-state joint) values.
	if math.Abs(out.PEvidence-0.0758524) > 1e-6 {
		t.Fatalf("P(evidence) = %g", out.PEvidence)
	}
	if math.Abs(out.Table[0].P-0.067183) > 2e-6 {
		t.Fatalf("P(TB=yes | ...) = %g", out.Table[0].P)
	}
}

func TestEnginesAgreeOnCLI(t *testing.T) {
	for _, net := range []string{"asia.bn", "car.bn", "student.bn"} {
		var outs []string
		for _, eng := range []string{"ve", "jt", "enum"} {
			q := map[string]string{"asia.bn": "Dyspnea,LungCancer", "car.bn": "Starts,BatteryDead", "student.bn": "Letter"}[net]
			e := map[string]string{"asia.bn": "Smoking=yes", "car.bn": "Lights=dim", "student.bn": "SAT=high"}[net]
			outs = append(outs, mustOK(t, "query", ex(net), "-q", q, "-e", e, "--engine", eng))
		}
		if outs[0] != outs[1] || outs[0] != outs[2] {
			t.Fatalf("%s: engines print different tables:\n%s\n%s\n%s", net, outs[0], outs[1], outs[2])
		}
	}
}

func TestExplainingAway(t *testing.T) {
	// Pearl's classic: an alarm raises P(burglary); learning of an earthquake explains it away.
	p := func(extra string) float64 {
		args := []string{"query", ex("burglar.bn"), "-q", "Burglary", "--json", "-e", "Alarm=yes" + extra}
		var out struct {
			Table []struct{ P float64 } `json:"table"`
		}
		json.Unmarshal([]byte(mustOK(t, args...)), &out)
		return out.Table[0].P
	}
	prior := 0.001
	alarm, quake := p(""), p(",Earthquake=yes")
	if !(alarm > 100*prior && quake < alarm/10) {
		t.Fatalf("prior %g, given alarm %g, given alarm+quake %g", prior, alarm, quake)
	}
	if math.Abs(alarm-0.37355) > 1e-4 {
		t.Fatalf("P(B|A) = %g, textbook says 0.3736", alarm)
	}
}

func TestMPEAndMAPCommands(t *testing.T) {
	o := mustOK(t, "mpe", ex("burglar.bn"), "-e", "JohnCalls=yes,MaryCalls=yes")
	if !strings.Contains(o, "Alarm") || !strings.Contains(o, "= yes") {
		t.Fatalf("unexpected MPE output:\n%s", o)
	}
	o = mustOK(t, "map", ex("burglar.bn"), "-q", "Burglary,Earthquake", "-e", "Alarm=yes", "--json")
	var r struct {
		Assignment map[string]string `json:"assignment"`
		Posterior  float64           `json:"posterior"`
	}
	json.Unmarshal([]byte(o), &r)
	// Joint weights given Alarm=yes: (B,E)=(n,n) .999*.998*.001=9.97e-4 beats (y,n) 9.38e-4 and (n,y) 5.79e-4,
	// so the jointly most probable explanation is "false alarm" even though P(B=yes|alarm)=0.37.
	if r.Assignment["Burglary"] != "no" || r.Assignment["Earthquake"] != "no" || math.Abs(r.Posterior-0.3961) > 1e-3 {
		t.Fatalf("unexpected MAP %v posterior %g", r.Assignment, r.Posterior)
	}
}

func TestDsepCommandAndIndependencies(t *testing.T) {
	o := mustOK(t, "dsep", ex("burglar.bn"), "-x", "Burglary", "-y", "Earthquake")
	if !strings.Contains(o, "are d-separated given nothing") {
		t.Fatal(o)
	}
	o = mustOK(t, "dsep", ex("burglar.bn"), "-x", "Burglary", "-y", "Earthquake", "-z", "JohnCalls")
	if !strings.Contains(o, "NOT d-separated") {
		t.Fatalf("observing a descendant of a collider must connect the parents:\n%s", o)
	}
	o = mustOK(t, "independencies", ex("burglar.bn"), "-z", "Alarm")
	if !strings.Contains(o, "JohnCalls ⫫ MaryCalls | {Alarm}") {
		t.Fatal(o)
	}
	o = mustOK(t, "blanket", ex("burglar.bn"), "-v", "Burglary")
	if !strings.Contains(o, "Alarm") || !strings.Contains(o, "Earthquake") {
		t.Fatal(o)
	}
}

func TestSampleLearnPipeline(t *testing.T) {
	dir := t.TempDir()
	csv, learned := filepath.Join(dir, "d.csv"), filepath.Join(dir, "l.bn")
	mustOK(t, "sample", ex("student.bn"), "-n", "30000", "--seed", "9", "-o", csv)
	o := mustOK(t, "learn", ex("student.bn"), csv, "--alpha", "1", "--truth", ex("student.bn"), "-o", learned)
	if !strings.Contains(o, "KL(truth‖learned)") {
		t.Fatal(o)
	}
	// the written network must be loadable and valid
	mustOK(t, "check", learned)
	// deterministic sampling
	a := mustOK(t, "sample", ex("student.bn"), "-n", "50", "--seed", "4")
	b := mustOK(t, "sample", ex("student.bn"), "-n", "50", "--seed", "4")
	if a != b {
		t.Fatal("same seed gave different samples")
	}
	// latent + missing → EM
	mustOK(t, "sample", ex("weather-hmm.bn"), "-n", "500", "--hide", "W1,W2,W3,W4,W5", "--missing", "0.1", "-o", csv)
	o = mustOK(t, "learn", ex("weather-hmm.bn"), csv, "--em", "--random", "--iters", "30")
	if !strings.Contains(o, "EM:") {
		t.Fatal(o)
	}
	// plain MLE must refuse latent columns instead of silently guessing
	_, e, rc := bayou(t, "learn", ex("weather-hmm.bn"), csv)
	if rc != 1 || !strings.Contains(e, "--em") {
		t.Fatalf("rc=%d err=%q", rc, e)
	}
}

func TestConvertRoundTrip(t *testing.T) {
	dir := t.TempDir()
	bif := filepath.Join(dir, "a.bif")
	mustOK(t, "convert", ex("car.bn"), "--to", "bif", "-o", bif)
	if a, b := mustOK(t, "convert", bif, "--to", "bn"), mustOK(t, "convert", ex("car.bn"), "--to", "bn"); a != b {
		t.Fatal("bn → bif → bn changed the network")
	}
}

func TestErrorsAndExitCodes(t *testing.T) {
	cases := []struct {
		args []string
		rc   int
		msg  string
	}{
		{nil, 2, ""},
		{[]string{"nosuch"}, 2, "unknown command"},
		{[]string{"query"}, 2, "missing network file"},
		{[]string{"query", ex("asia.bn")}, 2, "-q needs"},
		{[]string{"query", "nonexistent.bn", "-q", "A"}, 1, "no such file"},
		{[]string{"query", ex("asia.bn"), "-q", "Smokin"}, 1, `did you mean "Smoking"`},
		{[]string{"query", ex("asia.bn"), "-q", "Smoking", "-e", "XRay=maybe"}, 1, "no state"},
		{[]string{"query", ex("asia.bn"), "-q", "Smoking", "-e", "Smoking=yes"}, 1, "both queried and observed"},
		{[]string{"query", ex("asia.bn"), "-q", "Smoking", "-e", "Either=no,Tuberculosis=yes"}, 1, "impossible"},
		{[]string{"query", ex("asia.bn"), "-q", "Smoking", "--engine", "x"}, 2, "--engine"},
		{[]string{"query", ex("asia.bn"), "-q", "Smoking", "--bogus"}, 2, "bogus"},
		{[]string{"query", ex("asia.bn"), "extra", "-q", "Smoking"}, 2, "unexpected argument"},
		{[]string{"mpe", ex("sprinkler.bn"), "-e", "Cloudy=true,Sprinkler=on,Rain=true,WetGrass=true"}, 1, "nothing to explain"},
		{[]string{"dsep", ex("asia.bn"), "-x", "Smoking", "-y", "Smoking"}, 1, "both"},
		{[]string{"sample", ex("asia.bn"), "-n", "-1"}, 2, ">= 0"},
		{[]string{"sample", ex("asia.bn"), "--missing", "2"}, 2, "[0,1)"},
		{[]string{"convert", ex("asia.bn"), "--to", "pdf"}, 2, "--to"},
		{[]string{"gen", "--vars", "0"}, 2, "vars"},
	}
	for _, c := range cases {
		_, e, rc := bayou(t, c.args...)
		if rc != c.rc || !strings.Contains(e, c.msg) {
			t.Errorf("bayou %v: rc=%d (want %d) stderr=%q (want %q)", c.args, rc, c.rc, e, c.msg)
		}
	}
	o, _, rc := bayou(t, "help")
	if rc != 0 || !strings.Contains(o, "usage: bayou") {
		t.Error("help should exit 0")
	}
}

func TestCheckReportsEveryProblem(t *testing.T) {
	p := filepath.Join(t.TempDir(), "bad.bn")
	os.WriteFile(p, []byte("var A {a,b}\ncpt A = 0.5, 0.6\n"), 0o644)
	_, e, rc := bayou(t, "check", p)
	if rc != 1 || !strings.Contains(e, "sums to 1.1") || !strings.Contains(e, "bad.bn:") {
		t.Fatalf("rc=%d %q", rc, e)
	}
}

func TestGenIsLoadableAndDeterministic(t *testing.T) {
	a := mustOK(t, "gen", "--vars", "12", "--seed", "3")
	b := mustOK(t, "gen", "--vars", "12", "--seed", "3")
	if a != b {
		t.Fatal("gen not deterministic")
	}
	p := filepath.Join(t.TempDir(), "g.bn")
	os.WriteFile(p, []byte(a), 0o644)
	mustOK(t, "check", p)
	mustOK(t, "marginals", p)
}

func TestInfoWarnsWhenIntractable(t *testing.T) {
	p := filepath.Join(t.TempDir(), "big.bn")
	os.WriteFile(p, []byte(mustOK(t, "gen", "--vars", "200", "--parents", "4", "--seed", "1")), 0o644)
	o := mustOK(t, "info", p)
	if !strings.Contains(o, "infeasible") {
		t.Fatalf("expected a warning:\n%s", o)
	}
	_, e, rc := bayou(t, "marginals", p)
	if rc != 1 || !strings.Contains(e, "too large") {
		t.Fatalf("rc=%d %q", rc, e)
	}
}

func TestApproxCommand(t *testing.T) {
	o := mustOK(t, "approx", ex("burglar.bn"), "-q", "Burglary", "-e", "Alarm=yes", "-n", "50000", "--json")
	var r struct {
		MaxAbsError float64 `json:"max_abs_error"`
		ESS         float64 `json:"ess"`
	}
	if err := json.Unmarshal([]byte(o), &r); err != nil {
		t.Fatal(err)
	}
	if r.MaxAbsError > 0.02 || r.ESS < 100 {
		t.Fatalf("LW result off: %+v", r)
	}
	o = mustOK(t, "approx", ex("student.bn"), "-q", "Grade", "--method", "gibbs", "-n", "5000")
	if !strings.Contains(o, "R̂") || !strings.Contains(o, "exact (variable elimination) differs") {
		t.Fatal(o)
	}
	// works where exact inference cannot
	p := filepath.Join(t.TempDir(), "big.bn")
	os.WriteFile(p, []byte(mustOK(t, "gen", "--vars", "150", "--parents", "4", "--seed", "2")), 0o644)
	o = mustOK(t, "approx", p, "-q", "X149", "-e", "X0=s0", "--method", "gibbs", "-n", "2000")
	if !strings.Contains(o, "infeasible") {
		t.Fatalf("expected the infeasibility note:\n%s", o)
	}
	_, e, rc := bayou(t, "approx", ex("asia.bn"), "-q", "Smoking", "-e", "Either=no,Tuberculosis=yes")
	if rc != 1 || !strings.Contains(e, "probability zero") {
		t.Fatalf("rc=%d %q", rc, e)
	}
	if _, _, rc := bayou(t, "approx", ex("asia.bn"), "-q", "Smoking", "--method", "magic"); rc != 2 {
		t.Fatal("bad method accepted")
	}
}

func TestStructureCommand(t *testing.T) {
	dir := t.TempDir()
	csv, out := filepath.Join(dir, "d.csv"), filepath.Join(dir, "l.bn")
	mustOK(t, "sample", ex("student.bn"), "-n", "20000", "--seed", "5", "-o", csv)
	o := mustOK(t, "structure", ex("student.bn"), csv, "--score", "bic", "--truth", ex("student.bn"), "-o", out)
	if !strings.Contains(o, "SHD 0") || !strings.Contains(o, "Intelligence → Grade") {
		t.Fatal(o)
	}
	mustOK(t, "check", out)
	if _, e, rc := bayou(t, "structure", ex("student.bn"), csv, "--score", "aic"); rc != 2 || !strings.Contains(e, "unknown score") {
		t.Fatalf("rc=%d %q", rc, e)
	}
	// a CSV that lacks columns cannot be used for structure learning
	os.WriteFile(csv, []byte("Difficulty,Grade\neasy,A\nhard,B\n"), 0o644)
	if _, e, rc := bayou(t, "structure", ex("student.bn"), csv); rc != 1 || !strings.Contains(e, "every variable") {
		t.Fatalf("rc=%d %q", rc, e)
	}
}

func TestVOICommand(t *testing.T) {
	o := mustOK(t, "voi", ex("car.bn"), "-q", "BatteryDead", "-e", "Starts=no", "--detail", "--cost", "Radio=0.1")
	if !strings.Contains(o, "gain/cost") || !strings.Contains(o, "if you observe") {
		t.Fatal(o)
	}
	var r struct {
		Cands []struct {
			Variable string  `json:"variable"`
			Gain     float64 `json:"gain_bits"`
		} `json:"candidates"`
	}
	if err := json.Unmarshal([]byte(mustOK(t, "voi", ex("car.bn"), "-q", "BatteryDead", "--json")), &r); err != nil {
		t.Fatal(err)
	}
	if len(r.Cands) != 9 || r.Cands[0].Gain < r.Cands[1].Gain {
		t.Fatalf("%+v", r.Cands)
	}
	for _, bad := range [][]string{{"--cost", "Radio"}, {"--cost", "Nope=1"}, {"--cost", "Radio=-1"}, {"--cost", "Radio=abc"}} {
		args := append([]string{"voi", ex("car.bn"), "-q", "BatteryDead"}, bad...)
		if _, _, rc := bayou(t, args...); rc == 0 {
			t.Errorf("accepted %v", bad)
		}
	}
}

func TestReportCommand(t *testing.T) {
	p := filepath.Join(t.TempDir(), "r.html")
	mustOK(t, "report", ex("asia.bn"), "-e", "Smoking=yes", "-o", p)
	b, _ := os.ReadFile(p)
	s := string(b)
	for _, want := range []string{"<!doctype html>", "BayouEngine", `"name":"Asia"`, "prefers-color-scheme"} {
		if !strings.Contains(s, want) {
			t.Errorf("report lacks %q", want)
		}
	}
	if strings.Contains(s, "http://") && strings.Contains(strings.ReplaceAll(s, "http://www.w3.org/2000/svg", ""), "http://") {
		t.Error("report must be self-contained (no external URLs)")
	}
	if strings.Contains(s, "https://") {
		t.Error("report references an external resource")
	}
	if _, e, rc := bayou(t, "report", ex("asia.bn")); rc != 2 || !strings.Contains(e, "-o") {
		t.Fatalf("rc=%d %q", rc, e)
	}
	if _, e, rc := bayou(t, "report", ex("asia.bn"), "-o", p, "-e", "Either=no,Tuberculosis=yes"); rc != 1 || !strings.Contains(e, "impossible") {
		t.Fatalf("rc=%d %q", rc, e)
	}
}
