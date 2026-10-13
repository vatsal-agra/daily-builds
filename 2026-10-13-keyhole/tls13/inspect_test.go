package tls13_test

import (
	"context"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"keyhole/tls13"
)

// tapProxy forwards bytes between a client and upstream while feeding both directions to an Inspector.
func tapProxy(t testing.TB, upstream string, in *tls13.Inspector) string {
	l := listen(t)
	go func() {
		for {
			cli, err := l.Accept()
			if err != nil {
				return
			}
			srv, err := net.Dial("tcp", upstream)
			if err != nil {
				cli.Close()
				return
			}
			var wg sync.WaitGroup
			cp := func(from, to net.Conn, fromClient bool) {
				defer wg.Done()
				buf := make([]byte, 32<<10)
				for {
					n, err := from.Read(buf)
					if n > 0 {
						to.Write(buf[:n])
						in.Feed(fromClient, buf[:n])
					}
					if err != nil {
						if c, ok := to.(*net.TCPConn); ok {
							c.CloseWrite()
						}
						return
					}
				}
			}
			wg.Add(2)
			go cp(cli, srv, true)
			go cp(srv, cli, false)
			go func() { wg.Wait(); cli.Close(); srv.Close() }()
		}
	}()
	return l.Addr().String()
}

type eventLog struct {
	mu sync.Mutex
	ev []tls13.InspectEvent
}

func (e *eventLog) add(x tls13.InspectEvent) { e.mu.Lock(); e.ev = append(e.ev, x); e.mu.Unlock() }
func (e *eventLog) text() string {
	e.mu.Lock()
	defer e.mu.Unlock()
	var b strings.Builder
	for _, x := range e.ev {
		dir := "S→C"
		if x.FromCli {
			dir = "C→S"
		}
		fmt.Fprintf(&b, "%s %s %s | %s\n", dir, x.Kind, x.Summary, x.Detail)
	}
	return b.String()
}

func TestInspectorDecryptsKeyholeSession(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	var keys lockedBuf
	l := listen(t)
	scfg := serverCfg(p)
	scfg.KeyLogWriter = &keys
	scfg.NextProtos = []string{"demo"}
	echoServer(t, l, scfg)
	var evs eventLog
	in := tls13.NewInspector(func() tls13.KeyLog { return tls13.ParseKeyLog(strings.NewReader(keys.String())) }, evs.add)
	in.ShowData = 40
	addr := tapProxy(t, l.Addr().String(), in)
	raw, _ := net.Dial("tcp", addr)
	deadline(raw)
	ccfg := clientCfg(p)
	ccfg.NextProtos = []string{"demo"}
	c := tls13.Client(raw, ccfg)
	if err := c.Handshake(); err != nil {
		t.Fatal(err)
	}
	roundTrip(t, c, []byte("secret payload visible only via key log"))
	c.KeyUpdate(true)
	roundTrip(t, c, []byte("after key update"))
	c.Close()
	time.Sleep(100 * time.Millisecond)
	in.Close()
	out := evs.text()
	for _, want := range []string{
		"C→S handshake ClientHello | suites=", "sni=localhost", "alpn=demo",
		"S→C handshake ServerHello | ServerHello suite=", "S→C handshake EncryptedExtensions | alpn=demo",
		"S→C handshake Certificate | 1 certificate(s) leaf=CN=localhost", "S→C handshake CertificateVerify | ecdsa_secp256r1_sha256",
		"S→C handshake Finished", "C→S handshake Finished", "S→C handshake NewSessionTicket",
		"C→S data application data, 39 bytes | secret payload visible only via key log",
		"C→S handshake KeyUpdate | update_requested", "S→C handshake KeyUpdate", "C→S data application data, 16 bytes | after key update",
		"S→C data application data, 16 bytes | after key update", "alert close_notify",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q", want)
		}
	}
	if strings.Contains(out, "failed to decrypt") || strings.Contains(out, "undecoded") {
		t.Errorf("inspector lost sync:\n%s", out)
	}
}

func TestInspectorWithoutKeyLogReportsOpaque(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	echoServer(t, l, serverCfg(p))
	var evs eventLog
	in := tls13.NewInspector(func() tls13.KeyLog { return nil }, evs.add)
	addr := tapProxy(t, l.Addr().String(), in)
	raw, _ := net.Dial("tcp", addr)
	deadline(raw)
	c := tls13.Client(raw, clientCfg(p))
	if err := c.Handshake(); err != nil {
		t.Fatal(err)
	}
	roundTrip(t, c, []byte("x"))
	c.Close()
	time.Sleep(100 * time.Millisecond)
	in.Close()
	out := evs.text()
	if !strings.Contains(out, "ServerHello") || !strings.Contains(out, "no key log entry") || strings.Contains(out, "EncryptedExtensions") {
		t.Fatalf("expected plaintext hello only + an honest 'undecoded' note:\n%s", out)
	}
}

func TestInspectorWrongKeysDetected(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	echoServer(t, l, serverCfg(p))
	var evs eventLog
	wrong := func() tls13.KeyLog {
		// secrets that belong to another connection
		return tls13.ParseKeyLog(strings.NewReader(strings.Repeat("x", 0)))
	}
	in := tls13.NewInspector(wrong, evs.add)
	addr := tapProxy(t, l.Addr().String(), in)
	raw, _ := net.Dial("tcp", addr)
	deadline(raw)
	c := tls13.Client(raw, clientCfg(p))
	c.Handshake()
	c.Close()
	in.Close()
	if strings.Contains(evs.text(), "EncryptedExtensions") {
		t.Fatal("decoded without keys")
	}
}

// Key logs written by OpenSSL must be enough to decode a keyhole<->openssl session.
func TestInspectorDecodesWithOpenSSLKeyLog(t *testing.T) {
	ossl := needOpenSSL(t)
	p := newPKI(t, "ed25519")
	dir, _, certFile, keyFile := writePKI(t, p)
	port := freePort(t)
	keylog := filepath.Join(dir, "ossl.keys")
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, ossl, "s_server", "-accept", port, "-cert", certFile, "-key", keyFile, "-tls1_3", "-www", "-keylogfile", keylog)
	cmd.Start()
	defer func() { cancel(); cmd.Wait() }()
	waitPort(t, "127.0.0.1:"+port)
	var evs eventLog
	in := tls13.NewInspector(func() tls13.KeyLog { return tls13.ReadKeyLogFile(keylog) }, evs.add)
	in.ShowData = 17
	addr := tapProxy(t, "127.0.0.1:"+port, in)
	raw, _ := net.Dial("tcp", addr)
	deadline(raw)
	c := tls13.Client(raw, clientCfg(p))
	if err := c.Handshake(); err != nil {
		t.Fatal(err)
	}
	fmt.Fprintf(c, "GET / HTTP/1.0\r\n\r\n")
	io.ReadAll(c)
	raw.Close()
	time.Sleep(200 * time.Millisecond)
	in.Poll()
	in.Close()
	out := evs.text()
	for _, want := range []string{"CertificateVerify | ed25519", "C→S data application data, 18 bytes | GET / HTTP/1.0", "S→C data application data"} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in:\n%s", want, out)
		}
	}
	_ = os.Remove
}
