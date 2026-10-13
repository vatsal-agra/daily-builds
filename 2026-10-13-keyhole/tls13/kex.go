package tls13

import (
	"crypto/ecdh"
	"io"
)

type keyExchange struct {
	group uint16
	priv  *ecdh.PrivateKey
}

func curveFor(g uint16) ecdh.Curve {
	switch g {
	case X25519:
		return ecdh.X25519()
	case CurveP256:
		return ecdh.P256()
	}
	return nil
}

func newKeyExchange(rnd io.Reader, group uint16) (*keyExchange, error) {
	cv := curveFor(group)
	if cv == nil {
		return nil, fail(AlertInternalError, "unsupported group %d", group)
	}
	k, err := cv.GenerateKey(rnd)
	if err != nil {
		return nil, err
	}
	return &keyExchange{group, k}, nil
}

func (k *keyExchange) public() []byte { return k.priv.PublicKey().Bytes() }

// shared computes the ECDHE secret. Invalid points and (for X25519) all-zero outputs are rejected
// as illegal_parameter, as RFC 8446 §7.4.2 requires.
func (k *keyExchange) shared(peer []byte) ([]byte, error) {
	pub, err := curveFor(k.group).NewPublicKey(peer)
	if err != nil {
		return nil, fail(AlertIllegalParameter, "invalid %s key share: %v", GroupName(k.group), err)
	}
	s, err := k.priv.ECDH(pub)
	if err != nil {
		return nil, fail(AlertIllegalParameter, "bad %s key share: %v", GroupName(k.group), err)
	}
	return s, nil
}

// validPeerShare reports whether peer is a well-formed public value for group (used for early rejection).
func validPeerShare(group uint16, peer []byte) bool {
	cv := curveFor(group)
	if cv == nil {
		return false
	}
	_, err := cv.NewPublicKey(peer)
	return err == nil
}
