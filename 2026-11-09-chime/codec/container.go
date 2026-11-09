package codec

import (
	"encoding/binary"
	"errors"
	"fmt"
	"hash/crc32"
)

// .chm container:
//
//	 0  "CHM1"
//	 4  flags: bit0 noise-fill
//	 5  channels
//	 6  sample rate  u32
//	10  frames (samples per channel) u32
//	14  payload length u32
//	18  CRC32(payload) u32
//	22  band-layout fingerprint u32 (guards against FP differences between platforms)
//	26  payload (range coded)
const headerSize = 26

// layoutFingerprint hashes the band edges the decoder will derive for this rate.
func layoutFingerprint(rate int) uint32 {
	h := crc32.NewIEEE()
	var b [4]byte
	for _, m := range []int{LongM, ShortM} {
		for _, e := range LayoutFor(m, rate).Edges {
			binary.LittleEndian.PutUint32(b[:], uint32(e))
			h.Write(b[:])
		}
	}
	return h.Sum32()
}

func packContainer(a *Audio, an *Analysis, payload []byte) []byte {
	h := make([]byte, headerSize, headerSize+len(payload))
	copy(h, "CHM1")
	if an.p.NoiseFill {
		h[4] |= 1
	}
	h[5] = byte(len(a.Ch))
	binary.LittleEndian.PutUint32(h[6:], uint32(a.Rate))
	binary.LittleEndian.PutUint32(h[10:], uint32(a.Frames()))
	binary.LittleEndian.PutUint32(h[14:], uint32(len(payload)))
	binary.LittleEndian.PutUint32(h[18:], crc32.ChecksumIEEE(payload))
	binary.LittleEndian.PutUint32(h[22:], layoutFingerprint(a.Rate))
	return append(h, payload...)
}

// Header is the parsed container header.
type Header struct {
	NoiseFill bool
	Channels  int
	Rate      int
	Samples   int
	Payload   []byte
}

// ParseContainer validates a .chm image.
func ParseContainer(b []byte) (*Header, error) {
	if len(b) < headerSize || string(b[:4]) != "CHM1" {
		return nil, errors.New("chm: bad magic / too short")
	}
	h := &Header{
		NoiseFill: b[4]&1 != 0,
		Channels:  int(b[5]),
		Rate:      int(binary.LittleEndian.Uint32(b[6:])),
		Samples:   int(binary.LittleEndian.Uint32(b[10:])),
	}
	if b[4]&^1 != 0 {
		return nil, fmt.Errorf("chm: unknown flags %#x", b[4])
	}
	if h.Channels < 1 || h.Channels > 2 {
		return nil, fmt.Errorf("chm: bad channel count %d", h.Channels)
	}
	if h.Rate < 8000 || h.Rate > 192000 {
		return nil, fmt.Errorf("chm: bad sample rate %d", h.Rate)
	}
	if h.Samples <= 0 || h.Samples > 1<<30 {
		return nil, fmt.Errorf("chm: bad sample count %d", h.Samples)
	}
	plen := int(binary.LittleEndian.Uint32(b[14:]))
	if plen != len(b)-headerSize {
		return nil, fmt.Errorf("chm: payload length %d does not match file (%d)", plen, len(b)-headerSize)
	}
	if binary.LittleEndian.Uint32(b[22:]) != layoutFingerprint(h.Rate) {
		return nil, errors.New("chm: band layout differs from the encoder's (built on a platform with different floating point?)")
	}
	h.Payload = b[headerSize:]
	if crc32.ChecksumIEEE(h.Payload) != binary.LittleEndian.Uint32(b[18:]) {
		return nil, errors.New("chm: CRC mismatch (file is corrupt)")
	}
	return h, nil
}
