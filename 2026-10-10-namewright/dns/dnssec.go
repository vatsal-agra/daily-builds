package dns

import (
	"bytes"
	"crypto"
	"crypto/ecdsa"
	"crypto/ed25519"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha1"
	"crypto/sha256"
	"crypto/sha512"
	"crypto/x509"
	"encoding/binary"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"sort"
	"time"
)

// DNSSEC algorithm numbers (RFC 8624).
const (
	AlgRSASHA256       uint8 = 8  // verify only
	AlgECDSAP256SHA256 uint8 = 13 // sign + verify
	AlgED25519         uint8 = 15 // sign + verify
)

const (
	FlagZone   uint16 = 256
	FlagSEP    uint16 = 1
	flagRevoke uint16 = 128
)

// DS digest types.
const (
	DigestSHA1   uint8 = 1
	DigestSHA256 uint8 = 2
	DigestSHA384 uint8 = 4
)

func algName(a uint8) string {
	switch a {
	case AlgRSASHA256:
		return "RSASHA256"
	case AlgECDSAP256SHA256:
		return "ECDSAP256SHA256"
	case AlgED25519:
		return "ED25519"
	}
	return fmt.Sprintf("ALG%d", a)
}

// SupportedAlgorithm reports whether signatures of alg can be verified here.
func SupportedAlgorithm(a uint8) bool {
	return a == AlgRSASHA256 || a == AlgECDSAP256SHA256 || a == AlgED25519
}

// ---------------------------------------------------------------- keys

// Key is a DNSSEC signing key with its public DNSKEY record.
type Key struct {
	Owner  string
	Public DNSKEY
	priv   crypto.Signer
}

// GenerateKey creates an Ed25519 (alg 15) or ECDSA P-256 (alg 13) key. A KSK
// carries the SEP flag (257); a ZSK is 256.
func GenerateKey(owner string, alg uint8, ksk bool) (*Key, error) {
	flags := FlagZone
	if ksk {
		flags |= FlagSEP
	}
	k := &Key{Owner: CanonName(owner)}
	switch alg {
	case AlgED25519:
		pub, priv, err := ed25519.GenerateKey(rand.Reader)
		if err != nil {
			return nil, err
		}
		k.priv = priv
		k.Public = DNSKEY{flags, 3, alg, []byte(pub)}
	case AlgECDSAP256SHA256:
		priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		if err != nil {
			return nil, err
		}
		k.priv = priv
		pub := make([]byte, 64)
		priv.PublicKey.X.FillBytes(pub[:32])
		priv.PublicKey.Y.FillBytes(pub[32:])
		k.Public = DNSKEY{flags, 3, alg, pub}
	default:
		return nil, fmt.Errorf("cannot generate keys for algorithm %d (supported: 13, 15)", alg)
	}
	return k, nil
}

// Tag is the RFC 4034 appendix B key tag.
func (k *Key) Tag() uint16 { return KeyTag(k.Public) }

func KeyTag(d DNSKEY) uint16 {
	b := newBuilder()
	d.pack(b)
	var ac uint32
	for i, c := range b.buf {
		if i&1 == 0 {
			ac += uint32(c) << 8
		} else {
			ac += uint32(c)
		}
	}
	ac += ac >> 16 & 0xFFFF
	return uint16(ac & 0xFFFF)
}

// RR returns the DNSKEY record for this key.
func (k *Key) RR(ttl uint32) RR {
	return RR{Name: k.Owner, Type: TypeDNSKEY, Class: ClassIN, TTL: ttl, Data: k.Public}
}

// DS builds the delegation-signer record a parent publishes for this key.
func (k *Key) DS(digest uint8) (DS, error) { return MakeDS(k.Owner, k.Public, digest) }

// MakeDS computes DS = digest(owner | DNSKEY rdata) per RFC 4034 §5.1.4.
func MakeDS(owner string, key DNSKEY, digest uint8) (DS, error) {
	b := newBuilder()
	b.canon = true
	if err := b.name(owner, false); err != nil {
		return DS{}, err
	}
	key.pack(b)
	var sum []byte
	switch digest {
	case DigestSHA1:
		h := sha1.Sum(b.buf)
		sum = h[:]
	case DigestSHA256:
		h := sha256.Sum256(b.buf)
		sum = h[:]
	case DigestSHA384:
		h := sha512.Sum384(b.buf)
		sum = h[:]
	default:
		return DS{}, fmt.Errorf("unsupported DS digest type %d", digest)
	}
	return DS{KeyTag(key), key.Algorithm, digest, sum}, nil
}

// MarshalPrivate returns the private key as PKCS#8 PEM.
func (k *Key) MarshalPrivate() ([]byte, error) {
	der, err := x509.MarshalPKCS8PrivateKey(k.priv)
	if err != nil {
		return nil, err
	}
	return pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}), nil
}

// ParsePrivateKey rebuilds a Key from the PEM private key and its DNSKEY record.
func ParsePrivateKey(owner string, public DNSKEY, pemData []byte) (*Key, error) {
	blk, _ := pem.Decode(pemData)
	if blk == nil {
		return nil, errors.New("no PEM block in private key file")
	}
	pk, err := x509.ParsePKCS8PrivateKey(blk.Bytes)
	if err != nil {
		return nil, err
	}
	s, ok := pk.(crypto.Signer)
	if !ok {
		return nil, errors.New("private key cannot sign")
	}
	k := &Key{Owner: CanonName(owner), Public: public, priv: s}
	// the private key must belong to the published public key
	switch p := s.(type) {
	case ed25519.PrivateKey:
		if public.Algorithm != AlgED25519 || !bytes.Equal(p.Public().(ed25519.PublicKey), public.PublicKey) {
			return nil, errors.New("private key does not match DNSKEY")
		}
	case *ecdsa.PrivateKey:
		want := make([]byte, 64)
		p.PublicKey.X.FillBytes(want[:32])
		p.PublicKey.Y.FillBytes(want[32:])
		if public.Algorithm != AlgECDSAP256SHA256 || !bytes.Equal(want, public.PublicKey) {
			return nil, errors.New("private key does not match DNSKEY")
		}
	default:
		return nil, errors.New("unsupported private key type")
	}
	return k, nil
}

// ---------------------------------------------------------------- canonical forms

func canonicalRRWire(owner string, t Type, c Class, ttl uint32, d RData) ([]byte, error) {
	b := newBuilder()
	b.canon = true
	if err := b.name(owner, false); err != nil {
		return nil, err
	}
	b.u16(uint16(t))
	b.u16(uint16(c))
	b.u32(ttl)
	at := len(b.buf)
	b.u16(0)
	if err := d.pack(b); err != nil {
		return nil, err
	}
	binary.BigEndian.PutUint16(b.buf[at:], uint16(len(b.buf)-at-2))
	return b.buf, nil
}

// rrsigLabels counts owner labels without a leading wildcard (RFC 4034 §3.1.3).
func rrsigLabels(owner string) uint8 {
	l := Labels(owner)
	if len(l) > 0 && len(l[0]) == 1 && l[0][0] == '*' {
		l = l[1:]
	}
	return uint8(len(l))
}

// signedData assembles RRSIG_RDATA-without-signature followed by the sorted RRset.
func signedData(sig RRSIG, rrset []RR) ([]byte, error) {
	pre := newBuilder()
	pre.canon = true
	pre.u16(uint16(sig.TypeCovered))
	pre.u8(sig.Algorithm)
	pre.u8(sig.Labels)
	pre.u32(sig.OrigTTL)
	pre.u32(sig.Expiration)
	pre.u32(sig.Inception)
	pre.u16(sig.KeyTag)
	if err := pre.name(sig.SignerName, false); err != nil {
		return nil, err
	}
	type item struct{ rdata, full []byte }
	var items []item
	for _, r := range rrset {
		owner := r.Name
		if n := NumLabels(owner); int(sig.Labels) < n { // wildcard expansion: restore the wildcard owner
			l := Labels(CanonName(owner))
			owner = joinLabels(append([][]byte{[]byte("*")}, l[n-int(sig.Labels):]...))
		}
		full, err := canonicalRRWire(owner, r.Type, r.Class, sig.OrigTTL, r.Data)
		if err != nil {
			return nil, err
		}
		items = append(items, item{canonRData(r), full})
	}
	sort.Slice(items, func(i, j int) bool { return bytes.Compare(items[i].rdata, items[j].rdata) < 0 })
	out := pre.buf
	for i, it := range items {
		if i > 0 && bytes.Equal(items[i-1].full, it.full) {
			continue // duplicate RRs are signed once
		}
		out = append(out, it.full...)
	}
	return out, nil
}

// ---------------------------------------------------------------- sign / verify

func (k *Key) sign(data []byte) ([]byte, error) {
	switch k.Public.Algorithm {
	case AlgED25519:
		return k.priv.Sign(rand.Reader, data, crypto.Hash(0))
	case AlgECDSAP256SHA256:
		h := sha256.Sum256(data)
		r, s, err := ecdsa.Sign(rand.Reader, k.priv.(*ecdsa.PrivateKey), h[:])
		if err != nil {
			return nil, err
		}
		out := make([]byte, 64)
		r.FillBytes(out[:32])
		s.FillBytes(out[32:])
		return out, nil
	}
	return nil, fmt.Errorf("cannot sign with algorithm %d", k.Public.Algorithm)
}

// SignRRset produces an RRSIG over an RRset (same owner, type, class).
func SignRRset(k *Key, signer string, rrset []RR, inception, expiration time.Time) (RR, error) {
	if len(rrset) == 0 {
		return RR{}, errors.New("empty RRset")
	}
	ttl := rrset[0].TTL
	sig := RRSIG{
		TypeCovered: rrset[0].Type, Algorithm: k.Public.Algorithm, Labels: rrsigLabels(rrset[0].Name),
		OrigTTL: ttl, Expiration: uint32(expiration.Unix()), Inception: uint32(inception.Unix()),
		KeyTag: k.Tag(), SignerName: CanonName(signer),
	}
	data, err := signedData(sig, rrset)
	if err != nil {
		return RR{}, err
	}
	if sig.Signature, err = k.sign(data); err != nil {
		return RR{}, err
	}
	return RR{Name: rrset[0].Name, Type: TypeRRSIG, Class: ClassIN, TTL: ttl, Data: sig}, nil
}

// Verification errors.
var (
	ErrSigExpired     = errors.New("signature expired")
	ErrSigNotYet      = errors.New("signature not yet valid")
	ErrSigInvalid     = errors.New("signature does not verify")
	ErrAlgUnsupported = errors.New("unsupported DNSSEC algorithm")
)

// VerifyRRSIG checks sig over rrset with key at time now.
func VerifyRRSIG(sig RRSIG, key DNSKEY, rrset []RR, now time.Time) error {
	if sig.Algorithm != key.Algorithm || sig.KeyTag != KeyTag(key) {
		return errors.New("signature was not made by this key")
	}
	if key.Flags&FlagZone == 0 || key.Protocol != 3 || key.Flags&flagRevoke != 0 {
		return errors.New("key is not a usable zone key")
	}
	if len(rrset) == 0 || sig.TypeCovered != rrset[0].Type {
		return errors.New("signature covers a different type")
	}
	if int(sig.Labels) > NumLabels(rrset[0].Name) {
		return errors.New("RRSIG labels field exceeds owner label count")
	}
	n := uint32(now.Unix())
	if int32(n-sig.Inception) < 0 { // RFC 1982 serial arithmetic
		return ErrSigNotYet
	}
	if int32(sig.Expiration-n) < 0 {
		return ErrSigExpired
	}
	data, err := signedData(sig, rrset)
	if err != nil {
		return err
	}
	switch key.Algorithm {
	case AlgED25519:
		if len(key.PublicKey) != ed25519.PublicKeySize || !ed25519.Verify(key.PublicKey, data, sig.Signature) {
			return ErrSigInvalid
		}
		return nil
	case AlgECDSAP256SHA256:
		if len(key.PublicKey) != 64 || len(sig.Signature) != 64 {
			return ErrSigInvalid
		}
		pub := &ecdsa.PublicKey{Curve: elliptic.P256(), X: new(big.Int).SetBytes(key.PublicKey[:32]), Y: new(big.Int).SetBytes(key.PublicKey[32:])}
		if !pub.Curve.IsOnCurve(pub.X, pub.Y) {
			return ErrSigInvalid
		}
		h := sha256.Sum256(data)
		if !ecdsa.Verify(pub, h[:], new(big.Int).SetBytes(sig.Signature[:32]), new(big.Int).SetBytes(sig.Signature[32:])) {
			return ErrSigInvalid
		}
		return nil
	case AlgRSASHA256:
		pub, err := parseRSAKey(key.PublicKey)
		if err != nil {
			return err
		}
		h := sha256.Sum256(data)
		if rsa.VerifyPKCS1v15(pub, crypto.SHA256, h[:], sig.Signature) != nil {
			return ErrSigInvalid
		}
		return nil
	}
	return ErrAlgUnsupported
}

func parseRSAKey(b []byte) (*rsa.PublicKey, error) {
	if len(b) < 3 {
		return nil, errors.New("short RSA key")
	}
	el, off := int(b[0]), 1
	if el == 0 {
		el, off = int(binary.BigEndian.Uint16(b[1:])), 3
	}
	if off+el >= len(b) || el > 4 {
		return nil, errors.New("bad RSA exponent")
	}
	e := 0
	for _, c := range b[off : off+el] {
		e = e<<8 | int(c)
	}
	return &rsa.PublicKey{E: e, N: new(big.Int).SetBytes(b[off+el:])}, nil
}

// DSMatches reports whether ds is the digest of key (owner is the zone apex).
func DSMatches(owner string, ds DS, key DNSKEY) bool {
	if ds.Algorithm != key.Algorithm || ds.KeyTag != KeyTag(key) {
		return false
	}
	want, err := MakeDS(owner, key, ds.DigestType)
	return err == nil && bytes.Equal(want.Digest, ds.Digest)
}

// ---------------------------------------------------------------- zone signing

// SignOptions configures SignZone.
type SignOptions struct {
	KSK, ZSK   *Key // ZSK may be nil: the KSK then signs everything (CSK)
	Inception  time.Time
	Expiration time.Time
}

type rrKey struct {
	name string
	t    Type
}

// SignZone adds DNSKEY, NSEC and RRSIG records to the zone's records and
// returns the full signed set. Existing DNSSEC records are replaced. Glue and
// delegation NS sets are left unsigned, per RFC 4035 §2.2.
func SignZone(origin string, rrs []RR, opt SignOptions) ([]RR, error) {
	origin = CanonName(origin)
	if opt.KSK == nil {
		return nil, errors.New("a KSK is required")
	}
	zsk := opt.ZSK
	if zsk == nil {
		zsk = opt.KSK
	}
	if !opt.Expiration.After(opt.Inception) {
		return nil, errors.New("signature expiration must be after inception")
	}
	var plain []RR
	for _, r := range rrs {
		switch r.Type {
		case TypeRRSIG, TypeNSEC:
			continue
		case TypeDNSKEY:
			if CanonName(r.Name) == origin {
				continue
			}
		}
		plain = append(plain, r)
	}
	z0, err := NewZone(origin, plain)
	if err != nil {
		return nil, err
	}
	soa := z0.SOA()
	soaData := soa.Data.(SOA)
	keyTTL := soa.TTL
	out := append([]RR(nil), z0.Records()...)
	keys := []Key{*opt.KSK}
	if zsk != opt.KSK {
		keys = append(keys, *zsk)
	}
	for _, k := range keys {
		kk := k
		kk.Owner = origin
		out = append(out, kk.RR(keyTTL))
	}
	// zone with keys, to enumerate owners and types
	z1, err := NewZone(origin, out)
	if err != nil {
		return nil, err
	}
	// NSEC chain over authoritative names (not glue), in canonical order
	var owners []string
	for _, n := range z1.sorted {
		if cut := z1.findCut(n); cut != "" && cut != n {
			continue // glue
		}
		owners = append(owners, n)
	}
	for i, n := range owners {
		next := owners[(i+1)%len(owners)]
		node := z1.nodes[n]
		isCut := n != origin && len(node.rrsets[TypeNS]) > 0
		var types []Type
		for t := range node.rrsets {
			if isCut && t != TypeNS && t != TypeDS {
				continue
			}
			types = append(types, t)
		}
		types = append(types, TypeRRSIG, TypeNSEC)
		sort.Slice(types, func(a, b int) bool { return types[a] < types[b] })
		out = append(out, RR{Name: n, Type: TypeNSEC, Class: ClassIN, TTL: soaData.Minimum, Data: NSEC{next, types}})
	}
	z2, err := NewZone(origin, out)
	if err != nil {
		return nil, err
	}
	// sign every authoritative RRset
	var sigs []RR
	for _, n := range z2.sorted {
		cut := z2.findCut(n)
		if cut != "" && cut != n {
			continue // glue
		}
		node := z2.nodes[n]
		var types []int
		for t := range node.rrsets {
			types = append(types, int(t))
		}
		sort.Ints(types)
		for _, ti := range types {
			t := Type(ti)
			if t == TypeRRSIG || (t == TypeNS && cut == n) {
				continue
			}
			signer := zsk
			if t == TypeDNSKEY {
				signer = opt.KSK
			}
			sig, err := SignRRset(signer, origin, node.rrsets[t], opt.Inception, opt.Expiration)
			if err != nil {
				return nil, err
			}
			sigs = append(sigs, sig)
		}
	}
	return append(out, sigs...), nil
}

// VerifyZone checks every RRSIG in z against the zone's own DNSKEYs and that
// the NSEC chain is complete and consistent. It returns all problems found.
func VerifyZone(z *Zone, now time.Time) []error {
	var errs []error
	var keys []DNSKEY
	for _, r := range z.rrset(z.Origin, TypeDNSKEY) {
		keys = append(keys, r.Data.(DNSKEY))
	}
	if len(keys) == 0 {
		return []error{errors.New("zone has no DNSKEY at the apex")}
	}
	covered := map[rrKey]bool{}
	for _, name := range z.sorted {
		node := z.nodes[name]
		cut := z.findCut(name)
		if cut != "" && cut != name {
			continue
		}
		for t, set := range node.rrsets {
			if t == TypeRRSIG || (t == TypeNS && cut == name) {
				continue
			}
			ok := false
			var last error = errors.New("no RRSIG")
			for _, s := range z.sigs(name, t) {
				sig := s.Data.(RRSIG)
				for _, k := range keys {
					if sig.Algorithm == k.Algorithm && sig.KeyTag == KeyTag(k) {
						if err := VerifyRRSIG(sig, k, set, now); err == nil {
							ok = true
						} else {
							last = err
						}
					}
				}
			}
			if !ok {
				errs = append(errs, fmt.Errorf("%s %s: %v", name, t, last))
			}
			covered[rrKey{name, t}] = ok
		}
	}
	// NSEC chain
	var chain []string
	for _, n := range z.sorted {
		if len(z.nodes[n].rrsets[TypeNSEC]) > 0 {
			chain = append(chain, n)
		}
	}
	for i, n := range chain {
		nsec := z.nodes[n].rrsets[TypeNSEC][0].Data.(NSEC)
		if want := chain[(i+1)%len(chain)]; CompareNames(nsec.Next, want) != 0 {
			errs = append(errs, fmt.Errorf("%s NSEC points to %s, expected %s", n, nsec.Next, want))
		}
	}
	for _, n := range z.sorted {
		if cut := z.findCut(n); cut != "" && cut != n {
			continue
		}
		if len(z.nodes[n].rrsets[TypeNSEC]) == 0 {
			errs = append(errs, fmt.Errorf("%s has no NSEC record", n))
		}
	}
	return errs
}
