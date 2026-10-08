// Package wal is an append-only, CRC-framed write-ahead log.
//
// Frame: [u32 payload length][u32 CRC32-C of payload][payload].
// On Open the log is replayed; a torn or corrupt tail (the normal result of a
// crash mid-write) is detected by length/CRC and truncated away so later
// appends start from a clean boundary.
package wal

import (
	"bufio"
	"encoding/binary"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
	"os"
)

var table = crc32.MakeTable(crc32.Castagnoli)

const maxRecord = 64 << 20

type WAL struct {
	f    *os.File
	w    *bufio.Writer
	size int64
}

// Open opens (creating if needed) the log at path, calls apply for every
// intact record in order, and truncates any damaged tail. It returns the
// number of bytes of damaged tail that were discarded.
func Open(path string, apply func(rec []byte) error) (*WAL, int64, error) {
	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0o644)
	if err != nil {
		return nil, 0, err
	}
	st, err := f.Stat()
	if err != nil {
		f.Close()
		return nil, 0, err
	}
	r := bufio.NewReaderSize(f, 1<<20)
	var good int64
	var hdr [8]byte
	for {
		if _, err := io.ReadFull(r, hdr[:]); err != nil {
			break // EOF or torn header
		}
		n := binary.LittleEndian.Uint32(hdr[:4])
		sum := binary.LittleEndian.Uint32(hdr[4:])
		if n > maxRecord {
			break
		}
		buf := make([]byte, n)
		if _, err := io.ReadFull(r, buf); err != nil {
			break
		}
		if crc32.Checksum(buf, table) != sum {
			break
		}
		if err := apply(buf); err != nil {
			f.Close()
			return nil, 0, fmt.Errorf("wal: replay at offset %d: %w", good, err)
		}
		good += 8 + int64(n)
	}
	dropped := st.Size() - good
	if dropped > 0 {
		if err := f.Truncate(good); err != nil {
			f.Close()
			return nil, 0, err
		}
	}
	if _, err := f.Seek(good, io.SeekStart); err != nil {
		f.Close()
		return nil, 0, err
	}
	return &WAL{f: f, w: bufio.NewWriterSize(f, 1<<16), size: good}, dropped, nil
}

// Append buffers one record. Call Sync to make it durable.
func (w *WAL) Append(rec []byte) error {
	if len(rec) > maxRecord {
		return errors.New("wal: record too large")
	}
	var hdr [8]byte
	binary.LittleEndian.PutUint32(hdr[:4], uint32(len(rec)))
	binary.LittleEndian.PutUint32(hdr[4:], crc32.Checksum(rec, table))
	if _, err := w.w.Write(hdr[:]); err != nil {
		return err
	}
	if _, err := w.w.Write(rec); err != nil {
		return err
	}
	w.size += 8 + int64(len(rec))
	return nil
}

// Sync flushes buffered records and fsyncs the file.
func (w *WAL) Sync() error {
	if err := w.w.Flush(); err != nil {
		return err
	}
	return w.f.Sync()
}

// Size returns the logical size in bytes (including unsynced records).
func (w *WAL) Size() int64 { return w.size }

// Reset discards all records (used after the head has been flushed to a block).
func (w *WAL) Reset() error {
	w.w.Reset(w.f)
	if err := w.f.Truncate(0); err != nil {
		return err
	}
	if _, err := w.f.Seek(0, io.SeekStart); err != nil {
		return err
	}
	w.size = 0
	return w.f.Sync()
}

func (w *WAL) Close() error {
	err := w.Sync()
	if cerr := w.f.Close(); err == nil {
		err = cerr
	}
	return err
}
