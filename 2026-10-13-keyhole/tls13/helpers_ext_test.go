package tls13_test

import (
	"crypto/x509"
	"io"
	"net"
	"sync"
	"testing"
	"time"

	"keyhole/pki"
	"keyhole/tls13"
)

type testPKI struct {
	ca     *pki.CA
	pool   *x509.CertPool
	server *tls13.Certificate
	client *tls13.Certificate
}

var (
	pkiMu    sync.Mutex
	pkiCache = map[string]*testPKI{}
)

// newPKI returns a CA, a server certificate with the given key type and a client certificate.
func newPKI(t testing.TB, keyType string) *testPKI {
	t.Helper()
	pkiMu.Lock()
	defer pkiMu.Unlock()
	if p, ok := pkiCache[keyType]; ok {
		return p
	}
	ca, err := pki.NewCA("Keyhole Test CA", "ecdsa-p256")
	if err != nil {
		t.Fatal(err)
	}
	srv, _, err := ca.Issue(pki.Options{CommonName: "localhost", DNSNames: []string{"localhost", "example.test"}, IPs: []net.IP{net.ParseIP("127.0.0.1")}, KeyType: keyType})
	if err != nil {
		t.Fatal(err)
	}
	cli, _, err := ca.Issue(pki.Options{CommonName: "alice", KeyType: "ecdsa-p256", Client: true})
	if err != nil {
		t.Fatal(err)
	}
	p := &testPKI{ca, ca.Pool(), srv, cli}
	pkiCache[keyType] = p
	return p
}

func listen(t testing.TB) net.Listener {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { l.Close() })
	return l
}

// echoServer accepts connections and echoes until EOF. Errors from each connection are sent on errs.
func echoServer(t testing.TB, l net.Listener, cfg *tls13.Config) (conns chan *tls13.Conn, errs chan error) {
	conns, errs = make(chan *tls13.Conn, 512), make(chan error, 512)
	go func() {
		for {
			raw, err := l.Accept()
			if err != nil {
				return
			}
			go func() {
				c := tls13.Server(raw, cfg)
				if err := c.Handshake(); err != nil {
					errs <- err
					raw.Close()
					return
				}
				conns <- c
				_, err := io.Copy(c, c)
				errs <- err
				c.Close()
			}()
		}
	}()
	return
}

func deadline(c net.Conn) { c.SetDeadline(time.Now().Add(10 * time.Second)) }

func clientCfg(p *testPKI) *tls13.Config {
	return &tls13.Config{ServerName: "localhost", RootCAs: p.pool}
}

func serverCfg(p *testPKI) *tls13.Config {
	return &tls13.Config{Certificates: []tls13.Certificate{*p.server}}
}
