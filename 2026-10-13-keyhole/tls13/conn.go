// Package tls13 is a from-scratch TLS 1.3 (RFC 8446) implementation. It uses the standard library
// only for cryptographic primitives and X.509 parsing; the record layer, key schedule, handshake
// state machines, alerts, resumption and KeyUpdate are implemented here.
package tls13

import (
	"bufio"
	"crypto/x509"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"sync"
	"sync/atomic"
	"time"
)

// maxConsecutiveKeyUpdates bounds how many KeyUpdate messages a peer may send back-to-back; each
// update_requested forces us to derive keys and answer, so an unbounded stream is a CPU/bandwidth
// amplifier.
const maxConsecutiveKeyUpdates = 32

// ErrTruncated is returned by Read when the transport closes without a close_notify alert.
var ErrTruncated = errors.New("tls13: connection closed without close_notify (possible truncation attack)")

// Conn is a TLS 1.3 connection. It implements net.Conn.
type Conn struct {
	raw      net.Conn
	rd       *bufio.Reader
	cfg      *Config
	isClient bool

	hsMu    sync.Mutex
	hsErr   error
	hsDone  atomic.Bool
	inMu    sync.Mutex
	outMu   sync.Mutex
	in, out halfConn

	rbuf      []byte // raw bytes read but not yet a whole record
	hsBuf     []byte // received handshake bytes not yet consumed
	appBuf    []byte
	outBuf    []byte
	readErr   error
	writeErr  error
	closeSent bool

	suite      *suite
	transcript []byte
	prevLen    int // transcript length before the most recent message
	ccsSeen    int

	exporterMaster []byte
	resMaster      []byte
	clientRandom   []byte
	state          ConnectionState
	resumeChains   [][]*x509.Certificate
	kuRun          int // KeyUpdates received since the last application data
	kuSent, kuRecv atomic.Int32
	tickets        atomic.Int32
}

// Client returns a client-side Conn over raw. Call Handshake (or Read/Write) to run the handshake.
func Client(raw net.Conn, cfg *Config) *Conn { return newConn(raw, cfg, true) }

// Server returns a server-side Conn over raw.
func Server(raw net.Conn, cfg *Config) *Conn { return newConn(raw, cfg, false) }

func newConn(raw net.Conn, cfg *Config, client bool) *Conn {
	if cfg == nil {
		cfg = &Config{}
	}
	return &Conn{raw: raw, rd: bufio.NewReaderSize(raw, 32<<10), cfg: cfg, isClient: client}
}

// Dial connects to addr over TCP and completes a TLS 1.3 handshake.
func Dial(addr string, cfg *Config) (*Conn, error) {
	if cfg == nil {
		cfg = &Config{}
	}
	raw, err := net.DialTimeout("tcp", addr, 10*time.Second)
	if err != nil {
		return nil, err
	}
	if cfg.ServerName == "" && !cfg.InsecureSkipVerify {
		host, _, _ := net.SplitHostPort(addr)
		c2 := *cfg
		c2.ServerName = host
		cfg = &c2
	}
	c := Client(raw, cfg)
	if err := c.Handshake(); err != nil {
		raw.Close()
		return nil, err
	}
	return c, nil
}

func (c *Conn) LocalAddr() net.Addr                { return c.raw.LocalAddr() }
func (c *Conn) RemoteAddr() net.Addr               { return c.raw.RemoteAddr() }
func (c *Conn) SetDeadline(t time.Time) error      { return c.raw.SetDeadline(t) }
func (c *Conn) SetReadDeadline(t time.Time) error  { return c.raw.SetReadDeadline(t) }
func (c *Conn) SetWriteDeadline(t time.Time) error { return c.raw.SetWriteDeadline(t) }

// ConnectionState returns negotiated parameters (valid after the handshake).
func (c *Conn) ConnectionState() ConnectionState {
	c.hsMu.Lock()
	defer c.hsMu.Unlock()
	st := c.state
	st.KeyUpdatesSent, st.KeyUpdatesReceived = int(c.kuSent.Load()), int(c.kuRecv.Load())
	st.TicketsReceived = int(c.tickets.Load())
	return st
}

// ---------- output ----------

// flushLocked writes buffered records to the transport. outMu must be held.
func (c *Conn) flushLocked() error {
	if len(c.outBuf) == 0 {
		return c.writeErr
	}
	_, err := c.raw.Write(c.outBuf)
	c.outBuf = c.outBuf[:0]
	if err != nil && c.writeErr == nil {
		c.writeErr = err
	}
	return err
}

// writeRecordLocked fragments data into records of at most 2^14 bytes and appends them to outBuf.
func (c *Conn) writeRecordLocked(typ uint8, data []byte) error {
	if c.writeErr != nil {
		return c.writeErr
	}
	first := true
	for first || len(data) > 0 {
		first = false
		n := len(data)
		if n > c.cfg.maxFrag() {
			n = c.cfg.maxFrag()
		}
		pad := 0
		if c.out.protected() && c.cfg.RecordPadBlock > 0 {
			total := n + 1
			if r := total % c.cfg.RecordPadBlock; r != 0 {
				pad = c.cfg.RecordPadBlock - r
			}
			if n+1+pad > maxPlaintext+1 {
				pad = maxPlaintext + 1 - (n + 1)
			}
		}
		c.trace("send", "record", recName(typ, c.out.protected()), "", n)
		c.outBuf = append(c.outBuf, c.out.seal(typ, data[:n], pad)...)
		data = data[n:]
		if len(c.outBuf) > 64<<10 {
			if err := c.flushLocked(); err != nil {
				return err
			}
		}
	}
	return nil
}

func recName(typ uint8, enc bool) string {
	n := map[uint8]string{20: "change_cipher_spec", 21: "alert", 22: "handshake", 23: "application_data"}[typ]
	if enc {
		return n + " (encrypted)"
	}
	return n
}

// sendHS sends a handshake message and appends it to the transcript.
func (c *Conn) sendHS(msg []byte) error {
	c.prevLen = len(c.transcript)
	c.transcript = append(c.transcript, msg...)
	c.traceHS("send", msg)
	return c.writeRecordLocked(recHandshake, msg)
}

func (c *Conn) traceHS(dir string, msg []byte) {
	if c.cfg.Trace != nil {
		c.trace(dir, "handshake", HandshakeName(msg[0]), DescribeHandshake(msg), len(msg))
	}
}

func (c *Conn) sendCCS() error {
	c.trace("send", "record", "change_cipher_spec (compat)", "", 1)
	c.outBuf = append(c.outBuf, 20, 3, 3, 0, 1, 1)
	return nil
}

// sendAlertLocked sends an alert (best effort). outMu must be held.
func (c *Conn) sendAlertLocked(a Alert) {
	if c.writeErr != nil {
		return
	}
	level := byte(2)
	if a == AlertCloseNotify || a == AlertUserCanceled {
		level = 1
	}
	c.trace("send", "alert", a.String(), "", 2)
	c.writeRecordLocked(recAlert, []byte{level, byte(a)})
	c.flushLocked()
	if a == AlertCloseNotify {
		c.closeSent = true
	}
}

// abort reports err to the peer as an alert when it is a ProtocolError and returns it.
func (c *Conn) abortLocked(err error) error {
	var pe *ProtocolError
	if errors.As(err, &pe) {
		c.sendAlertLocked(pe.Alert)
		c.writeErr = err
	}
	return err
}

// ---------- input ----------

// readRecord returns the next application-relevant record. inMu must be held. Fatal protocol errors
// are returned as *ProtocolError for the caller to turn into alerts.
func (c *Conn) readRecord() (typ uint8, data []byte, err error) {
	for {
		var hdr [recHeaderLen]byte
		var body []byte
		hdr, body, err = c.readRawBuffered()
		if err != nil {
			return 0, nil, err
		}
		if hdr[0] == recChangeCipherSpec {
			if len(body) != 1 || body[0] != 1 {
				return 0, nil, fail(AlertUnexpectedMessage, "malformed change_cipher_spec")
			}
			c.ccsSeen++
			if c.hsDone.Load() || c.ccsSeen > 2 {
				return 0, nil, fail(AlertUnexpectedMessage, "unexpected change_cipher_spec")
			}
			c.trace("recv", "record", "change_cipher_spec (ignored)", "", 1)
			continue
		}
		enc := c.in.protected()
		if enc {
			if hdr[0] != recApplicationData {
				return 0, nil, fail(AlertUnexpectedMessage, "plaintext %s record after keys were installed", recName(hdr[0], false))
			}
			typ, data, err = c.in.open(hdr, body)
			if err != nil {
				return 0, nil, err
			}
		} else {
			typ, data = hdr[0], body
			if typ == recApplicationData {
				return 0, nil, fail(AlertUnexpectedMessage, "application data before handshake completed")
			}
			if len(data) > maxPlaintext {
				return 0, nil, fail(AlertRecordOverflow, "plaintext record too large")
			}
		}
		if len(data) == 0 && typ != recApplicationData {
			return 0, nil, fail(AlertUnexpectedMessage, "empty %s record", recName(typ, false))
		}
		c.trace("recv", "record", recName(typ, enc), "", len(data))
		return typ, data, nil
	}
}

// readRawBuffered reads one record, keeping partial bytes in c.rbuf so that a read-deadline timeout
// can be retried without losing or desynchronising the stream.
func (c *Conn) readRawBuffered() (hdr [recHeaderLen]byte, body []byte, err error) {
	for {
		if len(c.rbuf) >= recHeaderLen {
			copy(hdr[:], c.rbuf)
			n, herr := checkRecordHeader(hdr)
			if herr != nil {
				return hdr, nil, herr
			}
			if len(c.rbuf) >= recHeaderLen+n {
				body = append([]byte(nil), c.rbuf[recHeaderLen:recHeaderLen+n]...)
				c.rbuf = c.rbuf[recHeaderLen+n:]
				return hdr, body, nil
			}
		}
		var tmp [8192]byte
		m, rerr := c.rd.Read(tmp[:])
		c.rbuf = append(c.rbuf, tmp[:m]...)
		if rerr != nil && m == 0 {
			if rerr == io.EOF && len(c.rbuf) > 0 {
				rerr = io.ErrUnexpectedEOF
			}
			return hdr, nil, rerr
		}
	}
}

// handleAlert interprets an alert record. Returns a terminal error, or nil to continue.
func (c *Conn) handleAlert(data []byte) error {
	if len(data) != 2 {
		return fail(AlertDecodeError, "malformed alert (%d bytes)", len(data))
	}
	a := Alert(data[1])
	c.trace("recv", "alert", a.String(), "", 2)
	switch {
	case a == AlertCloseNotify:
		return io.EOF
	case a == AlertUserCanceled && data[0] == 1:
		return nil
	}
	return &AlertError{Alert: a}
}

// nextHandshakeMsg returns one complete handshake message from hsBuf, reading records as needed.
func (c *Conn) nextHandshakeMsg() ([]byte, error) {
	for {
		if len(c.hsBuf) >= 4 {
			n := int(c.hsBuf[1])<<16 | int(c.hsBuf[2])<<8 | int(c.hsBuf[3])
			if n > c.cfg.maxHS() {
				return nil, fail(AlertDecodeError, "handshake message of %d bytes exceeds limit", n)
			}
			if len(c.hsBuf) >= 4+n {
				msg := append([]byte(nil), c.hsBuf[:4+n]...)
				c.hsBuf = c.hsBuf[4+n:]
				return msg, nil
			}
		}
		typ, data, err := c.readRecord()
		if err != nil {
			return nil, c.mapReadErr(err)
		}
		if len(c.hsBuf) > 0 && typ != recHandshake {
			return nil, fail(AlertUnexpectedMessage, "%s record inside a fragmented handshake message", recName(typ, false))
		}
		switch typ {
		case recHandshake:
			c.hsBuf = append(c.hsBuf, data...)
		case recAlert:
			if err := c.handleAlert(data); err != nil {
				return nil, c.alertToHandshakeErr(err)
			}
		default:
			return nil, fail(AlertUnexpectedMessage, "unexpected %s record during handshake", recName(typ, false))
		}
	}
}

func (c *Conn) alertToHandshakeErr(err error) error {
	if err == io.EOF {
		return io.ErrUnexpectedEOF
	}
	return err
}

func (c *Conn) mapReadErr(err error) error {
	if err == io.EOF {
		return io.ErrUnexpectedEOF
	}
	return err
}

// readHS reads the next handshake message during the handshake and appends it to the transcript.
func (c *Conn) readHS(want uint8) ([]byte, error) {
	msg, err := c.nextHandshakeMsg()
	if err != nil {
		return nil, err
	}
	c.prevLen = len(c.transcript)
	c.transcript = append(c.transcript, msg...)
	c.traceHS("recv", msg)
	if want != 0 && msg[0] != want {
		return nil, fail(AlertUnexpectedMessage, "got %s, expected %s", HandshakeName(msg[0]), HandshakeName(want))
	}
	return msg, nil
}

func (c *Conn) transcriptHash() []byte       { return c.suite.sum(c.transcript) }
func (c *Conn) transcriptHashBefore() []byte { return c.suite.sum(c.transcript[:c.prevLen]) }

// ---------- key installation ----------

func (c *Conn) setReadSecret(secret []byte, label string) error {
	if len(c.hsBuf) != 0 {
		return fail(AlertUnexpectedMessage, "handshake data pending across a key change")
	}
	c.trace("-", "keys", "read keys: "+label, "", 0)
	return c.in.setSecret(c.suite, secret)
}

func (c *Conn) setWriteSecret(secret []byte, label string) error {
	c.trace("-", "keys", "write keys: "+label, "", 0)
	return c.out.setSecret(c.suite, secret)
}

func (c *Conn) keyLog(label string, secret []byte) {
	if c.cfg.KeyLogWriter == nil {
		return
	}
	fmt.Fprintf(c.cfg.KeyLogWriter, "%s %s %s\n", label, hex.EncodeToString(c.clientRandom), hex.EncodeToString(secret))
}

// logTraffic writes an NSS-format key log line for traffic secret generation gen (write==our sending key).
func (c *Conn) logTraffic(write bool, gen int, secret []byte) {
	client := c.isClient == write
	label := "SERVER_TRAFFIC_SECRET_"
	if client {
		label = "CLIENT_TRAFFIC_SECRET_"
	}
	c.keyLog(label+itoa(gen), secret)
}

// ---------- public I/O ----------

// Handshake runs the TLS handshake if it has not already completed.
func (c *Conn) Handshake() error {
	c.hsMu.Lock()
	defer c.hsMu.Unlock()
	if c.hsErr != nil {
		return c.hsErr
	}
	if c.hsDone.Load() {
		return nil
	}
	c.inMu.Lock()
	defer c.inMu.Unlock()
	c.outMu.Lock()
	defer c.outMu.Unlock()
	var err error
	if c.isClient {
		err = c.clientHandshake()
	} else {
		err = c.serverHandshake()
	}
	if err == nil {
		err = c.flushLocked()
	}
	if err != nil {
		if errors.Is(err, io.EOF) {
			err = io.ErrUnexpectedEOF
		}
		c.hsErr = c.abortLocked(err)
		return c.hsErr
	}
	c.hsDone.Store(true)
	c.hsBuf = nil
	c.transcript = nil
	return nil
}

// Read reads decrypted application data.
func (c *Conn) Read(p []byte) (int, error) {
	if err := c.Handshake(); err != nil {
		return 0, err
	}
	c.inMu.Lock()
	defer c.inMu.Unlock()
	if len(p) == 0 {
		return 0, nil
	}
	for len(c.appBuf) == 0 {
		if c.readErr != nil {
			return 0, c.readErr
		}
		typ, data, err := c.readRecord()
		if err != nil {
			var ne net.Error
			if errors.As(err, &ne) && ne.Timeout() {
				return 0, err // transient: partial bytes stay buffered, the caller may retry
			}
			c.readErr = c.failRead(err)
			return 0, c.readErr
		}
		if len(c.hsBuf) > 0 && typ != recHandshake {
			c.readErr = c.failRead(fail(AlertUnexpectedMessage, "%s record inside a fragmented handshake message", recName(typ, false)))
			return 0, c.readErr
		}
		switch typ {
		case recApplicationData:
			c.appBuf = data
			c.kuRun = 0
		case recAlert:
			if err := c.handleAlert(data); err != nil {
				if pe := (*ProtocolError)(nil); errors.As(err, &pe) {
					c.readErr = c.failRead(err)
				} else {
					c.readErr = err
				}
				return 0, c.readErr
			}
		case recHandshake:
			c.hsBuf = append(c.hsBuf, data...)
			if err := c.processPostHandshake(); err != nil {
				c.readErr = c.failRead(err)
				return 0, c.readErr
			}
		}
	}
	n := copy(p, c.appBuf)
	c.appBuf = c.appBuf[n:]
	return n, nil
}

// failRead converts a read-side failure into the right error, alerting the peer on protocol errors.
func (c *Conn) failRead(err error) error {
	var pe *ProtocolError
	if errors.As(err, &pe) {
		c.outMu.Lock()
		c.abortLocked(err)
		c.outMu.Unlock()
		return err
	}
	if errors.Is(err, io.ErrUnexpectedEOF) || err == io.EOF {
		return ErrTruncated
	}
	return err
}

// Write encrypts and sends application data.
func (c *Conn) Write(p []byte) (int, error) {
	if err := c.Handshake(); err != nil {
		return 0, err
	}
	c.outMu.Lock()
	defer c.outMu.Unlock()
	if c.closeSent {
		return 0, errors.New("tls13: write after close_notify")
	}
	if c.writeErr != nil {
		return 0, c.writeErr
	}
	total := 0
	for len(p) > 0 {
		if c.out.seq >= c.cfg.keyUpdateAfter() {
			if err := c.keyUpdateLocked(false); err != nil {
				return total, err
			}
		}
		n := len(p)
		if n > c.cfg.maxFrag() {
			n = c.cfg.maxFrag()
		}
		if err := c.writeRecordLocked(recApplicationData, p[:n]); err != nil {
			return total, err
		}
		p = p[n:]
		total += n
		if len(p) == 0 {
			break
		}
	}
	return total, c.flushLocked()
}

// CloseWrite sends close_notify, leaving the read side open.
func (c *Conn) CloseWrite() error {
	if !c.hsDone.Load() {
		return errors.New("tls13: CloseWrite before handshake")
	}
	c.outMu.Lock()
	defer c.outMu.Unlock()
	if c.closeSent {
		return nil
	}
	c.sendAlertLocked(AlertCloseNotify)
	return c.writeErr
}

// Close sends close_notify (if the handshake completed) and closes the transport.
func (c *Conn) Close() error {
	if !c.hsDone.Load() {
		return c.raw.Close()
	}
	var err error
	// Bound the wait for a Write that is blocked on a stalled peer: expire the deadline *before*
	// contending for outMu so that the blocked Write fails and releases it.
	c.raw.SetWriteDeadline(time.Now().Add(2 * time.Second))
	c.outMu.Lock()
	if !c.closeSent && c.writeErr == nil {
		c.sendAlertLocked(AlertCloseNotify)
	}
	c.outMu.Unlock()
	if e := c.raw.Close(); e != nil {
		err = e
	}
	return err
}

// ---------- post-handshake ----------

// processPostHandshake consumes whole messages from hsBuf. inMu held.
func (c *Conn) processPostHandshake() error {
	for {
		if len(c.hsBuf) < 4 {
			if len(c.hsBuf) > 0 {
				return nil // wait for more bytes
			}
			return nil
		}
		n := int(c.hsBuf[1])<<16 | int(c.hsBuf[2])<<8 | int(c.hsBuf[3])
		if n > c.cfg.maxHS() {
			return fail(AlertDecodeError, "handshake message of %d bytes exceeds limit", n)
		}
		if len(c.hsBuf) < 4+n {
			return nil
		}
		msg := append([]byte(nil), c.hsBuf[:4+n]...)
		c.hsBuf = c.hsBuf[4+n:]
		c.traceHS("recv", msg)
		switch {
		case msg[0] == hsNewSessionTicket && c.isClient:
			m, err := parseNewSessionTicket(msg)
			if err != nil {
				return err
			}
			c.storeTicket(m)
		case msg[0] == hsKeyUpdate:
			req, err := parseKeyUpdate(msg)
			if err != nil {
				return err
			}
			if len(c.hsBuf) != 0 {
				return fail(AlertUnexpectedMessage, "data after KeyUpdate in the same flight")
			}
			next := c.suite.nextTrafficSecret(c.in.secret)
			if err := c.setReadSecret(next, "KeyUpdate"); err != nil {
				return err
			}
			if c.kuRun++; c.kuRun > maxConsecutiveKeyUpdates {
				return fail(AlertUnexpectedMessage, "peer sent %d KeyUpdates without any application data", c.kuRun)
			}
			c.kuRecv.Add(1)
			c.logTraffic(false, int(c.kuRecv.Load()), next)
			if req {
				c.outMu.Lock()
				err := c.keyUpdateLocked(false)
				c.outMu.Unlock()
				if err != nil {
					return err
				}
			}
		default:
			return fail(AlertUnexpectedMessage, "unexpected post-handshake %s", HandshakeName(msg[0]))
		}
	}
}

// KeyUpdate rotates our sending keys; if requestPeer is set the peer is asked to rotate theirs too.
func (c *Conn) KeyUpdate(requestPeer bool) error {
	if err := c.Handshake(); err != nil {
		return err
	}
	c.outMu.Lock()
	defer c.outMu.Unlock()
	if err := c.keyUpdateLocked(requestPeer); err != nil {
		return err
	}
	return c.flushLocked()
}

func (c *Conn) keyUpdateLocked(requestPeer bool) error {
	msg := keyUpdateMsg(requestPeer)
	c.traceHS("send", msg)
	if err := c.writeRecordLocked(recHandshake, msg); err != nil {
		return err
	}
	if err := c.setWriteSecret(c.suite.nextTrafficSecret(c.out.secret), "KeyUpdate"); err != nil {
		return err
	}
	c.kuSent.Add(1)
	c.logTraffic(true, int(c.kuSent.Load()), c.out.secret)
	return nil
}

// ExportKeyingMaterial derives application keying material (RFC 8446 §7.5), matching
// SSL_export_keying_material / openssl s_client -keymatexport.
func (c *Conn) ExportKeyingMaterial(label string, context []byte, n int) ([]byte, error) {
	if !c.hsDone.Load() {
		return nil, errors.New("tls13: handshake not complete")
	}
	if n < 0 || n > 255*c.suite.hashLen() || n > 0xffff {
		return nil, errors.New("tls13: invalid exporter output length")
	}
	if len(label) > 200 || len(context) > 0xffff {
		return nil, errors.New("tls13: exporter label or context too long")
	}
	return c.suite.exporter(c.exporterMaster, label, context, n), nil
}

// PeerCertificates is a convenience for ConnectionState().PeerCertificates.
func (c *Conn) PeerCertificates() []*x509.Certificate { return c.ConnectionState().PeerCertificates }
