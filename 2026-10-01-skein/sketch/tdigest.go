package sketch

import (
	"errors"
	"fmt"
	"math"
	"sort"
)

type centroid struct {
	mean, weight float64
}

// TDigest is a merging t-digest (Dunning & Ertl) with the k1 (arcsine) scale
// function, which concentrates resolution in the tails: p99.9 is far more
// accurate than a uniform histogram of the same size.
type TDigest struct {
	delta    float64
	cs       []centroid // sorted by mean, already compressed
	buf      []centroid
	n        float64
	min, max float64
}

func NewTDigest(compression float64) (*TDigest, error) {
	if !(compression >= 10 && compression <= 10000) {
		return nil, fmt.Errorf("tdigest: compression %v out of range 10..10000", compression)
	}
	return &TDigest{delta: compression, min: math.Inf(1), max: math.Inf(-1)}, nil
}

func (t *TDigest) Compression() float64 { return t.delta }
func (t *TDigest) Count() float64       { return t.n }
func (t *TDigest) Min() float64         { return t.min }
func (t *TDigest) Max() float64         { return t.max }

func (t *TDigest) Centroids() int { t.flush(); return len(t.cs) }
func (t *TDigest) Bytes() int     { t.flush(); return len(t.cs) * 16 }

func (t *TDigest) Add(x float64) error { return t.AddWeighted(x, 1) }

func (t *TDigest) AddWeighted(x, w float64) error {
	if math.IsNaN(x) || math.IsInf(x, 0) {
		return errors.New("tdigest: value must be finite")
	}
	if !(w > 0) || math.IsInf(w, 0) {
		return errors.New("tdigest: weight must be positive and finite")
	}
	t.buf = append(t.buf, centroid{x, w})
	t.n += w
	if x < t.min {
		t.min = x
	}
	if x > t.max {
		t.max = x
	}
	if len(t.buf) >= int(6*t.delta) {
		t.flush()
	}
	return nil
}

func (t *TDigest) k(q float64) float64 {
	return t.delta / (2 * math.Pi) * math.Asin(2*q-1)
}

// flush merges the buffer into the compressed centroid list.
func (t *TDigest) flush() {
	if len(t.buf) == 0 {
		return
	}
	all := append(append(make([]centroid, 0, len(t.cs)+len(t.buf)), t.cs...), t.buf...)
	t.buf = t.buf[:0]
	sort.SliceStable(all, func(i, j int) bool { return all[i].mean < all[j].mean })
	out := make([]centroid, 0, int(t.delta)+8)
	cur := all[0]
	soFar := 0.0 // weight strictly before cur
	kLeft := t.k(0)
	for _, c := range all[1:] {
		qRight := (soFar + cur.weight + c.weight) / t.n
		if t.k(math.Min(qRight, 1))-kLeft <= 1 {
			w := cur.weight + c.weight
			cur.mean += (c.mean - cur.mean) * c.weight / w
			cur.weight = w
		} else {
			out = append(out, cur)
			soFar += cur.weight
			kLeft = t.k(soFar / t.n)
			cur = c
		}
	}
	out = append(out, cur)
	t.cs = out
}

// Quantile returns the estimated q-quantile, q in [0,1].
func (t *TDigest) Quantile(q float64) (float64, error) {
	if math.IsNaN(q) || q < 0 || q > 1 {
		return 0, fmt.Errorf("tdigest: quantile %v outside [0,1]", q)
	}
	t.flush()
	if t.n == 0 {
		return 0, errors.New("tdigest: empty")
	}
	if len(t.cs) == 1 || q == 0 {
		if q == 0 {
			return t.min, nil
		}
		return t.cs[0].mean, nil
	}
	if q == 1 {
		return t.max, nil
	}
	idx := q * t.n
	first, last := t.cs[0], t.cs[len(t.cs)-1]
	if idx < first.weight/2 {
		if first.weight == 1 {
			return t.min, nil
		}
		return t.min + (first.mean-t.min)*idx/(first.weight/2), nil
	}
	if idx > t.n-last.weight/2 {
		if last.weight == 1 {
			return t.max, nil
		}
		return t.max - (t.max-last.mean)*(t.n-idx)/(last.weight/2), nil
	}
	cum := 0.0
	for i := 0; i < len(t.cs)-1; i++ {
		c, d := t.cs[i], t.cs[i+1]
		left := cum + c.weight/2
		right := cum + c.weight + d.weight/2
		if idx >= left && idx <= right {
			f := (idx - left) / (right - left)
			return c.mean + f*(d.mean-c.mean), nil
		}
		cum += c.weight
	}
	return t.max, nil
}

// CDF returns the estimated fraction of values <= x.
func (t *TDigest) CDF(x float64) (float64, error) {
	t.flush()
	if t.n == 0 {
		return 0, errors.New("tdigest: empty")
	}
	if math.IsNaN(x) {
		return 0, errors.New("tdigest: NaN")
	}
	if x < t.min {
		return 0, nil
	}
	if x >= t.max {
		return 1, nil
	}
	first, last := t.cs[0], t.cs[len(t.cs)-1]
	if x < first.mean {
		if first.mean == t.min {
			return 0, nil
		}
		return first.weight / 2 * (x - t.min) / (first.mean - t.min) / t.n, nil
	}
	if x > last.mean {
		return 1 - last.weight/2*(t.max-x)/(t.max-last.mean)/t.n, nil
	}
	cum := 0.0
	for i := 0; i < len(t.cs); i++ {
		c := t.cs[i]
		if x == c.mean {
			// average over any run of equal means
			lo, hi := cum, cum
			for j := i; j < len(t.cs) && t.cs[j].mean == x; j++ {
				hi += t.cs[j].weight
			}
			return (lo + hi) / 2 / t.n, nil
		}
		if i+1 < len(t.cs) && x < t.cs[i+1].mean {
			d := t.cs[i+1]
			left := cum + c.weight/2
			right := cum + c.weight + d.weight/2
			return (left + (right-left)*(x-c.mean)/(d.mean-c.mean)) / t.n, nil
		}
		cum += c.weight
	}
	return 1, nil
}

// Merge folds o into t (compressions may differ; t's is kept).
func (t *TDigest) Merge(o *TDigest) {
	o.flush()
	for _, c := range o.cs {
		t.buf = append(t.buf, c)
		t.n += c.weight
	}
	if o.n > 0 {
		t.min = math.Min(t.min, o.min)
		t.max = math.Max(t.max, o.max)
	}
	t.flush()
}
