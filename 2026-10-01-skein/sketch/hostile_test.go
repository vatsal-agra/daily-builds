package sketch

import (
	"encoding/binary"
	"fmt"
	"hash/crc32"
	"math"
	"math/rand"
	"testing"
)

func refresh(b []byte) {
	binary.LittleEndian.PutUint32(b[len(b)-4:], crc32.ChecksumIEEE(b[:len(b)-4]))
}

func samples(t testing.TB) [][]byte {
	var out [][]byte
	add := func(v any) {
		b, err := Marshal(v)
		if err != nil {
			t.Fatal(err)
		}
		out = append(out, b)
	}
	h, _ := NewHLL(6)
	c, _ := NewCMSDims(16, 3)
	s, _ := NewSpaceSaving(4)
	bl, _ := NewBloomRaw(100, 3)
	ck, _ := NewCuckoo(30)
	td, _ := NewTDigest(20)
	mh, _ := NewMinHash(8)
	for i := 0; i < 50; i++ {
		k := fmt.Sprint(i)
		h.AddString(k)
		c.Add([]byte(k), 2)
		s.Add(k, 1)
		bl.Add([]byte(k))
		ck.AddUnique([]byte(k))
		td.Add(float64(i))
		mh.AddString(k)
	}
	bd, _ := NewBundle(BundleConfig{Precision: 4, Eps: 0.1, Delta: 0.5, TopK: 3, Compression: 10})
	for i := 0; i < 20; i++ {
		bd.Observe(fmt.Sprint(i%5), float64(i), true)
	}
	for _, v := range []any{h, c, s, bl, ck, td, mh, bd} {
		add(v)
	}
	return out
}

// Corrupt every byte position and also random multi-byte damage, re-sealing
// the checksum so the structural validators (not the CRC) have to catch it.
// Nothing may panic, and anything accepted must be usable.
func TestUnmarshalNeverPanicsOnResealedGarbage(t *testing.T) {
	r := rand.New(rand.NewSource(99))
	exercise := func(v any) {
		switch x := v.(type) {
		case *HLL:
			x.Estimate()
			x.AddString("z")
		case *CMS:
			x.Estimate([]byte("z"))
			x.Add([]byte("z"), 1)
		case *SpaceSaving:
			x.Add("z", 1)
			x.Top(3)
		case *Bloom:
			x.Contains([]byte("z"))
			x.Add([]byte("z"))
			x.EstimateCount()
		case *Cuckoo:
			x.Contains([]byte("z"))
			x.Add([]byte("z"))
			x.Delete([]byte("z"))
		case *TDigest:
			x.Quantile(0.5)
			x.CDF(1)
			x.Add(1)
		case *MinHash:
			x.AddString("z")
		case *Bundle:
			x.Observe("z", 1, true)
		}
	}
	for _, orig := range samples(t) {
		for pos := 0; pos < len(orig)-4; pos++ {
			for _, delta := range []byte{1, 0x80, 0xff} {
				b := append([]byte(nil), orig...)
				b[pos] ^= delta
				refresh(b)
				if v, err := Unmarshal(b); err == nil {
					exercise(v)
				}
			}
		}
		for i := 0; i < 3000; i++ {
			b := append([]byte(nil), orig...)
			for j := 0; j < 1+r.Intn(4); j++ {
				b[r.Intn(len(b)-4)] = byte(r.Intn(256))
			}
			if r.Intn(4) == 0 {
				b = b[:r.Intn(len(b))]
				if len(b) >= 4 {
					refresh(b)
				}
			}
			if v, err := Unmarshal(b); err == nil {
				exercise(v)
			}
		}
	}
}

func TestUnmarshalRejectsPlainDamage(t *testing.T) {
	for _, orig := range samples(t) {
		if _, err := Unmarshal(orig); err != nil {
			t.Fatalf("pristine rejected: %v", err)
		}
		b := append([]byte(nil), orig...)
		b[len(b)/2] ^= 0x10
		if _, err := Unmarshal(b); err == nil {
			t.Fatal("bit flip accepted")
		}
		if _, err := Unmarshal(orig[:len(orig)-1]); err == nil {
			t.Fatal("truncation accepted")
		}
	}
	if _, err := Unmarshal(nil); err == nil {
		t.Fatal("nil accepted")
	}
	if _, err := Unmarshal([]byte("hello world, definitely not a sketch")); err == nil {
		t.Fatal("garbage accepted")
	}
}

func TestTDigestUnmarshalRejectsNonFinite(t *testing.T) {
	td, _ := NewTDigest(20)
	td.Add(1)
	td.Add(2)
	for _, bad := range []float64{math.NaN(), math.Inf(1)} {
		x := *td
		x.n = bad
		b, _ := Marshal(&x)
		if _, err := Unmarshal(b); err == nil {
			t.Fatalf("n=%v accepted", bad)
		}
		y := *td
		y.min = bad
		b, _ = Marshal(&y)
		if _, err := Unmarshal(b); err == nil {
			t.Fatalf("min=%v accepted", bad)
		}
	}
	z := *td
	z.min, z.max = 5, 1
	b, _ := Marshal(&z)
	if _, err := Unmarshal(b); err == nil {
		t.Fatal("min>max accepted")
	}
}

func TestRoundTripPreservesBehaviour(t *testing.T) {
	r := rand.New(rand.NewSource(2))
	h, _ := NewHLL(12)
	td, _ := NewTDigest(100)
	ss, _ := NewSpaceSaving(30)
	bl, _ := NewBloom(5000, 0.01)
	ck, _ := NewCuckoo(5000)
	cm, _ := NewCMS(0.01, 0.01)
	for i := 0; i < 20000; i++ {
		k := fmt.Sprint(r.Intn(4000))
		h.AddString(k)
		td.Add(r.NormFloat64())
		ss.Add(k, 1)
		bl.Add([]byte(k))
		ck.AddUnique([]byte(k))
		cm.Add([]byte(k), 1)
	}
	for _, v := range []any{h, td, ss, bl, ck, cm} {
		b, _ := Marshal(v)
		w, err := Unmarshal(b)
		if err != nil {
			t.Fatalf("%s: %v", Kind(v), err)
		}
		b2, _ := Marshal(w)
		if string(b) != string(b2) {
			t.Fatalf("%s: re-marshal differs", Kind(v))
		}
	}
	b, _ := Marshal(td)
	w, _ := Unmarshal(b)
	for _, q := range []float64{0.01, 0.5, 0.99} {
		a, _ := td.Quantile(q)
		c, _ := w.(*TDigest).Quantile(q)
		if a != c {
			t.Fatalf("quantile drift %v %v", a, c)
		}
	}
}

func TestExtremeParams(t *testing.T) {
	if _, err := NewCMS(1e-12, 0.5); err == nil {
		t.Fatal("absurd eps accepted")
	}
	if _, err := NewBloom(1<<40, 1e-9); err == nil {
		t.Fatal("absurd bloom accepted")
	}
	if _, err := NewCuckoo(0); err == nil {
		t.Fatal("zero cuckoo")
	}
	c, _ := NewCuckoo(1)
	for i := 0; i < 100; i++ {
		c.Add([]byte(fmt.Sprint(i)))
	}
	td, _ := NewTDigest(10)
	if err := td.AddWeighted(1, math.Inf(1)); err == nil {
		t.Fatal("inf weight")
	}
	s, _ := NewSpaceSaving(1)
	s.Add("a", 1)
	s.Add("b", 5)
	if top := s.Top(5); len(top) != 1 || top[0].Key != "b" || top[0].Count != 6 || top[0].Err != 1 {
		t.Fatalf("k=1 behaviour %+v", top)
	}
}

func TestEmptyKeyAndBinaryKeys(t *testing.T) {
	h, _ := NewHLL(10)
	h.Add(nil)
	h.Add([]byte{})
	h.Add([]byte{0})
	if e := h.Estimate(); e < 1.5 || e > 2.6 {
		t.Fatalf("empty/zero-byte keys: %v", e)
	}
	s, _ := NewSpaceSaving(3)
	s.Add("", 2)
	if s.Top(1)[0].Count != 2 {
		t.Fatal("empty key")
	}
}

func TestTDigestSelfMergeAndMixedCompression(t *testing.T) {
	a, _ := NewTDigest(50)
	b, _ := NewTDigest(200)
	for i := 0; i < 10000; i++ {
		a.Add(float64(i))
		b.Add(float64(i + 10000))
	}
	a.Merge(b)
	if m, _ := a.Quantile(0.5); math.Abs(m-10000) > 200 {
		t.Fatalf("mixed-compression median %v", m)
	}
	if a.Centroids() > 400 {
		t.Fatalf("centroids %d", a.Centroids())
	}
	a.Merge(a)
	if a.Count() != 40000 {
		t.Fatalf("self merge count %v", a.Count())
	}
	e, _ := NewTDigest(50)
	a.Merge(e) // merging empty must not disturb min/max
	if a.Min() != 0 || a.Max() != 19999 {
		t.Fatal("empty merge corrupted range")
	}
}

func TestTDigestSortedAndDuplicateHeavyInput(t *testing.T) {
	for name, gen := range map[string]func(i int) float64{
		"ascending":  func(i int) float64 { return float64(i) },
		"descending": func(i int) float64 { return float64(-i) },
		"few-values": func(i int) float64 { return float64(i % 5) },
		"step":       func(i int) float64 { return math.Floor(float64(i) / 1000) },
	} {
		td, _ := NewTDigest(100)
		const n = 100000
		data := make([]float64, n)
		for i := range data {
			data[i] = gen(i)
			td.Add(data[i])
		}
		sorted := append([]float64(nil), data...)
		sortFloats(sorted)
		for _, q := range []float64{0.01, 0.25, 0.5, 0.75, 0.99} {
			got, _ := td.Quantile(q)
			// accept any value whose true rank interval contains q (+1% slack)
			lo := float64(lowerBound(sorted, got)) / n
			hi := float64(upperBound(sorted, got)) / n
			if q < lo-0.012 || q > hi+0.012 {
				t.Errorf("%s q=%v got=%v rank∈[%.4f,%.4f]", name, q, got, lo, hi)
			}
		}
		if td.Centroids() > 250 {
			t.Errorf("%s: %d centroids", name, td.Centroids())
		}
	}
}

func sortFloats(a []float64) { sortSlice(a) }

func lowerBound(a []float64, x float64) int {
	lo, hi := 0, len(a)
	for lo < hi {
		m := (lo + hi) / 2
		if a[m] < x {
			lo = m + 1
		} else {
			hi = m
		}
	}
	return lo
}
func upperBound(a []float64, x float64) int {
	lo, hi := 0, len(a)
	for lo < hi {
		m := (lo + hi) / 2
		if a[m] <= x {
			lo = m + 1
		} else {
			hi = m
		}
	}
	return lo
}

func TestHLLSequentialAndStructuredKeys(t *testing.T) {
	// weak hashes fail on counters / IPs / fixed-width ids
	for name, key := range map[string]func(i int) []byte{
		"le-uint32": func(i int) []byte { b := make([]byte, 4); binary.LittleEndian.PutUint32(b, uint32(i)); return b },
		"be-uint64": func(i int) []byte { b := make([]byte, 8); binary.BigEndian.PutUint64(b, uint64(i)); return b },
		"ip":        func(i int) []byte { return []byte(fmt.Sprintf("10.%d.%d.%d", i>>16&255, i>>8&255, i&255)) },
		"long-pfx":  func(i int) []byte { return []byte(fmt.Sprintf("a-very-long-common-prefix-for-every-single-key-%d", i)) },
	} {
		h, _ := NewHLL(14)
		const n = 100000
		for i := 0; i < n; i++ {
			h.Add(key(i))
		}
		if rel := math.Abs(h.Estimate()-n) / n; rel > 4*h.StdError() {
			t.Errorf("%s: rel err %.4f", name, rel)
		}
	}
}

func TestSpaceSavingAdversarialOrder(t *testing.T) {
	// worst case for SpaceSaving: many one-off keys arriving *after* the heavy hitters
	s, _ := NewSpaceSaving(20)
	exact := map[string]uint64{}
	feed := func(k string) { s.Add(k, 1); exact[k]++ }
	for i := 0; i < 15000; i++ {
		feed(fmt.Sprint("heavy", i%10))
	}
	for i := 0; i < 10000; i++ {
		feed(fmt.Sprint("noise", i))
	}
	have := map[string]Entry{}
	for _, e := range s.Top(-1) {
		have[e.Key] = e
		if tr := exact[e.Key]; !(e.Count-e.Err <= tr && tr <= e.Count) {
			t.Fatalf("bound violated for %s", e.Key)
		}
	}
	for i := 0; i < 10; i++ {
		if _, ok := have[fmt.Sprint("heavy", i)]; !ok {
			t.Fatalf("heavy%d evicted (freq 1500 > N/k=%d)", i, s.Total()/20)
		}
	}
}

func TestMinHashAndLSH(t *testing.T) {
	// estimator error vs exact Jaccard over many random set pairs
	r := rand.New(rand.NewSource(8))
	const k = 256
	var worst float64
	for trial := 0; trial < 60; trial++ {
		var a, b []string
		overlap := r.Intn(100)
		for i := 0; i < 100; i++ {
			a = append(a, fmt.Sprint("a", trial, i))
		}
		b = append(b, a[:overlap]...)
		for i := overlap; i < 100; i++ {
			b = append(b, fmt.Sprint("b", trial, i))
		}
		ma, _ := NewMinHash(k)
		mb, _ := NewMinHash(k)
		for _, x := range a {
			ma.AddString(x)
		}
		for _, x := range b {
			mb.AddString(x)
		}
		est, _ := ma.Jaccard(mb)
		if d := math.Abs(est - ExactJaccard(a, b)); d > worst {
			worst = d
		}
	}
	if worst > 0.12 { // 3σ at k=256 is ≈0.094
		t.Fatalf("worst MinHash error %.3f", worst)
	}
	// merge == union signature
	x, _ := NewMinHash(64)
	y, _ := NewMinHash(64)
	u, _ := NewMinHash(64)
	for i := 0; i < 50; i++ {
		x.AddString(fmt.Sprint(i))
		u.AddString(fmt.Sprint(i))
		y.AddString(fmt.Sprint(i + 50))
		u.AddString(fmt.Sprint(i + 50))
	}
	x.Merge(y)
	if j, _ := x.Jaccard(u); j != 1 {
		t.Fatalf("merged != union signature (%v)", j)
	}
	// empty handling
	e1, _ := NewMinHash(16)
	e2, _ := NewMinHash(16)
	if j, _ := e1.Jaccard(e2); j != 1 {
		t.Fatal("two empties")
	}
	if j, _ := e1.Jaccard(x2(16)); j != 0 {
		t.Fatal("empty vs nonempty")
	}

	// LSH recall / precision around the threshold
	l, err := NewLSH(128, 0.6)
	if err != nil {
		t.Fatal(err)
	}
	base := make([]string, 60)
	for i := range base {
		base[i] = fmt.Sprint("tok", i)
	}
	sigOf := func(items []string) *MinHash {
		m, _ := NewMinHash(128)
		for _, s := range items {
			m.AddString(s)
		}
		return m
	}
	l.Insert("base", sigOf(base))
	for i := 0; i < 200; i++ {
		var other []string
		for j := 0; j < 60; j++ {
			other = append(other, fmt.Sprint("junk", i, "-", j))
		}
		l.Insert(fmt.Sprint("junk", i), sigOf(other))
	}
	near := append(append([]string(nil), base[:55]...), "x1", "x2", "x3", "x4", "x5") // J = 55/65 ≈ 0.85
	ms, _ := l.Query(sigOf(near), 0.5)
	if len(ms) != 1 || ms[0].ID != "base" || math.Abs(ms[0].Jaccard-0.846) > 0.12 {
		t.Fatalf("LSH query: %+v", ms)
	}
	far := append(append([]string(nil), base[:10]...), make([]string, 0)...)
	for i := 0; i < 50; i++ {
		far = append(far, fmt.Sprint("far", i))
	}
	if ms, _ := l.Query(sigOf(far), 0.5); len(ms) != 0 {
		t.Fatalf("dissimilar doc matched: %+v", ms)
	}
	if err := l.Insert("e", e1); err == nil {
		t.Fatal("empty sig inserted")
	}
	if _, err := NewLSH(128, 1.2); err == nil {
		t.Fatal("bad threshold")
	}
}

func x2(k int) *MinHash {
	m, _ := NewMinHash(k)
	m.AddString("q")
	return m
}

func TestShingles(t *testing.T) {
	if got := Shingles("The  quick, brown FOX!", 2); len(got) != 3 || got[0] != "the quick" {
		t.Fatalf("%v", got)
	}
	if got := Shingles("one", 3); len(got) != 1 || got[0] != "one" {
		t.Fatalf("short doc %v", got)
	}
	if Shingles("  ...  ", 2) != nil {
		t.Fatal("punctuation-only should be empty")
	}
	if got := Shingles("héllo wörld ünï", 1); len(got) != 3 {
		t.Fatalf("unicode %v", got)
	}
}
