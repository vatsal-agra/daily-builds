package tls13

import (
	"bufio"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"time"
)

// This file is a passive TLS 1.3 session decoder: feed it the raw bytes of both directions of a
// connection plus an NSS-style key log and it reconstructs, decrypts and describes every record.
// It is what `keyhole inspect` uses, and it works on key logs written by OpenSSL, curl, Go's
// crypto/tls and keyhole itself.

// InspectEvent is one decoded thing seen on the wire.
type InspectEvent struct {
	At      time.Time
	FromCli bool   // true for client→server
	Kind    string // "record", "handshake", "alert", "data", "note"
	Summary string
	Detail  string
	Bytes   int
}

// KeyLog maps client_random (hex) → label → secret.
type KeyLog map[string]map[string][]byte

// ParseKeyLog reads an NSS key log file's content.
func ParseKeyLog(r io.Reader) KeyLog {
	kl := KeyLog{}
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 1<<16), 1<<20)
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) != 3 || strings.HasPrefix(f[0], "#") {
			continue
		}
		sec, err := hex.DecodeString(f[2])
		if err != nil {
			continue
		}
		m := kl[strings.ToLower(f[1])]
		if m == nil {
			m = map[string][]byte{}
			kl[strings.ToLower(f[1])] = m
		}
		m[f[0]] = sec
	}
	return kl
}

// ReadKeyLogFile parses path; a missing file yields an empty log.
func ReadKeyLogFile(path string) KeyLog {
	f, err := os.Open(path)
	if err != nil {
		return KeyLog{}
	}
	defer f.Close()
	return ParseKeyLog(f)
}

type stage int

const (
	stPlain stage = iota
	stHandshake
	stApp
)

type inspRec struct {
	hdr  [recHeaderLen]byte
	body []byte
}

type inspDir struct {
	cli     bool
	raw     []byte
	queue   []inspRec
	hc      halfConn
	want    stage // stage the next record is protected under
	have    stage // stage currently installed in hc
	hsBuf   []byte
	broken  bool
	nrec    int
	kuCount int
}

// Inspector decodes one connection.
type Inspector struct {
	mu       sync.Mutex
	keylog   func() KeyLog
	emit     func(InspectEvent)
	ShowData int // bytes of application-data plaintext to include in events (0 = lengths only)

	cli, srv inspDir
	random   []byte
	suite    *suite
	sawHRR   bool
	gotSH    bool
}

// NewInspector builds an Inspector. keylog is re-evaluated whenever a secret is needed, so it can
// re-read a growing file. emit receives events in decode order.
func NewInspector(keylog func() KeyLog, emit func(InspectEvent)) *Inspector {
	in := &Inspector{keylog: keylog, emit: emit}
	in.cli.cli = true
	return in
}

func (in *Inspector) event(d *inspDir, kind, summary, detail string, n int) {
	in.emit(InspectEvent{At: time.Now(), FromCli: d.cli, Kind: kind, Summary: summary, Detail: detail, Bytes: n})
}

// Feed adds raw TCP bytes seen flowing from the client (fromClient) or the server.
func (in *Inspector) Feed(fromClient bool, p []byte) {
	in.mu.Lock()
	defer in.mu.Unlock()
	d := &in.srv
	if fromClient {
		d = &in.cli
	}
	d.raw = append(d.raw, p...)
	for !d.broken {
		if len(d.raw) < recHeaderLen {
			break
		}
		n := int(d.raw[3])<<8 | int(d.raw[4])
		if d.raw[1] != 3 || n > maxCiphertext {
			in.event(d, "note", "not TLS: record header is invalid, ignoring the rest of this direction", "", len(d.raw))
			d.broken = true
			d.raw = nil
			return
		}
		if len(d.raw) < recHeaderLen+n {
			break
		}
		var r inspRec
		copy(r.hdr[:], d.raw[:recHeaderLen])
		r.body = append([]byte(nil), d.raw[recHeaderLen:recHeaderLen+n]...)
		d.raw = d.raw[recHeaderLen+n:]
		d.queue = append(d.queue, r)
	}
	in.drain()
}

// Poll retries records that were waiting for key log entries.
func (in *Inspector) Poll() {
	in.mu.Lock()
	defer in.mu.Unlock()
	in.drain()
}

// Close reports anything still undecodable.
func (in *Inspector) Close() {
	in.mu.Lock()
	defer in.mu.Unlock()
	in.drain()
	for _, d := range []*inspDir{&in.cli, &in.srv} {
		if len(d.queue) > 0 {
			in.event(d, "note", fmt.Sprintf("%d encrypted record(s) left undecoded: no key log entry for this connection", len(d.queue)), "", 0)
			d.queue = nil
		}
	}
}

func (in *Inspector) drain() {
	for progress := true; progress; {
		progress = false
		for _, d := range []*inspDir{&in.cli, &in.srv} {
			for len(d.queue) > 0 && !d.broken {
				if !in.process(d, d.queue[0]) {
					break
				}
				d.queue = d.queue[1:]
				progress = true
			}
		}
	}
}

// ensureKeys installs the secret needed for d's next record; false means "not available yet".
func (in *Inspector) ensureKeys(d *inspDir) bool {
	if d.want == stPlain || d.have == d.want {
		return true
	}
	if in.suite == nil || in.random == nil {
		return false
	}
	secrets := in.keylog()[hex.EncodeToString(in.random)]
	if secrets == nil {
		return false
	}
	var label string
	switch {
	case d.want == stHandshake && d.cli:
		label = "CLIENT_HANDSHAKE_TRAFFIC_SECRET"
	case d.want == stHandshake:
		label = "SERVER_HANDSHAKE_TRAFFIC_SECRET"
	case d.cli:
		label = "CLIENT_TRAFFIC_SECRET_0"
	default:
		label = "SERVER_TRAFFIC_SECRET_0"
	}
	sec, ok := secrets[label]
	if !ok {
		return false
	}
	if d.hc.setSecret(in.suite, sec) != nil {
		return false
	}
	d.have = d.want
	return true
}

func (in *Inspector) process(d *inspDir, r inspRec) bool {
	typ := r.hdr[0]
	if typ == recChangeCipherSpec {
		in.event(d, "record", "change_cipher_spec (TLS 1.3 compatibility, ignored)", "", len(r.body))
		return true
	}
	data := r.body
	enc := d.want != stPlain
	if enc {
		if typ != recApplicationData {
			in.event(d, "note", fmt.Sprintf("plaintext %s record after keys changed — protocol violation", recName(typ, false)), "", len(r.body))
			return true
		}
		if !in.ensureKeys(d) {
			return false
		}
		var err error
		typ, data, err = d.hc.open(r.hdr, r.body)
		if err != nil {
			in.event(d, "note", "record failed to decrypt — wrong secrets in the key log, or the session was not captured from its start", err.Error(), len(r.body))
			d.broken = true
			return true
		}
	}
	d.nrec++
	switch typ {
	case recHandshake:
		d.hsBuf = append(d.hsBuf, data...)
		for len(d.hsBuf) >= 4 {
			n := int(d.hsBuf[1])<<16 | int(d.hsBuf[2])<<8 | int(d.hsBuf[3])
			if len(d.hsBuf) < 4+n {
				break
			}
			msg := d.hsBuf[:4+n]
			d.hsBuf = d.hsBuf[4+n:]
			in.handshake(d, msg, enc)
		}
	case recAlert:
		if len(data) == 2 {
			lvl := "warning"
			if data[0] == 2 {
				lvl = "fatal"
			}
			in.event(d, "alert", fmt.Sprintf("alert %s (%s)", Alert(data[1]), lvl), "", len(data))
		}
	case recApplicationData:
		detail := ""
		if in.ShowData > 0 {
			s := data
			if len(s) > in.ShowData {
				s = s[:in.ShowData]
			}
			detail = strings.Map(func(r rune) rune {
				if r == '\n' || r == '\t' || (r >= 32 && r < 127) {
					return r
				}
				if r == '\r' {
					return -1
				}
				return '.'
			}, string(s))
		}
		in.event(d, "data", fmt.Sprintf("application data, %d bytes", len(data)), detail, len(data))
	}
	return true
}

func (in *Inspector) handshake(d *inspDir, msg []byte, enc bool) {
	name := HandshakeName(msg[0])
	switch msg[0] {
	case hsClientHello:
		if ch, err := parseClientHello(msg); err == nil && in.random == nil {
			in.random = ch.random
		}
	case hsServerHello:
		if sh, err := parseServerHello(msg); err == nil {
			if sh.hrr {
				in.sawHRR = true
				name = "HelloRetryRequest"
			} else if s := suiteByID(sh.suite); s != nil {
				in.suite, in.gotSH = s, true
				in.cli.want, in.srv.want = stHandshake, stHandshake
			}
		}
	case hsFinished:
		if enc && d.want == stHandshake {
			d.want = stApp
		}
	case hsKeyUpdate:
		if enc && in.suite != nil && d.hc.protected() && len(d.hsBuf) == 0 {
			d.hc.setSecret(in.suite, in.suite.nextTrafficSecret(d.hc.secret))
			d.kuCount++
		}
	}
	in.event(d, "handshake", name, DescribeHandshake(msg), len(msg))
}
