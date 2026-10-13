package tls13

import (
	"bytes"
	"encoding/hex"
	"testing"
)

func unhex(t testing.TB, s string) []byte {
	b, err := hex.DecodeString(s)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// Published constants for the PSK-less key schedule (RFC 8448 §3 trace; also the well-known
// "early secret" of every TLS 1.3 handshake without a PSK).
func TestKeyScheduleKnownConstants(t *testing.T) {
	s256 := suiteByID(TLS_AES_128_GCM_SHA256)
	early := s256.earlySecret(nil)
	if got := hex.EncodeToString(early); got != "33ad0a1c607ec03b09e6cd9893680ce210adf300aa1f2660e1b22e10f170f92a" {
		t.Fatalf("SHA-256 early secret = %s", got)
	}
	derived := deriveSecret(s256.hash, early, "derived", s256.sum(nil))
	if got := hex.EncodeToString(derived); got != "6f2615a108c702c5678f54fc9dbab69716c076189c48250cebeac3576c3611ba" {
		t.Fatalf("SHA-256 derived secret = %s", got)
	}
	s384 := suiteByID(TLS_AES_256_GCM_SHA384)
	if got := hex.EncodeToString(s384.earlySecret(nil)); got != "7ee8206f5570023e6dc7519eb1073bc4e791ad37b5c382aa10ba18e2357e716971f9362f2c2fe2a76bfd78dfec4ea9b5" {
		t.Fatalf("SHA-384 early secret = %s", got)
	}
}

// HKDF-SHA256 test case 1 from RFC 5869 Appendix A.1.
func TestHKDFRFC5869(t *testing.T) {
	s := suiteByID(TLS_AES_128_GCM_SHA256)
	ikm := bytes.Repeat([]byte{0x0b}, 22)
	salt := unhex(t, "000102030405060708090a0b0c")
	info := unhex(t, "f0f1f2f3f4f5f6f7f8f9")
	prk := hkdfExtract(s.hash, salt, ikm)
	if got := hex.EncodeToString(prk); got != "077709362c2e32df0ddc3f0dc47bba6390b6c73bb50f9c3122ec844ad7c2b3e5" {
		t.Fatalf("PRK = %s", got)
	}
	okm := hkdfExpand(s.hash, prk, info, 42)
	if got := hex.EncodeToString(okm); got != "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865" {
		t.Fatalf("OKM = %s", got)
	}
}

// The HkdfLabel encoding must match RFC 8446 §7.1 exactly: length || "tls13 "+label || context.
func TestExpandLabelEncoding(t *testing.T) {
	s := suiteByID(TLS_AES_128_GCM_SHA256)
	secret := bytes.Repeat([]byte{7}, 32)
	got := hkdfExpandLabel(s.hash, secret, "key", nil, 16)
	var b builder
	b.u16(16)
	b.u8(9)
	b.raw([]byte("tls13 key"))
	b.u8(0)
	want := hkdfExpand(s.hash, secret, b.b, 16)
	if !bytes.Equal(got, want) {
		t.Fatalf("label encoding differs")
	}
}

func TestRecordSealOpenRoundTripAndTamper(t *testing.T) {
	for _, id := range []uint16{TLS_AES_128_GCM_SHA256, TLS_AES_256_GCM_SHA384, TLS_CHACHA20_POLY1305_SHA256} {
		s := suiteByID(id)
		secret := bytes.Repeat([]byte{byte(id)}, s.hashLen())
		var w, r halfConn
		if err := w.setSecret(s, secret); err != nil {
			t.Fatal(err)
		}
		if err := r.setSecret(s, secret); err != nil {
			t.Fatal(err)
		}
		for i, pad := range []int{0, 5, 100} {
			payload := bytes.Repeat([]byte{byte(i + 1)}, 37*i+1)
			rec := w.seal(recHandshake, payload, pad)
			var hdr [5]byte
			copy(hdr[:], rec)
			typ, got, err := r.open(hdr, rec[5:])
			if err != nil || typ != recHandshake || !bytes.Equal(got, payload) {
				t.Fatalf("%s: round trip failed: typ=%d err=%v", s.name, typ, err)
			}
		}
		// out-of-order / replayed record must fail: sequence numbers are part of the nonce
		rec := w.seal(recApplicationData, []byte("x"), 0)
		var hdr [5]byte
		copy(hdr[:], rec)
		r.seq++ // reader skips one
		if _, _, err := r.open(hdr, rec[5:]); err == nil {
			t.Fatalf("%s: record accepted under wrong sequence number", s.name)
		}
		r.seq--
		bad := append([]byte(nil), rec...)
		bad[7] ^= 0x40
		if _, _, err := r.open(hdr, bad[5:]); err == nil {
			t.Fatalf("%s: tampered record accepted", s.name)
		}
	}
}

func TestNonceConstruction(t *testing.T) {
	h := halfConn{iv: unhex(t, "00112233445566778899aabb"), seq: 0x0102030405060708}
	if got := hex.EncodeToString(h.nonce()); got != "00112233455765738d9fadb3" {
		// iv XOR (4 zero bytes || seq big-endian)
		t.Fatalf("nonce = %s", got)
	}
}
