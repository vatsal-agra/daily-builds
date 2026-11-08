package codec

import (
	"encoding/binary"
	"errors"
	"fmt"
	"hash/crc32"
	"sort"
)

// Container layout (little endian):
//   "REEL" ver u8 | flags u8 | w u16 | h u16 | fpsNum u32 | fpsDen u32 | nFrames u32
//   per frame: type u8 | flags u8 (bit0 deblock) | qp u8 | dbOffset i8 | disp u32 |
//              payloadLen u32 | crc32 u32 | payload (range coded macroblocks)

const (
	magic       = "REEL"
	version     = 1
	hdrSize     = 4 + 1 + 1 + 2 + 2 + 4 + 4 + 4
	frameHdrLen = 1 + 1 + 1 + 1 + 4 + 4 + 4
)

// FrameStat describes one coded frame.
type FrameStat struct {
	Type, Disp, QP, Bytes int
	Skip, Intra           int // macroblock counts
	Inter16, InterSplit   int
	L0, L1, Bi            int // partitions by prediction direction
	PSNRY, PSNRU, PSNRV   float64
	SADEvals              int
	Deblock               bool
	MVs                   []MBMotion // optional (decoder fills for the visualiser)
}

// MBMotion is a per-macroblock summary kept for visualisation.
type MBMotion struct {
	Kind int // 0 skip, 1 inter, 2 intra, 3 split
	MVX  int
	MVY  int
	Dir  int
}

type streamHeader struct {
	W, H           int
	FPSNum, FPSDen int
	N              int
}

func putHeader(h streamHeader) []byte {
	b := make([]byte, hdrSize)
	copy(b, magic)
	b[4] = version
	binary.LittleEndian.PutUint16(b[6:], uint16(h.W))
	binary.LittleEndian.PutUint16(b[8:], uint16(h.H))
	binary.LittleEndian.PutUint32(b[10:], uint32(h.FPSNum))
	binary.LittleEndian.PutUint32(b[14:], uint32(h.FPSDen))
	binary.LittleEndian.PutUint32(b[18:], uint32(h.N))
	return b
}

func putFrameHeader(typ int, deblock bool, qp, dbOff, disp int, payload []byte) []byte {
	b := make([]byte, frameHdrLen)
	b[0] = byte(typ)
	if deblock {
		b[1] = 1
	}
	b[2] = byte(qp)
	b[3] = byte(int8(dbOff))
	binary.LittleEndian.PutUint32(b[4:], uint32(disp))
	binary.LittleEndian.PutUint32(b[8:], uint32(len(payload)))
	binary.LittleEndian.PutUint32(b[12:], crc32.ChecksumIEEE(payload))
	return b
}

// Decode decodes a .reel stream into display-order frames.
func Decode(data []byte) (v *Video, stats []FrameStat, err error) {
	defer func() {
		if r := recover(); r != nil {
			v, stats, err = nil, nil, fmt.Errorf("reel: corrupt stream (internal check failed: %v)", r)
		}
	}()
	if len(data) < hdrSize || string(data[:4]) != magic {
		return nil, nil, errors.New("reel: not a .reel stream (bad magic)")
	}
	if data[4] != version {
		return nil, nil, fmt.Errorf("reel: unsupported version %d", data[4])
	}
	h := streamHeader{
		W:      int(binary.LittleEndian.Uint16(data[6:])),
		H:      int(binary.LittleEndian.Uint16(data[8:])),
		FPSNum: int(binary.LittleEndian.Uint32(data[10:])),
		FPSDen: int(binary.LittleEndian.Uint32(data[14:])),
		N:      int(binary.LittleEndian.Uint32(data[18:])),
	}
	if h.W < 16 || h.H < 16 || h.W > maxDim || h.H > maxDim {
		return nil, nil, fmt.Errorf("reel: bad dimensions %dx%d", h.W, h.H)
	}
	if h.N < 1 || h.N > 1<<20 || h.FPSNum <= 0 || h.FPSDen <= 0 {
		return nil, nil, errors.New("reel: bad stream header")
	}
	pos := hdrSize
	var anchors []*Frame
	byDisp := map[int]*Frame{}
	for n := 0; n < h.N; n++ {
		if len(data)-pos < frameHdrLen {
			return nil, nil, fmt.Errorf("reel: frame %d: truncated header", n)
		}
		fh := data[pos : pos+frameHdrLen]
		typ, qp, dbOff := int(fh[0]), int(fh[2]), int(int8(fh[3]))
		disp := int(binary.LittleEndian.Uint32(fh[4:]))
		plen := int(binary.LittleEndian.Uint32(fh[8:]))
		crc := binary.LittleEndian.Uint32(fh[12:])
		pos += frameHdrLen
		if typ > FrameB || qp > MaxQP || fh[1]&^1 != 0 {
			return nil, nil, fmt.Errorf("reel: frame %d: bad frame header", n)
		}
		if plen < 0 || plen > len(data)-pos {
			return nil, nil, fmt.Errorf("reel: frame %d: payload truncated", n)
		}
		payload := data[pos : pos+plen]
		pos += plen
		if crc32.ChecksumIEEE(payload) != crc {
			return nil, nil, fmt.Errorf("reel: frame %d: checksum mismatch", n)
		}
		if disp >= h.N || byDisp[disp] != nil {
			return nil, nil, fmt.Errorf("reel: frame %d: bad display index %d", n, disp)
		}
		fc := newFrameCtx(typ, qp, h.W, h.H)
		fc.deblock = fh[1]&1 == 1
		fc.dbOffset = dbOff
		switch typ {
		case FrameP:
			if len(anchors) < 1 {
				return nil, nil, fmt.Errorf("reel: frame %d: P frame without reference", n)
			}
			fc.ref[0] = anchors[len(anchors)-1]
		case FrameB:
			if len(anchors) < 2 {
				return nil, nil, fmt.Errorf("reel: frame %d: B frame needs two anchors", n)
			}
			fc.ref[0], fc.ref[1] = anchors[len(anchors)-2], anchors[len(anchors)-1]
		}
		fc.cur = NewFrame(h.W, h.H)
		fc.cur.Disp = disp
		rd := newRCDec(payload)
		st := FrameStat{Type: typ, Disp: disp, QP: qp, Bytes: plen + frameHdrLen, Deblock: fc.deblock}
		for my := 0; my < fc.mbH; my++ {
			for mx := 0; mx < fc.mbW; mx++ {
				var mb MB
				if err := fc.codeMB(rd, &mb, mx, my); err != nil {
					return nil, nil, fmt.Errorf("frame %d: %w", n, err)
				}
				fc.reconMB(&mb, mx, my)
				st.count(&mb)
			}
		}
		if fc.deblock {
			fc.deblockFrame()
		}
		fc.cur.extend()
		byDisp[disp] = fc.cur
		if typ != FrameB {
			anchors = append(anchors, fc.cur)
			if len(anchors) > 2 {
				anchors = anchors[1:]
			}
		}
		stats = append(stats, st)
	}
	v = &Video{Width: h.W, Height: h.H, FPSNum: h.FPSNum, FPSDen: h.FPSDen}
	disps := make([]int, 0, len(byDisp))
	for d := range byDisp {
		disps = append(disps, d)
	}
	sort.Ints(disps)
	for i, d := range disps {
		if d != i {
			return nil, nil, fmt.Errorf("reel: missing display index %d", i)
		}
		v.Frames = append(v.Frames, byDisp[d])
	}
	return v, stats, nil
}

func (st *FrameStat) count(mb *MB) {
	switch {
	case mb.Skip:
		st.Skip++
	case mb.Intra:
		st.Intra++
	case mb.Shape == 0:
		st.Inter16++
	default:
		st.InterSplit++
	}
	if !mb.Skip && !mb.Intra {
		for pi := range partRects[mb.Shape] {
			switch mb.Parts[pi].Dir {
			case 1:
				st.L0++
			case 2:
				st.L1++
			default:
				st.Bi++
			}
		}
	}
}
