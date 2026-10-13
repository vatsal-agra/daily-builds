package tls13_test

import (
	"crypto/tls"
	"errors"
	"io"
	"net"
	"sync"
	"testing"
	"time"

	"keyhole/pki"
	"keyhole/tls13"
)

// pairHandshake runs a client and a server handshake over loopback and returns both errors.
func pairHandshake(t testing.TB, ccfg, scfg *tls13.Config) (cc, sc *tls13.Conn, cerr, serr error) {
	t.Helper()
	l := listen(t)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		raw, err := l.Accept()
		if err != nil {
			serr = err
			return
		}
		deadline(raw)
		sc = tls13.Server(raw, scfg)
		serr = sc.Handshake()
		if serr != nil {
			// let the peer read our alert before the socket goes away
			raw.Close()
		}
	}()
	raw, err := net.Dial("tcp", l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	deadline(raw)
	cc = tls13.Client(raw, ccfg)
	cerr = cc.Handshake()
	if cerr != nil {
		raw.Close() // lets a server still waiting on us see EOF instead of a timeout
	}
	wg.Wait()
	t.Cleanup(func() { raw.Close() })
	return
}

func wantAlert(t testing.TB, err error, local bool, a tls13.Alert) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected failure with alert %s, handshake succeeded", a)
	}
	if local {
		var pe *tls13.ProtocolError
		if !errors.As(err, &pe) || pe.Alert != a {
			t.Fatalf("expected local alert %s, got %v", a, err)
		}
		return
	}
	var ae *tls13.AlertError
	if !errors.As(err, &ae) || ae.Alert != a {
		t.Fatalf("expected remote alert %s, got %v", a, err)
	}
}

func TestHelloRetryRequest(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	scfg := serverCfg(p)
	scfg.Groups = []uint16{tls13.CurveP256} // client's first-choice share is X25519 -> HRR
	cc, sc, cerr, serr := pairHandshake(t, clientCfg(p), scfg)
	if cerr != nil || serr != nil {
		t.Fatalf("client=%v server=%v", cerr, serr)
	}
	for name, c := range map[string]*tls13.Conn{"client": cc, "server": sc} {
		st := c.ConnectionState()
		if !st.HelloRetryRequest || st.KeyShareGroup != tls13.CurveP256 {
			t.Fatalf("%s state: %+v", name, st)
		}
	}
	// data still flows
	go func() { cc.Write([]byte("after hrr")) }()
	buf := make([]byte, 9)
	if _, err := ioReadFull(sc, buf); err != nil || string(buf) != "after hrr" {
		t.Fatalf("%q %v", buf, err)
	}
}

func TestHelloRetryRequestAgainstGoAndOpenSSL(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l, _ := goEcho(t, goServerCfg(p, func(c *tls.Config) { c.CurvePreferences = []tls.CurveID{tls.CurveP256} }))
	c, err := dialWith(t, l, clientCfg(p))
	if err != nil {
		t.Fatal(err)
	}
	if st := c.ConnectionState(); !st.HelloRetryRequest || st.KeyShareGroup != tls13.CurveP256 {
		t.Fatalf("state %+v", st)
	}
	roundTrip(t, c, []byte("hrr via crypto/tls"))
}

func TestHandshakeFailures(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	otherCA, _ := pki.NewCA("Other CA", "ecdsa-p256")

	t.Run("unknown CA", func(t *testing.T) {
		ccfg := clientCfg(p)
		ccfg.RootCAs = otherCA.Pool()
		_, _, cerr, serr := pairHandshake(t, ccfg, serverCfg(p))
		wantAlert(t, cerr, true, tls13.AlertUnknownCA)
		wantAlert(t, serr, false, tls13.AlertUnknownCA)
	})
	t.Run("hostname mismatch", func(t *testing.T) {
		ccfg := clientCfg(p)
		ccfg.ServerName = "evil.test"
		_, _, cerr, serr := pairHandshake(t, ccfg, serverCfg(p))
		wantAlert(t, cerr, true, tls13.AlertBadCertificate)
		wantAlert(t, serr, false, tls13.AlertBadCertificate)
	})
	t.Run("expired certificate", func(t *testing.T) {
		ccfg := clientCfg(p)
		ccfg.Now = func() time.Time { return time.Now().Add(5 * 365 * 24 * time.Hour) }
		_, _, cerr, _ := pairHandshake(t, ccfg, serverCfg(p))
		wantAlert(t, cerr, true, tls13.AlertCertificateExpired)
	})
	t.Run("not yet valid", func(t *testing.T) {
		ccfg := clientCfg(p)
		ccfg.Now = func() time.Time { return time.Now().Add(-5 * 365 * 24 * time.Hour) }
		_, _, cerr, _ := pairHandshake(t, ccfg, serverCfg(p))
		wantAlert(t, cerr, true, tls13.AlertCertificateExpired)
	})
	t.Run("no common cipher suite", func(t *testing.T) {
		ccfg, scfg := clientCfg(p), serverCfg(p)
		ccfg.CipherSuites = []uint16{tls13.TLS_AES_128_GCM_SHA256}
		scfg.CipherSuites = []uint16{tls13.TLS_CHACHA20_POLY1305_SHA256}
		_, _, cerr, serr := pairHandshake(t, ccfg, scfg)
		wantAlert(t, serr, true, tls13.AlertHandshakeFailure)
		wantAlert(t, cerr, false, tls13.AlertHandshakeFailure)
	})
	t.Run("no common group", func(t *testing.T) {
		ccfg, scfg := clientCfg(p), serverCfg(p)
		ccfg.Groups = []uint16{tls13.X25519}
		scfg.Groups = []uint16{tls13.CurveP256}
		_, _, cerr, serr := pairHandshake(t, ccfg, scfg)
		wantAlert(t, serr, true, tls13.AlertHandshakeFailure)
		wantAlert(t, cerr, false, tls13.AlertHandshakeFailure)
	})
	t.Run("no application protocol", func(t *testing.T) {
		ccfg, scfg := clientCfg(p), serverCfg(p)
		ccfg.NextProtos = []string{"h3"}
		scfg.NextProtos = []string{"h2"}
		_, _, cerr, serr := pairHandshake(t, ccfg, scfg)
		wantAlert(t, serr, true, tls13.AlertNoApplicationProtocol)
		wantAlert(t, cerr, false, tls13.AlertNoApplicationProtocol)
	})
	t.Run("client certificate required", func(t *testing.T) {
		scfg := serverCfg(p)
		scfg.ClientAuth = tls13.RequireClientCert
		scfg.ClientCAs = p.pool
		_, _, cerr, serr := pairHandshake(t, clientCfg(p), scfg)
		wantAlert(t, serr, true, tls13.AlertCertificateRequired)
		_ = cerr
	})
	t.Run("client cert from untrusted CA", func(t *testing.T) {
		bad, _, _ := otherCA.Issue(pki.Options{CommonName: "mallory", Client: true})
		ccfg, scfg := clientCfg(p), serverCfg(p)
		ccfg.ClientCertificate = bad
		scfg.ClientAuth = tls13.RequireClientCert
		scfg.ClientCAs = p.pool
		_, _, _, serr := pairHandshake(t, ccfg, scfg)
		wantAlert(t, serr, true, tls13.AlertUnknownCA)
	})
	t.Run("server ServerName required", func(t *testing.T) {
		_, _, cerr, _ := pairHandshake(t, &tls13.Config{RootCAs: p.pool}, serverCfg(p))
		if cerr == nil {
			t.Fatal("client without ServerName must refuse to verify")
		}
	})
	t.Run("TLS 1.2-only server", func(t *testing.T) {
		l, err := tls.Listen("tcp", "127.0.0.1:0", &tls.Config{MaxVersion: tls.VersionTLS12,
			Certificates: []tls.Certificate{{Certificate: p.server.Chain, PrivateKey: p.server.Key}}})
		if err != nil {
			t.Fatal(err)
		}
		defer l.Close()
		go func() {
			c, err := l.Accept()
			if err == nil {
				c.(*tls.Conn).Handshake()
				c.Close()
			}
		}()
		_, err = dialWith(t, l, clientCfg(p))
		wantAlert(t, err, false, tls13.AlertProtocolVersion) // crypto/tls rejects our 1.3-only hello itself
	})
}

func TestMutualTLS(t *testing.T) {
	for _, mode := range []tls13.ClientAuthMode{tls13.RequestClientCert, tls13.RequireClientCert} {
		p := newPKI(t, "ecdsa-p256")
		scfg := serverCfg(p)
		scfg.ClientAuth = mode
		scfg.ClientCAs = p.pool
		ccfg := clientCfg(p)
		ccfg.ClientCertificate = p.client
		cc, sc, cerr, serr := pairHandshake(t, ccfg, scfg)
		if cerr != nil || serr != nil {
			t.Fatalf("mode %d: client=%v server=%v", mode, cerr, serr)
		}
		pc := sc.ConnectionState().PeerCertificates
		if len(pc) != 1 || pc[0].Subject.CommonName != "alice" {
			t.Fatalf("server saw client certs %v", pc)
		}
		_ = cc
	}
	// RequestClientCert accepts an anonymous client.
	p := newPKI(t, "ecdsa-p256")
	scfg := serverCfg(p)
	scfg.ClientAuth = tls13.RequestClientCert
	scfg.ClientCAs = p.pool
	_, sc, cerr, serr := pairHandshake(t, clientCfg(p), scfg)
	if cerr != nil || serr != nil || len(sc.ConnectionState().PeerCertificates) != 0 {
		t.Fatalf("anonymous client: %v %v", cerr, serr)
	}
	// Go client presenting a certificate to our server.
	l := listen(t)
	scfg2 := serverCfg(p)
	scfg2.ClientAuth = tls13.RequireClientCert
	scfg2.ClientCAs = p.pool
	conns, _ := echoServer(t, l, scfg2)
	c, err := tls.Dial("tcp", l.Addr().String(), &tls.Config{ServerName: "localhost", RootCAs: p.pool, MinVersion: tls.VersionTLS13,
		Certificates: []tls.Certificate{{Certificate: p.client.Chain, PrivateKey: p.client.Key}}})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	c.Write([]byte("x"))
	io.ReadFull(c, make([]byte, 1))
	sconn := <-conns
	if got := sconn.ConnectionState().PeerCertificates; len(got) != 1 || got[0].Subject.CommonName != "alice" {
		t.Fatalf("crypto/tls client cert not seen: %v", got)
	}
}
