// Package pki makes throwaway certificate authorities and leaf certificates for tests, demos and
// the keyhole CLI, and reads/writes the PEM files that go with them.
package pki

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/ed25519"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"net"
	"os"
	"time"

	"keyhole/tls13"
)

// CA is a signing certificate authority.
type CA struct {
	Cert *x509.Certificate
	DER  []byte
	Key  crypto.Signer
}

func GenerateKey(kind string) (crypto.Signer, error) {
	switch kind {
	case "", "ecdsa-p256":
		return ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	case "ecdsa-p384":
		return ecdsa.GenerateKey(elliptic.P384(), rand.Reader)
	case "ed25519":
		_, k, err := ed25519.GenerateKey(rand.Reader)
		return k, err
	case "rsa2048":
		return rsa.GenerateKey(rand.Reader, 2048)
	}
	return nil, fmt.Errorf("pki: unknown key type %q (want ecdsa-p256, ecdsa-p384, ed25519, rsa2048)", kind)
}

func serial() *big.Int {
	n, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 120))
	return n.Add(n, big.NewInt(1))
}

// NewCA creates a self-signed CA with the given key type.
func NewCA(name, keyType string) (*CA, error) {
	key, err := GenerateKey(keyType)
	if err != nil {
		return nil, err
	}
	tpl := &x509.Certificate{
		SerialNumber: serial(), Subject: pkix.Name{CommonName: name, Organization: []string{"Keyhole Test PKI"}},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(10 * 365 * 24 * time.Hour),
		IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageCRLSign,
	}
	der, err := x509.CreateCertificate(rand.Reader, tpl, tpl, key.Public(), key)
	if err != nil {
		return nil, err
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		return nil, err
	}
	return &CA{cert, der, key}, nil
}

func (ca *CA) Pool() *x509.CertPool {
	p := x509.NewCertPool()
	p.AddCert(ca.Cert)
	return p
}

// Options controls Issue.
type Options struct {
	CommonName string
	DNSNames   []string
	IPs        []net.IP
	KeyType    string // see GenerateKey
	Client     bool   // client-auth certificate instead of server-auth
	NotBefore  time.Time
	NotAfter   time.Time
	CA         bool // issue an intermediate CA
}

// Issue creates a leaf (or intermediate) certificate signed by ca.
func (ca *CA) Issue(o Options) (*tls13.Certificate, *x509.Certificate, error) {
	key, err := GenerateKey(o.KeyType)
	if err != nil {
		return nil, nil, err
	}
	if o.NotBefore.IsZero() {
		o.NotBefore = time.Now().Add(-time.Hour)
	}
	if o.NotAfter.IsZero() {
		o.NotAfter = time.Now().Add(365 * 24 * time.Hour)
	}
	tpl := &x509.Certificate{
		SerialNumber: serial(), Subject: pkix.Name{CommonName: o.CommonName},
		DNSNames: o.DNSNames, IPAddresses: o.IPs, NotBefore: o.NotBefore, NotAfter: o.NotAfter,
		KeyUsage: x509.KeyUsageDigitalSignature, BasicConstraintsValid: true,
	}
	switch {
	case o.CA:
		tpl.IsCA, tpl.KeyUsage = true, x509.KeyUsageCertSign|x509.KeyUsageDigitalSignature
	case o.Client:
		tpl.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth}
	default:
		tpl.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}
	}
	der, err := x509.CreateCertificate(rand.Reader, tpl, ca.Cert, key.Public(), ca.Key)
	if err != nil {
		return nil, nil, err
	}
	leaf, err := x509.ParseCertificate(der)
	if err != nil {
		return nil, nil, err
	}
	return &tls13.Certificate{Chain: [][]byte{der}, Key: key}, leaf, nil
}

// IssueIntermediate returns a sub-CA signed by ca.
func (ca *CA) IssueIntermediate(name, keyType string) (*CA, error) {
	c, leaf, err := ca.Issue(Options{CommonName: name, KeyType: keyType, CA: true})
	if err != nil {
		return nil, err
	}
	return &CA{leaf, c.Chain[0], c.Key}, nil
}

// ---------- PEM I/O ----------

func EncodeCertPEM(der []byte) []byte {
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
}

func EncodeKeyPEM(k crypto.Signer) ([]byte, error) {
	der, err := x509.MarshalPKCS8PrivateKey(k)
	if err != nil {
		return nil, err
	}
	return pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}), nil
}

// WriteFiles saves a certificate chain and key as PEM.
func WriteFiles(certPath, keyPath string, c *tls13.Certificate) error {
	var out []byte
	for _, d := range c.Chain {
		out = append(out, EncodeCertPEM(d)...)
	}
	if err := os.WriteFile(certPath, out, 0o644); err != nil {
		return err
	}
	kp, err := EncodeKeyPEM(c.Key)
	if err != nil {
		return err
	}
	return os.WriteFile(keyPath, kp, 0o600)
}

// LoadCertificate reads a PEM chain and PKCS#8/PKCS#1/EC private key.
func LoadCertificate(certPath, keyPath string) (*tls13.Certificate, error) {
	cb, err := os.ReadFile(certPath)
	if err != nil {
		return nil, err
	}
	kb, err := os.ReadFile(keyPath)
	if err != nil {
		return nil, err
	}
	c := &tls13.Certificate{}
	for {
		var blk *pem.Block
		blk, cb = pem.Decode(cb)
		if blk == nil {
			break
		}
		if blk.Type == "CERTIFICATE" {
			c.Chain = append(c.Chain, blk.Bytes)
		}
	}
	if len(c.Chain) == 0 {
		return nil, fmt.Errorf("%s: no CERTIFICATE blocks", certPath)
	}
	blk, _ := pem.Decode(kb)
	if blk == nil {
		return nil, fmt.Errorf("%s: no PEM block", keyPath)
	}
	var key any
	switch blk.Type {
	case "PRIVATE KEY":
		key, err = x509.ParsePKCS8PrivateKey(blk.Bytes)
	case "RSA PRIVATE KEY":
		key, err = x509.ParsePKCS1PrivateKey(blk.Bytes)
	case "EC PRIVATE KEY":
		key, err = x509.ParseECPrivateKey(blk.Bytes)
	default:
		err = fmt.Errorf("unsupported key block %q", blk.Type)
	}
	if err != nil {
		return nil, fmt.Errorf("%s: %w", keyPath, err)
	}
	s, ok := key.(crypto.Signer)
	if !ok {
		return nil, errors.New("private key is not a signer")
	}
	c.Key = s
	return c, nil
}

// LoadPool reads one or more PEM certificates into a pool.
func LoadPool(path string) (*x509.CertPool, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	p := x509.NewCertPool()
	if !p.AppendCertsFromPEM(b) {
		return nil, fmt.Errorf("%s: no certificates found", path)
	}
	return p, nil
}
