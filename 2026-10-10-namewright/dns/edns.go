package dns

// EDNS0 (RFC 6891) helpers. The OPT pseudo-record lives in Additional; its
// CLASS field carries the sender's UDP payload size and its TTL field packs
// extended-rcode(8) | version(8) | DO(1) | Z(15).

const dnssecOK = 1 << 15

// SetEDNS adds (or replaces) an OPT record on m.
func (m *Message) SetEDNS(udpSize uint16, do bool) {
	var ttl uint32
	if do {
		ttl |= dnssecOK
	}
	m.removeOPT()
	m.Additional = append(m.Additional, RR{Name: ".", Type: TypeOPT, Class: Class(udpSize), TTL: ttl, Data: OPT{}})
}

func (m *Message) removeOPT() {
	out := m.Additional[:0:0]
	for _, r := range m.Additional {
		if r.Type != TypeOPT {
			out = append(out, r)
		}
	}
	m.Additional = out
}

// EDNS describes a message's OPT record.
type EDNS struct {
	UDPSize  uint16
	Version  uint8
	ExtRcode uint8
	DO       bool
}

// GetEDNS returns the OPT parameters if present.
func (m *Message) GetEDNS() (EDNS, bool) {
	for _, r := range m.Additional {
		if r.Type == TypeOPT {
			return EDNS{
				UDPSize:  uint16(r.Class),
				ExtRcode: uint8(r.TTL >> 24),
				Version:  uint8(r.TTL >> 16),
				DO:       r.TTL&dnssecOK != 0,
			}, true
		}
	}
	return EDNS{}, false
}

// FullRcode combines the header rcode with the OPT extended bits.
func (m *Message) FullRcode() int {
	e, _ := m.GetEDNS()
	return int(e.ExtRcode)<<4 | int(m.Rcode)
}

// SetBadVers marks the response as BADVERS (extended rcode 16).
func (m *Message) setExtRcode(ext uint8) {
	for i, r := range m.Additional {
		if r.Type == TypeOPT {
			m.Additional[i].TTL = r.TTL&0x00FFFFFF | uint32(ext)<<24
		}
	}
}
