package tls13

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"errors"
	"io"
	"math/big"
	"net"
	"testing"
	"time"
)

// White-box tests that talk raw bytes to a real server / client to prove hostile input produces
// the right alert and never a panic or hang.

func selfSigned(t testing.TB) (Certificate, *x509.CertPool) {
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	tpl := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "localhost"}, DNSNames: []string{"localhost"},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), KeyUsage: x509.KeyUsageDigitalSignature,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}, IsCA: true, BasicConstraintsValid: true}
	der, err := x509.CreateCertificate(rand.Reader, tpl, tpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	leaf, _ := x509.ParseCertificate(der)
	pool := x509.NewCertPool()
	pool.AddCert(leaf)
	return Certificate{Chain: [][]byte{der}, Key: key}, pool
}

// rawServer starts a keyhole server; returns a raw client socket and the server's handshake result.
func rawServer(t *testing.T, mod func(*Config)) (net.Conn, chan error) {
	cert, _ := selfSigned(t)
	cfg := &Config{Certificates: []Certificate{cert}}
	if mod != nil {
		mod(cfg)
	}
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	res := make(chan error, 1)
	go func() {
		defer l.Close()
		raw, err := l.Accept()
		if err != nil {
			res <- err
			return
		}
		raw.SetDeadline(time.Now().Add(5 * time.Second))
		err = Server(raw, cfg).Handshake()
		res <- err
		raw.Close()
	}()
	c, err := net.Dial("tcp", l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	c.SetDeadline(time.Now().Add(5 * time.Second))
	t.Cleanup(func() { c.Close() })
	return c, res
}

func goodClientHello(t testing.TB) *clientHello {
	kx, err := newKeyExchange(rand.Reader, X25519)
	if err != nil {
		t.Fatal(err)
	}
	random, sid := make([]byte, 32), make([]byte, 32)
	rand.Read(random)
	rand.Read(sid)
	return &clientHello{random: random, sessionID: sid, suites: []uint16{TLS_AES_128_GCM_SHA256}, compression: []byte{0},
		serverName: "localhost", groups: []uint16{X25519, CurveP256}, sigAlgs: supportedSigAlgs, versions: []uint16{versionTLS13},
		keyShares: []keyShareEntry{{X25519, kx.public()}}, pskModes: []uint8{pskModeDHE}}
}

func record(typ uint8, body []byte) []byte {
	return append([]byte{typ, 3, 3, byte(len(body) >> 8), byte(len(body))}, body...)
}

// expectAlert reads the server's reply and requires a plaintext fatal alert with the given code.
func expectAlert(t *testing.T, c net.Conn, want Alert) {
	t.Helper()
	hdr := make([]byte, 5)
	if _, err := io.ReadFull(c, hdr); err != nil {
		t.Fatalf("no alert received: %v", err)
	}
	body := make([]byte, int(hdr[3])<<8|int(hdr[4]))
	io.ReadFull(c, body)
	if hdr[0] != recAlert || len(body) != 2 || body[0] != 2 || Alert(body[1]) != want {
		t.Fatalf("got record type %d body %x, want fatal alert %s", hdr[0], body, want)
	}
}

func expectServerErr(t *testing.T, res chan error, want Alert) {
	t.Helper()
	err := <-res
	var pe *ProtocolError
	if !errors.As(err, &pe) || pe.Alert != want {
		t.Fatalf("server error = %v, want local %s", err, want)
	}
}

// addExtension appends an extension to a marshalled ClientHello (fixing both length fields).
func addExtension(raw []byte, id uint16, data []byte) []byte {
	p := newParser(raw[4:])
	p.u16()
	p.take(32)
	p.vecBytes(1)
	p.vecBytes(2)
	p.vecBytes(1)
	extLenOff := len(raw) - p.left()
	ext := append([]byte{byte(id >> 8), byte(id), byte(len(data) >> 8), byte(len(data))}, data...)
	out := append(append([]byte(nil), raw...), ext...)
	n := int(out[extLenOff])<<8 | int(out[extLenOff+1]) + len(ext)
	out[extLenOff], out[extLenOff+1] = byte(n>>8), byte(n)
	m := len(out) - 4
	out[1], out[2], out[3] = byte(m>>16), byte(m>>8), byte(m)
	return out
}

func TestServerHostileInputs(t *testing.T) {
	type tc struct {
		name  string
		build func(t *testing.T) []byte // bytes to send
		want  Alert
	}
	cases := []tc{
		{"http request on TLS port", func(*testing.T) []byte { return []byte("GET / HTTP/1.1\r\nHost: x\r\n\r\n") }, AlertUnexpectedMessage},
		{"oversized record header", func(*testing.T) []byte { return []byte{22, 3, 3, 0xff, 0xff} }, AlertRecordOverflow},
		{"non-TLS version in record header", func(*testing.T) []byte { return []byte{22, 2, 0, 0, 5, 1, 2, 3, 4, 5} }, AlertProtocolVersion},
		{"plaintext application data", func(*testing.T) []byte { return record(recApplicationData, []byte("hi")) }, AlertUnexpectedMessage},
		{"empty handshake record", func(*testing.T) []byte { return record(recHandshake, nil) }, AlertUnexpectedMessage},
		{"handshake length 16 MiB", func(*testing.T) []byte { return record(recHandshake, []byte{1, 0xff, 0xff, 0xff}) }, AlertDecodeError},
		{"not a ClientHello first", func(*testing.T) []byte { return record(recHandshake, hsFrame(hsFinished, make([]byte, 32))) }, AlertUnexpectedMessage},
		{"truncated ClientHello body", func(*testing.T) []byte { return record(recHandshake, hsFrame(hsClientHello, []byte{3, 3, 1, 2, 3})) }, AlertDecodeError},
		{"no supported_versions (TLS 1.2 client)", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			ch.versions = nil
			// marshal always writes the extension; strip by crafting a TLS1.2-only version list
			ch.versions = []uint16{0x0303, 0x0302}
			return record(recHandshake, ch.marshal())
		}, AlertProtocolVersion},
		{"compression method 1", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			ch.compression = []byte{1}
			return record(recHandshake, ch.marshal())
		}, AlertIllegalParameter},
		{"no cipher suites", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			ch.suites = nil
			return record(recHandshake, ch.marshal())
		}, AlertDecodeError},
		{"only unknown cipher suites", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			ch.suites = []uint16{0x1304, 0xc02f}
			return record(recHandshake, ch.marshal())
		}, AlertHandshakeFailure},
		{"invalid P-256 point", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			ch.keyShares = []keyShareEntry{{CurveP256, append([]byte{4}, make([]byte, 64)...)}}
			return record(recHandshake, ch.marshal())
		}, AlertIllegalParameter},
		{"all-zero X25519 share", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			ch.keyShares = []keyShareEntry{{X25519, make([]byte, 32)}}
			return record(recHandshake, ch.marshal())
		}, AlertIllegalParameter},
		{"short X25519 share", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			ch.keyShares = []keyShareEntry{{X25519, make([]byte, 31)}}
			return record(recHandshake, ch.marshal())
		}, AlertIllegalParameter},
		{"duplicate key_share groups", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			ch.keyShares = append(ch.keyShares, ch.keyShares[0])
			return record(recHandshake, ch.marshal())
		}, AlertIllegalParameter},
		{"duplicate extension", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			raw := addExtension(ch.marshal(), extSupportedGroups, []byte{0, 2, 0, 0x1d})
			return record(recHandshake, raw)
		}, AlertIllegalParameter},
		{"malformed extension body", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			raw := addExtension(ch.marshal(), extCookie, []byte{0, 5, 1})
			return record(recHandshake, raw)
		}, AlertDecodeError},
		{"pre_shared_key not last", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			var psk builder
			psk.vec16(func(b *builder) { b.vec16(func(b *builder) { b.raw([]byte("x")) }); b.u32(0) })
			psk.vec16(func(b *builder) { b.vec8(func(b *builder) { b.raw(make([]byte, 32)) }) })
			raw := addExtension(ch.marshal(), extPreSharedKey, psk.b)
			raw = addExtension(raw, 0xfe00, []byte{1, 2, 3})
			return record(recHandshake, raw)
		}, AlertIllegalParameter},
		{"missing signature_algorithms", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			ch.sigAlgs = nil
			// An empty list is present but useless: server must not find a matching certificate.
			return record(recHandshake, ch.marshal())
		}, AlertHandshakeFailure},
		{"session id too long", func(t *testing.T) []byte {
			ch := goodClientHello(t)
			ch.sessionID = make([]byte, 33)
			return record(recHandshake, ch.marshal())
		}, AlertIllegalParameter},
		{"spurious change_cipher_spec payload", func(*testing.T) []byte { return record(recChangeCipherSpec, []byte{2}) }, AlertUnexpectedMessage},
		{"alert instead of hello", func(*testing.T) []byte { return record(recAlert, []byte{2, 40}) }, Alert(255)},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			conn, res := rawServer(t, nil)
			conn.Write(c.build(t))
			if c.want == 255 { // remote alert case: server surfaces AlertError, sends nothing
				err := <-res
				var ae *AlertError
				if !errors.As(err, &ae) || ae.Alert != AlertHandshakeFailure {
					t.Fatalf("got %v", err)
				}
				return
			}
			expectAlert(t, conn, c.want)
			expectServerErr(t, res, c.want)
		})
	}
}

// A ClientHello may be fragmented across records and still be accepted.
func TestServerAcceptsFragmentedClientHello(t *testing.T) {
	conn, res := rawServer(t, nil)
	raw := goodClientHello(t).marshal()
	for len(raw) > 0 {
		n := 100
		if n > len(raw) {
			n = len(raw)
		}
		conn.Write(record(recHandshake, raw[:n]))
		raw = raw[n:]
		time.Sleep(5 * time.Millisecond)
	}
	hdr := make([]byte, 5)
	if _, err := io.ReadFull(conn, hdr); err != nil || hdr[0] != recHandshake {
		t.Fatalf("expected ServerHello, got %x %v", hdr, err)
	}
	body := make([]byte, int(hdr[3])<<8|int(hdr[4]))
	io.ReadFull(conn, body)
	if body[0] != hsServerHello {
		t.Fatalf("first message %d", body[0])
	}
	conn.Close()
	<-res
}

// After the ServerHello the server must refuse plaintext records.
func TestServerRejectsPlaintextAfterKeys(t *testing.T) {
	conn, res := rawServer(t, nil)
	conn.Write(record(recHandshake, goodClientHello(t).marshal()))
	// drain the server's first flight, then send a plaintext Finished
	go io.Copy(io.Discard, conn)
	time.Sleep(100 * time.Millisecond)
	conn.Write(record(recHandshake, hsFrame(hsFinished, make([]byte, 32))))
	expectServerErr(t, res, AlertUnexpectedMessage)
}

// A garbage "encrypted" record in place of the client Finished must fail the MAC.
func TestServerBadRecordMAC(t *testing.T) {
	conn, res := rawServer(t, nil)
	conn.Write(record(recHandshake, goodClientHello(t).marshal()))
	go io.Copy(io.Discard, conn)
	time.Sleep(100 * time.Millisecond)
	conn.Write(record(recApplicationData, bytes.Repeat([]byte{0xAB}, 64)))
	expectServerErr(t, res, AlertBadRecordMAC)
}

// ---- hostile servers against our client ----

func fakeServer(t *testing.T, script func(c net.Conn)) (addr string) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { l.Close() })
	go func() {
		c, err := l.Accept()
		if err != nil {
			return
		}
		defer c.Close()
		c.SetDeadline(time.Now().Add(5 * time.Second))
		script(c)
	}()
	return l.Addr().String()
}

func readRecordFrom(c net.Conn) (uint8, []byte, error) {
	hdr, body, err := readRawRecord(c)
	return hdr[0], body, err
}

func clientAgainst(t *testing.T, script func(c net.Conn, ch *clientHello)) error {
	_, pool := selfSigned(t)
	addr := fakeServer(t, func(c net.Conn) {
		typ, body, err := readRecordFrom(c)
		if err != nil || typ != recHandshake {
			return
		}
		ch, err := parseClientHello(body)
		if err != nil {
			return
		}
		script(c, ch)
	})
	raw, err := net.Dial("tcp", addr)
	if err != nil {
		t.Fatal(err)
	}
	defer raw.Close()
	raw.SetDeadline(time.Now().Add(5 * time.Second))
	return Client(raw, &Config{ServerName: "localhost", RootCAs: pool}).Handshake()
}

func wantProto(t *testing.T, err error, a Alert) {
	t.Helper()
	var pe *ProtocolError
	if !errors.As(err, &pe) || pe.Alert != a {
		t.Fatalf("got %v, want local alert %s", err, a)
	}
}

func TestClientHostileServers(t *testing.T) {
	good := func(ch *clientHello) *serverHello {
		r := make([]byte, 32)
		rand.Read(r)
		kx, _ := newKeyExchange(rand.Reader, X25519)
		return &serverHello{random: r, sessionID: ch.sessionID, suite: TLS_AES_128_GCM_SHA256, hasKeyShr: true,
			keyShare: keyShareEntry{X25519, kx.public()}, pskSelect: -1}
	}
	send := func(c net.Conn, sh *serverHello) { c.Write(record(recHandshake, sh.marshal())) }

	t.Run("downgrade sentinel without supported_versions", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			r := make([]byte, 32)
			copy(r[24:], downgradeTLS12)
			var b builder
			b.u16(0x0303)
			b.raw(r)
			b.vec8(func(b *builder) { b.raw(ch.sessionID) })
			b.u16(0xc02f)
			b.u8(0)
			c.Write(record(recHandshake, hsFrame(hsServerHello, b.b)))
		})
		wantProto(t, err, AlertIllegalParameter)
	})
	t.Run("TLS 1.2 ServerHello", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			var b builder
			b.u16(0x0303)
			b.raw(make([]byte, 32))
			b.vec8(func(b *builder) { b.raw(ch.sessionID) })
			b.u16(0xc02f)
			b.u8(0)
			c.Write(record(recHandshake, hsFrame(hsServerHello, b.b)))
		})
		wantProto(t, err, AlertProtocolVersion)
	})
	t.Run("session id not echoed", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			sh := good(ch)
			sh.sessionID = []byte{1, 2, 3}
			send(c, sh)
		})
		wantProto(t, err, AlertIllegalParameter)
	})
	t.Run("unoffered cipher suite", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			sh := good(ch)
			sh.suite = 0xc02f
			send(c, sh)
		})
		wantProto(t, err, AlertIllegalParameter)
	})
	t.Run("key share for a group never offered", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			sh := good(ch)
			kx, _ := newKeyExchange(rand.Reader, CurveP256)
			sh.keyShare = keyShareEntry{CurveP256, kx.public()}
			send(c, sh)
		})
		wantProto(t, err, AlertIllegalParameter)
	})
	t.Run("all-zero X25519 server share", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			sh := good(ch)
			sh.keyShare.data = make([]byte, 32)
			send(c, sh)
		})
		wantProto(t, err, AlertIllegalParameter)
	})
	t.Run("selects a PSK we never offered", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			sh := good(ch)
			sh.pskSelect = 0
			send(c, sh)
		})
		wantProto(t, err, AlertIllegalParameter)
	})
	t.Run("two HelloRetryRequests", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			hrr := &serverHello{random: helloRetryRequestRandom, sessionID: ch.sessionID, suite: TLS_AES_128_GCM_SHA256,
				hrr: true, hasKeyShr: true, keyShare: keyShareEntry{group: CurveP256}, pskSelect: -1}
			send(c, hrr)
			if _, _, err := readRecordFrom(c); err != nil { // CCS
				return
			}
			readRecordFrom(c) // second ClientHello
			send(c, hrr)
		})
		wantProto(t, err, AlertUnexpectedMessage)
	})
	t.Run("HRR that changes nothing", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			hrr := &serverHello{random: helloRetryRequestRandom, sessionID: ch.sessionID, suite: TLS_AES_128_GCM_SHA256,
				hrr: true, pskSelect: -1}
			send(c, hrr)
		})
		wantProto(t, err, AlertIllegalParameter)
	})
	t.Run("HRR demanding the group already tried", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			hrr := &serverHello{random: helloRetryRequestRandom, sessionID: ch.sessionID, suite: TLS_AES_128_GCM_SHA256,
				hrr: true, hasKeyShr: true, keyShare: keyShareEntry{group: X25519}, pskSelect: -1}
			send(c, hrr)
		})
		wantProto(t, err, AlertIllegalParameter)
	})
	t.Run("server sends a fatal alert", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			c.Write(record(recAlert, []byte{2, byte(AlertInsufficientSecurity)}))
		})
		var ae *AlertError
		if !errors.As(err, &ae) || ae.Alert != AlertInsufficientSecurity {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("server hangs up mid-handshake", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {})
		if !errors.Is(err, io.ErrUnexpectedEOF) {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("random garbage", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) { c.Write(bytes.Repeat([]byte{0x99}, 64)) })
		if err == nil {
			t.Fatal("garbage accepted")
		}
	})
	t.Run("plaintext application data", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) { c.Write(record(recApplicationData, []byte("surprise"))) })
		wantProto(t, err, AlertUnexpectedMessage)
	})
	t.Run("ServerHello with unsolicited extension", func(t *testing.T) {
		err := clientAgainst(t, func(c net.Conn, ch *clientHello) {
			sh := good(ch)
			raw := sh.marshal()
			raw = append(raw, 0, 0) // placeholder to be replaced below
			raw = raw[:len(raw)-2]
			// append an ALPN extension (never allowed in ServerHello)
			ext := []byte{0, 16, 0, 2, 0, 0}
			n := int(raw[len(raw)-1]) // not used; recompute lengths explicitly
			_ = n
			body := append([]byte(nil), raw[4:]...)
			// extension block length sits at offset 2+32+1+32+2+1 = 70
			el := int(body[70])<<8 | int(body[71]) + len(ext)
			body[70], body[71] = byte(el>>8), byte(el)
			body = append(body, ext...)
			c.Write(record(recHandshake, hsFrame(hsServerHello, body)))
		})
		wantProto(t, err, AlertUnsupportedExtension)
	})
}

func selfSignedFuzz() (Certificate, *x509.CertPool) {
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	tpl := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "x"}, DNSNames: []string{"x"},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), KeyUsage: x509.KeyUsageDigitalSignature}
	der, _ := x509.CreateCertificate(rand.Reader, tpl, tpl, &key.PublicKey, key)
	return Certificate{Chain: [][]byte{der}, Key: key}, nil
}

// RFC 8446 §5.1: a handshake message split across records must not be interleaved with other records.
func TestServerRejectsInterleavedRecordInsideHandshakeMessage(t *testing.T) {
	for _, other := range []struct {
		name string
		rec  []byte
	}{
		{"alert", record(recAlert, []byte{1, 0})},
		{"application data", record(recApplicationData, []byte("x"))},
	} {
		t.Run(other.name, func(t *testing.T) {
			conn, res := rawServer(t, nil)
			raw := goodClientHello(t).marshal()
			conn.Write(record(recHandshake, raw[:50]))
			conn.Write(other.rec)
			expectAlert(t, conn, AlertUnexpectedMessage)
			expectServerErr(t, res, AlertUnexpectedMessage)
		})
	}
}
