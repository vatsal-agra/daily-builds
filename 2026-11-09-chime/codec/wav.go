package codec

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math"
)

// Audio is de-interleaved floating point PCM in the 16-bit integer range
// (full scale = ±32768).
type Audio struct {
	Rate int
	Ch   [][]float64
}

// Frames returns the number of sample frames.
func (a *Audio) Frames() int {
	if len(a.Ch) == 0 {
		return 0
	}
	return len(a.Ch[0])
}

// ReadWAV parses a RIFF/WAVE file (PCM 8/16/24/32-bit or float32; 1 or 2 channels).
func ReadWAV(data []byte) (*Audio, error) {
	if len(data) < 12 || string(data[0:4]) != "RIFF" || string(data[8:12]) != "WAVE" {
		return nil, errors.New("wav: not a RIFF/WAVE file")
	}
	pos := 12
	var fmtFound bool
	var format, ch, bits, rate, align int
	var pcm []byte
	for pos+8 <= len(data) {
		id := string(data[pos : pos+4])
		sz := int(binary.LittleEndian.Uint32(data[pos+4:]))
		body := pos + 8
		end := body + sz
		if end > len(data) || end < body {
			if id == "data" { // tolerate truncated/streamed files
				end = len(data)
			} else {
				return nil, fmt.Errorf("wav: chunk %q overruns file", id)
			}
		}
		switch id {
		case "fmt ":
			if sz < 16 {
				return nil, errors.New("wav: short fmt chunk")
			}
			format = int(binary.LittleEndian.Uint16(data[body:]))
			ch = int(binary.LittleEndian.Uint16(data[body+2:]))
			rate = int(binary.LittleEndian.Uint32(data[body+4:]))
			align = int(binary.LittleEndian.Uint16(data[body+12:]))
			bits = int(binary.LittleEndian.Uint16(data[body+14:]))
			if format == 0xFFFE && sz >= 26 { // WAVE_FORMAT_EXTENSIBLE
				format = int(binary.LittleEndian.Uint16(data[body+24:]))
			}
			fmtFound = true
		case "data":
			pcm = data[body:end]
		}
		pos = end + (sz & 1)
		if pcm != nil && fmtFound {
			break
		}
	}
	if !fmtFound {
		return nil, errors.New("wav: missing fmt chunk")
	}
	if pcm == nil {
		return nil, errors.New("wav: missing data chunk")
	}
	if ch < 1 || ch > 2 {
		return nil, fmt.Errorf("wav: %d channels unsupported (need 1 or 2)", ch)
	}
	if rate < 8000 || rate > 192000 {
		return nil, fmt.Errorf("wav: sample rate %d out of range", rate)
	}
	bps := bits / 8
	if bits%8 != 0 || bps < 1 || bps > 4 || align != bps*ch {
		return nil, fmt.Errorf("wav: unsupported sample layout (%d bits, align %d)", bits, align)
	}
	if !((format == 1 && bits >= 8) || (format == 3 && bits == 32)) {
		return nil, fmt.Errorf("wav: unsupported format tag %d/%d bits", format, bits)
	}
	n := len(pcm) / align
	a := &Audio{Rate: rate, Ch: make([][]float64, ch)}
	for c := range a.Ch {
		a.Ch[c] = make([]float64, n)
	}
	for i := 0; i < n; i++ {
		for c := 0; c < ch; c++ {
			p := pcm[i*align+c*bps:]
			var v float64
			switch {
			case format == 3:
				f := float64(math.Float32frombits(binary.LittleEndian.Uint32(p)))
				if math.IsNaN(f) || math.IsInf(f, 0) {
					return nil, fmt.Errorf("wav: non-finite float sample at frame %d", i)
				}
				v = math.Max(-32768, math.Min(32767, f*32768)) // hard-clip beyond full scale
			case bits == 8:
				v = (float64(p[0]) - 128) * 256
			case bits == 16:
				v = float64(int16(binary.LittleEndian.Uint16(p)))
			case bits == 24:
				x := int32(p[0]) | int32(p[1])<<8 | int32(int8(p[2]))<<16
				v = float64(x) / 256
			case bits == 32:
				v = float64(int32(binary.LittleEndian.Uint32(p))) / 65536
			}
			a.Ch[c][i] = v
		}
	}
	return a, nil
}

func clip16(v float64) int16 {
	r := math.Round(v)
	if r > 32767 {
		return 32767
	}
	if r < -32768 {
		return -32768
	}
	return int16(r)
}

// WriteWAV writes 16-bit PCM with hard clipping.
func WriteWAV(w io.Writer, a *Audio) error {
	ch := len(a.Ch)
	n := a.Frames()
	dsz := n * ch * 2
	hdr := make([]byte, 44)
	copy(hdr[0:], "RIFF")
	binary.LittleEndian.PutUint32(hdr[4:], uint32(36+dsz))
	copy(hdr[8:], "WAVEfmt ")
	binary.LittleEndian.PutUint32(hdr[16:], 16)
	binary.LittleEndian.PutUint16(hdr[20:], 1)
	binary.LittleEndian.PutUint16(hdr[22:], uint16(ch))
	binary.LittleEndian.PutUint32(hdr[24:], uint32(a.Rate))
	binary.LittleEndian.PutUint32(hdr[28:], uint32(a.Rate*ch*2))
	binary.LittleEndian.PutUint16(hdr[32:], uint16(ch*2))
	binary.LittleEndian.PutUint16(hdr[34:], 16)
	copy(hdr[36:], "data")
	binary.LittleEndian.PutUint32(hdr[40:], uint32(dsz))
	buf := make([]byte, 0, 44+dsz)
	buf = append(buf, hdr...)
	for i := 0; i < n; i++ {
		for c := 0; c < ch; c++ {
			buf = binary.LittleEndian.AppendUint16(buf, uint16(clip16(a.Ch[c][i])))
		}
	}
	_, err := w.Write(buf)
	return err
}
