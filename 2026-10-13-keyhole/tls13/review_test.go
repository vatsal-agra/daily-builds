package tls13_test

import (
	"bytes"
	"context"
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"os/exec"
	"strings"
	"sync"
	"testing"
	"time"

	"keyhole/pki"
	"keyhole/tls13"
)

// Regression tests that came out of the adversarial review (see REVIEW.md).

// Fragmenting every record into tiny pieces exercises handshake messages split across records.
func TestFragmentedRecordsEverywhere(t *testing.T) {
	p := newPKI(t, "rsa2048") // big Certificate message
	for _, frag := range []int{1, 7, 100} {
		t.Run(fmt.Sprint(frag), func(t *testing.T) {
			l := listen(t)
			scfg := serverCfg(p)
			scfg.MaxRecordPlaintext = frag
			echoServer(t, l, scfg)
			ccfg := clientCfg(p)
			ccfg.MaxRecordPlaintext = frag
			c, err := dialWith(t, l, ccfg)
			if err != nil {
				t.Fatal(err)
			}
			roundTrip(t, c, bytes.Repeat([]byte("frag"), 200))
		})
	}
	// and against the independent implementations
	gl, _ := goEcho(t, goServerCfg(p, nil))
	ccfg := clientCfg(p)
	ccfg.MaxRecordPlaintext = 3
	c, err := dialWith(t, gl, ccfg)
	if err != nil {
		t.Fatalf("crypto/tls rejected fragmented records from us: %v", err)
	}
	roundTrip(t, c, []byte("tiny records"))
	l := listen(t)
	scfg := serverCfg(p)
	scfg.MaxRecordPlaintext = 5
	echoServer(t, l, scfg)
	gc, err := tls.Dial("tcp", l.Addr().String(), &tls.Config{ServerName: "localhost", RootCAs: p.pool, MinVersion: tls.VersionTLS13})
	if err != nil {
		t.Fatalf("crypto/tls could not read our fragmented handshake: %v", err)
	}
	gc.Close()
}

func TestRecordPaddingInterop(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l, _ := goEcho(t, goServerCfg(p, nil))
	ccfg := clientCfg(p)
	ccfg.RecordPadBlock = 256
	c, err := dialWith(t, l, ccfg)
	if err != nil {
		t.Fatal(err)
	}
	roundTrip(t, c, []byte("padded"))
	roundTrip(t, c, bytes.Repeat([]byte{'p'}, 16384)) // full-size record must not overflow with padding
	l2 := listen(t)
	scfg := serverCfg(p)
	scfg.RecordPadBlock = 1000
	echoServer(t, l2, scfg)
	gc, err := tls.Dial("tcp", l2.Addr().String(), &tls.Config{ServerName: "localhost", RootCAs: p.pool, MinVersion: tls.VersionTLS13})
	if err != nil {
		t.Fatal(err)
	}
	gc.Write(bytes.Repeat([]byte{'z'}, 20000))
	io.ReadFull(gc, make([]byte, 20000))
	gc.Close()
}

func TestZeroLengthWriteSendsNothing(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	echoServer(t, l, serverCfg(p))
	c, err := dialWith(t, l, clientCfg(p))
	if err != nil {
		t.Fatal(err)
	}
	if n, err := c.Write(nil); n != 0 || err != nil {
		t.Fatalf("Write(nil) = %d, %v", n, err)
	}
	roundTrip(t, c, []byte("still fine"))
}

func TestConcurrentReadWriteWithKeyUpdates(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	scfg := serverCfg(p)
	scfg.KeyUpdateAfter = 3
	echoServer(t, l, scfg)
	ccfg := clientCfg(p)
	ccfg.KeyUpdateAfter = 4
	c, err := dialWith(t, l, ccfg)
	if err != nil {
		t.Fatal(err)
	}
	const writers, per = 4, 200
	var wg sync.WaitGroup
	for w := 0; w < writers; w++ {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			for i := 0; i < per; i++ {
				if _, err := c.Write([]byte("0123456789")); err != nil {
					t.Error(err)
					return
				}
				if i%50 == 0 {
					c.KeyUpdate(i%100 == 0)
				}
			}
		}(w)
	}
	got := 0
	done := make(chan struct{})
	go func() {
		buf := make([]byte, 4096)
		for got < writers*per*10 {
			n, err := c.Read(buf)
			if err != nil {
				t.Error(err)
				break
			}
			got += n
		}
		close(done)
	}()
	wg.Wait()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatalf("stalled with %d/%d bytes", got, writers*per*10)
	}
}

func TestHandshakeCalledConcurrentlyAndStateBeforeHandshake(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	echoServer(t, l, serverCfg(p))
	raw, _ := net.Dial("tcp", l.Addr().String())
	deadline(raw)
	c := tls13.Client(raw, clientCfg(p))
	var wg sync.WaitGroup
	for i := 0; i < 5; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if err := c.Handshake(); err != nil {
				t.Error(err)
			}
			_ = c.ConnectionState()
		}()
	}
	wg.Wait()
	roundTrip(t, c, []byte("ok"))
}

func TestCloseDuringHandshakeDoesNotHang(t *testing.T) {
	l := listen(t)
	go func() { // a server that accepts and then says nothing
		c, _ := l.Accept()
		time.Sleep(3 * time.Second)
		if c != nil {
			c.Close()
		}
	}()
	raw, _ := net.Dial("tcp", l.Addr().String())
	c := tls13.Client(raw, &tls13.Config{ServerName: "localhost", InsecureSkipVerify: true})
	errc := make(chan error, 1)
	go func() { errc <- c.Handshake() }()
	time.Sleep(100 * time.Millisecond)
	c.Close()
	select {
	case err := <-errc:
		if err == nil {
			t.Fatal("handshake succeeded against a mute server")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Close() during Handshake() did not unblock it")
	}
}

func TestHandshakeDeadline(t *testing.T) {
	l := listen(t)
	go func() { c, _ := l.Accept(); time.Sleep(2 * time.Second); c.Close() }()
	raw, _ := net.Dial("tcp", l.Addr().String())
	raw.SetDeadline(time.Now().Add(300 * time.Millisecond))
	start := time.Now()
	err := tls13.Client(raw, &tls13.Config{ServerName: "localhost", InsecureSkipVerify: true}).Handshake()
	if err == nil || time.Since(start) > time.Second {
		t.Fatalf("deadline not honoured: %v after %v", err, time.Since(start))
	}
}

func TestIntermediateChainAndIPServerName(t *testing.T) {
	root, _ := pki.NewCA("Root", "ecdsa-p384")
	inter, err := root.IssueIntermediate("Intermediate", "ecdsa-p256")
	if err != nil {
		t.Fatal(err)
	}
	leaf, _, err := inter.Issue(pki.Options{CommonName: "leaf", DNSNames: []string{"localhost"}, IPs: []net.IP{net.ParseIP("127.0.0.1")}, KeyType: "ed25519"})
	if err != nil {
		t.Fatal(err)
	}
	leaf.Chain = append(leaf.Chain, inter.DER) // server sends leaf + intermediate; root is the client's anchor
	l := listen(t)
	echoServer(t, l, &tls13.Config{Certificates: []tls13.Certificate{*leaf}})
	for _, name := range []string{"localhost", "127.0.0.1"} {
		c, err := dialWith(t, l, &tls13.Config{ServerName: name, RootCAs: root.Pool()})
		if err != nil {
			t.Fatalf("ServerName %s: %v", name, err)
		}
		if n := len(c.ConnectionState().VerifiedChains[0]); n != 3 {
			t.Fatalf("verified chain length %d", n)
		}
		roundTrip(t, c, []byte("chain"))
	}
	// Missing intermediate => unknown_ca
	leaf2 := *leaf
	leaf2.Chain = leaf.Chain[:1]
	l2 := listen(t)
	echoServer(t, l2, &tls13.Config{Certificates: []tls13.Certificate{leaf2}})
	_, err = dialWith(t, l2, &tls13.Config{ServerName: "localhost", RootCAs: root.Pool()})
	wantAlert(t, err, true, tls13.AlertUnknownCA)
}

func TestGetCertificateBySNI(t *testing.T) {
	ca, _ := pki.NewCA("CA", "ecdsa-p256")
	a, _, _ := ca.Issue(pki.Options{CommonName: "a.test", DNSNames: []string{"a.test"}})
	b, _, _ := ca.Issue(pki.Options{CommonName: "b.test", DNSNames: []string{"b.test"}, KeyType: "ed25519"})
	l := listen(t)
	echoServer(t, l, &tls13.Config{GetCertificate: func(name string) (*tls13.Certificate, error) {
		switch name {
		case "a.test":
			return a, nil
		case "b.test":
			return b, nil
		}
		return nil, fmt.Errorf("unknown host %q", name)
	}})
	for _, n := range []string{"a.test", "b.test"} {
		c, err := dialWith(t, l, &tls13.Config{ServerName: n, RootCAs: ca.Pool()})
		if err != nil {
			t.Fatalf("%s: %v", n, err)
		}
		if got := c.ConnectionState().PeerCertificates[0].Subject.CommonName; got != n {
			t.Fatalf("asked for %s, served %s", n, got)
		}
	}
	_, err := dialWith(t, l, &tls13.Config{ServerName: "c.test", RootCAs: ca.Pool()})
	wantAlert(t, err, false, tls13.AlertUnrecognizedName)
}

func TestCorruptedTicketsFallBackToFullHandshake(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	echoServer(t, l, serverCfg(p))
	cache := tls13.NewSessionCache()
	ccfg := clientCfg(p)
	ccfg.SessionCache = cache
	c, err := dialWith(t, l, ccfg)
	if err != nil {
		t.Fatal(err)
	}
	roundTrip(t, c, []byte("a"))
	c.Close()
	sess := cache.Take("localhost", time.Now())
	if sess == nil {
		t.Fatal("no ticket")
	}
	for name, mut := range map[string]func(*tls13.ClientSession){
		"flipped ticket bit": func(s *tls13.ClientSession) { s.Ticket[len(s.Ticket)/2] ^= 4 },
		"truncated ticket":   func(s *tls13.ClientSession) { s.Ticket = s.Ticket[:10] },
		"wrong PSK (binder fails)": func(s *tls13.ClientSession) {
			s.PSK = bytes.Repeat([]byte{9}, len(s.PSK))
		},
	} {
		s2 := *sess
		s2.Ticket = append([]byte(nil), sess.Ticket...)
		mut(&s2)
		cache.Put("localhost", &s2)
		c2, err := dialWith(t, l, ccfg)
		if name == "wrong PSK (binder fails)" {
			// A bad binder is an authentication failure: the server aborts with decrypt_error.
			wantAlert(t, err, false, tls13.AlertDecryptError)
			continue
		}
		if err != nil || c2.ConnectionState().DidResume {
			t.Fatalf("%s: err=%v resumed=%v", name, err, err == nil && c2.ConnectionState().DidResume)
		}
		roundTrip(t, c2, []byte("ok"))
	}
}

func TestOpenSSLHRRPlusResumption(t *testing.T) {
	ossl := needOpenSSL(t)
	p := newPKI(t, "ecdsa-p256")
	_, _, certFile, keyFile := writePKI(t, p)
	port := freePort(t)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, ossl, "s_server", "-accept", port, "-cert", certFile, "-key", keyFile, "-tls1_3", "-www", "-groups", "P-256")
	cmd.Start()
	defer func() { cancel(); cmd.Wait() }()
	addr := "127.0.0.1:" + port
	waitPort(t, addr)
	ccfg := clientCfg(p)
	ccfg.SessionCache = tls13.NewSessionCache()
	for i := 0; i < 2; i++ {
		raw, _ := net.Dial("tcp", addr)
		deadline(raw)
		c := tls13.Client(raw, ccfg)
		if err := c.Handshake(); err != nil {
			t.Fatalf("run %d: %v", i, err)
		}
		st := c.ConnectionState()
		if !st.HelloRetryRequest || st.KeyShareGroup != tls13.CurveP256 || st.DidResume != (i == 1) {
			t.Fatalf("run %d: %+v", i, st)
		}
		fmt.Fprintf(c, "GET / HTTP/1.0\r\n\r\n")
		body, _ := io.ReadAll(c)
		if !strings.Contains(string(body), "200 ok") {
			t.Fatalf("run %d: bad response %.200s", i, body)
		}
		raw.Close()
	}
}

// Throughput sanity: the hand-written ChaCha20-Poly1305 must not be pathologically slow.
func BenchmarkChaChaThroughput(b *testing.B) {
	p := newPKI(b, "ecdsa-p256")
	l := listen(b)
	scfg := serverCfg(p)
	scfg.CipherSuites = []uint16{tls13.TLS_CHACHA20_POLY1305_SHA256}
	go func() {
		raw, _ := l.Accept()
		c := tls13.Server(raw, scfg)
		io.Copy(io.Discard, c)
	}()
	raw, _ := net.Dial("tcp", l.Addr().String())
	ccfg := clientCfg(p)
	ccfg.CipherSuites = []uint16{tls13.TLS_CHACHA20_POLY1305_SHA256}
	c := tls13.Client(raw, ccfg)
	if err := c.Handshake(); err != nil {
		b.Fatal(err)
	}
	buf := make([]byte, 1<<20)
	b.SetBytes(int64(len(buf)))
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		c.Write(buf)
	}
	c.Close()
}
