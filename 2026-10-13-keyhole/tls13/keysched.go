package tls13

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/sha512"
	"crypto/subtle"
	"hash"
)

// Cipher suite identifiers (RFC 8446 Appendix B.4).
const (
	TLS_AES_128_GCM_SHA256       uint16 = 0x1301
	TLS_AES_256_GCM_SHA384       uint16 = 0x1302
	TLS_CHACHA20_POLY1305_SHA256 uint16 = 0x1303
)

type suite struct {
	id     uint16
	name   string
	keyLen int
	hash   func() hash.Hash
	aead   func(key []byte) (cipher.AEAD, error)
}

func aesGCM(key []byte) (cipher.AEAD, error) {
	b, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(b)
}

func chachaAEAD(key []byte) (cipher.AEAD, error) { return newChaCha20Poly1305(key) }

var suites = []*suite{
	{TLS_AES_128_GCM_SHA256, "TLS_AES_128_GCM_SHA256", 16, sha256.New, aesGCM},
	{TLS_AES_256_GCM_SHA384, "TLS_AES_256_GCM_SHA384", 32, sha512.New384, aesGCM},
	{TLS_CHACHA20_POLY1305_SHA256, "TLS_CHACHA20_POLY1305_SHA256", 32, sha256.New, chachaAEAD},
}

func suiteByID(id uint16) *suite {
	for _, s := range suites {
		if s.id == id {
			return s
		}
	}
	return nil
}

// SuiteName returns the IANA name of a cipher suite id.
func SuiteName(id uint16) string {
	if s := suiteByID(id); s != nil {
		return s.name
	}
	return "unknown"
}

func (s *suite) hashLen() int { return s.hash().Size() }

func (s *suite) sum(data []byte) []byte {
	h := s.hash()
	h.Write(data)
	return h.Sum(nil)
}

func (s *suite) zeros() []byte { return make([]byte, s.hashLen()) }

// earlySecret = HKDF-Extract(0, PSK) (PSK = 0^Hash.length when absent).
func (s *suite) earlySecret(psk []byte) []byte {
	if psk == nil {
		psk = s.zeros()
	}
	return hkdfExtract(s.hash, nil, psk)
}

func (s *suite) handshakeSecret(early, ecdhe []byte) []byte {
	derived := deriveSecret(s.hash, early, "derived", s.sum(nil))
	return hkdfExtract(s.hash, derived, ecdhe)
}

func (s *suite) masterSecret(handshake []byte) []byte {
	derived := deriveSecret(s.hash, handshake, "derived", s.sum(nil))
	return hkdfExtract(s.hash, derived, s.zeros())
}

func (s *suite) trafficKeys(secret []byte) (key, iv []byte) {
	return hkdfExpandLabel(s.hash, secret, "key", nil, s.keyLen), hkdfExpandLabel(s.hash, secret, "iv", nil, 12)
}

func (s *suite) nextTrafficSecret(secret []byte) []byte {
	return hkdfExpandLabel(s.hash, secret, "traffic upd", nil, s.hashLen())
}

// finishedMAC is HMAC(finished_key, transcriptHash) where finished_key derives from baseKey.
func (s *suite) finishedMAC(baseKey, transcriptHash []byte) []byte {
	fk := hkdfExpandLabel(s.hash, baseKey, "finished", nil, s.hashLen())
	m := hmac.New(s.hash, fk)
	m.Write(transcriptHash)
	return m.Sum(nil)
}

func (s *suite) resumptionPSK(resMaster, nonce []byte) []byte {
	return hkdfExpandLabel(s.hash, resMaster, "resumption", nonce, s.hashLen())
}

// exporter implements RFC 8446 §7.5.
func (s *suite) exporter(exporterMaster []byte, label string, context []byte, n int) []byte {
	derived := deriveSecret(s.hash, exporterMaster, label, s.sum(nil))
	return hkdfExpandLabel(s.hash, derived, "exporter", s.sum(context), n)
}

func ctEqual(a, b []byte) bool { return subtle.ConstantTimeCompare(a, b) == 1 }
