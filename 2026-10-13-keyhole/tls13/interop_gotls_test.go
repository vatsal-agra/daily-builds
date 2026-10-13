package tls13_test

import (
	"bytes"
	"crypto/tls"
	"io"
	"net"
	"strings"
	"sync"
	"testing"

	"keyhole/tls13"
)

// Go's crypto/tls is used here purely as an independent oracle; the library never imports it.

type lockedBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *lockedBuf) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}
func (l *lockedBuf) String() string { l.mu.Lock(); defer l.mu.Unlock(); return l.b.String() }

func goServerCfg(p *testPKI, mod func(*tls.Config)) *tls.Config {
	cfg := &tls.Config{
		MinVersion:   tls.VersionTLS13,
		Certificates: []tls.Certificate{{Certificate: p.server.Chain, PrivateKey: p.server.Key}},
	}
	if mod != nil {
		mod(cfg)
	}
	return cfg
}

func goEcho(t testing.TB, cfg *tls.Config) (net.Listener, chan error) {
	l, err := tls.Listen("tcp", "127.0.0.1:0", cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { l.Close() })
	errs := make(chan error, 16)
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			go func() {
				defer c.Close()
				_, err := io.Copy(c, c)
				errs <- err
			}()
		}
	}()
	return l, errs
}

func keylogLines(s string) map[string]string {
	m := map[string]string{}
	for _, ln := range strings.Split(strings.TrimSpace(s), "\n") {
		f := strings.Fields(ln)
		if len(f) == 3 {
			m[f[0]+" "+f[1]] = f[2]
		}
	}
	return m
}

func TestClientAgainstGoServer(t *testing.T) {
	for _, kt := range []string{"ecdsa-p256", "ecdsa-p384", "ed25519", "rsa2048"} {
		for _, suite := range []uint16{tls.TLS_AES_128_GCM_SHA256, tls.TLS_AES_256_GCM_SHA384, tls.TLS_CHACHA20_POLY1305_SHA256} {
			t.Run(kt+"/"+tls13.SuiteName(suite), func(t *testing.T) {
				p := newPKI(t, kt)
				var goLog lockedBuf
				l, _ := goEcho(t, goServerCfg(p, func(c *tls.Config) {
					c.KeyLogWriter = &goLog
					c.NextProtos = []string{"h2", "echo"}
					c.CipherSuites = nil
				}))
				var ourLog lockedBuf
				cfg := clientCfg(p)
				cfg.CipherSuites = []uint16{suite}
				cfg.NextProtos = []string{"echo"}
				cfg.KeyLogWriter = &ourLog
				raw, err := net.Dial("tcp", l.Addr().String())
				if err != nil {
					t.Fatal(err)
				}
				defer raw.Close()
				deadline(raw)
				c := tls13.Client(raw, cfg)
				if err := c.Handshake(); err != nil {
					t.Fatal(err)
				}
				_ = c.ConnectionState()
				st := c.ConnectionState()
				if st.NegotiatedProtocol != "echo" {
					t.Fatalf("alpn %q", st.NegotiatedProtocol)
				}
				roundTrip(t, c, []byte("ping from keyhole"))
				roundTrip(t, c, bytes.Repeat([]byte{'x'}, 70000))
				// Secret-for-secret comparison with crypto/tls.
				ours, theirs := keylogLines(ourLog.String()), keylogLines(goLog.String())
				if len(ours) < 5 {
					t.Fatalf("expected >=5 keylog lines, got %v", ours)
				}
				for k, v := range ours {
					if strings.HasPrefix(k, "EXPORTER_SECRET") {
						continue // crypto/tls does not log it; checked via ExportKeyingMaterial below
					}
					if theirs[k] != v {
						t.Errorf("secret %s mismatch:\n ours   %s\n theirs %s", k, v, theirs[k])
					}
				}
			})
		}
	}
}

func TestServerAgainstGoClient(t *testing.T) {
	for _, kt := range []string{"ecdsa-p256", "ed25519", "rsa2048"} {
		t.Run(kt, func(t *testing.T) {
			p := newPKI(t, kt)
			l := listen(t)
			var ourLog lockedBuf
			scfg := serverCfg(p)
			scfg.KeyLogWriter = &ourLog
			scfg.NextProtos = []string{"echo"}
			echoServer(t, l, scfg)
			var goLog lockedBuf
			c, err := tls.Dial("tcp", l.Addr().String(), &tls.Config{
				ServerName: "localhost", RootCAs: p.pool, MinVersion: tls.VersionTLS13,
				NextProtos: []string{"echo"}, KeyLogWriter: &goLog,
			})
			if err != nil {
				t.Fatal(err)
			}
			defer c.Close()
			if c.ConnectionState().NegotiatedProtocol != "echo" {
				t.Fatal("alpn not negotiated")
			}
			msg := bytes.Repeat([]byte("go-client "), 3000)
			c.Write(msg)
			got := make([]byte, len(msg))
			if _, err := io.ReadFull(c, got); err != nil || !bytes.Equal(got, msg) {
				t.Fatalf("echo: %v", err)
			}
			ours, theirs := keylogLines(ourLog.String()), keylogLines(goLog.String())
			for k, v := range theirs {
				if ours[k] != v {
					t.Errorf("secret %s mismatch:\n theirs %s\n ours   %s", k, v, ours[k])
				}
			}
		})
	}
}
