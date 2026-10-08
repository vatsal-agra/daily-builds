package store

import (
	"os"
	"path/filepath"

	"tide/internal/gorilla"
)

type CompactResult struct {
	BlocksBefore int   `json:"blocksBefore"`
	BlocksAfter  int   `json:"blocksAfter"`
	Samples      int   `json:"samples"`
	Duplicates   int   `json:"duplicatesRemoved"`
	BytesBefore  int64 `json:"bytesBefore"`
	BytesAfter   int64 `json:"bytesAfter"`
}

// Compact merges all on-disk blocks into one, deduplicating samples and
// re-packing chunks to full size. Crash-safe: the new block records its
// sources, and Open deletes any sources that survive a crash.
func (s *Store) Compact() (CompactResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	res := CompactResult{BlocksBefore: len(s.blocks), BlocksAfter: len(s.blocks)}
	for _, b := range s.blocks {
		res.BytesBefore += b.size
	}
	res.BytesAfter = res.BytesBefore
	if len(s.blocks) < 2 {
		return res, nil
	}
	perSeries := map[string]*Series{}
	total := 0
	for _, b := range s.blocks { // oldest-written first; later wins on equal ts
		for i, si := range b.idx.Series {
			key := b.labels[i].Key()
			ser := perSeries[key]
			if ser == nil {
				ser = &Series{Labels: b.labels[i]}
				perSeries[key] = ser
			}
			for _, c := range si.Chunks {
				it := gorilla.NewIterator(b.chunk(c))
				for it.Next() {
					t, v := it.At()
					ser.Samples = append(ser.Samples, Sample{t, v})
					total++
				}
				if err := it.Err(); err != nil {
					return res, err
				}
			}
		}
	}
	var srcs []chunkSource
	kept := 0
	for _, ser := range perSeries {
		samples := sortDedupe(ser.Samples)
		kept += len(samples)
		cs := chunkSource{labels: ser.Labels}
		var enc *gorilla.Encoder
		for _, sm := range samples {
			if enc == nil || enc.Len() >= s.opt.ChunkSize {
				if enc != nil {
					cs.chunks = append(cs.chunks, enc.Bytes())
				}
				enc = gorilla.NewEncoder()
			}
			if err := enc.Append(sm.T, sm.V); err != nil {
				return res, err
			}
		}
		if enc != nil {
			cs.chunks = append(cs.chunks, enc.Bytes())
		}
		srcs = append(srcs, cs)
	}
	var minT, maxT int64
	first := true
	for _, b := range s.blocks {
		if first || b.idx.MinT < minT {
			minT = b.idx.MinT
		}
		if first || b.idx.MaxT > maxT {
			maxT = b.idx.MaxT
		}
		first = false
	}
	old := s.blocks
	names := make([]string, len(old))
	for i, b := range old {
		names[i] = b.name
	}
	name := s.newBlockName(minT, maxT)
	if err := writeBlock(s.blockDir(), name, srcs, names); err != nil {
		return res, err
	}
	nb, err := loadBlock(s.blockDir(), name)
	if err != nil {
		return res, err
	}
	s.blocks = []*block{nb}
	for _, b := range old {
		os.Remove(filepath.Join(s.blockDir(), b.name))
	}
	_ = syncDir(s.blockDir())
	res.BlocksAfter = 1
	res.Samples = kept
	res.Duplicates = total - kept
	res.BytesAfter = nb.size
	return res, nil
}

// DropBefore deletes whole blocks whose newest sample is older than cutoff
// (unix ms). It returns the number of blocks removed.
func (s *Store) DropBefore(cutoff int64) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var keep []*block
	dropped := 0
	for _, b := range s.blocks {
		if b.idx.MaxT < cutoff {
			if err := os.Remove(filepath.Join(s.blockDir(), b.name)); err != nil && !os.IsNotExist(err) {
				return dropped, err
			}
			dropped++
			continue
		}
		keep = append(keep, b)
	}
	s.blocks = keep
	return dropped, nil
}
