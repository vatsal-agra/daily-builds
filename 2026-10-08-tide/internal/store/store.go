// Package store is the storage engine: WAL-backed in-memory head of Gorilla
// chunks, flushed to immutable checksummed blocks; queries merge both.
package store

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"tide/internal/gorilla"
	"tide/internal/wal"
)

type Sample struct {
	T int64 // unix milliseconds
	V float64
}

// Point is one sample for one series, as submitted by a writer.
type Point struct {
	Labels Labels
	T      int64
	V      float64
}

type Series struct {
	Labels  Labels
	Samples []Sample
}

type Options struct {
	Dir           string
	ChunkSize     int           // samples per chunk (default gorilla.MaxSamples)
	BlockDuration time.Duration // auto-flush when head spans this long (default 2h)
	FlushSamples  int           // auto-flush when head holds this many samples (default 1M)
	MaxSeries     int           // refuse new series beyond this many (default 1M)
}

type chunk struct {
	enc        *gorilla.Encoder
	minT, maxT int64
}

type memSeries struct {
	id     uint64
	key    string
	labels Labels
	chunks []*chunk
	n      int
}

type Store struct {
	opt  Options
	lock *os.File // exclusive flock on <dir>/LOCK

	mu      sync.RWMutex
	wal     *wal.WAL
	head    map[string]*memSeries
	byID    map[uint64]*memSeries
	lastT   map[string]int64 // newest timestamp ever stored per series (head + blocks); enforces ordering across flushes
	nextID  uint64
	headMin int64
	headMax int64
	headN   int
	blocks  []*block // ordered oldest-written first
	blkSeq  int64

	rejected struct{ outOfOrder, invalid int64 }
	accepted int64
	recovery struct {
		walSamples int
		walDropped int64
	}
}

var (
	ErrOutOfOrder = errors.New("out of order or duplicate sample")
	ErrInvalid    = errors.New("invalid sample")
)

// Accepted timestamp window (unix ms): 1970 .. year 9999. Wider values risk
// int64 overflow in delta-of-delta encoding and range arithmetic.
const (
	MinTimestamp = 0
	MaxTimestamp = 253402300799999
)

const (
	recSeries = 1
	recSample = 2
)

func Open(opt Options) (*Store, error) {
	if opt.Dir == "" {
		return nil, errors.New("store: Dir required")
	}
	if opt.ChunkSize <= 0 || opt.ChunkSize > gorilla.MaxSamples*8 {
		opt.ChunkSize = gorilla.MaxSamples
	}
	if opt.BlockDuration <= 0 {
		opt.BlockDuration = 2 * time.Hour
	}
	if opt.FlushSamples <= 0 {
		opt.FlushSamples = 1_000_000
	}
	if opt.MaxSeries <= 0 {
		opt.MaxSeries = 1_000_000
	}
	if err := os.MkdirAll(filepath.Join(opt.Dir, "blocks"), 0o755); err != nil {
		return nil, err
	}
	lock, err := lockDir(opt.Dir)
	if err != nil {
		return nil, err
	}
	s := &Store{lock: lock, opt: opt, head: map[string]*memSeries{}, byID: map[uint64]*memSeries{}, lastT: map[string]int64{}, nextID: 1}
	if err := s.loadBlocks(); err != nil {
		lock.Close()
		return nil, err
	}
	w, dropped, err := wal.Open(filepath.Join(opt.Dir, "wal.log"), s.replay)
	if err != nil {
		lock.Close()
		return nil, err
	}
	s.wal = w
	s.recovery.walDropped = dropped
	return s, nil
}

func (s *Store) blockDir() string { return filepath.Join(s.opt.Dir, "blocks") }

func (s *Store) loadBlocks() error {
	ents, err := os.ReadDir(s.blockDir())
	if err != nil {
		return err
	}
	byName := map[string]*block{}
	for _, e := range ents {
		n := e.Name()
		if strings.HasSuffix(n, ".tmp") { // interrupted write; never became visible
			os.Remove(filepath.Join(s.blockDir(), n))
			continue
		}
		if !strings.HasSuffix(n, ".blk") {
			continue
		}
		b, err := loadBlock(s.blockDir(), n)
		if err != nil {
			return err
		}
		byName[n] = b
	}
	// Finish interrupted compactions: a compacted block supersedes its sources.
	for _, b := range byName {
		for _, src := range b.idx.Sources {
			if _, ok := byName[src]; ok {
				os.Remove(filepath.Join(s.blockDir(), src))
				delete(byName, src)
			}
		}
	}
	for _, b := range byName {
		s.blocks = append(s.blocks, b)
	}
	s.sortBlocks()
	for _, b := range s.blocks {
		for i, si := range b.idx.Series {
			key := b.labels[i].Key()
			for _, c := range si.Chunks {
				if last, ok := s.lastT[key]; !ok || c.MaxT > last {
					s.lastT[key] = c.MaxT
				}
			}
		}
	}
	return nil
}

// sortBlocks orders blocks oldest-written first. Write order (not time order)
// decides precedence when two blocks hold the same timestamp: newer wins.
func (s *Store) sortBlocks() {
	sort.Slice(s.blocks, func(i, j int) bool { return s.blocks[i].seq < s.blocks[j].seq })
}

// ---- WAL records ----

func encSeriesRec(id uint64, ls Labels) []byte {
	b := []byte{recSeries}
	b = binary.AppendUvarint(b, id)
	b = binary.AppendUvarint(b, uint64(len(ls)))
	for _, l := range ls {
		b = binary.AppendUvarint(b, uint64(len(l.Name)))
		b = append(b, l.Name...)
		b = binary.AppendUvarint(b, uint64(len(l.Value)))
		b = append(b, l.Value...)
	}
	return b
}

func encSampleRec(id uint64, t int64, v float64) []byte {
	b := []byte{recSample}
	b = binary.AppendUvarint(b, id)
	b = binary.AppendVarint(b, t)
	return binary.LittleEndian.AppendUint64(b, math.Float64bits(v))
}

type recReader struct {
	b   []byte
	err error
}

func (r *recReader) uvarint() uint64 {
	v, n := binary.Uvarint(r.b)
	if n <= 0 {
		r.err = errors.New("bad uvarint")
		return 0
	}
	r.b = r.b[n:]
	return v
}

func (r *recReader) str() string {
	n := int(r.uvarint())
	if r.err != nil || n > len(r.b) {
		r.err = errors.New("bad string")
		return ""
	}
	s := string(r.b[:n])
	r.b = r.b[n:]
	return s
}

func (s *Store) replay(rec []byte) error {
	if len(rec) == 0 {
		return errors.New("empty record")
	}
	r := &recReader{b: rec[1:]}
	switch rec[0] {
	case recSeries:
		id := r.uvarint()
		n := int(r.uvarint())
		var ls Labels
		for i := 0; i < n && r.err == nil; i++ {
			ls = append(ls, Label{r.str(), r.str()})
		}
		if r.err != nil {
			return r.err
		}
		ms := &memSeries{id: id, key: ls.Key(), labels: ls}
		s.head[ms.key] = ms
		s.byID[id] = ms
		if id >= s.nextID {
			s.nextID = id + 1
		}
	case recSample:
		id := r.uvarint()
		t, n := binary.Varint(r.b)
		if n <= 0 || len(r.b) < n+8 {
			return errors.New("bad sample record")
		}
		v := math.Float64frombits(binary.LittleEndian.Uint64(r.b[n:]))
		ms := s.byID[id]
		if ms == nil {
			return fmt.Errorf("sample for unknown series %d", id)
		}
		if last, ok := s.lastT[ms.key]; ok && t <= last {
			return nil // already persisted in a block (crash after block write, before WAL reset)
		}
		if err := s.appendHead(ms, t, v); err == nil {
			s.recovery.walSamples++
		}
	default:
		return fmt.Errorf("unknown record type %d", rec[0])
	}
	return nil
}

// ---- head ----

func (s *Store) appendHead(ms *memSeries, t int64, v float64) error {
	var c *chunk
	if len(ms.chunks) > 0 {
		c = ms.chunks[len(ms.chunks)-1]
	}
	if c == nil || c.enc.Len() >= s.opt.ChunkSize {
		c = &chunk{enc: gorilla.NewEncoder(), minT: t}
		ms.chunks = append(ms.chunks, c)
	}
	if err := c.enc.Append(t, v); err != nil {
		return err
	}
	c.maxT = t
	s.lastT[ms.key] = t
	ms.n++
	if s.headN == 0 || t < s.headMin {
		s.headMin = t
	}
	if s.headN == 0 || t > s.headMax {
		s.headMax = t
	}
	s.headN++
	return nil
}

// AppendResult reports what happened to a batch. Rejected points (out of
// order, duplicate, NaN/Inf, bad labels) never fail the batch.
type AppendResult struct {
	Accepted     int
	OutOfOrder   int
	Invalid      int
	FirstInvalid string
}

// Append writes points durably (one WAL fsync per call).
func (s *Store) Append(points []Point) (AppendResult, error) {
	var res AppendResult
	s.mu.Lock()
	defer s.mu.Unlock()
	wrote := false
	for _, p := range points {
		if math.IsNaN(p.V) || math.IsInf(p.V, 0) {
			s.noteInvalid(&res, "non-finite value")
			continue
		}
		if p.T < MinTimestamp || p.T > MaxTimestamp {
			s.noteInvalid(&res, fmt.Sprintf("timestamp %d out of range", p.T))
			continue
		}
		ls := p.Labels
		if err := ls.Validate(); err != nil {
			s.noteInvalid(&res, err.Error())
			continue
		}
		key := ls.Key()
		last, known := s.lastT[key]
		if known && p.T <= last {
			s.rejected.outOfOrder++
			res.OutOfOrder++
			continue
		}
		ms := s.head[key]
		if ms == nil {
			if !known && len(s.lastT) >= s.opt.MaxSeries {
				s.noteInvalid(&res, fmt.Sprintf("series limit (%d) reached", s.opt.MaxSeries))
				continue
			}
			ms = &memSeries{id: s.nextID, key: key, labels: ls}
			if err := s.wal.Append(encSeriesRec(ms.id, ls)); err != nil {
				return res, err
			}
			s.nextID++
			s.head[key] = ms
			s.byID[ms.id] = ms
		}
		if err := s.wal.Append(encSampleRec(ms.id, p.T, p.V)); err != nil {
			return res, err
		}
		wrote = true
		if err := s.appendHead(ms, p.T, p.V); err != nil {
			return res, err
		}
		s.accepted++
		res.Accepted++
	}
	if wrote {
		if err := s.wal.Sync(); err != nil {
			return res, err
		}
	}
	if s.headN > 0 && (s.headN >= s.opt.FlushSamples || time.Duration(s.headMax-s.headMin)*time.Millisecond >= s.opt.BlockDuration) {
		if err := s.flushLocked(); err != nil {
			return res, err
		}
	}
	return res, nil
}

func (s *Store) noteInvalid(res *AppendResult, why string) {
	s.rejected.invalid++
	res.Invalid++
	if res.FirstInvalid == "" {
		res.FirstInvalid = why
	}
}

// ---- flush ----

// Flush persists the head as a block and resets the WAL.
func (s *Store) Flush() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.flushLocked()
}

func (s *Store) flushLocked() error {
	if s.headN == 0 {
		return nil
	}
	srcs := make([]chunkSource, 0, len(s.head))
	for _, ms := range s.head {
		if ms.n == 0 {
			continue
		}
		cs := chunkSource{labels: ms.labels}
		for _, c := range ms.chunks {
			cs.chunks = append(cs.chunks, c.enc.Bytes())
		}
		srcs = append(srcs, cs)
	}
	name := s.newBlockName(s.headMin, s.headMax)
	if err := writeBlock(s.blockDir(), name, srcs, nil); err != nil {
		return err
	}
	b, err := loadBlock(s.blockDir(), name)
	if err != nil {
		return err
	}
	// The block is durable; only now is it safe to drop the WAL. A crash
	// between these two steps just replays duplicates that queries dedupe.
	if err := s.wal.Reset(); err != nil {
		return err
	}
	s.blocks = append(s.blocks, b)
	s.sortBlocks()
	s.head = map[string]*memSeries{}
	s.byID = map[uint64]*memSeries{}
	s.nextID = 1
	s.headN, s.headMin, s.headMax = 0, 0, 0
	return nil
}

func (s *Store) newBlockName(minT, maxT int64) string {
	s.blkSeq++
	return fmt.Sprintf("b-%d-%d-%d.blk", minT, maxT, time.Now().UnixNano()+s.blkSeq)
}

// ---- query ----

// Select returns every series matching all matchers, with samples in
// [mint, maxt] merged across blocks and head, sorted by time, one sample per
// timestamp (newer sources win). Series with no samples in range are omitted.
func (s *Store) Select(ms []*Matcher, mint, maxt int64) ([]Series, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	type acc struct {
		labels  Labels
		samples []Sample
		sorted  bool
	}
	got := map[string]*acc{}
	add := func(ls Labels, it *gorilla.Iterator) error {
		key := ls.Key()
		a := got[key]
		if a == nil {
			a = &acc{labels: ls, sorted: true}
			got[key] = a
		}
		for it.Next() {
			t, v := it.At()
			if t < mint || t > maxt {
				continue
			}
			if n := len(a.samples); n > 0 && t <= a.samples[n-1].T {
				a.sorted = false
			}
			a.samples = append(a.samples, Sample{t, v})
		}
		return it.Err()
	}
	for _, b := range s.blocks {
		if b.idx.MaxT < mint || b.idx.MinT > maxt {
			continue
		}
		for i, si := range b.idx.Series {
			if !matchAll(ms, b.labels[i]) {
				continue
			}
			for _, c := range si.Chunks {
				if c.MaxT < mint || c.MinT > maxt {
					continue
				}
				if err := add(b.labels[i], gorilla.NewIterator(b.chunk(c))); err != nil {
					return nil, fmt.Errorf("block %s: %w", b.name, err)
				}
			}
		}
	}
	for _, m := range s.head {
		if m.n == 0 || !matchAll(ms, m.labels) {
			continue
		}
		for _, c := range m.chunks {
			if c.maxT < mint || c.minT > maxt {
				continue
			}
			if err := add(m.labels, gorilla.NewIterator(c.enc.Bytes())); err != nil {
				return nil, err
			}
		}
	}
	out := make([]Series, 0, len(got))
	for _, a := range got {
		if len(a.samples) == 0 {
			continue
		}
		if !a.sorted {
			a.samples = sortDedupe(a.samples)
		}
		out = append(out, Series{Labels: a.labels, Samples: a.samples})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Labels.Key() < out[j].Labels.Key() })
	return out, nil
}

// sortDedupe orders by time; for equal timestamps the later-appended sample
// (the newer source) wins.
func sortDedupe(in []Sample) []Sample {
	type ix struct {
		s Sample
		i int
	}
	tmp := make([]ix, len(in))
	for i, x := range in {
		tmp[i] = ix{x, i}
	}
	sort.Slice(tmp, func(a, b int) bool {
		if tmp[a].s.T != tmp[b].s.T {
			return tmp[a].s.T < tmp[b].s.T
		}
		return tmp[a].i < tmp[b].i
	})
	out := in[:0:0]
	for _, x := range tmp {
		if n := len(out); n > 0 && out[n-1].T == x.s.T {
			out[n-1] = x.s
			continue
		}
		out = append(out, x.s)
	}
	return out
}

// SeriesLabels lists the label sets of all series matching ms.
func (s *Store) SeriesLabels(ms []*Matcher) []Labels {
	s.mu.RLock()
	defer s.mu.RUnlock()
	seen := map[string]Labels{}
	for _, b := range s.blocks {
		for _, ls := range b.labels {
			if matchAll(ms, ls) {
				seen[ls.Key()] = ls
			}
		}
	}
	for _, m := range s.head {
		if m.n > 0 && matchAll(ms, m.labels) {
			seen[m.labels.Key()] = m.labels
		}
	}
	out := make([]Labels, 0, len(seen))
	for _, ls := range seen {
		out = append(out, ls)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Key() < out[j].Key() })
	return out
}

// TimeRange returns the min/max timestamp stored (ok=false when empty).
func (s *Store) TimeRange() (minT, maxT int64, ok bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.timeRangeLocked()
}

func (s *Store) timeRangeLocked() (minT, maxT int64, ok bool) {
	for _, b := range s.blocks {
		if !ok || b.idx.MinT < minT {
			minT = b.idx.MinT
		}
		if !ok || b.idx.MaxT > maxT {
			maxT = b.idx.MaxT
		}
		ok = true
	}
	if s.headN > 0 {
		if !ok || s.headMin < minT {
			minT = s.headMin
		}
		if !ok || s.headMax > maxT {
			maxT = s.headMax
		}
		ok = true
	}
	return
}

// ---- stats ----

type Stats struct {
	Series          int     `json:"series"`
	HeadSeries      int     `json:"headSeries"`
	HeadSamples     int     `json:"headSamples"`
	HeadChunkBytes  int     `json:"headChunkBytes"`
	Blocks          int     `json:"blocks"`
	BlockSamples    int     `json:"blockSamples"`
	BlockBytes      int64   `json:"blockBytes"`
	BlockChunkBytes int64   `json:"blockChunkBytes"`
	WALBytes        int64   `json:"walBytes"`
	TotalSamples    int     `json:"totalSamples"`
	BytesPerSample  float64 `json:"bytesPerSample"`
	CompressionX    float64 `json:"compressionRatio"` // vs 16 raw bytes per sample
	Accepted        int64   `json:"accepted"`
	OutOfOrder      int64   `json:"rejectedOutOfOrder"`
	Invalid         int64   `json:"rejectedInvalid"`
	RecoveredWAL    int     `json:"recoveredWalSamples"`
	WALTornBytes    int64   `json:"walTornBytesDropped"`
	MinT            int64   `json:"minT"`
	MaxT            int64   `json:"maxT"`
}

func (s *Store) Stats() Stats {
	s.mu.RLock()
	defer s.mu.RUnlock()
	st := Stats{HeadSeries: len(s.head), HeadSamples: s.headN, Blocks: len(s.blocks), WALBytes: s.wal.Size(),
		Accepted: s.accepted, OutOfOrder: s.rejected.outOfOrder, Invalid: s.rejected.invalid,
		RecoveredWAL: s.recovery.walSamples, WALTornBytes: s.recovery.walDropped}
	keys := map[string]struct{}{}
	for k, m := range s.head {
		keys[k] = struct{}{}
		for _, c := range m.chunks {
			st.HeadChunkBytes += c.enc.Size()
		}
	}
	for _, b := range s.blocks {
		st.BlockSamples += b.idx.Samples
		st.BlockBytes += b.size
		for i, si := range b.idx.Series {
			keys[b.labels[i].Key()] = struct{}{}
			for _, c := range si.Chunks {
				st.BlockChunkBytes += int64(c.Len)
			}
		}
	}
	st.Series = len(keys)
	st.TotalSamples = st.HeadSamples + st.BlockSamples
	if st.TotalSamples > 0 {
		st.BytesPerSample = (float64(st.HeadChunkBytes) + float64(st.BlockChunkBytes)) / float64(st.TotalSamples)
		st.CompressionX = 16 / st.BytesPerSample
	}
	if mn, mx, ok := s.timeRangeLocked(); ok {
		st.MinT, st.MaxT = mn, mx
	}
	return st
}

func (s *Store) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	err := s.wal.Close()
	if lerr := s.lock.Close(); err == nil { // closing releases the flock
		err = lerr
	}
	return err
}
