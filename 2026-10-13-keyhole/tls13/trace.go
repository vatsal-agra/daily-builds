package tls13

import (
	"crypto/x509"
	"fmt"
	"strings"
	"time"
)

// TraceEvent is emitted for every record, handshake message and state change when Config.Trace is set.
type TraceEvent struct {
	At     time.Time
	Side   string // "client" or "server"
	Dir    string // "send", "recv" or "-"
	Kind   string // "record", "handshake", "alert", "keys", "info"
	Name   string
	Detail string
	Bytes  int
}

func (c *Conn) trace(dir, kind, name, detail string, n int) {
	if c.cfg.Trace == nil {
		return
	}
	side := "server"
	if c.isClient {
		side = "client"
	}
	c.cfg.Trace(TraceEvent{At: c.cfg.now(), Side: side, Dir: dir, Kind: kind, Name: name, Detail: detail, Bytes: n})
}

// HandshakeName returns the message name for a handshake type byte.
func HandshakeName(t uint8) string {
	if n, ok := hsNames[t]; ok {
		return n
	}
	return fmt.Sprintf("handshake(%d)", t)
}

func groupList(gs []uint16) string {
	var s []string
	for _, g := range gs {
		s = append(s, GroupName(g))
	}
	return strings.Join(s, ",")
}

func suiteList(ids []uint16) string {
	var s []string
	for _, id := range ids {
		n := SuiteName(id)
		if n == "unknown" {
			n = fmt.Sprintf("0x%04x", id)
		}
		s = append(s, strings.TrimPrefix(n, "TLS_"))
	}
	return strings.Join(s, ",")
}

// DescribeHandshake renders a one-line summary of a complete handshake message (header included).
// It never panics on malformed input.
func DescribeHandshake(msg []byte) string {
	if len(msg) < 4 {
		return "(truncated)"
	}
	typ := msg[0]
	switch typ {
	case hsClientHello:
		m, err := parseClientHello(msg)
		if err != nil {
			return "malformed: " + err.Error()
		}
		parts := []string{"suites=" + suiteList(m.suites)}
		if m.serverName != "" {
			parts = append(parts, "sni="+m.serverName)
		}
		if len(m.groups) > 0 {
			parts = append(parts, "groups="+groupList(m.groups))
		}
		var ks []uint16
		for _, k := range m.keyShares {
			ks = append(ks, k.group)
		}
		if len(ks) > 0 {
			parts = append(parts, "key_share="+groupList(ks))
		}
		if len(m.alpn) > 0 {
			parts = append(parts, "alpn="+strings.Join(m.alpn, ","))
		}
		if len(m.psks) > 0 {
			parts = append(parts, fmt.Sprintf("psk=%d", len(m.psks)))
		}
		if len(m.cookie) > 0 {
			parts = append(parts, "cookie")
		}
		return strings.Join(parts, " ")
	case hsServerHello:
		m, err := parseServerHello(msg)
		if err != nil {
			return "malformed: " + err.Error()
		}
		kind := "ServerHello"
		if m.hrr {
			kind = "HelloRetryRequest"
		}
		s := fmt.Sprintf("%s suite=%s", kind, strings.TrimPrefix(SuiteName(m.suite), "TLS_"))
		if m.hasKeyShr {
			s += " group=" + GroupName(m.keyShare.group)
		}
		if m.pskSelect >= 0 {
			s += fmt.Sprintf(" psk=%d", m.pskSelect)
		}
		return s
	case hsEncryptedExtensions:
		m, err := parseEncryptedExtensions(msg)
		if err != nil {
			return "malformed: " + err.Error()
		}
		if m.hasALPN {
			return "alpn=" + m.alpn
		}
		return "no alpn"
	case hsCertificate:
		m, err := parseCertificate(msg)
		if err != nil {
			return "malformed: " + err.Error()
		}
		if len(m.certs) == 0 {
			return "empty certificate list"
		}
		s := fmt.Sprintf("%d certificate(s)", len(m.certs))
		if cert, err := x509.ParseCertificate(m.certs[0]); err == nil {
			s += " leaf=" + cert.Subject.String()
		}
		return s
	case hsCertificateRequest:
		m, err := parseCertificateRequest(msg)
		if err != nil {
			return "malformed: " + err.Error()
		}
		var n []string
		for _, a := range m.sigAlgs {
			n = append(n, SigAlgName(a))
		}
		return "sigalgs=" + strings.Join(n, ",")
	case hsCertificateVerify:
		m, err := parseCertificateVerify(msg)
		if err != nil {
			return "malformed: " + err.Error()
		}
		return fmt.Sprintf("%s sig=%dB", SigAlgName(m.alg), len(m.sig))
	case hsFinished:
		return fmt.Sprintf("verify_data=%dB", len(msg)-4)
	case hsNewSessionTicket:
		m, err := parseNewSessionTicket(msg)
		if err != nil {
			return "malformed: " + err.Error()
		}
		return fmt.Sprintf("lifetime=%ds ticket=%dB", m.lifetime, len(m.ticket))
	case hsKeyUpdate:
		req, err := parseKeyUpdate(msg)
		if err != nil {
			return "malformed"
		}
		if req {
			return "update_requested"
		}
		return "update_not_requested"
	}
	return fmt.Sprintf("%dB", len(msg)-4)
}
