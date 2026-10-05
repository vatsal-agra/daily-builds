package sketch

import (
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"
	"unicode"
)

// MinHash estimates Jaccard similarity: P[min-hash agree] = |A∩B|/|A∪B|.
type MinHash struct {
	sig   []uint64
	empty bool
}

func NewMinHash(k int) (*MinHash, error) {
	if k < 1 || k > 4096 {
		return nil, fmt.Errorf("minhash: k=%d out of range 1..4096", k)
	}
	m := &MinHash{sig: make([]uint64, k), empty: true}
	for i := range m.sig {
		m.sig[i] = math.MaxUint64
	}
	return m, nil
}

func (m *MinHash) K() int      { return len(m.sig) }
func (m *MinHash) Empty() bool { return m.empty }
func (m *MinHash) Bytes() int  { return len(m.sig) * 8 }

func (m *MinHash) Add(item []byte) {
	h := Hash64(item, 0x9a1)
	for i := range m.sig {
		if v := Mix64(h ^ Mix64(uint64(i)+1)); v < m.sig[i] {
			m.sig[i] = v
		}
	}
	m.empty = false
}

func (m *MinHash) AddString(s string) { m.Add([]byte(s)) }

// Jaccard estimates similarity with another signature (standard error ≈ sqrt(J(1-J)/k)).
func (m *MinHash) Jaccard(o *MinHash) (float64, error) {
	if len(m.sig) != len(o.sig) {
		return 0, errors.New("minhash: signatures have different k")
	}
	if m.empty && o.empty {
		return 1, nil
	}
	if m.empty || o.empty {
		return 0, nil
	}
	eq := 0
	for i := range m.sig {
		if m.sig[i] == o.sig[i] {
			eq++
		}
	}
	return float64(eq) / float64(len(m.sig)), nil
}

// Merge makes m the signature of the union of both sets.
func (m *MinHash) Merge(o *MinHash) error {
	if len(m.sig) != len(o.sig) {
		return errors.New("minhash: different k")
	}
	for i, v := range o.sig {
		if v < m.sig[i] {
			m.sig[i] = v
		}
	}
	m.empty = m.empty && o.empty
	return nil
}

// Words splits text into lowercase alphanumeric tokens.
func Words(s string) []string {
	return strings.FieldsFunc(strings.ToLower(s), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	})
}

// Shingles returns the distinct word n-grams of text (all words if fewer than n).
func Shingles(text string, n int) []string {
	w := Words(text)
	if n < 1 {
		n = 1
	}
	if len(w) == 0 {
		return nil
	}
	if len(w) <= n {
		return []string{strings.Join(w, " ")}
	}
	seen := map[string]struct{}{}
	var out []string
	for i := 0; i+n <= len(w); i++ {
		s := strings.Join(w[i:i+n], " ")
		if _, ok := seen[s]; !ok {
			seen[s] = struct{}{}
			out = append(out, s)
		}
	}
	return out
}

// SignatureOf builds a signature of text's word shingles.
func SignatureOf(text string, k, shingle int) (*MinHash, error) {
	m, err := NewMinHash(k)
	if err != nil {
		return nil, err
	}
	for _, s := range Shingles(text, shingle) {
		m.AddString(s)
	}
	return m, nil
}

// ExactJaccard is the ground truth for two sets of strings.
func ExactJaccard(a, b []string) float64 {
	sa := map[string]struct{}{}
	for _, x := range a {
		sa[x] = struct{}{}
	}
	sb := map[string]struct{}{}
	for _, x := range b {
		sb[x] = struct{}{}
	}
	if len(sa) == 0 && len(sb) == 0 {
		return 1
	}
	inter := 0
	for x := range sa {
		if _, ok := sb[x]; ok {
			inter++
		}
	}
	return float64(inter) / float64(len(sa)+len(sb)-inter)
}

// OptimalBands picks (bands, rows) with bands*rows <= k whose S-curve
// 1-(1-s^r)^b has its steepest point nearest `threshold`, weighting false
// negatives and false positives equally.
func OptimalBands(k int, threshold float64) (bands, rows int) {
	best := math.Inf(1)
	bands, rows = k, 1
	for r := 1; r <= k; r++ {
		b := k / r
		if b < 1 {
			continue
		}
		fp, fn := 0.0, 0.0
		const steps = 200
		for i := 0; i < steps; i++ {
			s := (float64(i) + 0.5) / steps
			p := 1 - math.Pow(1-math.Pow(s, float64(r)), float64(b))
			if s < threshold {
				fp += p / steps
			} else {
				fn += (1 - p) / steps
			}
		}
		if e := fp + fn; e < best {
			best, bands, rows = e, b, r
		}
	}
	return
}

// LSH is a banded locality-sensitive-hashing index over MinHash signatures.
type LSH struct {
	bands, rows int
	k           int
	tables      []map[uint64][]int
	ids         []string
	sigs        []*MinHash
}

func NewLSH(k int, threshold float64) (*LSH, error) {
	if k < 2 || k > 4096 {
		return nil, fmt.Errorf("lsh: k=%d out of range", k)
	}
	if !(threshold > 0 && threshold < 1) {
		return nil, fmt.Errorf("lsh: threshold %v must be in (0,1)", threshold)
	}
	b, r := OptimalBands(k, threshold)
	l := &LSH{bands: b, rows: r, k: k, tables: make([]map[uint64][]int, b)}
	for i := range l.tables {
		l.tables[i] = map[uint64][]int{}
	}
	return l, nil
}

func (l *LSH) Bands() int { return l.bands }
func (l *LSH) Rows() int  { return l.rows }
func (l *LSH) Len() int   { return len(l.ids) }

func (l *LSH) bandKey(m *MinHash, b int) uint64 {
	h := uint64(b) + 1
	for _, v := range m.sig[b*l.rows : (b+1)*l.rows] {
		h = Mix64(h ^ v)
	}
	return h
}

// Insert adds a document signature; empty signatures are rejected.
func (l *LSH) Insert(id string, m *MinHash) error {
	if m.K() != l.k {
		return errors.New("lsh: signature k mismatch")
	}
	if m.empty {
		return errors.New("lsh: empty signature")
	}
	n := len(l.ids)
	l.ids = append(l.ids, id)
	l.sigs = append(l.sigs, m)
	for b := 0; b < l.bands; b++ {
		key := l.bandKey(m, b)
		l.tables[b][key] = append(l.tables[b][key], n)
	}
	return nil
}

type Match struct {
	ID      string
	Jaccard float64
}

// Query returns indexed items colliding with m in any band, with estimated
// Jaccard >= minJ, best first.
func (l *LSH) Query(m *MinHash, minJ float64) ([]Match, error) {
	if m.K() != l.k {
		return nil, errors.New("lsh: signature k mismatch")
	}
	seen := map[int]bool{}
	var out []Match
	for b := 0; b < l.bands; b++ {
		for _, i := range l.tables[b][l.bandKey(m, b)] {
			if seen[i] {
				continue
			}
			seen[i] = true
			j, _ := m.Jaccard(l.sigs[i])
			if j >= minJ {
				out = append(out, Match{l.ids[i], j})
			}
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Jaccard != out[j].Jaccard {
			return out[i].Jaccard > out[j].Jaccard
		}
		return out[i].ID < out[j].ID
	})
	return out, nil
}
