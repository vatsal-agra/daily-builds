package tls13_test

import (
	"bytes"
	"context"
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"keyhole/tls13"
)

func TestResumptionBetweenKeyholePeers(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	for _, suite := range []uint16{tls13.TLS_AES_128_GCM_SHA256, tls13.TLS_AES_256_GCM_SHA384, tls13.TLS_CHACHA20_POLY1305_SHA256} {
		t.Run(tls13.SuiteName(suite), func(t *testing.T) {
			l := listen(t)
			scfg := serverCfg(p)
			scfg.CipherSuites = []uint16{suite}
			echoServer(t, l, scfg)
			cache := tls13.NewSessionCache()
			ccfg := clientCfg(p)
			ccfg.SessionCache = cache
			ccfg.CipherSuites = []uint16{suite}

			c1, err := dialWith(t, l, ccfg)
			if err != nil {
				t.Fatal(err)
			}
			if c1.ConnectionState().DidResume {
				t.Fatal("first connection cannot resume")
			}
			roundTrip(t, c1, []byte("first")) // also lets the client process the NewSessionTicket
			if cache.Len("localhost") != 1 {
				t.Fatalf("cache has %d tickets", cache.Len("localhost"))
			}
			c1.Close()

			c2, err := dialWith(t, l, ccfg)
			if err != nil {
				t.Fatal(err)
			}
			st := c2.ConnectionState()
			if !st.DidResume || len(st.PeerCertificates) != 1 || len(st.VerifiedChains) == 0 || st.SignatureAlgorithm != 0 {
				t.Fatalf("expected PSK resumption with the original (re-verified) chain and no new CertificateVerify, got %+v", st)
			}
			roundTrip(t, c2, []byte("second"))
			// tickets are single-use: the cache entry was consumed, and replaced by the new connection's ticket
			c3, err := dialWith(t, l, ccfg)
			if err != nil || !c3.ConnectionState().DidResume {
				t.Fatalf("third connection should resume via the ticket issued on the second: %v", err)
			}
		})
	}
}

func TestResumptionRejectedFallsBackToFullHandshake(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	scfg := serverCfg(p)
	scfg.TicketKey = bytes.Repeat([]byte{1}, 32)
	echoServer(t, l, scfg)
	cache := tls13.NewSessionCache()
	ccfg := clientCfg(p)
	ccfg.SessionCache = cache
	c1, err := dialWith(t, l, ccfg)
	if err != nil {
		t.Fatal(err)
	}
	roundTrip(t, c1, []byte("x"))
	c1.Close()

	// A second server instance with a different ticket key must not honour the ticket, and the
	// client must transparently complete a full handshake.
	l2 := listen(t)
	scfg2 := serverCfg(p)
	scfg2.TicketKey = bytes.Repeat([]byte{2}, 32)
	echoServer(t, l2, scfg2)
	c2, err := dialWith(t, l2, ccfg)
	if err != nil {
		t.Fatal(err)
	}
	if c2.ConnectionState().DidResume {
		t.Fatal("resumed with a ticket sealed under another key")
	}
	roundTrip(t, c2, []byte("full handshake after rejection"))
}

func TestResumptionWithHelloRetryRequest(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	scfg := serverCfg(p)
	scfg.Groups = []uint16{tls13.CurveP256} // forces an HRR on every connection
	echoServer(t, l, scfg)
	ccfg := clientCfg(p)
	ccfg.SessionCache = tls13.NewSessionCache()
	c1, err := dialWith(t, l, ccfg)
	if err != nil {
		t.Fatal(err)
	}
	roundTrip(t, c1, []byte("a"))
	c1.Close()
	c2, err := dialWith(t, l, ccfg)
	if err != nil {
		t.Fatal(err)
	}
	st := c2.ConnectionState()
	if !st.DidResume || !st.HelloRetryRequest {
		t.Fatalf("want resumption across an HRR, got %+v", st)
	}
	roundTrip(t, c2, []byte("b"))
}

func TestResumptionExpiry(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	echoServer(t, l, serverCfg(p))
	cache := tls13.NewSessionCache()
	ccfg := clientCfg(p)
	ccfg.SessionCache = cache
	c1, _ := dialWith(t, l, ccfg)
	roundTrip(t, c1, []byte("a"))
	c1.Close()
	// Client clock two days later: ticket (24 h lifetime) is not even offered.
	ccfg2 := *ccfg
	ccfg2.Now = func() time.Time { return time.Now().Add(48 * time.Hour) }
	ccfg2.Now = func() time.Time { return time.Now().Add(48 * time.Hour) }
	c2, err := dialWith(t, l, &ccfg2)
	if err == nil && c2.ConnectionState().DidResume {
		t.Fatal("expired ticket was used")
	}
}

func TestResumptionWithGoServer(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l, _ := goEcho(t, goServerCfg(p, nil))
	ccfg := clientCfg(p)
	ccfg.SessionCache = tls13.NewSessionCache()
	c1, err := dialWith(t, l, ccfg)
	if err != nil {
		t.Fatal(err)
	}
	roundTrip(t, c1, []byte("a"))
	c1.Close()
	c2, err := dialWith(t, l, ccfg)
	if err != nil {
		t.Fatal(err)
	}
	if !c2.ConnectionState().DidResume {
		t.Fatal("crypto/tls server did not accept our PSK binder / ticket")
	}
	roundTrip(t, c2, []byte("b"))
}

func TestGoClientResumesWithOurServer(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	echoServer(t, l, serverCfg(p))
	cfg := &tls.Config{ServerName: "localhost", RootCAs: p.pool, MinVersion: tls.VersionTLS13, ClientSessionCache: tls.NewLRUClientSessionCache(4)}
	for i := 0; i < 2; i++ {
		c, err := tls.Dial("tcp", l.Addr().String(), cfg)
		if err != nil {
			t.Fatal(err)
		}
		c.Write([]byte("x"))
		io.ReadFull(c, make([]byte, 1)) // lets crypto/tls process the ticket
		if i == 1 && !c.ConnectionState().DidResume {
			t.Fatal("crypto/tls client could not resume against our server")
		}
		c.Close()
	}
}

func TestKeyUpdate(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	conns, _ := echoServer(t, l, serverCfg(p))
	c, err := dialWith(t, l, clientCfg(p))
	if err != nil {
		t.Fatal(err)
	}
	roundTrip(t, c, []byte("before"))
	if err := c.KeyUpdate(false); err != nil {
		t.Fatal(err)
	}
	roundTrip(t, c, []byte("after our update"))
	if err := c.KeyUpdate(true); err != nil { // ask the server to rotate too
		t.Fatal(err)
	}
	roundTrip(t, c, []byte("after update_requested"))
	roundTrip(t, c, []byte("and again"))
	sc := <-conns
	cst, sst := c.ConnectionState(), sc.ConnectionState()
	if cst.KeyUpdatesSent != 2 || sst.KeyUpdatesReceived != 2 || sst.KeyUpdatesSent != 1 || cst.KeyUpdatesReceived != 1 {
		t.Fatalf("client %+v\nserver %+v", cst, sst)
	}
}

func TestAutomaticKeyUpdate(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	scfg := serverCfg(p)
	scfg.KeyUpdateAfter = 5
	conns, _ := echoServer(t, l, scfg)
	ccfg := clientCfg(p)
	ccfg.KeyUpdateAfter = 7
	c, err := dialWith(t, l, ccfg)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 50; i++ {
		roundTrip(t, c, []byte(fmt.Sprintf("message %d", i)))
	}
	sc := <-conns
	if c.ConnectionState().KeyUpdatesSent < 5 || sc.ConnectionState().KeyUpdatesSent < 5 {
		t.Fatalf("expected several automatic key updates: %+v / %+v", c.ConnectionState(), sc.ConnectionState())
	}
}

func TestKeyUpdateWithGoServer(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l, _ := goEcho(t, goServerCfg(p, nil))
	c, err := dialWith(t, l, clientCfg(p))
	if err != nil {
		t.Fatal(err)
	}
	roundTrip(t, c, []byte("one"))
	if err := c.KeyUpdate(true); err != nil { // crypto/tls must respond with its own KeyUpdate
		t.Fatal(err)
	}
	roundTrip(t, c, []byte("two"))
	roundTrip(t, c, []byte("three"))
	if c.ConnectionState().KeyUpdatesReceived != 1 {
		t.Fatalf("crypto/tls did not answer update_requested: %+v", c.ConnectionState())
	}
}

func TestKeyUpdateFloodIsRejected(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	conns, errs := echoServer(t, l, serverCfg(p))
	c, err := dialWith(t, l, clientCfg(p))
	if err != nil {
		t.Fatal(err)
	}
	<-conns
	go io.Copy(io.Discard, c)
	var sawErr error
	for i := 0; i < 5000 && sawErr == nil; i++ {
		if err := c.KeyUpdate(true); err != nil {
			sawErr = err
		}
		select {
		case sawErr = <-errs:
		default:
		}
	}
	select {
	case sawErr = <-errs:
	case <-time.After(3 * time.Second):
	}
	if sawErr == nil {
		t.Fatal("server tolerated 5000 consecutive update_requested messages")
	}
}

func TestOpenSSLKeyUpdateAndResumption(t *testing.T) {
	ossl := needOpenSSL(t)
	p := newPKI(t, "ecdsa-p256")
	dir, caFile, _, _ := writePKI(t, p)
	_ = dir

	// openssl s_client sends KeyUpdate to us ("K" => update_requested), we must follow and answer.
	l := listen(t)
	conns, _ := echoServer(t, l, serverCfg(p))
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, ossl, "s_client", "-connect", l.Addr().String(), "-tls1_3", "-CAfile", caFile, "-servername", "localhost")
	stdin, _ := cmd.StdinPipe()
	var out lockedBuf
	cmd.Stdout, cmd.Stderr = &out, &out
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	wait := func(s string) {
		for i := 0; i < 100; i++ {
			if strings.Contains(out.String(), s) {
				return
			}
			time.Sleep(50 * time.Millisecond)
		}
		t.Fatalf("never saw %q in:\n%s", s, out.String())
	}
	fmt.Fprint(stdin, "one\n")
	wait("one")
	fmt.Fprint(stdin, "K\n")
	wait("KEYUPDATE")
	fmt.Fprint(stdin, "two\n")
	wait("two")
	fmt.Fprint(stdin, "three\n")
	wait("three")
	sc := <-conns
	if st := sc.ConnectionState(); st.KeyUpdatesReceived != 1 || st.KeyUpdatesSent != 1 {
		t.Fatalf("server state after openssl KeyUpdate: %+v", st)
	}
	stdin.Close()
	cancel()
	cmd.Wait()
}

func TestOpenSSLClientResumesWithOurServer(t *testing.T) {
	ossl := needOpenSSL(t)
	p := newPKI(t, "ecdsa-p256")
	dir, caFile, _, _ := writePKI(t, p)
	l := listen(t)
	echoServer(t, l, serverCfg(p))
	sess := filepath.Join(dir, "sess.pem")
	run := func(args ...string) string {
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		base := []string{"s_client", "-connect", l.Addr().String(), "-tls1_3", "-CAfile", caFile, "-servername", "localhost"}
		cmd := exec.CommandContext(ctx, ossl, append(base, args...)...)
		stdin, _ := cmd.StdinPipe()
		var out lockedBuf
		cmd.Stdout, cmd.Stderr = &out, &out
		cmd.Start()
		fmt.Fprint(stdin, "ping\n")
		for i := 0; i < 100 && !strings.Contains(out.String(), "ping"); i++ {
			time.Sleep(30 * time.Millisecond)
		}
		time.Sleep(100 * time.Millisecond) // let the ticket arrive and be written
		stdin.Close()
		cancel()
		cmd.Wait()
		return out.String()
	}
	first := run("-sess_out", sess)
	if !strings.Contains(first, "New, TLSv1.3") {
		t.Fatalf("first run:\n%s", first)
	}
	second := run("-sess_in", sess)
	if !strings.Contains(second, "Reused, TLSv1.3") {
		t.Fatalf("OpenSSL did not resume against our server:\n%s", second)
	}
}

func TestKeyholeClientResumesWithOpenSSLServer(t *testing.T) {
	ossl := needOpenSSL(t)
	p := newPKI(t, "ecdsa-p256")
	_, _, certFile, keyFile := writePKI(t, p)
	port := freePort(t)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, ossl, "s_server", "-accept", port, "-cert", certFile, "-key", keyFile, "-tls1_3", "-www")
	cmd.Start()
	defer func() { cancel(); cmd.Wait() }()
	addr := "127.0.0.1:" + port
	waitPort(t, addr)
	ccfg := clientCfg(p)
	ccfg.SessionCache = tls13.NewSessionCache()
	for i := 0; i < 3; i++ {
		raw, _ := net.Dial("tcp", addr)
		deadline(raw)
		c := tls13.Client(raw, ccfg)
		if err := c.Handshake(); err != nil {
			t.Fatalf("run %d: %v", i, err)
		}
		fmt.Fprintf(c, "GET / HTTP/1.0\r\n\r\n")
		body, _ := io.ReadAll(c)
		if !strings.Contains(string(body), "Reused, TLSv1.3") == (i > 0) {
			t.Fatalf("run %d: OpenSSL's own status page disagrees about reuse:\n%.300s", i, body)
		}
		if got := c.ConnectionState().DidResume; got != (i > 0) {
			t.Fatalf("run %d: DidResume=%v", i, got)
		}
		raw.Close()
	}
}

func TestMutualTLSWithOpenSSL(t *testing.T) {
	ossl := needOpenSSL(t)
	p := newPKI(t, "ecdsa-p256")
	dir, caFile, _, _ := writePKI(t, p)
	cc, ck := filepath.Join(dir, "cli.pem"), filepath.Join(dir, "cli.key")
	if err := writeCert(cc, ck, p.client); err != nil {
		t.Fatal(err)
	}
	l := listen(t)
	scfg := serverCfg(p)
	scfg.ClientAuth = tls13.RequireClientCert
	scfg.ClientCAs = p.pool
	conns, errs := echoServer(t, l, scfg)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, ossl, "s_client", "-connect", l.Addr().String(), "-tls1_3", "-CAfile", caFile,
		"-servername", "localhost", "-cert", cc, "-key", ck)
	stdin, _ := cmd.StdinPipe()
	var out lockedBuf
	cmd.Stdout, cmd.Stderr = &out, &out
	cmd.Start()
	fmt.Fprint(stdin, "mtls\n")
	for i := 0; i < 100 && !strings.Contains(out.String(), "mtls"); i++ {
		time.Sleep(30 * time.Millisecond)
	}
	select {
	case sc := <-conns:
		if pc := sc.ConnectionState().PeerCertificates; len(pc) < 1 || pc[0].Subject.CommonName != "alice" { // openssl appends the CA it found in -CAfile
			t.Fatalf("server saw %v", pc)
		}
	case err := <-errs:
		t.Fatalf("server: %v\n%s", err, out.String())
	case <-time.After(5 * time.Second):
		t.Fatalf("no connection:\n%s", out.String())
	}
	stdin.Close()
	cancel()
	cmd.Wait()
}
