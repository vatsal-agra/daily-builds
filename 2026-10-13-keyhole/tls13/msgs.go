package tls13

import (
	"bytes"
)

// Handshake message types (RFC 8446 §4).
const (
	hsClientHello         uint8 = 1
	hsServerHello         uint8 = 2
	hsNewSessionTicket    uint8 = 4
	hsEndOfEarlyData      uint8 = 5
	hsEncryptedExtensions uint8 = 8
	hsCertificate         uint8 = 11
	hsCertificateRequest  uint8 = 13
	hsCertificateVerify   uint8 = 15
	hsFinished            uint8 = 20
	hsKeyUpdate           uint8 = 24
	hsMessageHash         uint8 = 254
)

var hsNames = map[uint8]string{
	1: "ClientHello", 2: "ServerHello", 4: "NewSessionTicket", 5: "EndOfEarlyData",
	8: "EncryptedExtensions", 11: "Certificate", 13: "CertificateRequest", 15: "CertificateVerify",
	20: "Finished", 24: "KeyUpdate", 254: "MessageHash",
}

// Extension identifiers.
const (
	extServerName          uint16 = 0
	extSupportedGroups     uint16 = 10
	extSignatureAlgorithms uint16 = 13
	extALPN                uint16 = 16
	extPreSharedKey        uint16 = 41
	extEarlyData           uint16 = 42
	extSupportedVersions   uint16 = 43
	extCookie              uint16 = 44
	extPSKKeyExchangeModes uint16 = 45
	extKeyShare            uint16 = 51
)

// Named groups.
const (
	X25519    uint16 = 0x001d
	CurveP256 uint16 = 0x0017
)

const (
	versionTLS13 uint16 = 0x0304
	versionTLS12 uint16 = 0x0303
	pskModeDHE   uint8  = 1
)

// helloRetryRequestRandom is SHA-256("HelloRetryRequest") (RFC 8446 §4.1.3).
var helloRetryRequestRandom = []byte{
	0xCF, 0x21, 0xAD, 0x74, 0xE5, 0x9A, 0x61, 0x11, 0xBE, 0x1D, 0x8C, 0x02, 0x1E, 0x65, 0xB8, 0x91,
	0xC2, 0xA2, 0x11, 0x16, 0x7A, 0xBB, 0x8C, 0x5E, 0x07, 0x9E, 0x09, 0xE2, 0xC8, 0xA8, 0x33, 0x9C,
}

// Downgrade sentinels (RFC 8446 §4.1.3): last 8 bytes of ServerHello.random when negotiating <1.3.
var (
	downgradeTLS12 = []byte("DOWNGRD\x01")
	downgradeTLS11 = []byte("DOWNGRD\x00")
)

func hsFrame(typ uint8, body []byte) []byte {
	out := make([]byte, 0, 4+len(body))
	out = append(out, typ, byte(len(body)>>16), byte(len(body)>>8), byte(len(body)))
	return append(out, body...)
}

// splitHandshake separates the 4-byte header from a complete message.
func splitHandshake(msg []byte) (typ uint8, body []byte) { return msg[0], msg[4:] }

type keyShareEntry struct {
	group uint16
	data  []byte
}

type pskIdentity struct {
	identity []byte
	age      uint32
}

// extReader iterates a block of extensions rejecting duplicates and truncation.
func readExtensions(p *parser, f func(id uint16, data *parser) error) error {
	seen := map[uint16]bool{}
	for !p.empty() {
		id := p.u16()
		data := p.sub16()
		if !p.ok() {
			return fail(AlertDecodeError, "malformed extension block")
		}
		if seen[id] {
			return fail(AlertIllegalParameter, "duplicate extension %d", id)
		}
		seen[id] = true
		if err := f(id, data); err != nil {
			return err
		}
		if !data.ok() || !data.empty() {
			return fail(AlertDecodeError, "malformed body of extension %d", id)
		}
	}
	return nil
}

// ---------- ClientHello ----------

type clientHello struct {
	raw          []byte
	random       []byte
	sessionID    []byte
	suites       []uint16
	compression  []byte
	serverName   string
	groups       []uint16
	sigAlgs      []uint16
	alpn         []string
	versions     []uint16
	keyShares    []keyShareEntry
	pskModes     []uint8
	cookie       []byte
	psks         []pskIdentity
	binders      [][]byte
	earlyData    bool
	bindersStart int // offset in raw of the binders vector (for truncated-transcript hashing)
	hasExt       map[uint16]bool
}

func (m *clientHello) marshal() []byte {
	var b builder
	b.u16(versionTLS12)
	b.raw(m.random)
	b.vec8(func(b *builder) { b.raw(m.sessionID) })
	b.vec16(func(b *builder) {
		for _, s := range m.suites {
			b.u16(s)
		}
	})
	b.vec8(func(b *builder) { b.raw([]byte{0}) })
	bindersAt := -1
	b.vec16(func(b *builder) {
		ext := func(id uint16, f func(*builder)) {
			b.u16(id)
			b.vec16(f)
		}
		if m.serverName != "" {
			ext(extServerName, func(b *builder) {
				b.vec16(func(b *builder) {
					b.u8(0)
					b.vec16(func(b *builder) { b.raw([]byte(m.serverName)) })
				})
			})
		}
		ext(extSupportedVersions, func(b *builder) {
			b.vec8(func(b *builder) {
				for _, v := range m.versions {
					b.u16(v)
				}
			})
		})
		ext(extSupportedGroups, func(b *builder) {
			b.vec16(func(b *builder) {
				for _, g := range m.groups {
					b.u16(g)
				}
			})
		})
		ext(extSignatureAlgorithms, func(b *builder) {
			b.vec16(func(b *builder) {
				for _, s := range m.sigAlgs {
					b.u16(s)
				}
			})
		})
		if len(m.alpn) > 0 {
			ext(extALPN, func(b *builder) {
				b.vec16(func(b *builder) {
					for _, p := range m.alpn {
						b.vec8(func(b *builder) { b.raw([]byte(p)) })
					}
				})
			})
		}
		if len(m.keyShares) > 0 || m.hasExt[extKeyShare] {
			ext(extKeyShare, func(b *builder) {
				b.vec16(func(b *builder) {
					for _, ks := range m.keyShares {
						b.u16(ks.group)
						b.vec16(func(b *builder) { b.raw(ks.data) })
					}
				})
			})
		}
		if len(m.pskModes) > 0 {
			ext(extPSKKeyExchangeModes, func(b *builder) {
				b.vec8(func(b *builder) { b.raw(m.pskModes) })
			})
		}
		if len(m.cookie) > 0 {
			ext(extCookie, func(b *builder) { b.vec16(func(b *builder) { b.raw(m.cookie) }) })
		}
		if len(m.psks) > 0 { // must be last
			b.u16(extPreSharedKey)
			b.vec16(func(b *builder) {
				b.vec16(func(b *builder) {
					for _, p := range m.psks {
						b.vec16(func(b *builder) { b.raw(p.identity) })
						b.u32(p.age)
					}
				})
				bindersAt = len(b.b)
				b.vec16(func(b *builder) {
					for _, bd := range m.binders {
						b.vec8(func(b *builder) { b.raw(bd) })
					}
				})
			})
		}
	})
	body := b.b
	raw := hsFrame(hsClientHello, body)
	if bindersAt >= 0 {
		m.bindersStart = 4 + bindersAt
	} else {
		m.bindersStart = -1
	}
	m.raw = raw
	return raw
}

func parseClientHello(msg []byte) (*clientHello, error) {
	_, body := splitHandshake(msg)
	p := newParser(body)
	m := &clientHello{raw: msg, hasExt: map[uint16]bool{}, bindersStart: -1}
	ver := p.u16()
	m.random = p.bytes(32)
	m.sessionID = p.vecBytes(1)
	cs := p.sub16()
	for !cs.empty() && cs.ok() {
		m.suites = append(m.suites, cs.u16())
	}
	m.compression = p.vecBytes(1)
	if !p.ok() || !cs.ok() {
		return nil, fail(AlertDecodeError, "malformed ClientHello")
	}
	if len(m.suites) == 0 || len(m.suites)*2 > 1<<15 {
		return nil, fail(AlertDecodeError, "ClientHello offers no cipher suites")
	}
	if len(m.sessionID) > 32 {
		return nil, fail(AlertIllegalParameter, "session id too long")
	}
	if !bytes.Equal(m.compression, []byte{0}) {
		return nil, fail(AlertIllegalParameter, "ClientHello must offer exactly the null compression method")
	}
	_ = ver
	extStart := len(body) - p.left()
	if p.empty() {
		return m, nil // no extensions: caller rejects for lack of supported_versions
	}
	exts := p.sub16()
	if !p.ok() || !p.empty() {
		return nil, fail(AlertDecodeError, "trailing data after ClientHello extensions")
	}
	var lastID uint16
	err := readExtensions(exts, func(id uint16, d *parser) error {
		m.hasExt[id] = true
		lastID = id
		switch id {
		case extServerName:
			list := d.sub16()
			for !list.empty() && list.ok() {
				typ := list.u8()
				name := list.vecBytes(2)
				if typ == 0 && m.serverName == "" {
					m.serverName = string(name)
					if m.serverName == "" {
						return fail(AlertDecodeError, "empty server name")
					}
				}
			}
			if !list.ok() {
				return fail(AlertDecodeError, "malformed server_name")
			}
		case extSupportedGroups:
			l := d.sub16()
			for !l.empty() && l.ok() {
				m.groups = append(m.groups, l.u16())
			}
			if !l.ok() {
				return fail(AlertDecodeError, "malformed supported_groups")
			}
		case extSignatureAlgorithms:
			l := d.sub16()
			for !l.empty() && l.ok() {
				m.sigAlgs = append(m.sigAlgs, l.u16())
			}
			if !l.ok() {
				return fail(AlertDecodeError, "malformed signature_algorithms")
			}
		case extALPN:
			l := d.sub16()
			for !l.empty() && l.ok() {
				pr := l.vecBytes(1)
				if len(pr) == 0 {
					return fail(AlertDecodeError, "empty ALPN protocol name")
				}
				m.alpn = append(m.alpn, string(pr))
			}
			if !l.ok() {
				return fail(AlertDecodeError, "malformed ALPN")
			}
		case extSupportedVersions:
			l := d.sub8()
			for !l.empty() && l.ok() {
				m.versions = append(m.versions, l.u16())
			}
			if !l.ok() {
				return fail(AlertDecodeError, "malformed supported_versions")
			}
		case extKeyShare:
			l := d.sub16()
			seen := map[uint16]bool{}
			for !l.empty() && l.ok() {
				g := l.u16()
				kx := l.vecBytes(2)
				if !l.ok() {
					break
				}
				if seen[g] {
					return fail(AlertIllegalParameter, "duplicate key share for group %d", g)
				}
				seen[g] = true
				m.keyShares = append(m.keyShares, keyShareEntry{g, kx})
			}
			if !l.ok() {
				return fail(AlertDecodeError, "malformed key_share")
			}
		case extPSKKeyExchangeModes:
			m.pskModes = append([]uint8(nil), d.vecBytes(1)...)
		case extCookie:
			m.cookie = d.vecBytes(2)
			if len(m.cookie) == 0 {
				return fail(AlertDecodeError, "empty cookie")
			}
		case extEarlyData:
			m.earlyData = true
		case extPreSharedKey:
			ids := d.sub16()
			for !ids.empty() && ids.ok() {
				id := ids.vecBytes(2)
				age := ids.u32()
				m.psks = append(m.psks, pskIdentity{id, age})
			}
			// binders vector begins right after identities; compute its offset in raw.
			bindersOff := len(msg) - d.left()
			bs := d.sub16()
			for !bs.empty() && bs.ok() {
				m.binders = append(m.binders, bs.vecBytes(1))
			}
			if !ids.ok() || !bs.ok() || len(m.psks) == 0 {
				return fail(AlertDecodeError, "malformed pre_shared_key")
			}
			if len(m.psks) != len(m.binders) {
				return fail(AlertIllegalParameter, "PSK identity/binder count mismatch")
			}
			m.bindersStart = bindersOff
		default:
			d.take(d.left()) // unknown / unsupported extensions are skipped (RFC 8446 §4.2)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	_ = extStart
	if m.hasExt[extPreSharedKey] && lastID != extPreSharedKey {
		return nil, fail(AlertIllegalParameter, "pre_shared_key must be the last extension")
	}
	return m, nil
}

// ---------- ServerHello / HelloRetryRequest ----------

type serverHello struct {
	raw       []byte
	random    []byte
	sessionID []byte
	suite     uint16
	version   uint16 // supported_versions selection
	keyShare  keyShareEntry
	// for HRR the keyShare.data is empty and keyShare.group is the selected group
	hrr       bool
	cookie    []byte
	pskSelect int // -1 when absent
	hasKeyShr bool
	legacyVer uint16
}

func (m *serverHello) marshal() []byte {
	var b builder
	b.u16(versionTLS12)
	b.raw(m.random)
	b.vec8(func(b *builder) { b.raw(m.sessionID) })
	b.u16(m.suite)
	b.u8(0)
	b.vec16(func(b *builder) {
		b.u16(extSupportedVersions)
		b.vec16(func(b *builder) { b.u16(versionTLS13) })
		if m.hasKeyShr {
			b.u16(extKeyShare)
			b.vec16(func(b *builder) {
				b.u16(m.keyShare.group)
				if !m.hrr {
					b.vec16(func(b *builder) { b.raw(m.keyShare.data) })
				}
			})
		}
		if len(m.cookie) > 0 {
			b.u16(extCookie)
			b.vec16(func(b *builder) { b.vec16(func(b *builder) { b.raw(m.cookie) }) })
		}
		if m.pskSelect >= 0 {
			b.u16(extPreSharedKey)
			b.vec16(func(b *builder) { b.u16(uint16(m.pskSelect)) })
		}
	})
	m.raw = hsFrame(hsServerHello, b.b)
	return m.raw
}

func parseServerHello(msg []byte) (*serverHello, error) {
	_, body := splitHandshake(msg)
	p := newParser(body)
	m := &serverHello{raw: msg, pskSelect: -1}
	m.legacyVer = p.u16()
	m.random = p.bytes(32)
	m.sessionID = p.vecBytes(1)
	m.suite = p.u16()
	comp := p.u8()
	if !p.ok() {
		return nil, fail(AlertDecodeError, "malformed ServerHello")
	}
	m.hrr = bytes.Equal(m.random, helloRetryRequestRandom)
	if len(m.sessionID) > 32 {
		return nil, fail(AlertIllegalParameter, "session id too long")
	}
	if comp != 0 {
		return nil, fail(AlertIllegalParameter, "ServerHello selects compression %d", comp)
	}
	if p.empty() {
		return m, nil // TLS 1.2-style hello with no extensions; caller decides
	}
	exts := p.sub16()
	if !p.ok() || !p.empty() {
		return nil, fail(AlertDecodeError, "trailing data after ServerHello extensions")
	}
	err := readExtensions(exts, func(id uint16, d *parser) error {
		switch id {
		case extSupportedVersions:
			m.version = d.u16()
		case extKeyShare:
			m.hasKeyShr = true
			m.keyShare.group = d.u16()
			if !m.hrr {
				m.keyShare.data = d.vecBytes(2)
			}
		case extCookie:
			m.cookie = d.vecBytes(2)
			if len(m.cookie) == 0 {
				return fail(AlertDecodeError, "empty cookie")
			}
		case extPreSharedKey:
			m.pskSelect = int(d.u16())
		default:
			return fail(AlertUnsupportedExtension, "ServerHello carries unsolicited extension %d", id)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return m, nil
}

// ---------- EncryptedExtensions ----------

type encryptedExtensions struct {
	alpn       string
	hasALPN    bool
	serverName bool
}

func (m *encryptedExtensions) marshal() []byte {
	var b builder
	b.vec16(func(b *builder) {
		if m.serverName {
			b.u16(extServerName)
			b.vec16(func(b *builder) {})
		}
		if m.hasALPN {
			b.u16(extALPN)
			b.vec16(func(b *builder) {
				b.vec16(func(b *builder) { b.vec8(func(b *builder) { b.raw([]byte(m.alpn)) }) })
			})
		}
	})
	return hsFrame(hsEncryptedExtensions, b.b)
}

func parseEncryptedExtensions(msg []byte) (*encryptedExtensions, error) {
	_, body := splitHandshake(msg)
	p := newParser(body)
	exts := p.sub16()
	if !p.ok() || !p.empty() {
		return nil, fail(AlertDecodeError, "malformed EncryptedExtensions")
	}
	m := &encryptedExtensions{}
	err := readExtensions(exts, func(id uint16, d *parser) error {
		switch id {
		case extServerName:
			m.serverName = true
		case extALPN:
			l := d.sub16()
			pr := l.vecBytes(1)
			if !l.ok() || !l.empty() || len(pr) == 0 {
				return fail(AlertDecodeError, "malformed ALPN in EncryptedExtensions")
			}
			m.alpn, m.hasALPN = string(pr), true
		case extSupportedGroups:
			d.take(d.left())
		case extSignatureAlgorithms, extKeyShare, extSupportedVersions, extCookie,
			extPreSharedKey, extPSKKeyExchangeModes:
			return fail(AlertIllegalParameter, "extension %d not allowed in EncryptedExtensions", id)
		default:
			return fail(AlertUnsupportedExtension, "unsolicited extension %d in EncryptedExtensions", id)
		}
		return nil
	})
	return m, err
}

// ---------- Certificate / CertificateRequest / CertificateVerify ----------

type certificateMsg struct {
	context []byte
	certs   [][]byte
}

func (m *certificateMsg) marshal() []byte {
	var b builder
	b.vec8(func(b *builder) { b.raw(m.context) })
	b.vec24(func(b *builder) {
		for _, c := range m.certs {
			b.vec24(func(b *builder) { b.raw(c) })
			b.vec16(func(b *builder) {}) // no per-certificate extensions
		}
	})
	return hsFrame(hsCertificate, b.b)
}

func parseCertificate(msg []byte) (*certificateMsg, error) {
	_, body := splitHandshake(msg)
	p := newParser(body)
	m := &certificateMsg{}
	m.context = p.vecBytes(1)
	list := p.sub24()
	if !p.ok() || !p.empty() {
		return nil, fail(AlertDecodeError, "malformed Certificate")
	}
	for !list.empty() && list.ok() {
		c := list.vecBytes(3)
		exts := list.sub16()
		if !list.ok() || len(c) == 0 {
			return nil, fail(AlertDecodeError, "malformed certificate entry")
		}
		if err := readExtensions(exts, func(id uint16, d *parser) error {
			d.take(d.left()) // status_request / SCT: accepted, ignored
			return nil
		}); err != nil {
			return nil, err
		}
		m.certs = append(m.certs, c)
	}
	if !list.ok() {
		return nil, fail(AlertDecodeError, "malformed certificate list")
	}
	return m, nil
}

type certificateRequest struct {
	context []byte
	sigAlgs []uint16
}

func (m *certificateRequest) marshal() []byte {
	var b builder
	b.vec8(func(b *builder) { b.raw(m.context) })
	b.vec16(func(b *builder) {
		b.u16(extSignatureAlgorithms)
		b.vec16(func(b *builder) {
			b.vec16(func(b *builder) {
				for _, s := range m.sigAlgs {
					b.u16(s)
				}
			})
		})
	})
	return hsFrame(hsCertificateRequest, b.b)
}

func parseCertificateRequest(msg []byte) (*certificateRequest, error) {
	_, body := splitHandshake(msg)
	p := newParser(body)
	m := &certificateRequest{}
	m.context = p.vecBytes(1)
	exts := p.sub16()
	if !p.ok() || !p.empty() {
		return nil, fail(AlertDecodeError, "malformed CertificateRequest")
	}
	have := false
	err := readExtensions(exts, func(id uint16, d *parser) error {
		if id == extSignatureAlgorithms {
			have = true
			l := d.sub16()
			for !l.empty() && l.ok() {
				m.sigAlgs = append(m.sigAlgs, l.u16())
			}
			if !l.ok() {
				return fail(AlertDecodeError, "malformed signature_algorithms")
			}
			return nil
		}
		d.take(d.left()) // certificate_authorities, oid_filters, ... ignored
		return nil
	})
	if err != nil {
		return nil, err
	}
	if !have {
		return nil, fail(AlertMissingExtension, "CertificateRequest lacks signature_algorithms")
	}
	return m, nil
}

type certificateVerify struct {
	alg uint16
	sig []byte
}

func (m *certificateVerify) marshal() []byte {
	var b builder
	b.u16(m.alg)
	b.vec16(func(b *builder) { b.raw(m.sig) })
	return hsFrame(hsCertificateVerify, b.b)
}

func parseCertificateVerify(msg []byte) (*certificateVerify, error) {
	_, body := splitHandshake(msg)
	p := newParser(body)
	m := &certificateVerify{alg: p.u16(), sig: p.vecBytes(2)}
	if !p.ok() || !p.empty() {
		return nil, fail(AlertDecodeError, "malformed CertificateVerify")
	}
	return m, nil
}

// ---------- NewSessionTicket / KeyUpdate ----------

type newSessionTicket struct {
	lifetime uint32
	ageAdd   uint32
	nonce    []byte
	ticket   []byte
}

func (m *newSessionTicket) marshal() []byte {
	var b builder
	b.u32(m.lifetime)
	b.u32(m.ageAdd)
	b.vec8(func(b *builder) { b.raw(m.nonce) })
	b.vec16(func(b *builder) { b.raw(m.ticket) })
	b.vec16(func(b *builder) {})
	return hsFrame(hsNewSessionTicket, b.b)
}

func parseNewSessionTicket(msg []byte) (*newSessionTicket, error) {
	_, body := splitHandshake(msg)
	p := newParser(body)
	m := &newSessionTicket{lifetime: p.u32(), ageAdd: p.u32()}
	m.nonce = p.vecBytes(1)
	m.ticket = p.vecBytes(2)
	exts := p.sub16()
	if !p.ok() || !p.empty() || len(m.ticket) == 0 {
		return nil, fail(AlertDecodeError, "malformed NewSessionTicket")
	}
	if err := readExtensions(exts, func(id uint16, d *parser) error { d.take(d.left()); return nil }); err != nil {
		return nil, err
	}
	return m, nil
}

func keyUpdateMsg(requestPeer bool) []byte {
	v := byte(0)
	if requestPeer {
		v = 1
	}
	return hsFrame(hsKeyUpdate, []byte{v})
}

func parseKeyUpdate(msg []byte) (requested bool, err error) {
	_, body := splitHandshake(msg)
	if len(body) != 1 || body[0] > 1 {
		return false, fail(AlertIllegalParameter, "malformed KeyUpdate")
	}
	return body[0] == 1, nil
}
