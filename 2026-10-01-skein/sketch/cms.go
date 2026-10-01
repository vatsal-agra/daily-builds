package sketch

import (
	"errors"
	"fmt"
	"math"
	"sort"
)

// CMS is a Count-Min sketch with conservative update. Estimates never
// under-count; with width w=ceil(e/eps) and depth d=ceil(ln(1/delta)),
// estimate <= true + eps*N with probability >= 1-delta.
type CMS struct {
	w, d  uint32
	total uint64
	cells []uint32
}

func NewCMS(eps, delta float64) (*CMS, error) {
	if !(eps > 0 && eps < 1) || !(delta > 0 && delta < 1) {
		return nil, fmt.Errorf("cms: eps and delta must be in (0,1), got %v, %v", eps, delta)
	}
	w := uint32(math.Ceil(math.E / eps))
	d := uint32(math.Ceil(math.Log(1 / delta)))
	if d < 1 {
		d = 1
	}
	return NewCMSDims(int(w), int(d))
}

func NewCMSDims(w, d int) (*CMS, error) {
	if w < 1 || d < 1 || w > 1<<28 || d > 32 {
		return nil, fmt.Errorf("cms: bad dimensions %dx%d", w, d)
	}
	return &CMS{w: uint32(w), d: uint32(d), cells: make([]uint32, w*d)}, nil
}

func (c *CMS) Width() int       { return int(c.w) }
func (c *CMS) Depth() int       { return int(c.d) }
func (c *CMS) Total() uint64    { return c.total }
func (c *CMS) Bytes() int       { return len(c.cells) * 4 }
func (c *CMS) Epsilon() float64 { return math.E / float64(c.w) }
func (c *CMS) Delta() float64   { return math.Exp(-float64(c.d)) }

func (c *CMS) slot(row uint32, h1, h2 uint64) int {
	return int(row)*int(c.w) + int((h1+uint64(row)*h2)%uint64(c.w))
}

// Add increments key by n using conservative update: only the minimal
// counters are raised, which strictly tightens the estimate.
func (c *CMS) Add(key []byte, n uint32) {
	if n == 0 {
		return
	}
	h1, h2 := pair(key)
	min := uint32(math.MaxUint32)
	for r := uint32(0); r < c.d; r++ {
		if v := c.cells[c.slot(r, h1, h2)]; v < min {
			min = v
		}
	}
	target := uint64(min) + uint64(n)
	if target > math.MaxUint32 {
		target = math.MaxUint32
	}
	for r := uint32(0); r < c.d; r++ {
		s := c.slot(r, h1, h2)
		if uint64(c.cells[s]) < target {
			c.cells[s] = uint32(target)
		}
	}
	c.total += uint64(n)
}

func (c *CMS) Estimate(key []byte) uint32 {
	h1, h2 := pair(key)
	min := uint32(math.MaxUint32)
	for r := uint32(0); r < c.d; r++ {
		if v := c.cells[c.slot(r, h1, h2)]; v < min {
			min = v
		}
	}
	return min
}

// Merge adds o's counters into c. The result still never under-counts
// (sum of upper bounds), though it is not identical to a single-pass sketch.
func (c *CMS) Merge(o *CMS) error {
	if c.w != o.w || c.d != o.d {
		return errors.New("cms: cannot merge different dimensions")
	}
	for i, v := range o.cells {
		s := uint64(c.cells[i]) + uint64(v)
		if s > math.MaxUint32 {
			s = math.MaxUint32
		}
		c.cells[i] = uint32(s)
	}
	c.total += o.total
	return nil
}

// ---------------------------------------------------------------------

// Entry is one tracked heavy hitter. The true count lies in [Count-Err, Count].
type Entry struct {
	Key   string
	Count uint64
	Err   uint64
}

// SpaceSaving is the Metwally et al. top-K sketch: k counters, guaranteed to
// retain every item whose frequency exceeds N/k. Backed by a min-heap.
type SpaceSaving struct {
	k     int
	total uint64
	heap  []*Entry
	idx   map[string]int // key -> heap position
}

func NewSpaceSaving(k int) (*SpaceSaving, error) {
	if k < 1 || k > 1<<24 {
		return nil, fmt.Errorf("spacesaving: k=%d out of range", k)
	}
	return &SpaceSaving{k: k, idx: make(map[string]int)}, nil
}

func (s *SpaceSaving) K() int        { return s.k }
func (s *SpaceSaving) Total() uint64 { return s.total }

func (s *SpaceSaving) swap(i, j int) {
	s.heap[i], s.heap[j] = s.heap[j], s.heap[i]
	s.idx[s.heap[i].Key] = i
	s.idx[s.heap[j].Key] = j
}
func (s *SpaceSaving) up(i int) {
	for i > 0 {
		p := (i - 1) / 2
		if s.heap[p].Count <= s.heap[i].Count {
			break
		}
		s.swap(i, p)
		i = p
	}
}
func (s *SpaceSaving) down(i int) {
	n := len(s.heap)
	for {
		l, m := 2*i+1, i
		if l < n && s.heap[l].Count < s.heap[m].Count {
			m = l
		}
		if r := l + 1; r < n && s.heap[r].Count < s.heap[m].Count {
			m = r
		}
		if m == i {
			return
		}
		s.swap(i, m)
		i = m
	}
}

func (s *SpaceSaving) Add(key string, n uint64) {
	if n == 0 {
		return
	}
	s.total += n
	if i, ok := s.idx[key]; ok {
		s.heap[i].Count += n
		s.down(i)
		return
	}
	if len(s.heap) < s.k {
		s.heap = append(s.heap, &Entry{Key: key, Count: n})
		s.idx[key] = len(s.heap) - 1
		s.up(len(s.heap) - 1)
		return
	}
	// Evict the minimum: the newcomer inherits its count as error.
	e := s.heap[0]
	delete(s.idx, e.Key)
	e.Err = e.Count
	e.Count += n
	e.Key = key
	s.idx[key] = 0
	s.down(0)
}

// Top returns up to n entries by descending count.
func (s *SpaceSaving) Top(n int) []Entry {
	out := make([]Entry, len(s.heap))
	for i, e := range s.heap {
		out[i] = *e
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Count != out[j].Count {
			return out[i].Count > out[j].Count
		}
		return out[i].Key < out[j].Key
	})
	if n >= 0 && n < len(out) {
		out = out[:n]
	}
	return out
}

func (s *SpaceSaving) minCount() uint64 {
	if len(s.heap) < s.k {
		return 0 // not full: absent items truly have count 0
	}
	return s.heap[0].Count
}

// Merge combines two summaries (Agarwal et al., "Mergeable Summaries"): an
// item missing from a full summary may have had up to that summary's minimum
// count, so the minimum is added to both its count and its error.
func (s *SpaceSaving) Merge(o *SpaceSaving) error {
	if s.k != o.k {
		return errors.New("spacesaving: cannot merge different k")
	}
	ms, mo := s.minCount(), o.minCount()
	comb := map[string]*Entry{}
	for _, e := range s.heap {
		c := *e
		comb[e.Key] = &c
	}
	for _, e := range o.heap {
		if c, ok := comb[e.Key]; ok {
			c.Count += e.Count
			c.Err += e.Err
		} else {
			c := *e
			comb[e.Key] = &c
		}
	}
	inS := make(map[string]bool, len(s.heap))
	for _, e := range s.heap {
		inS[e.Key] = true
	}
	inO := make(map[string]bool, len(o.heap))
	for _, e := range o.heap {
		inO[e.Key] = true
	}
	all := make([]*Entry, 0, len(comb))
	for key, e := range comb {
		if !inS[key] {
			e.Count += ms
			e.Err += ms
		}
		if !inO[key] {
			e.Count += mo
			e.Err += mo
		}
		all = append(all, e)
	}
	sort.Slice(all, func(i, j int) bool {
		if all[i].Count != all[j].Count {
			return all[i].Count > all[j].Count
		}
		return all[i].Key < all[j].Key
	})
	if len(all) > s.k {
		all = all[:s.k]
	}
	s.total += o.total
	s.heap = s.heap[:0]
	s.idx = make(map[string]int, len(all))
	for _, e := range all {
		s.heap = append(s.heap, e)
	}
	// heapify
	for i := len(s.heap)/2 - 1; i >= 0; i-- {
		s.down(i)
	}
	for i, e := range s.heap {
		s.idx[e.Key] = i
	}
	return nil
}
