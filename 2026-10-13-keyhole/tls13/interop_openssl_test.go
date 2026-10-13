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
	"testing"
	"time"

	"keyhole/pki"
	"keyhole/tls13"
)

func needOpenSSL(t testing.TB) string {
	p, err := exec.LookPath("openssl")
	if err != nil {
		t.Skip("openssl not installed")
	}
	return p
}

func freePort(t testing.TB) string {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	_, port, _ := net.SplitHostPort(l.Addr().String())
	return port
}

func waitPort(t testing.TB, addr string) {
	for i := 0; i < 100; i++ {
		if c, err := net.Dial("tcp", addr); err == nil {
			c.Close()
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("server never came up on %s", addr)
}

func writePKI(t testing.TB, p *testPKI) (dir, caFile, certFile, keyFile string) {
	dir = t.TempDir()
	caFile = filepath.Join(dir, "ca.pem")
	os.WriteFile(caFile, pki.EncodeCertPEM(p.ca.DER), 0o644)
	certFile, keyFile = filepath.Join(dir, "srv.pem"), filepath.Join(dir, "srv.key")
	if err := pki.WriteFiles(certFile, keyFile, p.server); err != nil {
		t.Fatal(err)
	}
	return
}

// keyhole client -> openssl s_server
func TestClientAgainstOpenSSLServer(t *testing.T) {
	ossl := needOpenSSL(t)
	for _, kt := range []string{"ecdsa-p256", "ed25519", "rsa2048"} {
		for _, suite := range []string{"TLS_AES_128_GCM_SHA256", "TLS_AES_256_GCM_SHA384", "TLS_CHACHA20_POLY1305_SHA256"} {
			t.Run(kt+"/"+suite, func(t *testing.T) {
				p := newPKI(t, kt)
				dir, _, certFile, keyFile := writePKI(t, p)
				port := freePort(t)
				ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
				defer cancel()
				keylog := filepath.Join(dir, "ossl.keys")
				cmd := exec.CommandContext(ctx, ossl, "s_server", "-accept", port, "-cert", certFile, "-key", keyFile,
					"-tls1_3", "-ciphersuites", suite, "-www", "-keylogfile", keylog, "-alpn", "http/1.1", "-no_ticket")
				if err := cmd.Start(); err != nil {
					t.Fatal(err)
				}
				defer func() { cancel(); cmd.Wait() }()
				addr := "127.0.0.1:" + port
				waitPort(t, addr)

				var ours lockedBuf
				cfg := clientCfg(p)
				cfg.CipherSuites = []uint16{map[string]uint16{
					"TLS_AES_128_GCM_SHA256": tls13.TLS_AES_128_GCM_SHA256, "TLS_AES_256_GCM_SHA384": tls13.TLS_AES_256_GCM_SHA384,
					"TLS_CHACHA20_POLY1305_SHA256": tls13.TLS_CHACHA20_POLY1305_SHA256}[suite]}
				cfg.NextProtos = []string{"http/1.1"}
				cfg.KeyLogWriter = &ours
				raw, err := net.Dial("tcp", addr)
				if err != nil {
					t.Fatal(err)
				}
				defer raw.Close()
				deadline(raw)
				c := tls13.Client(raw, cfg)
				if err := c.Handshake(); err != nil {
					t.Fatalf("handshake: %v", err)
				}
				if got := c.ConnectionState().NegotiatedProtocol; got != "http/1.1" {
					t.Fatalf("alpn %q", got)
				}
				fmt.Fprintf(c, "GET / HTTP/1.0\r\n\r\n")
				body, err := io.ReadAll(c)
				if err != nil && err != io.EOF {
					t.Fatalf("read: %v", err)
				}
				if !strings.Contains(string(body), "HTTP/1.0 200 ok") || !strings.Contains(string(body), "Cipher is "+suite) {
					t.Fatalf("unexpected response:\n%.400s", body)
				}
				kl, _ := os.ReadFile(keylog)
				theirs := keylogLines(string(kl))
				for k, v := range keylogLines(ours.String()) {
					if strings.HasPrefix(k, "EXPORTER") {
						continue
					}
					if theirs[k] != v {
						t.Errorf("secret %s differs from OpenSSL's: ours %s theirs %q", k, v, theirs[k])
					}
				}
			})
		}
	}
}

// keyhole server -> openssl s_client
func TestServerAgainstOpenSSLClient(t *testing.T) {
	ossl := needOpenSSL(t)
	for _, kt := range []string{"ecdsa-p256", "ecdsa-p384", "ed25519", "rsa2048"} {
		t.Run(kt, func(t *testing.T) {
			p := newPKI(t, kt)
			dir, caFile, _, _ := writePKI(t, p)
			l := listen(t)
			var ours lockedBuf
			scfg := serverCfg(p)
			scfg.KeyLogWriter = &ours
			scfg.NextProtos = []string{"h2", "http/1.1"}
			conns, _ := echoServer(t, l, scfg)
			keylog := filepath.Join(dir, "ossl.keys")
			ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, ossl, "s_client", "-connect", l.Addr().String(), "-tls1_3", "-CAfile", caFile,
				"-servername", "localhost", "-verify_return_error", "-verify_hostname", "localhost", "-alpn", "http/1.1",
				"-keylogfile", keylog, "-keymatexport", "keyhole-test", "-keymatexportlen", "32", "-ign_eof")
			cmd.Stdin = strings.NewReader("hello from openssl\n")
			var stdout, stderr lockedBuf
			cmd.Stdout, cmd.Stderr = &stdout, &stderr
			// -ign_eof keeps s_client open after stdin EOF; end it ourselves after the echo arrives.
			if err := cmd.Start(); err != nil {
				t.Fatal(err)
			}
			done := make(chan error, 1)
			go func() { done <- cmd.Wait() }()
			for i := 0; i < 100 && !strings.Contains(stdout.String(), "hello from openssl"); i++ {
				time.Sleep(50 * time.Millisecond)
			}
			cancel()
			<-done
			if !strings.Contains(stdout.String(), "hello from openssl") {
				t.Fatalf("no echo.\nstdout: %s\nstderr: %s", stdout.String(), stderr.String())
			}
			all := stdout.String() + stderr.String()
			i := strings.Index(all, "Keying material: ")
			if i < 0 {
				t.Fatalf("no keying material printed: %s", all)
			}
			theirKM := strings.ToLower(strings.Fields(all[i+len("Keying material: "):])[0])
			sc := <-conns
			km, err := sc.ExportKeyingMaterial("keyhole-test", nil, 32)
			if err != nil || fmt.Sprintf("%x", km) != theirKM {
				t.Fatalf("exporter mismatch: ours %x theirs %s (%v)", km, theirKM, err)
			}
			kl, _ := os.ReadFile(keylog)
			theirs := keylogLines(string(kl))
			for k, v := range keylogLines(ours.String()) {
				if strings.HasPrefix(k, "EXPORTER") {
					continue
				}
				if theirs[k] != v {
					t.Errorf("secret %s differs from OpenSSL's: ours %s theirs %q", k, v, theirs[k])
				}
			}
		})
	}
}

func writeCert(certPath, keyPath string, c *tls13.Certificate) error { return pki.WriteFiles(certPath, keyPath, c) }
