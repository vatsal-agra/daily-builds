package sketch

import (
	"fmt"
	"math"
)

// Bundle is the CLI's single-pass analytics state: distinct keys, key
// frequencies, top-K and a value distribution — all mergeable.
type Bundle struct {
	Records  uint64
	Distinct *HLL
	Freq     *CMS
	Top      *SpaceSaving
	Dist     *TDigest
}

type BundleConfig struct {
	Precision   int
	Eps, Delta  float64
	TopK        int
	Compression float64
}

func DefaultBundleConfig() BundleConfig {
	return BundleConfig{Precision: 14, Eps: 0.001, Delta: 0.01, TopK: 500, Compression: 100}
}

func NewBundle(c BundleConfig) (*Bundle, error) {
	h, err := NewHLL(c.Precision)
	if err != nil {
		return nil, err
	}
	f, err := NewCMS(c.Eps, c.Delta)
	if err != nil {
		return nil, err
	}
	s, err := NewSpaceSaving(c.TopK)
	if err != nil {
		return nil, err
	}
	t, err := NewTDigest(c.Compression)
	if err != nil {
		return nil, err
	}
	return &Bundle{Distinct: h, Freq: f, Top: s, Dist: t}, nil
}

// Observe records one key (always) and one numeric value (if hasVal).
func (b *Bundle) Observe(key string, val float64, hasVal bool) error {
	if hasVal && (math.IsNaN(val) || math.IsInf(val, 0)) {
		return fmt.Errorf("non-finite value %v", val)
	}
	b.Records++
	b.Distinct.AddString(key)
	b.Freq.Add([]byte(key), 1)
	b.Top.Add(key, 1)
	if hasVal {
		return b.Dist.Add(val)
	}
	return nil
}

func (b *Bundle) Merge(o *Bundle) error {
	// validate everything first so a failed merge leaves b untouched
	if b.Distinct.p != o.Distinct.p || b.Freq.w != o.Freq.w || b.Freq.d != o.Freq.d || b.Top.k != o.Top.k {
		return fmt.Errorf("bundles were built with different parameters")
	}
	if err := b.Distinct.Merge(o.Distinct); err != nil {
		return err
	}
	if err := b.Freq.Merge(o.Freq); err != nil {
		return err
	}
	if err := b.Top.Merge(o.Top); err != nil {
		return err
	}
	b.Dist.Merge(o.Dist)
	b.Records += o.Records
	return nil
}
