package main

import (
	"bytes"
	"fmt"
	"math"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"testing"
)

var (
	buildOnce sync.Once
	binPath   string
	buildErr  error
)

func skein(t *testing.T, args ...string) (string, string, int) {
	t.Helper()
	buildOnce.Do(func() {
		dir, err := os.MkdirTemp("", "skein-bin")
		if err != nil {
			buildErr = err
			return
		}
		binPath = filepath.Join(dir, "skein")
		if out, err := exec.Command("go", "build", "-o", binPath, ".").CombinedOutput(); err != nil {
			buildErr = fmt.Errorf("%v\n%s", err, out)
		}
	})
	if buildErr != nil {
		t.Fatal(buildErr)
	}
	cmd := exec.Command(binPath, args...)
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

// workload writes two shard files + the concatenation; returns exact stats.
type workload struct {
	dir                 string
	shardA, shardB, all string
	distinct            int
	counts              map[string]int
	values              []float64
}

func makeWorkload(t *testing.T, n int) *workload {
	t.Helper()
	dir := t.TempDir()
	w := &workload{dir: dir, counts: map[string]int{}}
	r := rand.New(rand.NewSource(4))
	z := rand.NewZipf(r, 1.15, 1, 15000)
	var a, b, all strings.Builder
	for i := 0; i < n; i++ {
		k := fmt.Sprintf("user%d", z.Uint64())
		v := math.Exp(r.NormFloat64()*0.7 + 3)
		line := fmt.Sprintf("%s\t%.4f\n", k, v)
		w.counts[k]++
		w.values = append(w.values, v)
		all.WriteString(line)
		if i%2 == 0 {
			a.WriteString(line)
		} else {
			b.WriteString(line)
		}
	}
	w.distinct = len(w.counts)
	w.shardA, w.shardB, w.all = filepath.Join(dir, "a.tsv"), filepath.Join(dir, "b.tsv"), filepath.Join(dir, "all.tsv")
	for p, s := range map[string]string{w.shardA: a.String(), w.shardB: b.String(), w.all: all.String()} {
		if err := os.WriteFile(p, []byte(s), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return w
}

func TestStatsAccuracyAndMergeEquivalence(t *testing.T) {
	w := makeWorkload(t, 120000)
	sa, sb, sall, merged := filepath.Join(w.dir, "a.skn"), filepath.Join(w.dir, "b.skn"), filepath.Join(w.dir, "all.skn"), filepath.Join(w.dir, "m.skn")
	out, _, code := skein(t, "stats", "-f", "1", "-v", "2", "-o", sall, w.all)
	if code != 0 {
		t.Fatalf("stats exit %d", code)
	}
	skein(t, "stats", "-f", "1", "-v", "2", "-o", sa, w.shardA)
	skein(t, "stats", "-f", "1", "-v", "2", "-o", sb, w.shardB)
	if _, e, code := skein(t, "merge", "-o", merged, sa, sb); code != 0 {
		t.Fatalf("merge: %s", e)
	}

	// distinct estimate within 4σ (σ=0.81%)
	m := regexp.MustCompile(`distinct keys\s+≈ ([\d.]+)(k?)`).FindStringSubmatch(out)
	if m == nil {
		t.Fatalf("no distinct line in:\n%s", out)
	}
	if !strings.Contains(out, fmt.Sprintf("records            %d", 120000)) {
		t.Fatalf("record count missing:\n%s", out)
	}
	// top-1 is the true top key with an exact count
	var best string
	for k, v := range w.counts {
		if v > w.counts[best] {
			best = k
		}
	}
	if !strings.Contains(out, fmt.Sprintf("1. %s", best)) || !strings.Contains(out, strconv.Itoa(w.counts[best])) {
		t.Fatalf("true top key %s (%d) not reported first:\n%s", best, w.counts[best], out)
	}

	// merged state ≡ single-pass state for the exactly-mergeable parts
	im, _, _ := skein(t, "inspect", merged)
	ia, _, _ := skein(t, "inspect", sall)
	re := regexp.MustCompile(`records \d+; distinct ≈ \d+`)
	if re.FindString(im) != re.FindString(ia) || re.FindString(im) == "" {
		t.Fatalf("merged != single pass:\n%s\n%s", im, ia)
	}
	// incremental update: load A, feed B  ==  merge(A,B)
	skein(t, "stats", "-load", sa, "-f", "1", "-v", "2", "-o", filepath.Join(w.dir, "inc.skn"), w.shardB)
	ii, _, _ := skein(t, "inspect", filepath.Join(w.dir, "inc.skn"))
	if re.FindString(ii) != re.FindString(ia) {
		t.Fatalf("incremental != single pass:\n%s\n%s", ii, ia)
	}
}

func TestCountExactComparison(t *testing.T) {
	w := makeWorkload(t, 60000)
	out, _, code := skein(t, "count", "-f", "1", "-exact", w.all)
	if code != 0 {
		t.Fatal(out)
	}
	m := regexp.MustCompile(`error ([+-][\d.]+)%`).FindStringSubmatch(out)
	if m == nil {
		t.Fatalf("no error line:\n%s", out)
	}
	e, _ := strconv.ParseFloat(m[1], 64)
	if math.Abs(e) > 4*0.81 {
		t.Fatalf("HLL error %.2f%% too large", e)
	}
	if !strings.Contains(out, fmt.Sprintf("exact distinct = %d", w.distinct)) {
		t.Fatalf("exact count wrong:\n%s want %d", out, w.distinct)
	}
}

func TestTopReportsGuaranteedBounds(t *testing.T) {
	w := makeWorkload(t, 80000)
	out, _, code := skein(t, "top", "-f", "1", "-k", "5", w.all)
	if code != 0 {
		t.Fatal(out)
	}
	re := regexp.MustCompile(`\d+\. (\S+)\s+(\d+)\s+\(true ∈ \[(\d+), (\d+)\]\)`)
	ms := re.FindAllStringSubmatch(out, -1)
	if len(ms) != 5 {
		t.Fatalf("want 5 rows:\n%s", out)
	}
	for _, m := range ms {
		lo, _ := strconv.Atoi(m[3])
		hi, _ := strconv.Atoi(m[4])
		if tr := w.counts[m[1]]; tr < lo || tr > hi {
			t.Fatalf("%s true=%d outside [%d,%d]", m[1], tr, lo, hi)
		}
	}
}

func TestQuantileMatchesExactWithinRankError(t *testing.T) {
	w := makeWorkload(t, 80000)
	out, _, code := skein(t, "quantile", "-v", "2", "-q", "0.5,0.9,0.99", "-exact", w.all)
	if code != 0 {
		t.Fatal(out)
	}
	re := regexp.MustCompile(`p([\d.]+)\s+([\d.e+-]+)\s+exact ([\d.e+-]+)`)
	ms := re.FindAllStringSubmatch(out, -1)
	if len(ms) != 3 {
		t.Fatalf("rows:\n%s", out)
	}
	for _, m := range ms {
		got, _ := strconv.ParseFloat(m[2], 64)
		ex, _ := strconv.ParseFloat(m[3], 64)
		if math.Abs(got-ex)/ex > 0.03 {
			t.Errorf("p%s got %v exact %v", m[1], got, ex)
		}
	}
}

func TestMembershipBloomAndCuckoo(t *testing.T) {
	w := makeWorkload(t, 30000)
	bf := filepath.Join(w.dir, "b.skn")
	if _, e, code := skein(t, "member", "build", "-f", "1", "-n", strconv.Itoa(w.distinct), "-o", bf, w.all); code != 0 {
		t.Fatal(e)
	}
	out, _, code := skein(t, "member", "check", bf, "user0", "never-seen-key-xyz")
	if code != 3 || !strings.Contains(out, "user0") || !strings.Contains(out, "probably present") || !strings.Contains(out, "definitely absent") {
		t.Fatalf("bloom check code=%d\n%s", code, out)
	}
	if _, _, code := skein(t, "member", "check", bf, "user0"); code != 0 {
		t.Fatal("present key should exit 0")
	}
	if _, e, code := skein(t, "member", "del", bf, "user0"); code == 0 || !strings.Contains(e, "cuckoo") {
		t.Fatalf("bloom delete must fail clearly: %q", e)
	}

	cf := filepath.Join(w.dir, "c.skn")
	out, e, code := skein(t, "member", "build", "-cuckoo", "-f", "1", "-n", strconv.Itoa(w.distinct+500), "-o", cf, w.all)
	if code != 0 {
		t.Fatal(e)
	}
	if !strings.Contains(out, fmt.Sprintf("%d distinct keys stored", w.distinct)) {
		t.Fatalf("cuckoo should store each distinct key once:\n%s want %d", out, w.distinct)
	}
	if o, _, _ := skein(t, "member", "del", cf, "user0"); !strings.Contains(o, "deleted") {
		t.Fatalf("delete: %s", o)
	}
	if _, _, code := skein(t, "member", "check", cf, "user0"); code != 3 {
		t.Fatal("deleted key must be absent")
	}
	if _, _, code := skein(t, "member", "check", cf, "user1"); code != 0 {
		t.Fatal("other keys must survive delete")
	}
	if _, e, code := skein(t, "member", "build", "-cuckoo", "-n", "10", "-o", filepath.Join(w.dir, "x.skn"), w.all); code == 0 || !strings.Contains(e, "raise -n") {
		t.Fatalf("undersized cuckoo must fail helpfully: %q", e)
	}
}

func TestSimAndDups(t *testing.T) {
	dir := t.TempDir()
	a := filepath.Join(dir, "a.txt")
	b := filepath.Join(dir, "b.txt")
	base := strings.Repeat("the quick brown fox jumps over the lazy dog while sixty five other words follow ", 1)
	var wa, wb []string
	for i := 0; i < 80; i++ {
		wa = append(wa, fmt.Sprintf("w%d", i))
		wb = append(wb, fmt.Sprintf("w%d", i+20))
	}
	os.WriteFile(a, []byte(base+strings.Join(wa, " ")), 0o644)
	os.WriteFile(b, []byte(base+strings.Join(wb, " ")), 0o644)
	out, _, code := skein(t, "sim", "-shingle", "1", "-k", "512", "-exact", a, b)
	if code != 0 {
		t.Fatal(out)
	}
	m := regexp.MustCompile(`estimated Jaccard similarity: ([\d.]+)`).FindStringSubmatch(out)
	x := regexp.MustCompile(`exact Jaccard similarity:\s+([\d.]+)`).FindStringSubmatch(out)
	if m == nil || x == nil {
		t.Fatal(out)
	}
	est, _ := strconv.ParseFloat(m[1], 64)
	ex, _ := strconv.ParseFloat(x[1], 64)
	if math.Abs(est-ex) > 0.1 {
		t.Fatalf("est %v exact %v", est, ex)
	}

	docs := filepath.Join(dir, "docs.txt")
	os.WriteFile(docs, []byte("the quick brown fox jumps over the lazy dog today\n"+
		"completely unrelated sentence about database indexes and b trees\n"+
		"the quick brown fox jumps over the lazy dog tonight\n"+
		"the quick brown fox jumps over the lazy dog today\n"+
		"\n"+
		"!!!\n"), 0o644)
	out, _, code = skein(t, "dups", "-t", "0.6", docs)
	if code != 0 {
		t.Fatal(out)
	}
	if !strings.Contains(out, "line 1  ~  line 3") || !strings.Contains(out, "line 1  ~  line 4") || strings.Contains(out, "line 2") && strings.Contains(out, "~  line 2") {
		t.Fatalf("dups:\n%s", out)
	}
	if !strings.Contains(out, "1.00  line 1  ~  line 4") {
		t.Fatalf("exact duplicate not scored 1.00:\n%s", out)
	}
	if !strings.Contains(out, "1 empty skipped") {
		t.Fatalf("punctuation-only line should be reported as skipped:\n%s", out)
	}
}

func TestMergeRefusesMismatchesAndInspectRejectsCorruption(t *testing.T) {
	w := makeWorkload(t, 2000)
	h1, h2, st := filepath.Join(w.dir, "h1.skn"), filepath.Join(w.dir, "h2.skn"), filepath.Join(w.dir, "s.skn")
	skein(t, "count", "-f", "1", "-p", "10", "-o", h1, w.shardA)
	skein(t, "count", "-f", "1", "-p", "12", "-o", h2, w.shardB)
	skein(t, "stats", "-f", "1", "-o", st, w.all)
	if _, e, code := skein(t, "merge", "-o", filepath.Join(w.dir, "x"), h1, h2); code == 0 || !strings.Contains(e, "precision") {
		t.Fatalf("precision mismatch: %q", e)
	}
	if _, e, code := skein(t, "merge", "-o", filepath.Join(w.dir, "x"), h1, st); code == 0 || !strings.Contains(e, "cannot merge") {
		t.Fatalf("type mismatch: %q", e)
	}
	if _, err := os.Stat(filepath.Join(w.dir, "x")); err == nil {
		t.Fatal("failed merge must not write output")
	}
	b, _ := os.ReadFile(st)
	b[len(b)/2] ^= 0xff
	bad := filepath.Join(w.dir, "bad.skn")
	os.WriteFile(bad, b, 0o644)
	if _, e, code := skein(t, "inspect", bad); code == 0 || !strings.Contains(e, "corrupt") {
		t.Fatalf("corruption not detected: %q", e)
	}
	if _, e, code := skein(t, "stats", "-load", bad, w.all); code == 0 || !strings.Contains(e, "corrupt") {
		t.Fatalf("load of corrupt state: %q", e)
	}
}

func TestInputEdgeCases(t *testing.T) {
	dir := t.TempDir()
	empty := filepath.Join(dir, "empty")
	os.WriteFile(empty, nil, 0o644)
	crlf := filepath.Join(dir, "crlf.csv")
	os.WriteFile(crlf, []byte("a,1\r\nb,x\r\nc\r\n\r\nd,4\r\n"), 0o644)
	for _, args := range [][]string{{"stats", empty}, {"top", empty}, {"quantile", empty}, {"count", "missing-file"}, {"top", "-k", "0", crlf}, {"bogus"}, {"member"}, {"count", "-p", "99", crlf}, {"quantile", "-q", "NaN", crlf}, {"stats", "-d", ",", "-f", "9", crlf}} {
		if _, e, code := skein(t, args...); code == 0 || strings.TrimSpace(e) == "" {
			t.Errorf("%v: want failure with message, got code %d stderr %q", args, code, e)
		}
	}
	out, e, code := skein(t, "stats", "-d", ",", "-f", "1", "-v", "2", crlf)
	if code != 0 || !strings.Contains(out, "records            2") || !strings.Contains(e, "skipped 2") {
		t.Fatalf("crlf/bad-lines handling: code=%d\n%s\n%s", code, out, e)
	}
	// stdin
	cmd := exec.Command(binPath, "count")
	cmd.Stdin = strings.NewReader("x\ny\nx\n")
	o, _ := cmd.Output()
	if !strings.Contains(string(o), "lines 3, distinct ≈ 2") {
		t.Fatalf("stdin: %s", o)
	}
	if o, _, code := skein(t, "stats", "-f", "1", "-p", "10", "-load", empty); code == 0 {
		t.Fatalf("flag/load conflict accepted: %s", o)
	}
}

func TestReportQuick(t *testing.T) {
	out := filepath.Join(t.TempDir(), "r.html")
	if _, e, code := skein(t, "report", "-quick", "-o", out); code != 0 {
		t.Fatal(e)
	}
	b, _ := os.ReadFile(out)
	s := string(b)
	if strings.Count(s, "<svg") != 6 || strings.Contains(s, "NaN") || strings.Contains(s, "no data") || strings.Contains(s, "+Inf") {
		t.Fatalf("report malformed: svgs=%d", strings.Count(s, "<svg"))
	}
	for _, want := range []string{"HyperLogLog", "Count-Min", "Bloom vs cuckoo", "t-digest", "SpaceSaving", "MinHash", "prefers-color-scheme"} {
		if !strings.Contains(s, want) {
			t.Errorf("report lacks %q", want)
		}
	}
}
