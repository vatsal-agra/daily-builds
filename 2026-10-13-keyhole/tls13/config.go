package tls13

import (
	"crypto"
	"crypto/rand"
	"crypto/x509"
	"io"
	"sync"
	"time"
)

// Certificate is a certificate chain (leaf first, DER) and its private key.
type Certificate struct {
	Chain [][]byte
	Key   crypto.Signer
}

// ClientAuthMode controls server-side client-certificate handling.
type ClientAuthMode int

const (
	NoClientCert      ClientAuthMode = iota // do not request a certificate
	RequestClientCert                       // request; accept an empty reply, verify if present
	RequireClientCert                       // request; abort with certificate_required if empty
)

// Config configures a Conn. The zero value is usable for a client that verifies against the
// system roots; servers need Certificates.
type Config struct {
	Rand io.Reader        // default crypto/rand
	Now  func() time.Time // default time.Now

	// Server side.
	Certificates []Certificate
	// GetCertificate, if set, picks the certificate from the client's SNI (before Certificates).
	GetCertificate func(serverName string) (*Certificate, error)
	ClientAuth     ClientAuthMode
	ClientCAs      *x509.CertPool // roots used to verify client certificates
	TicketKey      []byte         // 32-byte key sealing session tickets; random per process when nil
	NoTickets      bool           // do not issue NewSessionTicket messages
	// ServerPrefs makes the server pick the cipher suite by its own preference order (default on).

	// Client side.
	ServerName         string
	RootCAs            *x509.CertPool
	InsecureSkipVerify bool
	ClientCertificate  *Certificate
	SessionCache       *SessionCache

	// Both sides.
	NextProtos   []string
	CipherSuites []uint16 // preference order; default AES-128-GCM, ChaCha20, AES-256-GCM
	Groups       []uint16 // preference order; default X25519, P-256
	KeyLogWriter io.Writer
	Trace        func(TraceEvent)

	// KeyUpdateAfter triggers an automatic KeyUpdate once this many records have been sent under
	// one key (default 1<<24; RFC 8446 §5.5 limits AES-GCM to 2^24.5 records).
	KeyUpdateAfter uint64
	// RecordPadBlock, if >0, pads every protected record to a multiple of this many bytes.
	RecordPadBlock int
	// MaxRecordPlaintext caps the plaintext carried by each record we send (default and maximum
	// 16384). Small values force fragmentation, which is useful for interoperability testing.
	MaxRecordPlaintext int
	// MaxHandshakeBytes caps one handshake message (default 128 KiB).
	MaxHandshakeBytes int

	// debug / test hooks
	ticketKey []byte
}

func (c *Config) rand() io.Reader {
	if c.Rand != nil {
		return c.Rand
	}
	return rand.Reader
}

func (c *Config) now() time.Time {
	if c.Now != nil {
		return c.Now()
	}
	return time.Now()
}

func (c *Config) suites() []*suite {
	ids := c.CipherSuites
	if len(ids) == 0 {
		ids = []uint16{TLS_AES_128_GCM_SHA256, TLS_CHACHA20_POLY1305_SHA256, TLS_AES_256_GCM_SHA384}
	}
	var out []*suite
	for _, id := range ids {
		if s := suiteByID(id); s != nil {
			out = append(out, s)
		}
	}
	return out
}

func (c *Config) groups() []uint16 {
	if len(c.Groups) > 0 {
		var out []uint16
		for _, g := range c.Groups {
			if g == X25519 || g == CurveP256 {
				out = append(out, g)
			}
		}
		return out
	}
	return []uint16{X25519, CurveP256}
}

func (c *Config) maxFrag() int {
	if c.MaxRecordPlaintext > 0 && c.MaxRecordPlaintext < maxPlaintext {
		return c.MaxRecordPlaintext
	}
	return maxPlaintext
}

func (c *Config) maxHS() int {
	if c.MaxHandshakeBytes > 0 {
		return c.MaxHandshakeBytes
	}
	return 128 << 10
}

func (c *Config) keyUpdateAfter() uint64 {
	if c.KeyUpdateAfter > 0 {
		return c.KeyUpdateAfter
	}
	return 1 << 24
}

var ticketKeyMu sync.Mutex

func (c *Config) sealKey() []byte {
	if len(c.TicketKey) == 32 {
		return c.TicketKey
	}
	if len(c.TicketKey) != 0 {
		return nil // rejected by validateServer
	}
	ticketKeyMu.Lock()
	defer ticketKeyMu.Unlock()
	if c.ticketKey == nil {
		k := make([]byte, 32)
		if _, err := io.ReadFull(c.rand(), k); err != nil {
			return nil
		}
		c.ticketKey = k
	}
	return c.ticketKey
}

// ConnectionState describes a completed handshake.
type ConnectionState struct {
	Version            uint16
	CipherSuite        uint16
	ServerName         string // SNI the client sent (server side) or requested (client side)
	NegotiatedProtocol string // ALPN
	PeerCertificates   []*x509.Certificate
	VerifiedChains     [][]*x509.Certificate
	DidResume          bool
	HelloRetryRequest  bool
	KeyShareGroup      uint16
	SignatureAlgorithm uint16 // CertificateVerify scheme used by the peer (0 on resumption)
	TicketsReceived    int
	KeyUpdatesSent     int
	KeyUpdatesReceived int
}

// GroupName / SigAlgName give human-readable names for traces and the CLI.
func GroupName(g uint16) string {
	switch g {
	case X25519:
		return "x25519"
	case CurveP256:
		return "secp256r1"
	}
	return "group(" + itoa(int(g)) + ")"
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}
