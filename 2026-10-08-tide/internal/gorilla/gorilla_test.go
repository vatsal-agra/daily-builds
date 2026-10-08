package gorilla

import (
	"math"
	"math/rand"
	"testing"
)

func roundTrip(t *testing.T, ts []int64, vs []float64) []byte {
	t.Helper()
	e := NewEncoder()
	for i := range ts {
		if err := e.Append(ts[i], vs[i]); err != nil {
			t.Fatal(err)
		}
	}
	b := e.Bytes()
	it := NewIterator(b)
	for i := range ts {
		if !it.Next() {
			t.Fatalf("sample %d: early end: %v", i, it.Err())
		}
		gt, gv := it.At()
		if gt != ts[i] || math.Float64bits(gv) != math.Float64bits(vs[i]) {
			t.Fatalf("sample %d: got (%d,%v) want (%d,%v)", i, gt, gv, ts[i], vs[i])
		}
	}
	if it.Next() || it.Err() != nil {
		t.Fatalf("extra data or error: %v", it.Err())
	}
	return b
}

func TestEmptyAndSingle(t *testing.T) {
	roundTrip(t, nil, nil)
	roundTrip(t, []int64{42}, []float64{3.14})
	roundTrip(t, []int64{42, 43}, []float64{3.14, 3.14})
}

func TestRegularSeriesCompressesWell(t *testing.T) {
	var ts []int64
	var vs []float64
	for i := 0; i < 120; i++ {
		ts = append(ts, 1_700_000_000_000+int64(i)*10_000)
		vs = append(vs, 42)
	}
	b := roundTrip(t, ts, vs)
	if len(b) > 52 {
		t.Fatalf("constant regular series took %d bytes, want <= 52", len(b))
	}
}

func TestSpecialFloats(t *testing.T) {
	vs := []float64{0, math.Copysign(0, -1), math.Inf(1), math.Inf(-1), math.NaN(), math.MaxFloat64,
		math.SmallestNonzeroFloat64, 1, -1, 1e-300, 1e300, 5e-324}
	ts := make([]int64, len(vs))
	for i := range ts {
		ts[i] = int64(i * 1000)
	}
	roundTrip(t, ts, vs)
}

func TestDoDBuckets(t *testing.T) {
	// deltas chosen to hit every delta-of-delta width incl. negative and 64-bit.
	deltas := []int64{1000, 1000, 1001, 1064, 1000, 800, 1300, 100, 5000, 1, 1, 1 << 40, 1}
	ts := []int64{0}
	for _, d := range deltas {
		ts = append(ts, ts[len(ts)-1]+d)
	}
	vs := make([]float64, len(ts))
	roundTrip(t, ts, vs)
}

func TestRandomized(t *testing.T) {
	rng := rand.New(rand.NewSource(7))
	for iter := 0; iter < 300; iter++ {
		n := 1 + rng.Intn(MaxSamples)
		ts := make([]int64, n)
		vs := make([]float64, n)
		cur := rng.Int63n(1 << 45)
		v := rng.NormFloat64() * 100
		for i := range ts {
			cur += 1 + rng.Int63n(30000)
			ts[i] = cur
			switch rng.Intn(4) {
			case 0:
			case 1:
				v += rng.NormFloat64()
			case 2:
				v = float64(rng.Intn(1000))
			default:
				v = math.Float64frombits(rng.Uint64())
			}
			vs[i] = v
		}
		roundTrip(t, ts, vs)
	}
}

func TestOutOfOrderRejected(t *testing.T) {
	e := NewEncoder()
	_ = e.Append(10, 1)
	_ = e.Append(20, 1)
	if e.Append(20, 2) != ErrOutOfOrder || e.Append(5, 2) != ErrOutOfOrder {
		t.Fatal("expected ErrOutOfOrder")
	}
	if e.Len() != 2 {
		t.Fatal("rejected sample changed state")
	}
}

func TestTruncatedChunkErrors(t *testing.T) {
	e := NewEncoder()
	for i := 0; i < 50; i++ {
		_ = e.Append(int64(i*1000), float64(i)*1.5)
	}
	b := e.Bytes()
	it := NewIterator(b[:len(b)/2])
	for it.Next() {
	}
	if it.Err() == nil {
		t.Fatal("expected error on truncated chunk")
	}
}

func TestSnapshotWhileAppending(t *testing.T) {
	e := NewEncoder()
	_ = e.Append(1, 1)
	_ = e.Append(2, 2)
	snap := e.Bytes()
	_ = e.Append(3, 9)
	it := NewIterator(snap)
	n := 0
	for it.Next() {
		n++
	}
	if n != 2 || it.Err() != nil {
		t.Fatalf("snapshot corrupted: n=%d err=%v", n, it.Err())
	}
}
