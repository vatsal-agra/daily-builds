package codec

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
)

// Video is a decoded sequence in display order.
type Video struct {
	Width, Height  int
	FPSNum, FPSDen int
	Frames         []*Frame
}

// FPS returns the frame rate as a float.
func (v *Video) FPS() float64 {
	if v.FPSDen == 0 {
		return 25
	}
	return float64(v.FPSNum) / float64(v.FPSDen)
}

// maxDim bounds picture size so a hostile header cannot demand gigabytes.
const maxDim = 4096

// ReadY4M parses a YUV4MPEG2 stream (4:2:0 only).
func ReadY4M(r io.Reader) (*Video, error) {
	br := bufio.NewReaderSize(r, 1<<20)
	line, err := br.ReadString('\n')
	if err != nil {
		return nil, fmt.Errorf("y4m: reading header: %w", err)
	}
	fields := strings.Fields(strings.TrimSpace(line))
	if len(fields) == 0 || fields[0] != "YUV4MPEG2" {
		return nil, errors.New("y4m: missing YUV4MPEG2 signature")
	}
	v := &Video{FPSNum: 25, FPSDen: 1}
	for _, f := range fields[1:] {
		if len(f) < 2 {
			continue
		}
		val := f[1:]
		switch f[0] {
		case 'W':
			v.Width, _ = strconv.Atoi(val)
		case 'H':
			v.Height, _ = strconv.Atoi(val)
		case 'F':
			p := strings.SplitN(val, ":", 2)
			if len(p) == 2 {
				n, e1 := strconv.Atoi(p[0])
				d, e2 := strconv.Atoi(p[1])
				if e1 == nil && e2 == nil && n > 0 && d > 0 {
					v.FPSNum, v.FPSDen = n, d
				}
			}
		case 'C':
			if !strings.HasPrefix(val, "420") {
				return nil, fmt.Errorf("y4m: unsupported chroma format C%s (only 4:2:0)", val)
			}
		case 'I':
			if val != "p" && val != "?" {
				return nil, fmt.Errorf("y4m: interlaced input (I%s) not supported", val)
			}
		}
	}
	if v.Width < 16 || v.Height < 16 || v.Width > maxDim || v.Height > maxDim {
		return nil, fmt.Errorf("y4m: bad dimensions %dx%d (need 16..%d)", v.Width, v.Height, maxDim)
	}
	cw, ch := (v.Width+1)/2, (v.Height+1)/2
	size := v.Width*v.Height + 2*cw*ch
	buf := make([]byte, size)
	for {
		hdr, err := br.ReadString('\n')
		if err == io.EOF && hdr == "" {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("y4m: frame %d header: %w", len(v.Frames), err)
		}
		if !strings.HasPrefix(hdr, "FRAME") {
			return nil, fmt.Errorf("y4m: frame %d: expected FRAME marker", len(v.Frames))
		}
		if _, err := io.ReadFull(br, buf); err != nil {
			return nil, fmt.Errorf("y4m: frame %d truncated: %w", len(v.Frames), err)
		}
		v.Frames = append(v.Frames, FromPlanar(v.Width, v.Height, buf))
	}
	if len(v.Frames) == 0 {
		return nil, errors.New("y4m: no frames")
	}
	return v, nil
}

// WriteY4M writes the sequence as YUV4MPEG2 4:2:0.
func WriteY4M(w io.Writer, v *Video) error {
	bw := bufio.NewWriterSize(w, 1<<20)
	fmt.Fprintf(bw, "YUV4MPEG2 W%d H%d F%d:%d Ip A1:1 C420jpeg\n", v.Width, v.Height, v.FPSNum, v.FPSDen)
	for _, f := range v.Frames {
		bw.WriteString("FRAME\n")
		bw.Write(f.Planar())
	}
	return bw.Flush()
}

// Y4MBytes is a convenience wrapper.
func Y4MBytes(v *Video) []byte {
	var b bytes.Buffer
	_ = WriteY4M(&b, v)
	return b.Bytes()
}
