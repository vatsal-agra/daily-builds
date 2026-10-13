package tls13

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/ed25519"
	"crypto/elliptic"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/sha512"
	"fmt"
	"io"
)

// Signature schemes supported for CertificateVerify.
const (
	ECDSAWithP256AndSHA256 uint16 = 0x0403
	ECDSAWithP384AndSHA384 uint16 = 0x0503
	PSSWithSHA256          uint16 = 0x0804
	PSSWithSHA384          uint16 = 0x0805
	PSSWithSHA512          uint16 = 0x0806
	Ed25519                uint16 = 0x0807
)

var supportedSigAlgs = []uint16{
	Ed25519, ECDSAWithP256AndSHA256, ECDSAWithP384AndSHA384, PSSWithSHA256, PSSWithSHA384, PSSWithSHA512,
}

// SigAlgName names a signature scheme.
func SigAlgName(a uint16) string {
	switch a {
	case ECDSAWithP256AndSHA256:
		return "ecdsa_secp256r1_sha256"
	case ECDSAWithP384AndSHA384:
		return "ecdsa_secp384r1_sha384"
	case PSSWithSHA256:
		return "rsa_pss_rsae_sha256"
	case PSSWithSHA384:
		return "rsa_pss_rsae_sha384"
	case PSSWithSHA512:
		return "rsa_pss_rsae_sha512"
	case Ed25519:
		return "ed25519"
	}
	return fmt.Sprintf("sigalg(0x%04x)", a)
}

func sigHash(a uint16) crypto.Hash {
	switch a {
	case ECDSAWithP256AndSHA256, PSSWithSHA256:
		return crypto.SHA256
	case ECDSAWithP384AndSHA384, PSSWithSHA384:
		return crypto.SHA384
	case PSSWithSHA512:
		return crypto.SHA512
	}
	return 0
}

func digest(h crypto.Hash, data []byte) []byte {
	switch h {
	case crypto.SHA256:
		s := sha256.Sum256(data)
		return s[:]
	case crypto.SHA384:
		s := sha512.Sum384(data)
		return s[:]
	case crypto.SHA512:
		s := sha512.Sum512(data)
		return s[:]
	}
	return nil
}

// signedContent is the CertificateVerify input (RFC 8446 §4.4.3).
func signedContent(server bool, transcriptHash []byte) []byte {
	ctx := "TLS 1.3, client CertificateVerify"
	if server {
		ctx = "TLS 1.3, server CertificateVerify"
	}
	out := make([]byte, 0, 64+len(ctx)+1+len(transcriptHash))
	for i := 0; i < 64; i++ {
		out = append(out, 0x20)
	}
	out = append(out, ctx...)
	out = append(out, 0)
	return append(out, transcriptHash...)
}

// candidateSigAlgs lists schemes that a key of this type can produce, in preference order.
func candidateSigAlgs(pub crypto.PublicKey) []uint16 {
	switch k := pub.(type) {
	case ed25519.PublicKey:
		return []uint16{Ed25519}
	case *ecdsa.PublicKey:
		switch k.Curve {
		case elliptic.P256():
			return []uint16{ECDSAWithP256AndSHA256}
		case elliptic.P384():
			return []uint16{ECDSAWithP384AndSHA384}
		}
	case *rsa.PublicKey:
		return []uint16{PSSWithSHA256, PSSWithSHA384, PSSWithSHA512}
	}
	return nil
}

// pickSigAlg chooses a scheme usable with pub that the peer advertised.
func pickSigAlg(pub crypto.PublicKey, peer []uint16) (uint16, bool) {
	for _, c := range candidateSigAlgs(pub) {
		for _, p := range peer {
			if c == p {
				return c, true
			}
		}
	}
	return 0, false
}

func signCertVerify(rnd io.Reader, key crypto.Signer, alg uint16, content []byte) ([]byte, error) {
	switch alg {
	case Ed25519:
		return key.Sign(rnd, content, crypto.Hash(0))
	case ECDSAWithP256AndSHA256, ECDSAWithP384AndSHA384:
		h := sigHash(alg)
		return key.Sign(rnd, digest(h, content), h)
	case PSSWithSHA256, PSSWithSHA384, PSSWithSHA512:
		h := sigHash(alg)
		return key.Sign(rnd, digest(h, content), &rsa.PSSOptions{SaltLength: rsa.PSSSaltLengthEqualsHash, Hash: h})
	}
	return nil, fmt.Errorf("tls13: cannot sign with scheme 0x%04x", alg)
}

func verifyCertVerify(pub crypto.PublicKey, alg uint16, content, sig []byte) error {
	ok := false
	for _, c := range candidateSigAlgs(pub) {
		if c == alg {
			ok = true
		}
	}
	if !ok {
		return fail(AlertIllegalParameter, "signature scheme %s does not match the certificate's key type", SigAlgName(alg))
	}
	bad := fail(AlertDecryptError, "CertificateVerify signature (%s) is invalid", SigAlgName(alg))
	switch k := pub.(type) {
	case ed25519.PublicKey:
		if !ed25519.Verify(k, content, sig) {
			return bad
		}
	case *ecdsa.PublicKey:
		if !ecdsa.VerifyASN1(k, digest(sigHash(alg), content), sig) {
			return bad
		}
	case *rsa.PublicKey:
		if k.N.BitLen() < 2048 {
			return fail(AlertInsufficientSecurity, "RSA key of %d bits is too small", k.N.BitLen())
		}
		h := sigHash(alg)
		if rsa.VerifyPSS(k, h, digest(h, content), sig, &rsa.PSSOptions{SaltLength: rsa.PSSSaltLengthEqualsHash}) != nil {
			return bad
		}
	}
	return nil
}
