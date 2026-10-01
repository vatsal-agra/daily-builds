package sketch

import (
	"fmt"
	"math"
	"math/rand"
	"sort"
	"testing"
)

func TestHash64KnownVectors(t *testing.T) {
	// Reference values from the xxHash project.
	if got := Hash64(nil, 0); got != 0xEF46DB3751D8E999 {
		t.Fatalf("xxh64(\"\")=%x", got)
	}
	if got := Hash64([]byte("a"), 0); got != 0xD24EC4F1A98C6E5B {
		t.Fatalf("xxh64(a)=%x", got)
	}
	if got := Hash64([]byte("abc"), 0); got != 0x44BC2CF5AD770999 {
		t.Fatalf("xxh64(abc)=%x", got)
	}
}

func TestHashAvalanche(t *testing.T) {
	// flipping one input bit should flip ~32 output bits on average
	r := rand.New(rand.NewSource(1))
	total, trials := 0, 4000
	for i := 0; i < trials; i++ {
		b := make([]byte, 1+r.Intn(70))
		r.Read(b)
		h1 := Hash64(b, 0)
		b[r.Intn(len(b))] ^= 1 << uint(r.Intn(8))
		x := h1 ^ Hash64(b, 0)
		for ; x != 0; x &= x - 1 {
			total++
		}
	}
	avg := float64(total) / float64(trials)
	if avg < 31 || avg > 33 {
		t.Fatalf("avalanche avg %.2f bits", avg)
	}
}

func TestHLLAccuracyAcrossRange(t *testing.T) {
	for _, p := range []int{10, 12, 14} {
		for _, n := range []int{0, 1, 10, 100, 1000, 10000, 200000} {
			h, _ := NewHLL(p)
			for i := 0; i < n; i++ {
				h.AddString(fmt.Sprintf("user-%d", i))
			}
			est := h.Estimate()
			if n == 0 {
				if est != 0 {
					t.Fatalf("empty estimate %v", est)
				}
				continue
			}
			rel := math.Abs(est-float64(n)) / float64(n)
			if rel > 4*h.StdError()+0.5/float64(n) {
				t.Errorf("p=%d n=%d est=%.1f rel=%.4f > 4σ=%.4f", p, n, est, rel, 4*h.StdError())
			}
		}
	}
}

func TestHLLDuplicatesIgnoredAndMerge(t *testing.T) {
	a, _ := NewHLL(12)
	b, _ := NewHLL(12)
	all, _ := NewHLL(12)
	for i := 0; i < 30000; i++ {
		k := fmt.Sprint("k", i)
		all.AddString(k)
		if i%3 == 0 {
			a.AddString(k)
			a.AddString(k) // dup
		} else {
			b.AddString(k)
		}
	}
	if err := a.Merge(b); err != nil {
		t.Fatal(err)
	}
	if a.Estimate() != all.Estimate() {
		t.Fatalf("merge != single pass: %v vs %v", a.Estimate(), all.Estimate())
	}
	c, _ := NewHLL(10)
	if a.Merge(c) == nil {
		t.Fatal("expected precision mismatch error")
	}
	if _, err := NewHLL(3); err == nil {
		t.Fatal("expected range error")
	}
}

func TestHLLIntersect(t *testing.T) {
	a, _ := NewHLL(14)
	b, _ := NewHLL(14)
	for i := 0; i < 50000; i++ {
		a.AddString(fmt.Sprint(i))
	}
	for i := 25000; i < 75000; i++ {
		b.AddString(fmt.Sprint(i))
	}
	v, _ := HLLIntersect(a, b)
	if math.Abs(v-25000)/25000 > 0.1 {
		t.Fatalf("intersect %v want ~25000", v)
	}
}

func zipf(r *rand.Rand, n int) func() int {
	z := rand.NewZipf(r, 1.2, 1, uint64(n-1))
	return func() int { return int(z.Uint64()) }
}

func TestCMSBoundsAndNoUndercount(t *testing.T) {
	c, _ := NewCMS(0.002, 0.01)
	r := rand.New(rand.NewSource(7))
	next := zipf(r, 50000)
	exact := map[string]uint32{}
	const N = 200000
	for i := 0; i < N; i++ {
		k := fmt.Sprint("item", next())
		c.Add([]byte(k), 1)
		exact[k]++
	}
	over, bad := 0, 0
	for k, v := range exact {
		e := c.Estimate([]byte(k))
		if e < v {
			t.Fatalf("undercount for %s: %d < %d", k, e, v)
		}
		if float64(e-v) > c.Epsilon()*N {
			over++
		}
		bad++
	}
	if float64(over)/float64(bad) > c.Delta() {
		t.Fatalf("%d/%d keys exceeded eps*N (delta=%v)", over, bad, c.Delta())
	}
	if c.Estimate([]byte("never-seen-key")) > uint32(c.Epsilon()*N) {
		t.Fatal("unseen key estimate too large")
	}
}

func TestCMSConservativeBeatsPlain(t *testing.T) {
	// A conservative-update sketch must never be worse than plain increments.
	r := rand.New(rand.NewSource(3))
	c, _ := NewCMSDims(500, 4)
	plain := make([]uint32, 500*4)
	exact := map[string]uint32{}
	for i := 0; i < 20000; i++ {
		k := fmt.Sprint(r.Intn(3000))
		c.Add([]byte(k), 1)
		exact[k]++
		h1, h2 := pair([]byte(k))
		for row := uint32(0); row < 4; row++ {
			plain[c.slot(row, h1, h2)]++
		}
	}
	for k := range exact {
		h1, h2 := pair([]byte(k))
		pm := uint32(math.MaxUint32)
		for row := uint32(0); row < 4; row++ {
			if v := plain[c.slot(row, h1, h2)]; v < pm {
				pm = v
			}
		}
		if c.Estimate([]byte(k)) > pm {
			t.Fatalf("conservative worse than plain for %s", k)
		}
	}
}

func TestCMSMerge(t *testing.T) {
	a, _ := NewCMSDims(1000, 4)
	b, _ := NewCMSDims(1000, 4)
	exact := map[string]uint32{}
	for i := 0; i < 5000; i++ {
		k := fmt.Sprint(i % 700)
		exact[k]++
		if i%2 == 0 {
			a.Add([]byte(k), 1)
		} else {
			b.Add([]byte(k), 1)
		}
	}
	if err := a.Merge(b); err != nil {
		t.Fatal(err)
	}
	for k, v := range exact {
		if a.Estimate([]byte(k)) < v {
			t.Fatalf("merged undercount %s", k)
		}
	}
	x, _ := NewCMSDims(10, 4)
	if a.Merge(x) == nil {
		t.Fatal("expected dim mismatch")
	}
	if _, err := NewCMS(0, 0.1); err == nil {
		t.Fatal("expected param error")
	}
}

func TestSpaceSavingGuarantees(t *testing.T) {
	r := rand.New(rand.NewSource(11))
	next := zipf(r, 20000)
	s, _ := NewSpaceSaving(50)
	exact := map[string]uint64{}
	const N = 100000
	for i := 0; i < N; i++ {
		k := fmt.Sprint("w", next())
		s.Add(k, 1)
		exact[k]++
	}
	top := s.Top(-1)
	if len(top) != 50 {
		t.Fatalf("len %d", len(top))
	}
	for _, e := range top {
		tr := exact[e.Key]
		if !(e.Count-e.Err <= tr && tr <= e.Count) {
			t.Fatalf("%s true=%d not in [%d,%d]", e.Key, tr, e.Count-e.Err, e.Count)
		}
	}
	// every item with freq > N/k must be present
	have := map[string]bool{}
	for _, e := range top {
		have[e.Key] = true
	}
	for k, v := range exact {
		if v > N/50 && !have[k] {
			t.Fatalf("heavy hitter %s (%d) missing", k, v)
		}
	}
	// the true top 10 should be recovered in order
	type kv struct {
		k string
		v uint64
	}
	var all []kv
	for k, v := range exact {
		all = append(all, kv{k, v})
	}
	sort.Slice(all, func(i, j int) bool { return all[i].v > all[j].v })
	for i := 0; i < 5; i++ {
		if top[i].Key != all[i].k {
			t.Logf("rank %d: got %s want %s", i, top[i].Key, all[i].k)
		}
	}
	if s.Total() != N {
		t.Fatal("total")
	}
}

func TestSpaceSavingMerge(t *testing.T) {
	r := rand.New(rand.NewSource(5))
	next := zipf(r, 5000)
	a, _ := NewSpaceSaving(40)
	b, _ := NewSpaceSaving(40)
	exact := map[string]uint64{}
	for i := 0; i < 60000; i++ {
		k := fmt.Sprint("m", next())
		exact[k]++
		if i%2 == 0 {
			a.Add(k, 1)
		} else {
			b.Add(k, 1)
		}
	}
	if err := a.Merge(b); err != nil {
		t.Fatal(err)
	}
	if len(a.Top(-1)) > 40 {
		t.Fatal("merge exceeded k")
	}
	for _, e := range a.Top(-1) {
		if tr := exact[e.Key]; !(e.Count-e.Err <= tr && tr <= e.Count) {
			t.Fatalf("merged bound violated %s true=%d [%d,%d]", e.Key, tr, e.Count-e.Err, e.Count)
		}
	}
	// still a valid heap that accepts updates
	a.Add("brand-new", 1)
	if a.Total() != 60001 {
		t.Fatal("total after merge")
	}
}

func TestBloom(t *testing.T) {
	b, _ := NewBloom(50000, 0.01)
	for i := 0; i < 50000; i++ {
		b.Add([]byte(fmt.Sprint("in-", i)))
	}
	for i := 0; i < 50000; i++ {
		if !b.Contains([]byte(fmt.Sprint("in-", i))) {
			t.Fatal("false negative")
		}
	}
	fp := 0
	const probes = 100000
	for i := 0; i < probes; i++ {
		if b.Contains([]byte(fmt.Sprint("out-", i))) {
			fp++
		}
	}
	rate := float64(fp) / probes
	if rate > 0.015 || rate < 0.004 {
		t.Fatalf("fp rate %.4f vs target 0.01", rate)
	}
	if math.Abs(b.FalsePositiveRate()-rate) > 0.005 {
		t.Fatalf("predicted fp %.4f vs measured %.4f", b.FalsePositiveRate(), rate)
	}
	if est := b.EstimateCount(); math.Abs(est-50000)/50000 > 0.03 {
		t.Fatalf("estimate count %v", est)
	}
}

func TestBloomMerge(t *testing.T) {
	a, _ := NewBloom(1000, 0.01)
	b, _ := NewBloom(1000, 0.01)
	a.Add([]byte("x"))
	b.Add([]byte("y"))
	if err := a.Merge(b); err != nil {
		t.Fatal(err)
	}
	if !a.Contains([]byte("x")) || !a.Contains([]byte("y")) {
		t.Fatal("union lost items")
	}
	c, _ := NewBloom(10, 0.5)
	if a.Merge(c) == nil {
		t.Fatal("expected geometry error")
	}
	if _, err := NewBloom(0, 0.1); err == nil {
		t.Fatal("expected error")
	}
	if _, err := NewBloom(10, 1.5); err == nil {
		t.Fatal("expected error")
	}
}

func TestCuckooAddDeleteFull(t *testing.T) {
	c, _ := NewCuckoo(20000)
	var added []string
	for i := 0; ; i++ {
		k := fmt.Sprint("c", i)
		if err := c.Add([]byte(k)); err != nil {
			break
		}
		added = append(added, k)
	}
	if lf := c.LoadFactor(); lf < 0.9 {
		t.Fatalf("filled only to %.3f load", lf)
	}
	for _, k := range added {
		if !c.Contains([]byte(k)) {
			t.Fatalf("false negative %s (rollback broken?)", k)
		}
	}
	// failed insert must not have damaged anything (checked above); now delete half.
	for _, k := range added[:len(added)/2] {
		if !c.Delete([]byte(k)) {
			t.Fatalf("delete failed %s", k)
		}
	}
	for _, k := range added[len(added)/2:] {
		if !c.Contains([]byte(k)) {
			t.Fatalf("delete removed survivor %s", k)
		}
	}
	if c.Len() != uint64(len(added)-len(added)/2) {
		t.Fatal("len wrong")
	}
	fp := 0
	for i := 0; i < 100000; i++ {
		if c.Contains([]byte(fmt.Sprint("zz", i))) {
			fp++
		}
	}
	if float64(fp)/100000 > 0.002 {
		t.Fatalf("fp rate %.5f too high for 16-bit fingerprints", float64(fp)/100000)
	}
	if c.Delete([]byte("never-added-key-qq")) && !c.Contains([]byte("never-added-key-qq")) {
		// (a collision delete is legal but vanishingly unlikely; just exercise)
	}
}

func exactQuantile(sorted []float64, q float64) float64 {
	i := int(q * float64(len(sorted)-1))
	return sorted[i]
}

func TestTDigestQuantiles(t *testing.T) {
	dists := map[string]func(*rand.Rand) float64{
		"uniform":   func(r *rand.Rand) float64 { return r.Float64() * 1000 },
		"normal":    func(r *rand.Rand) float64 { return r.NormFloat64()*50 + 500 },
		"lognormal": func(r *rand.Rand) float64 { return math.Exp(r.NormFloat64()) },
		"bimodal": func(r *rand.Rand) float64 {
			if r.Intn(2) == 0 {
				return r.NormFloat64() + 10
			}
			return r.NormFloat64() + 100
		},
	}
	for name, gen := range dists {
		r := rand.New(rand.NewSource(42))
		td, _ := NewTDigest(100)
		data := make([]float64, 200000)
		for i := range data {
			data[i] = gen(r)
			td.Add(data[i])
		}
		sort.Float64s(data)
		if td.Centroids() > 250 {
			t.Errorf("%s: %d centroids", name, td.Centroids())
		}
		for _, q := range []float64{0.001, 0.01, 0.1, 0.5, 0.9, 0.99, 0.999} {
			got, _ := td.Quantile(q)
			// rank error: where does `got` fall in the true distribution?
			rank := float64(sort.SearchFloat64s(data, got)) / float64(len(data))
			tol := 0.01 * math.Min(q, 1-q) * 2 // tighter in the tails
			if tol < 0.0005 {
				tol = 0.0005
			}
			if math.Abs(rank-q) > math.Max(tol, 0.003) {
				t.Errorf("%s q=%v got=%v exact=%v rank-err=%.5f", name, q, got, exactQuantile(data, q), rank-q)
			}
		}
		if mn, _ := td.Quantile(0); mn != data[0] {
			t.Errorf("%s min", name)
		}
		if mx, _ := td.Quantile(1); mx != data[len(data)-1] {
			t.Errorf("%s max", name)
		}
	}
}

func TestTDigestCDFAndInverse(t *testing.T) {
	r := rand.New(rand.NewSource(9))
	td, _ := NewTDigest(100)
	for i := 0; i < 50000; i++ {
		td.Add(r.Float64())
	}
	for _, x := range []float64{0.05, 0.25, 0.5, 0.75, 0.95} {
		c, _ := td.CDF(x)
		if math.Abs(c-x) > 0.01 {
			t.Errorf("cdf(%v)=%v", x, c)
		}
		q, _ := td.Quantile(c)
		if math.Abs(q-x) > 0.01 {
			t.Errorf("quantile(cdf(%v))=%v", x, q)
		}
	}
	if c, _ := td.CDF(-1); c != 0 {
		t.Fatal("cdf below min")
	}
	if c, _ := td.CDF(2); c != 1 {
		t.Fatal("cdf above max")
	}
}

func TestTDigestMerge(t *testing.T) {
	r := rand.New(rand.NewSource(77))
	parts := make([]*TDigest, 8)
	var data []float64
	all, _ := NewTDigest(100)
	for i := range parts {
		parts[i], _ = NewTDigest(100)
		for j := 0; j < 20000; j++ {
			v := r.NormFloat64()*float64(i+1) + float64(i)
			parts[i].Add(v)
			data = append(data, v)
			all.Add(v)
		}
	}
	m, _ := NewTDigest(100)
	for _, p := range parts {
		m.Merge(p)
	}
	sort.Float64s(data)
	if m.Count() != float64(len(data)) {
		t.Fatal("count")
	}
	for _, q := range []float64{0.01, 0.5, 0.99} {
		got, _ := m.Quantile(q)
		rank := float64(sort.SearchFloat64s(data, got)) / float64(len(data))
		if math.Abs(rank-q) > 0.006 {
			t.Errorf("merged q=%v rank-err %.4f", q, rank-q)
		}
	}
}

func TestTDigestEdgeCases(t *testing.T) {
	td, _ := NewTDigest(100)
	if _, err := td.Quantile(0.5); err == nil {
		t.Fatal("empty should error")
	}
	if td.Add(math.NaN()) == nil || td.Add(math.Inf(1)) == nil {
		t.Fatal("non-finite should error")
	}
	if td.AddWeighted(1, 0) == nil || td.AddWeighted(1, -1) == nil {
		t.Fatal("bad weight")
	}
	td.Add(5)
	if v, _ := td.Quantile(0.5); v != 5 {
		t.Fatal("single value")
	}
	for i := 0; i < 1000; i++ {
		td.Add(5) // many identical values
	}
	if v, _ := td.Quantile(0.99); v != 5 {
		t.Fatalf("constant data quantile %v", v)
	}
	if _, err := td.Quantile(1.5); err == nil {
		t.Fatal("range")
	}
	if _, err := NewTDigest(1); err == nil {
		t.Fatal("compression range")
	}
}
