package tls13

import (
	"crypto/hmac"
	"hash"
)

// hkdfExtract is HKDF-Extract (RFC 5869 §2.2).
func hkdfExtract(h func() hash.Hash, salt, ikm []byte) []byte {
	if salt == nil {
		salt = make([]byte, h().Size())
	}
	m := hmac.New(h, salt)
	m.Write(ikm)
	return m.Sum(nil)
}

// hkdfExpand is HKDF-Expand (RFC 5869 §2.3).
func hkdfExpand(h func() hash.Hash, prk, info []byte, n int) []byte {
	out := make([]byte, 0, n)
	var t []byte
	for i := byte(1); len(out) < n; i++ {
		m := hmac.New(h, prk)
		m.Write(t)
		m.Write(info)
		m.Write([]byte{i})
		t = m.Sum(nil)
		out = append(out, t...)
	}
	return out[:n]
}

// hkdfExpandLabel is HKDF-Expand-Label (RFC 8446 §7.1).
func hkdfExpandLabel(h func() hash.Hash, secret []byte, label string, context []byte, n int) []byte {
	var b builder
	b.u16(uint16(n))
	b.vec8(func(b *builder) { b.raw([]byte("tls13 " + label)) })
	b.vec8(func(b *builder) { b.raw(context) })
	return hkdfExpand(h, secret, b.b, n)
}

// deriveSecret is Derive-Secret(Secret, Label, Messages) given an already-hashed transcript.
func deriveSecret(h func() hash.Hash, secret []byte, label string, transcriptHash []byte) []byte {
	return hkdfExpandLabel(h, secret, label, transcriptHash, h().Size())
}
