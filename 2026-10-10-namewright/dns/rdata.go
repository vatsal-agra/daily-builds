package dns

import (
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"net/netip"
	"sort"
	"strconv"
	"strings"
	"time"
)

// RData is the type-specific payload of a resource record.
type RData interface {
	pack(b *builder) error
	String() string // presentation format
}

type A struct{ Addr netip.Addr }
type AAAA struct{ Addr netip.Addr }
type NS struct{ Host string }
type CNAME struct{ Target string }
type PTR struct{ Target string }
type MX struct {
	Pref uint16
	Host string
}
type TXT struct{ Strings []string }
type SOA struct {
	MName, RName                            string
	Serial, Refresh, Retry, Expire, Minimum uint32
}
type SRV struct {
	Priority, Weight, Port uint16
	Target                 string
}
type CAA struct {
	Flags uint8
	Tag   string
	Value string
}
type DNSKEY struct {
	Flags     uint16
	Protocol  uint8
	Algorithm uint8
	PublicKey []byte
}
type DS struct {
	KeyTag     uint16
	Algorithm  uint8
	DigestType uint8
	Digest     []byte
}
type RRSIG struct {
	TypeCovered Type
	Algorithm   uint8
	Labels      uint8
	OrigTTL     uint32
	Expiration  uint32
	Inception   uint32
	KeyTag      uint16
	SignerName  string
	Signature   []byte
}
type NSEC struct {
	Next  string
	Types []Type
}
type EDNSOption struct {
	Code uint16
	Data []byte
}
type OPT struct{ Options []EDNSOption }

// Unknown carries rdata of a type this package has no codec for (RFC 3597).
type Unknown struct{ Raw []byte }

func (d A) pack(b *builder) error {
	if !d.Addr.Is4() {
		return fmt.Errorf("dns: A record needs an IPv4 address, got %v", d.Addr)
	}
	a := d.Addr.As4()
	b.buf = append(b.buf, a[:]...)
	return nil
}
func (d AAAA) pack(b *builder) error {
	if !d.Addr.Is6() || d.Addr.Is4In6() {
		return fmt.Errorf("dns: AAAA record needs an IPv6 address, got %v", d.Addr)
	}
	a := d.Addr.As16()
	b.buf = append(b.buf, a[:]...)
	return nil
}
func (d NS) pack(b *builder) error    { return b.name(d.Host, true) }
func (d CNAME) pack(b *builder) error { return b.name(d.Target, true) }
func (d PTR) pack(b *builder) error   { return b.name(d.Target, true) }
func (d MX) pack(b *builder) error {
	b.u16(d.Pref)
	return b.name(d.Host, true)
}
func (d TXT) pack(b *builder) error {
	if len(d.Strings) == 0 {
		return fmt.Errorf("dns: TXT needs at least one string")
	}
	for _, s := range d.Strings {
		if err := b.charString(s); err != nil {
			return err
		}
	}
	return nil
}
func (d SOA) pack(b *builder) error {
	if err := b.name(d.MName, true); err != nil {
		return err
	}
	if err := b.name(d.RName, true); err != nil {
		return err
	}
	for _, v := range []uint32{d.Serial, d.Refresh, d.Retry, d.Expire, d.Minimum} {
		b.u32(v)
	}
	return nil
}
func (d SRV) pack(b *builder) error {
	b.u16(d.Priority)
	b.u16(d.Weight)
	b.u16(d.Port)
	return b.name(d.Target, false)
}
func (d CAA) pack(b *builder) error {
	b.u8(d.Flags)
	if err := b.charString(d.Tag); err != nil {
		return err
	}
	b.buf = append(b.buf, d.Value...)
	return nil
}
func (d DNSKEY) pack(b *builder) error {
	b.u16(d.Flags)
	b.u8(d.Protocol)
	b.u8(d.Algorithm)
	b.buf = append(b.buf, d.PublicKey...)
	return nil
}
func (d DS) pack(b *builder) error {
	b.u16(d.KeyTag)
	b.u8(d.Algorithm)
	b.u8(d.DigestType)
	b.buf = append(b.buf, d.Digest...)
	return nil
}
func (d RRSIG) pack(b *builder) error {
	b.u16(uint16(d.TypeCovered))
	b.u8(d.Algorithm)
	b.u8(d.Labels)
	b.u32(d.OrigTTL)
	b.u32(d.Expiration)
	b.u32(d.Inception)
	b.u16(d.KeyTag)
	if err := b.rawName(d.SignerName); err != nil {
		return err
	}
	b.buf = append(b.buf, d.Signature...)
	return nil
}
func (d NSEC) pack(b *builder) error {
	if err := b.rawName(d.Next); err != nil {
		return err
	}
	b.buf = append(b.buf, packBitmap(d.Types)...)
	return nil
}
func (d OPT) pack(b *builder) error {
	for _, o := range d.Options {
		b.u16(o.Code)
		b.u16(uint16(len(o.Data)))
		b.buf = append(b.buf, o.Data...)
	}
	return nil
}
func (d Unknown) pack(b *builder) error {
	b.buf = append(b.buf, d.Raw...)
	return nil
}

func packBitmap(types []Type) []byte {
	ts := append([]Type(nil), types...)
	sort.Slice(ts, func(i, j int) bool { return ts[i] < ts[j] })
	var out []byte
	i := 0
	for i < len(ts) {
		win := uint8(ts[i] >> 8)
		var bm [32]byte
		last := -1
		for i < len(ts) && uint8(ts[i]>>8) == win {
			lo := int(ts[i] & 0xFF)
			bm[lo/8] |= 0x80 >> (lo % 8)
			if lo/8 > last {
				last = lo / 8
			}
			i++
		}
		out = append(out, win, uint8(last+1))
		out = append(out, bm[:last+1]...)
	}
	return out
}

func unpackBitmap(b []byte) ([]Type, error) {
	var ts []Type
	prev := -1
	for len(b) > 0 {
		if len(b) < 2 {
			return nil, ErrShort
		}
		win, n := int(b[0]), int(b[1])
		if win <= prev || n == 0 || n > 32 || len(b) < 2+n {
			return nil, fmt.Errorf("dns: malformed NSEC type bitmap")
		}
		prev = win
		for i := 0; i < n; i++ {
			for bit := 0; bit < 8; bit++ {
				if b[2+i]&(0x80>>bit) != 0 {
					ts = append(ts, Type(win<<8|i*8+bit))
				}
			}
		}
		b = b[2+n:]
	}
	return ts, nil
}

func unpackRData(t Type, p *parser, end int) (RData, error) {
	rest := func() []byte { v := p.msg[p.off:end]; p.off = end; return append([]byte(nil), v...) }
	switch t {
	case TypeA:
		v, err := p.bytes(4)
		if err != nil {
			return nil, err
		}
		return A{netip.AddrFrom4([4]byte(v))}, nil
	case TypeAAAA:
		v, err := p.bytes(16)
		if err != nil {
			return nil, err
		}
		return AAAA{netip.AddrFrom16([16]byte(v))}, nil
	case TypeNS, TypeCNAME, TypePTR:
		n, err := p.name()
		if err != nil {
			return nil, err
		}
		switch t {
		case TypeNS:
			return NS{n}, nil
		case TypeCNAME:
			return CNAME{n}, nil
		}
		return PTR{n}, nil
	case TypeMX:
		pref, err := p.u16()
		if err != nil {
			return nil, err
		}
		n, err := p.name()
		return MX{pref, n}, err
	case TypeTXT:
		var ss []string
		for p.off < end {
			s, err := p.charString()
			if err != nil {
				return nil, err
			}
			ss = append(ss, s)
		}
		if len(ss) == 0 {
			return nil, fmt.Errorf("dns: empty TXT")
		}
		return TXT{ss}, nil
	case TypeSOA:
		var s SOA
		var err error
		if s.MName, err = p.name(); err != nil {
			return nil, err
		}
		if s.RName, err = p.name(); err != nil {
			return nil, err
		}
		for _, f := range []*uint32{&s.Serial, &s.Refresh, &s.Retry, &s.Expire, &s.Minimum} {
			if *f, err = p.u32(); err != nil {
				return nil, err
			}
		}
		return s, nil
	case TypeSRV:
		var s SRV
		var err error
		for _, f := range []*uint16{&s.Priority, &s.Weight, &s.Port} {
			if *f, err = p.u16(); err != nil {
				return nil, err
			}
		}
		s.Target, err = p.name()
		return s, err
	case TypeCAA:
		fl, err := p.u8()
		if err != nil {
			return nil, err
		}
		tag, err := p.charString()
		if err != nil {
			return nil, err
		}
		return CAA{fl, tag, string(rest())}, nil
	case TypeDNSKEY:
		if end-p.off < 4 {
			return nil, ErrShort
		}
		fl, _ := p.u16()
		pr, _ := p.u8()
		al, _ := p.u8()
		return DNSKEY{fl, pr, al, rest()}, nil
	case TypeDS:
		if end-p.off < 4 {
			return nil, ErrShort
		}
		kt, _ := p.u16()
		al, _ := p.u8()
		dt, _ := p.u8()
		return DS{kt, al, dt, rest()}, nil
	case TypeRRSIG:
		var s RRSIG
		tc, err := p.u16()
		if err != nil {
			return nil, err
		}
		s.TypeCovered = Type(tc)
		if s.Algorithm, err = p.u8(); err != nil {
			return nil, err
		}
		if s.Labels, err = p.u8(); err != nil {
			return nil, err
		}
		for _, f := range []*uint32{&s.OrigTTL, &s.Expiration, &s.Inception} {
			if *f, err = p.u32(); err != nil {
				return nil, err
			}
		}
		if s.KeyTag, err = p.u16(); err != nil {
			return nil, err
		}
		if s.SignerName, err = p.name(); err != nil {
			return nil, err
		}
		s.Signature = rest()
		return s, nil
	case TypeNSEC:
		n, err := p.name()
		if err != nil {
			return nil, err
		}
		ts, err := unpackBitmap(p.msg[p.off:end])
		if err != nil {
			return nil, err
		}
		p.off = end
		return NSEC{n, ts}, nil
	case TypeOPT:
		var o OPT
		for p.off < end {
			code, err := p.u16()
			if err != nil {
				return nil, err
			}
			l, err := p.u16()
			if err != nil {
				return nil, err
			}
			if p.off+int(l) > end {
				return nil, ErrShort
			}
			d, _ := p.bytes(int(l))
			o.Options = append(o.Options, EDNSOption{code, append([]byte(nil), d...)})
		}
		return o, nil
	}
	return Unknown{rest()}, nil
}

// ---------------------------------------------------------------- presentation

func quoteTXT(s string) string {
	var sb strings.Builder
	sb.WriteByte('"')
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c == '"' || c == '\\':
			sb.WriteByte('\\')
			sb.WriteByte(c)
		case c < ' ' || c >= 0x7f:
			fmt.Fprintf(&sb, "\\%03d", c)
		default:
			sb.WriteByte(c)
		}
	}
	sb.WriteByte('"')
	return sb.String()
}

func (d A) String() string     { return d.Addr.String() }
func (d AAAA) String() string  { return d.Addr.String() }
func (d NS) String() string    { return d.Host }
func (d CNAME) String() string { return d.Target }
func (d PTR) String() string   { return d.Target }
func (d MX) String() string    { return fmt.Sprintf("%d %s", d.Pref, d.Host) }
func (d TXT) String() string {
	q := make([]string, len(d.Strings))
	for i, s := range d.Strings {
		q[i] = quoteTXT(s)
	}
	return strings.Join(q, " ")
}
func (d SOA) String() string {
	return fmt.Sprintf("%s %s %d %d %d %d %d", d.MName, d.RName, d.Serial, d.Refresh, d.Retry, d.Expire, d.Minimum)
}
func (d SRV) String() string {
	return fmt.Sprintf("%d %d %d %s", d.Priority, d.Weight, d.Port, d.Target)
}
func (d CAA) String() string { return fmt.Sprintf("%d %s %s", d.Flags, d.Tag, quoteTXT(d.Value)) }
func (d DNSKEY) String() string {
	return fmt.Sprintf("%d %d %d %s", d.Flags, d.Protocol, d.Algorithm, base64.StdEncoding.EncodeToString(d.PublicKey))
}
func (d DS) String() string {
	return fmt.Sprintf("%d %d %d %s", d.KeyTag, d.Algorithm, d.DigestType, strings.ToUpper(hex.EncodeToString(d.Digest)))
}
func (d RRSIG) String() string {
	return fmt.Sprintf("%s %d %d %d %s %s %d %s %s", d.TypeCovered, d.Algorithm, d.Labels, d.OrigTTL,
		sigTime(d.Expiration), sigTime(d.Inception), d.KeyTag, d.SignerName, base64.StdEncoding.EncodeToString(d.Signature))
}
func (d NSEC) String() string {
	ts := make([]string, len(d.Types))
	for i, t := range d.Types {
		ts[i] = t.String()
	}
	return d.Next + " " + strings.Join(ts, " ")
}
func (d OPT) String() string {
	var parts []string
	for _, o := range d.Options {
		parts = append(parts, fmt.Sprintf("%d:%x", o.Code, o.Data))
	}
	return strings.Join(parts, " ")
}
func (d Unknown) String() string {
	if len(d.Raw) == 0 {
		return `\# 0`
	}
	return fmt.Sprintf(`\# %d %s`, len(d.Raw), hex.EncodeToString(d.Raw))
}

func (r RR) String() string {
	return fmt.Sprintf("%s\t%d\t%s\t%s\t%s", r.Name, r.TTL, r.Class, r.Type, r.Data)
}

// ---------------------------------------------------------------- RR helpers

// Equal reports whether two RRs are the same record (name case-insensitive,
// rdata compared by wire encoding in canonical form).
func (r RR) Equal(o RR) bool {
	if r.Type != o.Type || r.Class != o.Class || CompareNames(r.Name, o.Name) != 0 {
		return false
	}
	a, b := canonRData(r), canonRData(o)
	return string(a) == string(b)
}

func canonRData(r RR) []byte {
	b := newBuilder()
	b.canon = true
	if r.Data != nil {
		_ = r.Data.pack(b)
	}
	return b.buf
}

// NewA etc. are small constructors used by tests and the signer.
func MustAddr(s string) netip.Addr { return netip.MustParseAddr(s) }

// sigTime renders an RRSIG timestamp as YYYYMMDDHHmmSS (UTC).
func sigTime(v uint32) string { return time.Unix(int64(v), 0).UTC().Format("20060102150405") }

// parseSigTime accepts YYYYMMDDHHmmSS or plain epoch seconds.
func parseSigTime(s string) (uint32, error) {
	if len(s) == 14 && allDigits(s) {
		t, err := time.Parse("20060102150405", s)
		if err != nil {
			return 0, err
		}
		return uint32(t.Unix()), nil
	}
	v, err := strconv.ParseUint(s, 10, 32)
	if err != nil {
		return 0, fmt.Errorf("bad signature time %q", s)
	}
	return uint32(v), nil
}

func ttlString(v uint32) string { return strconv.FormatUint(uint64(v), 10) }

// Lowered returns a copy of r with the owner and any embedded domain names
// lower-cased. The resolver uses it to undo case randomisation (0x20) and
// compression-induced case borrowing before records enter the cache.
func (r RR) Lowered() RR {
	r.Name = CanonName(r.Name)
	switch d := r.Data.(type) {
	case NS:
		r.Data = NS{CanonName(d.Host)}
	case CNAME:
		r.Data = CNAME{CanonName(d.Target)}
	case PTR:
		r.Data = PTR{CanonName(d.Target)}
	case MX:
		r.Data = MX{d.Pref, CanonName(d.Host)}
	case SRV:
		d.Target = CanonName(d.Target)
		r.Data = d
	case SOA:
		d.MName, d.RName = CanonName(d.MName), CanonName(d.RName)
		r.Data = d
	}
	return r
}
