package dns

import (
	"encoding/binary"
	"errors"
	"fmt"
)

type Type uint16
type Class uint16
type Rcode uint8

const (
	TypeA      Type = 1
	TypeNS     Type = 2
	TypeCNAME  Type = 5
	TypeSOA    Type = 6
	TypePTR    Type = 12
	TypeMX     Type = 15
	TypeTXT    Type = 16
	TypeAAAA   Type = 28
	TypeSRV    Type = 33
	TypeOPT    Type = 41
	TypeDS     Type = 43
	TypeRRSIG  Type = 46
	TypeNSEC   Type = 47
	TypeDNSKEY Type = 48
	TypeAXFR   Type = 252
	TypeANY    Type = 255
	TypeCAA    Type = 257
)

const (
	ClassIN  Class = 1
	ClassCH  Class = 3
	ClassANY Class = 255
)

const (
	RcodeSuccess  Rcode = 0
	RcodeFormErr  Rcode = 1
	RcodeServFail Rcode = 2
	RcodeNXDomain Rcode = 3
	RcodeNotImp   Rcode = 4
	RcodeRefused  Rcode = 5
)

var typeNames = map[Type]string{
	TypeA: "A", TypeNS: "NS", TypeCNAME: "CNAME", TypeSOA: "SOA", TypePTR: "PTR",
	TypeMX: "MX", TypeTXT: "TXT", TypeAAAA: "AAAA", TypeSRV: "SRV", TypeOPT: "OPT",
	TypeDS: "DS", TypeRRSIG: "RRSIG", TypeNSEC: "NSEC", TypeDNSKEY: "DNSKEY",
	TypeAXFR: "AXFR", TypeANY: "ANY", TypeCAA: "CAA",
}

var rcodeNames = []string{"NOERROR", "FORMERR", "SERVFAIL", "NXDOMAIN", "NOTIMP", "REFUSED"}

func (t Type) String() string {
	if s, ok := typeNames[t]; ok {
		return s
	}
	return fmt.Sprintf("TYPE%d", uint16(t))
}

func (c Class) String() string {
	switch c {
	case ClassIN:
		return "IN"
	case ClassCH:
		return "CH"
	case ClassANY:
		return "ANY"
	}
	return fmt.Sprintf("CLASS%d", uint16(c))
}

func (r Rcode) String() string {
	if int(r) < len(rcodeNames) {
		return rcodeNames[r]
	}
	return fmt.Sprintf("RCODE%d", uint8(r))
}

// ParseType maps "A", "aaaa", "TYPE65280" to a Type.
func ParseType(s string) (Type, bool) {
	u := upper(s)
	for t, n := range typeNames {
		if n == u {
			return t, true
		}
	}
	var n int
	if _, err := fmt.Sscanf(u, "TYPE%d", &n); err == nil && n >= 0 && n <= 65535 && fmt.Sprintf("TYPE%d", n) == u {
		return Type(n), true
	}
	return 0, false
}

func upper(s string) string {
	b := []byte(s)
	for i, c := range b {
		if c >= 'a' && c <= 'z' {
			b[i] = c - 32
		}
	}
	return string(b)
}

// Header flag bits within the 16-bit flags word.
const (
	flagQR = 1 << 15
	flagAA = 1 << 10
	flagTC = 1 << 9
	flagRD = 1 << 8
	flagRA = 1 << 7
	flagAD = 1 << 5
	flagCD = 1 << 4
)

type Question struct {
	Name  string
	Type  Type
	Class Class
}

type RR struct {
	Name  string
	Type  Type
	Class Class
	TTL   uint32
	Data  RData
}

type Message struct {
	ID                 uint16
	Response           bool
	Opcode             uint8
	Authoritative      bool
	Truncated          bool
	RecursionDesired   bool
	RecursionAvailable bool
	AuthenticData      bool
	CheckingDisabled   bool
	Rcode              Rcode
	Question           []Question
	Answer             []RR
	Authority          []RR
	Additional         []RR
}

var (
	ErrShort    = errors.New("dns: message truncated")
	ErrPointer  = errors.New("dns: bad compression pointer")
	ErrTooLarge = errors.New("dns: rdata too large")
)

// ---------------------------------------------------------------- builder

type builder struct {
	buf   []byte
	comp  map[string]int
	canon bool // DNSSEC canonical form: names lower-cased and never compressed
}

func newBuilder() *builder { return &builder{comp: map[string]int{}} }

func (b *builder) u8(v uint8)   { b.buf = append(b.buf, v) }
func (b *builder) u16(v uint16) { b.buf = binary.BigEndian.AppendUint16(b.buf, v) }
func (b *builder) u32(v uint32) { b.buf = binary.BigEndian.AppendUint32(b.buf, v) }

// name writes a domain name, using compression pointers when allowed.
func (b *builder) name(n string, compress bool) error {
	labels, err := splitName(n)
	if err != nil {
		return err
	}
	if b.canon {
		compress = false
		for i := range labels {
			labels[i] = lowerBytes(labels[i])
		}
	}
	for i := range labels {
		key := string(lowerBytes([]byte(joinLabels(labels[i:]))))
		if compress {
			if off, ok := b.comp[key]; ok {
				b.u16(0xC000 | uint16(off))
				return nil
			}
		}
		if len(b.buf) < 0x3FFF {
			if _, ok := b.comp[key]; !ok {
				b.comp[key] = len(b.buf)
			}
		}
		b.u8(uint8(len(labels[i])))
		b.buf = append(b.buf, labels[i]...)
	}
	b.u8(0)
	return nil
}

// rawName writes a name uncompressed and with case preserved even in canonical
// mode (RFC 6840 §5.1: NSEC next-name and RRSIG signer are not down-cased).
func (b *builder) rawName(n string) error {
	c := b.canon
	b.canon = false
	err := b.name(n, false)
	b.canon = c
	return err
}

func (b *builder) charString(s string) error {
	if len(s) > 255 {
		return fmt.Errorf("dns: character-string of %d bytes exceeds 255", len(s))
	}
	b.u8(uint8(len(s)))
	b.buf = append(b.buf, s...)
	return nil
}

func (b *builder) rr(r RR) error {
	if err := b.name(r.Name, true); err != nil {
		return err
	}
	b.u16(uint16(r.Type))
	b.u16(uint16(r.Class))
	b.u32(r.TTL)
	lenAt := len(b.buf)
	b.u16(0)
	if r.Data == nil {
		return fmt.Errorf("dns: RR %s %s has no data", r.Name, r.Type)
	}
	if err := r.Data.pack(b); err != nil {
		return err
	}
	n := len(b.buf) - lenAt - 2
	if n > 0xFFFF {
		return ErrTooLarge
	}
	binary.BigEndian.PutUint16(b.buf[lenAt:], uint16(n))
	return nil
}

func (m *Message) flags() uint16 {
	var f uint16
	if m.Response {
		f |= flagQR
	}
	f |= uint16(m.Opcode&0xF) << 11
	if m.Authoritative {
		f |= flagAA
	}
	if m.Truncated {
		f |= flagTC
	}
	if m.RecursionDesired {
		f |= flagRD
	}
	if m.RecursionAvailable {
		f |= flagRA
	}
	if m.AuthenticData {
		f |= flagAD
	}
	if m.CheckingDisabled {
		f |= flagCD
	}
	f |= uint16(m.Rcode & 0xF)
	return f
}

// Pack encodes the whole message with name compression.
func (m *Message) Pack() ([]byte, error) {
	out, tc, err := m.packLimit(0)
	if err != nil {
		return nil, err
	}
	_ = tc
	return out, nil
}

// PackLimit encodes the message so that it fits max bytes. Additional records
// that do not fit are dropped silently; if an answer or authority record does
// not fit, packing stops there and the TC bit is set (callers should retry over
// TCP). OPT records in Additional are always kept when they fit.
func (m *Message) PackLimit(max int) ([]byte, error) {
	out, _, err := m.packLimit(max)
	return out, err
}

func (m *Message) packLimit(max int) ([]byte, bool, error) {
	b := newBuilder()
	b.u16(m.ID)
	b.u16(m.flags())
	for i := 0; i < 4; i++ {
		b.u16(0)
	}
	for _, q := range m.Question {
		if err := b.name(q.Name, true); err != nil {
			return nil, false, err
		}
		b.u16(uint16(q.Type))
		b.u16(uint16(q.Class))
	}
	binary.BigEndian.PutUint16(b.buf[4:], uint16(len(m.Question)))
	counts := [3]int{}
	truncated := false
	fits := func() bool { return max <= 0 || len(b.buf) <= max }
	addSection := func(rrs []RR, slot int, mustFit bool) error {
		for _, r := range rrs {
			if truncated {
				return nil
			}
			save := len(b.buf)
			var saveComp map[string]int
			if max > 0 {
				saveComp = make(map[string]int, len(b.comp))
				for k, v := range b.comp {
					saveComp[k] = v
				}
			}
			if err := b.rr(r); err != nil {
				return err
			}
			if !fits() {
				b.buf = b.buf[:save]
				b.comp = saveComp
				if mustFit {
					truncated = true
				}
				continue
			}
			counts[slot]++
		}
		return nil
	}
	if err := addSection(m.Answer, 0, true); err != nil {
		return nil, false, err
	}
	if err := addSection(m.Authority, 1, true); err != nil {
		return nil, false, err
	}
	if !truncated {
		// non-OPT additional first, then OPT so that it is the last record kept
		var opt, rest []RR
		for _, r := range m.Additional {
			if r.Type == TypeOPT {
				opt = append(opt, r)
			} else {
				rest = append(rest, r)
			}
		}
		if err := addSection(opt, 2, false); err != nil {
			return nil, false, err
		}
		if err := addSection(rest, 2, false); err != nil {
			return nil, false, err
		}
	}
	if truncated {
		b.buf[2] |= flagTC >> 8
	}
	binary.BigEndian.PutUint16(b.buf[6:], uint16(counts[0]))
	binary.BigEndian.PutUint16(b.buf[8:], uint16(counts[1]))
	binary.BigEndian.PutUint16(b.buf[10:], uint16(counts[2]))
	return b.buf, truncated, nil
}

// ---------------------------------------------------------------- parser

type parser struct {
	msg []byte
	off int
}

func (p *parser) need(n int) error {
	if n < 0 || p.off+n > len(p.msg) {
		return ErrShort
	}
	return nil
}

func (p *parser) u8() (uint8, error) {
	if err := p.need(1); err != nil {
		return 0, err
	}
	v := p.msg[p.off]
	p.off++
	return v, nil
}

func (p *parser) u16() (uint16, error) {
	if err := p.need(2); err != nil {
		return 0, err
	}
	v := binary.BigEndian.Uint16(p.msg[p.off:])
	p.off += 2
	return v, nil
}

func (p *parser) u32() (uint32, error) {
	if err := p.need(4); err != nil {
		return 0, err
	}
	v := binary.BigEndian.Uint32(p.msg[p.off:])
	p.off += 4
	return v, nil
}

func (p *parser) bytes(n int) ([]byte, error) {
	if err := p.need(n); err != nil {
		return nil, err
	}
	v := p.msg[p.off : p.off+n]
	p.off += n
	return v, nil
}

func (p *parser) charString() (string, error) {
	n, err := p.u8()
	if err != nil {
		return "", err
	}
	b, err := p.bytes(int(n))
	return string(b), err
}

// name reads a possibly-compressed name. Pointers must point strictly before
// the position of the pointer itself, which rules out loops without needing a
// hop counter; total decoded length is capped at 255.
func (p *parser) name() (string, error) {
	var labels [][]byte
	off := p.off
	jumped := false
	total := 1
	for {
		if off >= len(p.msg) {
			return "", ErrShort
		}
		c := p.msg[off]
		switch c & 0xC0 {
		case 0x00:
			if c == 0 {
				if !jumped {
					p.off = off + 1
				}
				return joinLabels(labels), nil
			}
			n := int(c)
			if off+1+n > len(p.msg) {
				return "", ErrShort
			}
			total += n + 1
			if total > maxName {
				return "", errors.New("dns: name too long")
			}
			labels = append(labels, p.msg[off+1:off+1+n])
			off += 1 + n
		case 0xC0:
			if off+2 > len(p.msg) {
				return "", ErrShort
			}
			ptr := int(c&0x3F)<<8 | int(p.msg[off+1])
			if ptr >= off {
				return "", ErrPointer
			}
			if !jumped {
				p.off = off + 2
			}
			jumped = true
			off = ptr
		default:
			return "", errors.New("dns: reserved label type")
		}
	}
}

func (p *parser) rr() (RR, error) {
	var r RR
	var err error
	if r.Name, err = p.name(); err != nil {
		return r, err
	}
	t, err := p.u16()
	if err != nil {
		return r, err
	}
	c, err := p.u16()
	if err != nil {
		return r, err
	}
	ttl, err := p.u32()
	if err != nil {
		return r, err
	}
	rdlen, err := p.u16()
	if err != nil {
		return r, err
	}
	if err := p.need(int(rdlen)); err != nil {
		return r, err
	}
	r.Type, r.Class, r.TTL = Type(t), Class(c), ttl
	end := p.off + int(rdlen)
	sub := &parser{msg: p.msg[:end], off: p.off}
	r.Data, err = unpackRData(r.Type, sub, end)
	if err != nil {
		return r, fmt.Errorf("%s %s: %w", r.Name, r.Type, err)
	}
	if sub.off != end {
		return r, fmt.Errorf("dns: %s rdata has %d trailing bytes", r.Type, end-sub.off)
	}
	p.off = end
	return r, nil
}

// Unpack decodes a wire-format message. It never panics on malformed input.
func Unpack(msg []byte) (*Message, error) {
	if len(msg) < 12 {
		return nil, ErrShort
	}
	p := &parser{msg: msg}
	m := &Message{}
	m.ID, _ = p.u16()
	f, _ := p.u16()
	m.Response = f&flagQR != 0
	m.Opcode = uint8(f >> 11 & 0xF)
	m.Authoritative = f&flagAA != 0
	m.Truncated = f&flagTC != 0
	m.RecursionDesired = f&flagRD != 0
	m.RecursionAvailable = f&flagRA != 0
	m.AuthenticData = f&flagAD != 0
	m.CheckingDisabled = f&flagCD != 0
	m.Rcode = Rcode(f & 0xF)
	var cnt [4]int
	for i := range cnt {
		v, _ := p.u16()
		cnt[i] = int(v)
	}
	// every question needs >=5 bytes and every RR >=11: reject absurd counts up front
	if cnt[0]*5+(cnt[1]+cnt[2]+cnt[3])*11 > len(msg)-12 {
		return nil, ErrShort
	}
	for i := 0; i < cnt[0]; i++ {
		name, err := p.name()
		if err != nil {
			return nil, err
		}
		t, err := p.u16()
		if err != nil {
			return nil, err
		}
		c, err := p.u16()
		if err != nil {
			return nil, err
		}
		m.Question = append(m.Question, Question{name, Type(t), Class(c)})
	}
	for s, dst := range []*[]RR{&m.Answer, &m.Authority, &m.Additional} {
		for i := 0; i < cnt[s+1]; i++ {
			r, err := p.rr()
			if err != nil {
				return nil, err
			}
			*dst = append(*dst, r)
		}
	}
	return m, nil
}
