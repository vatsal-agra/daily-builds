package tls13_test

import (
	"errors"
	"io"
	"net"
	"sync"
	"testing"
	"time"

	"keyhole/tls13"
)

// recordProxy sits between a client and an upstream server and lets a test rewrite, drop or
// duplicate whole TLS records in either direction. idx counts records per direction from 0.
type recordProxy struct {
	l        net.Listener
	toClient func(idx int, rec []byte) [][]byte // nil result drops the record; return nil,... to close use closeAfter
	toServer func(idx int, rec []byte) [][]byte
	closeAt  int // close both sockets after this many server->client records have been handled (-1: never)
}

func newProxy(t testing.TB, upstream string, p *recordProxy) string {
	l := listen(t)
	p.l = l
	if p.closeAt == 0 {
		p.closeAt = -1
	}
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
			var once sync.Once
			closeBoth := func() { once.Do(func() { time.Sleep(20 * time.Millisecond); cli.Close(); srv.Close() }) }
			pump := func(from, to net.Conn, f func(int, []byte) [][]byte, closeAt int) {
				defer closeBoth()
				for i := 0; ; i++ {
					hdr := make([]byte, 5)
					if _, err := io.ReadFull(from, hdr); err != nil {
						return
					}
					body := make([]byte, int(hdr[3])<<8|int(hdr[4]))
					if _, err := io.ReadFull(from, body); err != nil {
						return
					}
					rec := append(hdr, body...)
					out := [][]byte{rec}
					if f != nil {
						out = f(i, rec)
					}
					for _, r := range out {
						to.Write(r)
					}
					if closeAt >= 0 && i+1 >= closeAt {
						return
					}
				}
			}
			go pump(srv, cli, p.toClient, p.closeAt)
			go pump(cli, srv, p.toServer, -1)
		}
	}()
	return l.Addr().String()
}

func flip(rec []byte, off int) []byte {
	r := append([]byte(nil), rec...)
	r[off] ^= 0x01
	return r
}

func TestTamperedHandshakeRecordDetected(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	for target := 1; target <= 4; target++ { // each encrypted server record after ServerHello/CCS
		l := listen(t)
		_, errs := echoServer(t, l, serverCfg(p))
		n := 0
		addr := newProxy(t, l.Addr().String(), &recordProxy{toClient: func(idx int, rec []byte) [][]byte {
			if rec[0] == 23 {
				n++
				if n == target {
					return [][]byte{flip(rec, 8)}
				}
			}
			return [][]byte{rec}
		}})
		raw, _ := net.Dial("tcp", addr)
		deadline(raw)
		err := tls13.Client(raw, clientCfg(p)).Handshake()
		var pe *tls13.ProtocolError
		if !errors.As(err, &pe) || pe.Alert != tls13.AlertBadRecordMAC {
			t.Fatalf("target %d: client error = %v", target, err)
		}
		select {
		case serr := <-errs:
			var ae *tls13.AlertError
			if !errors.As(serr, &ae) || ae.Alert != tls13.AlertBadRecordMAC {
				t.Fatalf("target %d: server error = %v", target, serr)
			}
		case <-time.After(3 * time.Second):
			t.Fatalf("target %d: server never learned of the failure", target)
		}
		raw.Close()
	}
}

func TestTamperedApplicationRecord(t *testing.T) {
	p := newPKI(t, "ed25519")
	l := listen(t)
	_, errs := echoServer(t, l, serverCfg(p))
	hsDone := false
	n := 0
	addr := newProxy(t, l.Addr().String(), &recordProxy{toClient: func(idx int, rec []byte) [][]byte {
		if rec[0] == 23 {
			n++
			if hsDone {
				return [][]byte{flip(rec, len(rec)-1)} // corrupt the tag of the first data record
			}
			// server flight: EE, Cert, CV, Fin (4 records or fewer when coalesced) then NewSessionTicket
			if n >= 5 {
				hsDone = true
			}
		}
		return [][]byte{rec}
	}})
	raw, _ := net.Dial("tcp", addr)
	deadline(raw)
	c := tls13.Client(raw, clientCfg(p))
	if err := c.Handshake(); err != nil {
		t.Fatal(err)
	}
	// NewSessionTicket is the 5th encrypted record; reading it requires a Read call.
	c.Write([]byte("hello"))
	buf := make([]byte, 16)
	_, err := c.Read(buf)
	var pe *tls13.ProtocolError
	if !errors.As(err, &pe) || pe.Alert != tls13.AlertBadRecordMAC {
		t.Fatalf("client Read error = %v", err)
	}
	select {
	case serr := <-errs:
		var ae *tls13.AlertError
		if !errors.As(serr, &ae) || ae.Alert != tls13.AlertBadRecordMAC {
			t.Fatalf("server error = %v", serr)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("server never saw the alert")
	}
	// the connection is dead afterwards, deterministically
	if _, err := c.Read(buf); err == nil {
		t.Fatal("Read succeeded after fatal error")
	}
	if _, err := c.Write([]byte("x")); err == nil {
		t.Fatal("Write succeeded after fatal error")
	}
}

func TestReplayedRecordRejected(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	echoServer(t, l, serverCfg(p))
	seen := 0
	addr := newProxy(t, l.Addr().String(), &recordProxy{toClient: func(idx int, rec []byte) [][]byte {
		if rec[0] == 23 {
			seen++
			if seen == 6 { // first data record after the handshake: deliver it twice
				return [][]byte{rec, rec}
			}
		}
		return [][]byte{rec}
	}})
	raw, _ := net.Dial("tcp", addr)
	deadline(raw)
	c := tls13.Client(raw, clientCfg(p))
	if err := c.Handshake(); err != nil {
		t.Fatal(err)
	}
	c.Write([]byte("abc"))
	buf := make([]byte, 3)
	if _, err := io.ReadFull(c, buf); err != nil {
		t.Fatalf("first copy should be fine: %v", err)
	}
	_, err := c.Read(buf)
	var pe *tls13.ProtocolError
	if !errors.As(err, &pe) || pe.Alert != tls13.AlertBadRecordMAC {
		t.Fatalf("replayed record: %v", err)
	}
}

func TestTruncationAttackDetected(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	// server writes a message and closes (-> close_notify record); the proxy drops that record.
	go func() {
		raw, _ := l.Accept()
		deadline(raw)
		sc := tls13.Server(raw, serverCfg(p))
		sc.Write([]byte("important data"))
		sc.Close()
	}()
	var recs int
	addr := newProxy(t, l.Addr().String(), &recordProxy{toClient: func(idx int, rec []byte) [][]byte {
		if rec[0] == 23 {
			recs++
			if recs >= 7 { // handshake(4) + ticket(1) + data(1) = 6; 7th is close_notify
				return nil
			}
		}
		return [][]byte{rec}
	}})
	raw, _ := net.Dial("tcp", addr)
	deadline(raw)
	c := tls13.Client(raw, clientCfg(p))
	if err := c.Handshake(); err != nil {
		t.Fatal(err)
	}
	buf := make([]byte, 64)
	n, err := c.Read(buf)
	if err != nil || string(buf[:n]) != "important data" {
		t.Fatalf("data: %q %v", buf[:n], err)
	}
	_, err = c.Read(buf)
	if !errors.Is(err, tls13.ErrTruncated) {
		t.Fatalf("expected ErrTruncated, got %v", err)
	}
}

func TestCleanCloseGivesEOF(t *testing.T) {
	p := newPKI(t, "ecdsa-p256")
	l := listen(t)
	go func() {
		raw, _ := l.Accept()
		deadline(raw)
		sc := tls13.Server(raw, serverCfg(p))
		sc.Write([]byte("bye"))
		sc.Close()
	}()
	c, err := dialWith(t, l, clientCfg(p))
	if err != nil {
		t.Fatal(err)
	}
	all, err := io.ReadAll(c)
	if err != nil || string(all) != "bye" {
		t.Fatalf("%q %v", all, err)
	}
	if _, err := c.Read(make([]byte, 1)); err != io.EOF {
		t.Fatalf("second read: %v", err)
	}
}
