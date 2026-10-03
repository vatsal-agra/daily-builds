// Package index stores landmark hashes in an inverted index and identifies clips by offset-histogram voting.
package index

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"hash/crc32"
	"os"
	"sort"

	"landmark/internal/fp"
)

// Song is catalogue metadata.
type Song struct {
	ID     uint32
	Name   string
	Frames int // length in STFT frames
	Hashes int // landmarks stored
}

// Posting says "this hash occurs in Song at frame T".
type Posting struct {
	Song uint32
	T    int32
}

// Index is the in-memory inverted index.
type Index struct {
	Params fp.Params
	Songs  []Song
	table  map[uint32][]Posting
}

// New creates an empty index for the given fingerprint parameters.
func New(p fp.Params) *Index { return &Index{Params: p, table: map[uint32][]Posting{}} }

// Add registers a song and all of its landmarks.
func (ix *Index) Add(name string, hashes []fp.Hash, frames int) (uint32, error) {
	if name == "" {
		return 0, errors.New("empty song name")
	}
	for _, s := range ix.Songs {
		if s.Name == name {
			return 0, fmt.Errorf("song %q already indexed", name)
		}
	}
	if len(hashes) == 0 {
		return 0, fmt.Errorf("song %q produced no landmarks (silent or too short?)", name)
	}
	id := uint32(len(ix.Songs))
	ix.Songs = append(ix.Songs, Song{ID: id, Name: name, Frames: frames, Hashes: len(hashes)})
	for _, h := range hashes {
		ix.table[h.H] = append(ix.table[h.H], Posting{id, h.T})
	}
	return id, nil
}

// NumKeys is the number of distinct hash keys.
func (ix *Index) NumKeys() int { return len(ix.table) }

// Match is a candidate identification.
type Match struct {
	Song      Song
	Score     int     // votes in the winning offset bin (±1 frame)
	Offset    int32   // song frame at which the query begins
	OffsetSec float64 // same, in seconds
	Hits      int     // all hash collisions with this song (noise floor context)
	Alt       int     // best vote count at an offset >2 frames away from Offset (periodic/looped material)
	Hist      map[int32]int
}

// Query tallies (song, Δt) votes for every query hash. Results are sorted best-first.
func (ix *Index) Query(q []fp.Hash) []Match {
	type key struct {
		song  uint32
		delta int32
	}
	votes := map[key]int{}
	hits := map[uint32]int{}
	for _, h := range q {
		for _, po := range ix.table[h.H] {
			votes[key{po.Song, po.T - h.T}]++
			hits[po.Song]++
		}
	}
	best := map[uint32]Match{}
	for k, v := range votes {
		s := v + votes[key{k.song, k.delta - 1}] + votes[key{k.song, k.delta + 1}]
		cur, ok := best[k.song]
		if !ok || s > cur.Score || (s == cur.Score && k.delta < cur.Offset) {
			best[k.song] = Match{Song: ix.Songs[k.song], Score: s, Offset: k.delta, Hits: hits[k.song]}
		}
	}
	// second peak per song: strongest offset bin not adjacent to the winner. A real match has one
	// dominant peak; rhythm-only or looped coincidences produce a comb of near-equal peaks.
	for k, v := range votes {
		m := best[k.song]
		d := k.delta - m.Offset
		if d < 0 {
			d = -d
		}
		if d > 2 {
			if s := v + votes[key{k.song, k.delta - 1}] + votes[key{k.song, k.delta + 1}]; s > m.Alt {
				m.Alt = s
				best[k.song] = m
			}
		}
	}
	out := make([]Match, 0, len(best))
	for _, m := range best {
		m.OffsetSec = float64(m.Offset) * ix.Params.FrameSeconds()
		out = append(out, m)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Score != out[j].Score {
			return out[i].Score > out[j].Score
		}
		return out[i].Song.ID < out[j].Song.ID
	})
	return out
}

// Histogram returns the raw Δ-vote histogram for one song (for visualisation).
func (ix *Index) Histogram(q []fp.Hash, song uint32) map[int32]int {
	h := map[int32]int{}
	for _, qh := range q {
		for _, po := range ix.table[qh.H] {
			if po.Song == song {
				h[po.T-qh.T]++
			}
		}
	}
	return h
}

// Policy decides when the top match is trustworthy.
type Policy struct {
	MinScore     int     // absolute floor on aligned votes
	Ratio        float64 // winner must beat the runner-up song by this factor
	SpeedPenalty int     // extra votes demanded when the match needed a speed correction (multiple-comparison guard)
	LoopFactor   int     // if the song has a rival offset peak (loop / rhythm-only coincidence), require MinScore×LoopFactor
}

// DefaultPolicy is tuned by the eval harness (see REVIEW.md).
func DefaultPolicy() Policy { return Policy{MinScore: 11, Ratio: 2.0, LoopFactor: 4, SpeedPenalty: 6} }

// Verdict is the final answer for a query.
type Verdict struct {
	Found      bool
	Best       Match
	RunnerUp   int
	Confidence float64 // 1 - runnerUp/score, in [0,1]
	// OffsetAmbiguous: the winning song has another offset with at least half the votes, i.e. the
	// clip lies in repeated/looped material and the reported start time may be one of several.
	OffsetAmbiguous bool
	Reason          string
}

// Decide applies the policy to sorted matches.
func (p Policy) Decide(ms []Match) Verdict {
	if len(ms) == 0 {
		return Verdict{Reason: "no hash collisions with any indexed song"}
	}
	v := Verdict{Best: ms[0]}
	if len(ms) > 1 {
		v.RunnerUp = ms[1].Score
	}
	if v.Best.Score > 0 {
		v.Confidence = 1 - float64(v.RunnerUp)/float64(v.Best.Score)
	}
	v.OffsetAmbiguous = 2*v.Best.Alt >= v.Best.Score
	switch {
	case v.OffsetAmbiguous && v.Best.Score < p.MinScore*p.LoopFactor:
		v.Reason = fmt.Sprintf("only a periodic alignment (%d votes, rival offset %d) — rhythm/loop coincidence, not strong enough (< %d)", v.Best.Score, v.Best.Alt, p.MinScore*p.LoopFactor)
	case v.Best.Score < p.MinScore:
		v.Reason = fmt.Sprintf("best alignment has only %d votes (< %d)", v.Best.Score, p.MinScore)
	case float64(v.Best.Score) < p.Ratio*float64(v.RunnerUp):
		v.Reason = fmt.Sprintf("ambiguous: %d votes vs runner-up %d", v.Best.Score, v.RunnerUp)
	default:
		v.Found = true
		v.Reason = "ok"
	}
	return v
}

const magic = "LMKIDX02"

// Save writes the index in a compact varint format with a CRC32 trailer.
func (ix *Index) Save(path string) error {
	var b bytes.Buffer
	b.WriteString(magic)
	pj, _ := json.Marshal(ix.Params)
	putU(&b, uint64(len(pj)))
	b.Write(pj)
	putU(&b, uint64(len(ix.Songs)))
	for _, s := range ix.Songs {
		putU(&b, uint64(len(s.Name)))
		b.WriteString(s.Name)
		putU(&b, uint64(s.Frames))
		putU(&b, uint64(s.Hashes))
	}
	keys := make([]uint32, 0, len(ix.table))
	for k := range ix.table {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool { return keys[i] < keys[j] })
	putU(&b, uint64(len(keys)))
	var prev uint32
	for _, k := range keys {
		putU(&b, uint64(k-prev))
		prev = k
		ps := ix.table[k]
		putU(&b, uint64(len(ps)))
		for _, po := range ps {
			putU(&b, uint64(po.Song))
			putU(&b, uint64(po.T))
		}
	}
	var crc [4]byte
	binary.LittleEndian.PutUint32(crc[:], crc32.ChecksumIEEE(b.Bytes()))
	b.Write(crc[:])
	return os.WriteFile(path, b.Bytes(), 0o644)
}

func putU(b *bytes.Buffer, v uint64) {
	var t [binary.MaxVarintLen64]byte
	b.Write(t[:binary.PutUvarint(t[:], v)])
}

// Load reads and validates an index file.
func Load(path string) (*Index, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(raw) < len(magic)+4 || string(raw[:len(magic)]) != magic {
		return nil, fmt.Errorf("%s: not a landmark index (bad magic)", path)
	}
	body, tail := raw[:len(raw)-4], raw[len(raw)-4:]
	if crc32.ChecksumIEEE(body) != binary.LittleEndian.Uint32(tail) {
		return nil, fmt.Errorf("%s: checksum mismatch — file is corrupt", path)
	}
	r := &reader{b: body[len(magic):]}
	ix := &Index{table: map[uint32][]Posting{}}
	pj := r.bytes(int(r.u()))
	if r.err == nil {
		if e := json.Unmarshal(pj, &ix.Params); e != nil {
			return nil, fmt.Errorf("%s: bad params: %w", path, e)
		}
	}
	ns := int(r.u())
	for i := 0; i < ns && r.err == nil; i++ {
		name := string(r.bytes(int(r.u())))
		ix.Songs = append(ix.Songs, Song{ID: uint32(i), Name: name, Frames: int(r.u()), Hashes: int(r.u())})
	}
	nk := int(r.u())
	var key uint32
	for i := 0; i < nk && r.err == nil; i++ {
		key += uint32(r.u())
		n := int(r.u())
		if n > len(r.b) {
			r.err = errors.New("posting count exceeds file")
			break
		}
		ps := make([]Posting, n)
		for j := range ps {
			s := uint32(r.u())
			if int(s) >= len(ix.Songs) {
				r.err = errors.New("posting references unknown song")
				break
			}
			ps[j] = Posting{s, int32(r.u())}
		}
		ix.table[key] = ps
	}
	if r.err != nil {
		return nil, fmt.Errorf("%s: truncated or malformed: %w", path, r.err)
	}
	return ix, nil
}

type reader struct {
	b   []byte
	err error
}

func (r *reader) u() uint64 {
	if r.err != nil {
		return 0
	}
	v, n := binary.Uvarint(r.b)
	if n <= 0 {
		r.err = errors.New("bad varint")
		return 0
	}
	r.b = r.b[n:]
	return v
}

func (r *reader) bytes(n int) []byte {
	if r.err != nil {
		return nil
	}
	if n < 0 || n > len(r.b) {
		r.err = errors.New("length out of range")
		return nil
	}
	out := r.b[:n]
	r.b = r.b[n:]
	return out
}
