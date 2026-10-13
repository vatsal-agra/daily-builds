package tls13

import (
	"crypto/cipher"
	"encoding/binary"
	"io"
)

// Record content types (RFC 8446 §5.1).
const (
	recChangeCipherSpec uint8 = 20
	recAlert            uint8 = 21
	recHandshake        uint8 = 22
	recApplicationData  uint8 = 23
)

const (
	maxPlaintext  = 1 << 14
	maxCiphertext = maxPlaintext + 256
	recHeaderLen  = 5
)

// halfConn is one direction of the record protection state.
type halfConn struct {
	suite  *suite
	aead   cipher.AEAD
	iv     []byte
	secret []byte
	seq    uint64
}

func (h *halfConn) protected() bool { return h.aead != nil }

// setSecret installs traffic keys derived from secret and resets the sequence number.
func (h *halfConn) setSecret(s *suite, secret []byte) error {
	key, iv := s.trafficKeys(secret)
	a, err := s.aead(key)
	if err != nil {
		return err
	}
	h.suite, h.aead, h.iv, h.secret, h.seq = s, a, iv, secret, 0
	return nil
}

func (h *halfConn) nonce() []byte {
	n := make([]byte, len(h.iv))
	copy(n, h.iv)
	var sq [8]byte
	binary.BigEndian.PutUint64(sq[:], h.seq)
	for i := 0; i < 8; i++ {
		n[len(n)-8+i] ^= sq[i]
	}
	return n
}

// seal builds one complete record for content of the given type. pad is the number of zero
// padding bytes appended to the TLSInnerPlaintext when the direction is protected.
func (h *halfConn) seal(typ uint8, data []byte, pad int) []byte {
	if !h.protected() {
		rec := make([]byte, recHeaderLen, recHeaderLen+len(data))
		rec[0], rec[1], rec[2] = typ, 3, 3
		binary.BigEndian.PutUint16(rec[3:], uint16(len(data)))
		return append(rec, data...)
	}
	inner := make([]byte, 0, len(data)+1+pad)
	inner = append(inner, data...)
	inner = append(inner, typ)
	inner = append(inner, make([]byte, pad)...)
	hdr := [recHeaderLen]byte{recApplicationData, 3, 3}
	binary.BigEndian.PutUint16(hdr[3:], uint16(len(inner)+h.aead.Overhead()))
	out := h.aead.Seal(hdr[:], h.nonce(), inner, hdr[:])
	h.seq++
	return out
}

// open decrypts a protected record body and returns the inner content type and payload.
func (h *halfConn) open(hdr [recHeaderLen]byte, body []byte) (uint8, []byte, error) {
	pt, err := h.aead.Open(nil, h.nonce(), body, hdr[:])
	if err != nil {
		return 0, nil, fail(AlertBadRecordMAC, "record authentication failed")
	}
	h.seq++
	// strip zero padding, find content type
	i := len(pt) - 1
	for i >= 0 && pt[i] == 0 {
		i--
	}
	if i < 0 {
		return 0, nil, fail(AlertUnexpectedMessage, "protected record has no content type (all padding)")
	}
	if i > maxPlaintext {
		return 0, nil, fail(AlertRecordOverflow, "decrypted record too large")
	}
	return pt[i], pt[:i], nil
}

// readRawRecord reads one record header+body from r.
func checkRecordHeader(hdr [recHeaderLen]byte) (int, error) {
	n := int(binary.BigEndian.Uint16(hdr[3:]))
	switch hdr[0] {
	case recChangeCipherSpec, recAlert, recHandshake, recApplicationData:
	default:
		return 0, fail(AlertUnexpectedMessage, "unknown record type %d", hdr[0])
	}
	if hdr[1] != 3 {
		return 0, fail(AlertProtocolVersion, "record version %02x%02x is not TLS", hdr[1], hdr[2])
	}
	if n > maxCiphertext {
		return 0, fail(AlertRecordOverflow, "record length %d exceeds limit", n)
	}
	return n, nil
}

func readRawRecord(r io.Reader) (hdr [recHeaderLen]byte, body []byte, err error) {
	if _, err = io.ReadFull(r, hdr[:]); err != nil {
		return
	}
	var n int
	if n, err = checkRecordHeader(hdr); err != nil {
		return
	}
	body = make([]byte, n)
	if _, err = io.ReadFull(r, body); err != nil {
		if err == io.EOF {
			err = io.ErrUnexpectedEOF
		}
	}
	return
}
