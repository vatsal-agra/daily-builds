package tls13

import (
	"bytes"
	"crypto/rand"
	"net"
	"testing"
	"time"
)

// Native Go fuzzers. `go test` runs the seed corpus; `go test -fuzz=FuzzX -fuzztime=30s` explores.
// The invariant everywhere: arbitrary bytes never panic, hang, or allocate without bound.

func seedHellos(f *testing.F) {
	kx, _ := newKeyExchange(rand.Reader, X25519)
	ch := &clientHello{random: make([]byte, 32), sessionID: make([]byte, 32), suites: []uint16{0x1301, 0x1303}, compression: []byte{0},
		serverName: "example.test", groups: []uint16{X25519, CurveP256}, sigAlgs: supportedSigAlgs, alpn: []string{"h2", "http/1.1"},
		versions: []uint16{versionTLS13}, keyShares: []keyShareEntry{{X25519, kx.public()}}, pskModes: []uint8{1}, cookie: []byte("cookie"),
		psks: []pskIdentity{{[]byte("ticket"), 7}}, binders: [][]byte{make([]byte, 32)}}
	f.Add(ch.marshal())
	sh := &serverHello{random: make([]byte, 32), sessionID: make([]byte, 32), suite: 0x1301, hasKeyShr: true, keyShare: keyShareEntry{X25519, kx.public()}, pskSelect: 0}
	f.Add(sh.marshal())
	hrr := &serverHello{random: helloRetryRequestRandom, sessionID: nil, suite: 0x1301, hrr: true, hasKeyShr: true, keyShare: keyShareEntry{group: CurveP256}, cookie: []byte("c"), pskSelect: -1}
	f.Add(hrr.marshal())
	f.Add((&encryptedExtensions{alpn: "h2", hasALPN: true, serverName: true}).marshal())
	f.Add((&certificateMsg{certs: [][]byte{{1, 2, 3}, {4, 5}}}).marshal())
	f.Add((&certificateRequest{sigAlgs: supportedSigAlgs}).marshal())
	f.Add((&certificateVerify{alg: Ed25519, sig: make([]byte, 64)}).marshal())
	f.Add((&newSessionTicket{lifetime: 5, ageAdd: 9, nonce: []byte{0}, ticket: []byte("tkt")}).marshal())
	f.Add(keyUpdateMsg(true))
	f.Add(hsFrame(hsFinished, make([]byte, 32)))
}

func FuzzHandshakeParsers(f *testing.F) {
	seedHellos(f)
	f.Fuzz(func(t *testing.T, msg []byte) {
		if len(msg) < 4 {
			return
		}
		// Re-frame so the declared length matches (the framing layer is fuzzed separately).
		framed := hsFrame(msg[0], msg[4:])
		parseClientHello(framed)
		parseServerHello(framed)
		parseEncryptedExtensions(framed)
		parseCertificate(framed)
		parseCertificateRequest(framed)
		parseCertificateVerify(framed)
		parseNewSessionTicket(framed)
		parseKeyUpdate(framed)
		DescribeHandshake(msg)
	})
}

// Whatever parseClientHello accepts must survive a marshal → parse round trip unchanged.
func FuzzClientHelloRoundTrip(f *testing.F) {
	seedHellos(f)
	f.Fuzz(func(t *testing.T, msg []byte) {
		if len(msg) < 4 {
			return
		}
		framed := hsFrame(hsClientHello, msg[4:])
		a, err := parseClientHello(framed)
		if err != nil || len(a.psks) > 0 || len(a.hasExt) == 0 {
			return
		}
		a.sessionID = append([]byte(nil), a.sessionID...)
		b, err := parseClientHello(a.marshal())
		if err != nil {
			t.Fatalf("re-parse of our own marshal failed: %v", err)
		}
		if !bytes.Equal(a.random, b.random) || a.serverName != b.serverName || len(a.suites) != len(b.suites) ||
			len(a.keyShares) != len(b.keyShares) || len(a.alpn) != len(b.alpn) || len(a.groups) != len(b.groups) {
			t.Fatalf("round trip changed the hello")
		}
	})
}

func FuzzRecordOpen(f *testing.F) {
	s := suiteByID(TLS_AES_128_GCM_SHA256)
	var w halfConn
	w.setSecret(s, bytes.Repeat([]byte{1}, 32))
	rec := w.seal(recHandshake, []byte("hello"), 3)
	f.Add(rec)
	f.Add([]byte{23, 3, 3, 0, 0})
	f.Fuzz(func(t *testing.T, rec []byte) {
		r := bytes.NewReader(rec)
		hdr, body, err := readRawRecord(r)
		if err != nil {
			return
		}
		var h halfConn
		h.setSecret(s, bytes.Repeat([]byte{1}, 32))
		h.open(hdr, body)
	})
}

// FuzzServerStream throws an arbitrary byte stream at a live server handshake.
func FuzzServerStream(f *testing.F) {
	kx, _ := newKeyExchange(rand.Reader, X25519)
	ch := &clientHello{random: make([]byte, 32), sessionID: make([]byte, 32), suites: []uint16{0x1301}, compression: []byte{0},
		serverName: "x", groups: []uint16{X25519}, sigAlgs: supportedSigAlgs, versions: []uint16{versionTLS13},
		keyShares: []keyShareEntry{{X25519, kx.public()}}, pskModes: []uint8{1}}
	f.Add(record(recHandshake, ch.marshal()))
	f.Add(append(record(recHandshake, ch.marshal()), record(recApplicationData, []byte("junk"))...))
	f.Add([]byte("GET / HTTP/1.1\r\n\r\n"))
	cert, _ := selfSignedFuzz()
	f.Fuzz(func(t *testing.T, stream []byte) {
		a, b := net.Pipe()
		defer a.Close()
		defer b.Close()
		a.SetDeadline(time.Now().Add(2 * time.Second))
		b.SetDeadline(time.Now().Add(2 * time.Second))
		go func() { // drain whatever the server answers, then feed the stream
			go func() {
				buf := make([]byte, 4096)
				for {
					if _, err := b.Read(buf); err != nil {
						return
					}
				}
			}()
			b.Write(stream)
			b.Close()
		}()
		Server(a, &Config{Certificates: []Certificate{cert}}).Handshake()
	})
}

// FuzzClientStream does the same against the client side.
func FuzzClientStream(f *testing.F) {
	sh := &serverHello{random: make([]byte, 32), suite: 0x1301, hasKeyShr: true, keyShare: keyShareEntry{X25519, make([]byte, 32)}, pskSelect: -1}
	f.Add(record(recHandshake, sh.marshal()))
	f.Add(record(recAlert, []byte{2, 40}))
	f.Fuzz(func(t *testing.T, stream []byte) {
		a, b := net.Pipe()
		defer a.Close()
		defer b.Close()
		a.SetDeadline(time.Now().Add(2 * time.Second))
		b.SetDeadline(time.Now().Add(2 * time.Second))
		go func() {
			go func() {
				buf := make([]byte, 4096)
				for {
					if _, err := b.Read(buf); err != nil {
						return
					}
				}
			}()
			b.Write(stream)
			b.Close()
		}()
		Client(a, &Config{ServerName: "x", InsecureSkipVerify: true}).Handshake()
	})
}
