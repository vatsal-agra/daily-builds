package codec

import (
	"encoding/binary"
	"hash/crc32"
	"math/rand"
	"strings"
	"testing"
	"time"
)

// fixCRC recomputes frame checksums so that payload mutations reach the
// range decoder / syntax layer instead of being rejected by the CRC.
func fixCRC(b []byte) {
	pos := hdrSize
	for pos+frameHdrLen <= len(b) {
		plen := int(binary.LittleEndian.Uint32(b[pos+8:]))
		if plen < 0 || pos+frameHdrLen+plen > len(b) {
			return
		}
		pay := b[pos+frameHdrLen : pos+frameHdrLen+plen]
		binary.LittleEndian.PutUint32(b[pos+12:], crc32.ChecksumIEEE(pay))
		pos += frameHdrLen + plen
	}
}

// Corrupt streams must produce an error (or a decode), never a panic or a hang.
func TestFuzzDecoderNoPanic(t *testing.T) {
	v := gen(t, "mixed", 64, 48, 8)
	p := DefaultParams()
	p.BFrames = 1
	r, err := Encode(v, p)
	if err != nil {
		t.Fatal(err)
	}
	rng := rand.New(rand.NewSource(1))
	start := time.Now()
	var errs, oks int
	for it := 0; it < 3000; it++ {
		b := append([]byte(nil), r.Stream...)
		switch it % 4 {
		case 0: // flip payload bytes, fix CRC
			for k := 0; k < 1+rng.Intn(4); k++ {
				b[hdrSize+frameHdrLen+rng.Intn(len(b)-hdrSize-frameHdrLen)] ^= byte(1 << uint(rng.Intn(8)))
			}
			fixCRC(b)
		case 1: // random header corruption
			b[rng.Intn(hdrSize+frameHdrLen)] = byte(rng.Intn(256))
		case 2: // truncate
			b = b[:rng.Intn(len(b))]
		case 3: // random garbage in the middle, fix CRC
			i := hdrSize + frameHdrLen + rng.Intn(len(b)-hdrSize-frameHdrLen)
			for k := i; k < len(b) && k < i+16; k++ {
				b[k] = byte(rng.Intn(256))
			}
			fixCRC(b)
		}
		_, _, err := decodeNoRecover(b)
		if err != nil {
			errs++
			if strings.Contains(err.Error(), "internal check failed") {
				t.Fatalf("iteration %d: decoder hit an internal panic instead of a clean error: %v", it, err)
			}
		} else {
			oks++
		}
	}
	if time.Since(start) > 60*time.Second {
		t.Fatalf("fuzzing too slow: %v (possible hang)", time.Since(start))
	}
	t.Logf("%d rejected, %d decoded (mutation landed in don't-care bits)", errs, oks)
}

func TestY4MRejects(t *testing.T) {
	bad := map[string]string{
		"nosig":   "NOTY4M W16 H16\n",
		"10bit":   "YUV4MPEG2 W16 H16 F30:1 C420p10\n",
		"422":     "YUV4MPEG2 W16 H16 F30:1 C422\n",
		"tiny":    "YUV4MPEG2 W4 H4 F30:1\n",
		"huge":    "YUV4MPEG2 W999999 H999999 F30:1\n",
		"interl":  "YUV4MPEG2 W16 H16 F30:1 It\n",
		"noframe": "YUV4MPEG2 W16 H16 F30:1\n",
		"trunc":   "YUV4MPEG2 W16 H16 F30:1\nFRAME\nabc",
	}
	for name, s := range bad {
		body := strings.Repeat("x", 16*16*3/2)
		if name == "10bit" || name == "422" || name == "interl" {
			s += "FRAME\n" + body // a complete frame: only the tag may cause the error
		}
		if _, err := ReadY4M(strings.NewReader(s)); err == nil {
			t.Errorf("%s: expected an error", name)
		}
	}
}

// A hostile 4096x4096 header with no payload must fail fast.
func TestHugeEmptyStream(t *testing.T) {
	b := putHeader(streamHeader{4096, 4096, 30, 1, 1 << 20})
	b = append(b, putFrameHeader(FrameI, false, 28, 0, 0, nil)...)
	start := time.Now()
	if _, _, err := Decode(b); err == nil {
		t.Fatal("expected error")
	}
	if time.Since(start) > 3*time.Second {
		t.Fatalf("took %v", time.Since(start))
	}
}

func cutsOf(t *testing.T, preset string, n int) []int {
	t.Helper()
	v := gen(t, preset, 96, 80, n)
	var out []int
	for i, c := range detectCuts(v) {
		if c {
			out = append(out, i)
		}
	}
	return out
}

// Review finding: the first cut detector used a plain frame difference and
// flagged every frame of a fast scroll. Scene-cut detection must fire at the
// real cut and nowhere else, whatever the motion or noise level.
func TestSceneCutDetection(t *testing.T) {
	if c := cutsOf(t, "cut", 20); len(c) != 1 || c[0] != 10 {
		t.Errorf("cut preset: want exactly [10], got %v", c)
	}
	for _, pre := range []string{"pan", "objects", "mixed", "noise", "zoom"} {
		if c := cutsOf(t, pre, 20); len(c) != 0 {
			t.Errorf("%s: false scene cuts at %v", pre, c)
		}
	}
	// vertical scroll of a hard-edged binary pattern: large raw difference, perfectly predictable
	v := gen(t, "pan", 96, 96, 12)
	for f, fr := range v.Frames {
		for y := 0; y < 96; y++ {
			for x := 0; x < 96; x++ {
				val := uint8(0)
				if hash2(x, y+f, 5)&1 == 1 {
					val = 255
				}
				fr.Y.Pix[fr.Y.idx(x, y)] = val
			}
		}
	}
	for i, c := range detectCuts(v) {
		if c {
			t.Errorf("binary scroll: false cut at %d", i)
		}
	}
}
