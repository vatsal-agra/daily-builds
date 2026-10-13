package tls13_test

import (
	"bytes"
	"net"
	"testing"

	"keyhole/tls13"
)

func dialWith(t testing.TB, l net.Listener, cfg *tls13.Config) (*tls13.Conn, error) {
	t.Helper()
	raw, err := net.Dial("tcp", l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { raw.Close() })
	deadline(raw)
	c := tls13.Client(raw, cfg)
	return c, c.Handshake()
}

func roundTrip(t testing.TB, c *tls13.Conn, msg []byte) {
	t.Helper()
	if _, err := c.Write(msg); err != nil {
		t.Fatalf("write: %v", err)
	}
	got := make([]byte, len(msg))
	if _, err := ioReadFull(c, got); err != nil {
		t.Fatalf("read: %v", err)
	}
	if !bytes.Equal(got, msg) {
		t.Fatalf("echo mismatch: got %d bytes", len(got))
	}
}

func ioReadFull(c *tls13.Conn, b []byte) (int, error) {
	n := 0
	for n < len(b) {
		m, err := c.Read(b[n:])
		n += m
		if err != nil {
			return n, err
		}
	}
	return n, nil
}

func TestBasicHandshakeAllSuites(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	for _, suite := range []uint16{tls13.TLS_AES_128_GCM_SHA256, tls13.TLS_AES_256_GCM_SHA384, tls13.TLS_CHACHA20_POLY1305_SHA256} {
		t.Run(tls13.SuiteName(suite), func(t *testing.T) {
			l := listen(t)
			scfg := serverCfg(p)
			scfg.CipherSuites = []uint16{suite}
			echoServer(t, l, scfg)
			ccfg := clientCfg(p)
			c, err := dialWith(t, l, ccfg)
			if err != nil {
				t.Fatal(err)
			}
			st := c.ConnectionState()
			if st.CipherSuite != suite || st.Version != 0x0304 {
				t.Fatalf("state %+v", st)
			}
			roundTrip(t, c, []byte("hello keyhole"))
			big := bytes.Repeat([]byte("0123456789abcdef"), 5000) // spans several records
			roundTrip(t, c, big)
		})
	}
}
