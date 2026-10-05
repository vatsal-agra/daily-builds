// Package wavio reads and writes RIFF/WAVE files.
package wavio

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"os"
)

// Decode parses a WAV byte slice into mono float samples in [-1,1] plus the sample rate.
// Multi-channel audio is averaged to mono.
func Decode(b []byte) ([]float64, int, error) {
	if len(b) < 12 || string(b[0:4]) != "RIFF" || string(b[8:12]) != "WAVE" {
		return nil, 0, errors.New("not a RIFF/WAVE file")
	}
	var (
		format, channels, bits, rate int
		haveFmt                      bool
		data                         []byte
	)
	pos := 12
	for pos+8 <= len(b) {
		id := string(b[pos : pos+4])
		size := int(binary.LittleEndian.Uint32(b[pos+4:]))
		body := pos + 8
		end := body + size
		if end > len(b) {
			end = len(b) // tolerate truncated final chunk
		}
		switch id {
		case "fmt ":
			if end-body < 16 {
				return nil, 0, errors.New("short fmt chunk")
			}
			format = int(binary.LittleEndian.Uint16(b[body:]))
			channels = int(binary.LittleEndian.Uint16(b[body+2:]))
			rate = int(binary.LittleEndian.Uint32(b[body+4:]))
			bits = int(binary.LittleEndian.Uint16(b[body+14:]))
			if format == 0xFFFE && end-body >= 26 { // WAVE_FORMAT_EXTENSIBLE
				format = int(binary.LittleEndian.Uint16(b[body+24:]))
			}
			haveFmt = true
		case "data":
			data = b[body:end]
		}
		pos = body + size + size&1
	}
	if !haveFmt || data == nil {
		return nil, 0, errors.New("missing fmt or data chunk")
	}
	if channels < 1 || rate < 1 {
		return nil, 0, errors.New("invalid fmt chunk")
	}
	if format != 1 && format != 3 {
		return nil, 0, fmt.Errorf("unsupported WAV format tag %d (need PCM or float)", format)
	}
	bps := bits / 8
	if bits%8 != 0 || bps < 1 || (format == 1 && bps > 4) || (format == 3 && bps != 4 && bps != 8) {
		return nil, 0, fmt.Errorf("unsupported bit depth %d", bits)
	}
	frames := len(data) / (bps * channels)
	out := make([]float64, frames)
	for i := 0; i < frames; i++ {
		var sum float64
		for c := 0; c < channels; c++ {
			o := (i*channels + c) * bps
			sum += sample(data[o:o+bps], format, bps)
		}
		out[i] = sum / float64(channels)
	}
	return out, rate, nil
}

func sample(p []byte, format, bps int) float64 {
	if format == 3 {
		if bps == 4 {
			return float64(math.Float32frombits(binary.LittleEndian.Uint32(p)))
		}
		return math.Float64frombits(binary.LittleEndian.Uint64(p))
	}
	switch bps {
	case 1:
		return (float64(p[0]) - 128) / 128
	case 2:
		return float64(int16(binary.LittleEndian.Uint16(p))) / 32768
	case 3:
		v := int32(p[0]) | int32(p[1])<<8 | int32(p[2])<<16
		if v&0x800000 != 0 {
			v |= ^0xFFFFFF
		}
		return float64(v) / 8388608
	default:
		return float64(int32(binary.LittleEndian.Uint32(p))) / 2147483648
	}
}

// Encode serialises mono samples as 16-bit PCM, hard-clipping to [-1,1].
func Encode(x []float64, rate int) []byte {
	n := len(x) * 2
	b := make([]byte, 44+n)
	copy(b[0:], "RIFF")
	binary.LittleEndian.PutUint32(b[4:], uint32(36+n))
	copy(b[8:], "WAVEfmt ")
	binary.LittleEndian.PutUint32(b[16:], 16)
	binary.LittleEndian.PutUint16(b[20:], 1)
	binary.LittleEndian.PutUint16(b[22:], 1)
	binary.LittleEndian.PutUint32(b[24:], uint32(rate))
	binary.LittleEndian.PutUint32(b[28:], uint32(rate*2))
	binary.LittleEndian.PutUint16(b[32:], 2)
	binary.LittleEndian.PutUint16(b[34:], 16)
	copy(b[36:], "data")
	binary.LittleEndian.PutUint32(b[40:], uint32(n))
	for i, v := range x {
		if v > 1 {
			v = 1
		} else if v < -1 {
			v = -1
		}
		binary.LittleEndian.PutUint16(b[44+2*i:], uint16(int16(math.Round(v*32767))))
	}
	return b
}

// Read loads a WAV file from disk.
func Read(path string) ([]float64, int, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, 0, err
	}
	x, r, err := Decode(b)
	if err != nil {
		return nil, 0, fmt.Errorf("%s: %w", path, err)
	}
	return x, r, nil
}

// Write stores mono samples as a 16-bit WAV file.
func Write(path string, x []float64, rate int) error {
	return os.WriteFile(path, Encode(x, rate), 0o644)
}
