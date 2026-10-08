package store

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"hash/crc32"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"tide/internal/gorilla"
)

// Block file layout:
//
//	"TIDEBLK1" | chunk bytes ... | index JSON | u32 indexLen | u32 crc(index) | "TIDEEND1"
const (
	blockMagic = "TIDEBLK1"
	blockEnd   = "TIDEEND1"
)

var crcTable = crc32.MakeTable(crc32.Castagnoli)

type chunkRef struct {
	MinT int64  `json:"minT"`
	MaxT int64  `json:"maxT"`
	N    int    `json:"n"`
	Off  int    `json:"off"`
	Len  int    `json:"len"`
	CRC  uint32 `json:"crc"`
}

type seriesIndex struct {
	Labels map[string]string `json:"labels"`
	Chunks []chunkRef        `json:"chunks"`
}

type blockIndex struct {
	MinT    int64         `json:"minT"`
	MaxT    int64         `json:"maxT"`
	Samples int           `json:"samples"`
	Sources []string      `json:"sources,omitempty"` // blocks this one was compacted from
	Series  []seriesIndex `json:"series"`
}

// block is an immutable, fully loaded on-disk block.
type block struct {
	name   string
	data   []byte
	idx    blockIndex
	labels []Labels // parallel to idx.Series
	size   int64
	seq    int64 // creation stamp parsed from the file name
}

// chunkSource is one series worth of encoded chunks, input to writeBlock.
type chunkSource struct {
	labels Labels
	chunks [][]byte
}

// writeBlock atomically writes a block into dir and returns its file name.
func writeBlock(dir, name string, srcs []chunkSource, sources []string) error {
	sort.Slice(srcs, func(i, j int) bool { return srcs[i].labels.Key() < srcs[j].labels.Key() })
	var body []byte
	body = append(body, blockMagic...)
	idx := blockIndex{Sources: sources, Series: []seriesIndex{}}
	first := true
	for _, s := range srcs {
		si := seriesIndex{Labels: s.labels.Map()}
		for _, c := range s.chunks {
			n := gorilla.ChunkCount(c)
			if n == 0 {
				continue
			}
			it := gorilla.NewIterator(c)
			var minT, maxT int64
			for i := 0; it.Next(); i++ {
				t, _ := it.At()
				if i == 0 {
					minT = t
				}
				maxT = t
			}
			if it.Err() != nil {
				return fmt.Errorf("refusing to write corrupt chunk: %w", it.Err())
			}
			si.Chunks = append(si.Chunks, chunkRef{MinT: minT, MaxT: maxT, N: n, Off: len(body), Len: len(c), CRC: crc32.Checksum(c, crcTable)})
			body = append(body, c...)
			idx.Samples += n
			if first || minT < idx.MinT {
				idx.MinT = minT
			}
			if first || maxT > idx.MaxT {
				idx.MaxT = maxT
			}
			first = false
		}
		if len(si.Chunks) > 0 {
			idx.Series = append(idx.Series, si)
		}
	}
	ib, err := json.Marshal(idx)
	if err != nil {
		return err
	}
	body = append(body, ib...)
	var foot [8]byte
	binary.LittleEndian.PutUint32(foot[:4], uint32(len(ib)))
	binary.LittleEndian.PutUint32(foot[4:], crc32.Checksum(ib, crcTable))
	body = append(body, foot[:]...)
	body = append(body, blockEnd...)

	tmp := filepath.Join(dir, name+".tmp")
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(body); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmp, filepath.Join(dir, name)); err != nil {
		return err
	}
	return syncDir(dir)
}

func syncDir(dir string) error {
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}

var errCorruptBlock = errors.New("corrupt block")

func loadBlock(dir, name string) (*block, error) {
	data, err := os.ReadFile(filepath.Join(dir, name))
	if err != nil {
		return nil, err
	}
	bad := func(why string) (*block, error) { return nil, fmt.Errorf("%w %s: %s", errCorruptBlock, name, why) }
	if len(data) < len(blockMagic)+8+len(blockEnd) || string(data[:8]) != blockMagic || string(data[len(data)-8:]) != blockEnd {
		return bad("bad magic")
	}
	foot := data[len(data)-16 : len(data)-8]
	ilen := int(binary.LittleEndian.Uint32(foot[:4]))
	if ilen > len(data)-16-8 {
		return bad("index length")
	}
	ib := data[len(data)-16-ilen : len(data)-16]
	if crc32.Checksum(ib, crcTable) != binary.LittleEndian.Uint32(foot[4:]) {
		return bad("index checksum")
	}
	b := &block{name: name, data: data, size: int64(len(data))}
	if i := strings.LastIndexByte(name, '-'); i >= 0 {
		b.seq, _ = strconv.ParseInt(strings.TrimSuffix(name[i+1:], ".blk"), 10, 64)
	}
	if err := json.Unmarshal(ib, &b.idx); err != nil {
		return bad(err.Error())
	}
	dataEnd := len(data) - 16 - ilen
	for _, s := range b.idx.Series {
		b.labels = append(b.labels, NewLabels(s.Labels))
		for _, c := range s.Chunks {
			if c.Off < 8 || c.Off+c.Len > dataEnd {
				return bad("chunk out of range")
			}
			if crc32.Checksum(data[c.Off:c.Off+c.Len], crcTable) != c.CRC {
				return bad("chunk checksum")
			}
		}
	}
	return b, nil
}

func (b *block) chunk(r chunkRef) []byte { return b.data[r.Off : r.Off+r.Len] }
