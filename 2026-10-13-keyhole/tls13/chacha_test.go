package tls13

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"
)

// Vectors in testdata/chacha_vectors.json were produced by an independent implementation
// (Python `cryptography`/OpenSSL) via testdata/gen_chacha.py.
func TestChaCha20Poly1305Vectors(t *testing.T) {
	raw, err := os.ReadFile("testdata/chacha_vectors.json")
	if err != nil {
		t.Fatal(err)
	}
	var vs []struct{ Key, Nonce, Pt, Aad, Ct string }
	if err := json.Unmarshal(raw, &vs); err != nil {
		t.Fatal(err)
	}
	if len(vs) < 100 {
		t.Fatalf("only %d vectors", len(vs))
	}
	for i, v := range vs {
		key, _ := hex.DecodeString(v.Key)
		nonce, _ := hex.DecodeString(v.Nonce)
		pt, _ := hex.DecodeString(v.Pt)
		aad, _ := hex.DecodeString(v.Aad)
		ct, _ := hex.DecodeString(v.Ct)
		a, _ := newChaCha20Poly1305(key)
		if got := a.Seal(nil, nonce, pt, aad); !bytes.Equal(got, ct) {
			t.Fatalf("vector %d: seal mismatch\n got %x\nwant %x", i, got, ct)
		}
		got, err := a.Open(nil, nonce, ct, aad)
		if err != nil || !bytes.Equal(got, pt) {
			t.Fatalf("vector %d: open failed: %v", i, err)
		}
		if len(ct) > 0 {
			bad := append([]byte(nil), ct...)
			bad[len(bad)/2] ^= 1
			if _, err := a.Open(nil, nonce, bad, aad); err == nil {
				t.Fatalf("vector %d: tampered ciphertext accepted", i)
			}
		}
	}
}

// RFC 8439 §2.8.2 AEAD test vector.
func TestChaCha20Poly1305RFC8439(t *testing.T) {
	key, _ := hex.DecodeString("808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f")
	nonce, _ := hex.DecodeString("070000004041424344454647")
	aad, _ := hex.DecodeString("50515253c0c1c2c3c4c5c6c7")
	pt := []byte("Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it.")
	want := "d31a8d34648e60db7b86afbc53ef7ec2a4aded51296e08fea9e2b5a736ee62d63dbea45e8ca9671282fafb69da92728b1a71de0a9e060b2905d6a5b67ecd3b3692ddbd7f2d778b8c9803aee328091b58fab324e4fad675945585808b4831d7bc3ff4def08e4b7a9de576d26586cec64b61161ae10b594f09e26a7e902ecbd0600691"
	a, _ := newChaCha20Poly1305(key)
	if got := hex.EncodeToString(a.Seal(nil, nonce, pt, aad)); got != want {
		t.Fatalf("got %s\nwant %s", got, want)
	}
}
