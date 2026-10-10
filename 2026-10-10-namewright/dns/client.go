package dns

import (
	"crypto/rand"
	"encoding/binary"
	"errors"
	"fmt"
	"net"
	"time"
)

// Client sends a single query to a single server.
type Client struct {
	Timeout  time.Duration
	Retries  int    // extra UDP attempts after the first
	UDPSize  uint16 // advertised EDNS buffer (0 = no EDNS)
	DO       bool   // request DNSSEC records
	Case0x20 bool   // randomise query-name case and require an exact echo
	TCPOnly  bool
}

func randID() uint16 {
	var b [2]byte
	rand.Read(b[:])
	return binary.BigEndian.Uint16(b[:])
}

// randomCase flips ASCII letters pseudo-randomly (draft-vixie-dnsext-dns0x20).
func randomCase(name string) string {
	b := []byte(name)
	var r [32]byte
	rand.Read(r[:])
	for i, c := range b {
		if (c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z') && r[i%32]>>(uint(i)/32%8)&1 == 1 {
			b[i] = c ^ 0x20
		}
	}
	return string(b)
}

// NewQuery builds a standard query.
func NewQuery(name string, t Type, rd bool) *Message {
	return &Message{ID: randID(), RecursionDesired: rd,
		Question: []Question{{Name: CanonName(name), Type: t, Class: ClassIN}}}
}

// Exchange performs query/response against addr ("host:port"). If the UDP
// answer is truncated it transparently retries over TCP.
func (c *Client) Exchange(addr string, name string, t Type, rd bool) (*Message, error) {
	q := NewQuery(name, t, rd)
	if c.Case0x20 {
		q.Question[0].Name = randomCase(q.Question[0].Name)
	}
	if c.UDPSize > 0 {
		q.SetEDNS(c.UDPSize, c.DO)
	}
	wire, err := q.Pack()
	if err != nil {
		return nil, err
	}
	timeout := c.Timeout
	if timeout == 0 {
		timeout = 2 * time.Second
	}
	if !c.TCPOnly {
		var lastErr error
		for attempt := 0; attempt <= c.Retries; attempt++ {
			resp, err := c.udp(addr, wire, q, timeout)
			if err == nil {
				if resp.Truncated {
					return c.tcp(addr, wire, q, timeout)
				}
				return resp, nil
			}
			lastErr = err
			var ne net.Error
			if !errors.As(err, &ne) || !ne.Timeout() {
				break
			}
		}
		return nil, lastErr
	}
	return c.tcp(addr, wire, q, timeout)
}

func (c *Client) check(resp *Message, q *Message) error {
	if resp.ID != q.ID || !resp.Response {
		return errors.New("dns: response does not match query (id/QR)")
	}
	if len(resp.Question) != 1 || resp.Question[0].Type != q.Question[0].Type ||
		resp.Question[0].Class != q.Question[0].Class {
		return errors.New("dns: response question mismatch")
	}
	if c.Case0x20 {
		if resp.Question[0].Name != q.Question[0].Name {
			return errors.New("dns: response failed 0x20 case check")
		}
	} else if CompareNames(resp.Question[0].Name, q.Question[0].Name) != 0 {
		return errors.New("dns: response question mismatch")
	}
	return nil
}

func (c *Client) udp(addr string, wire []byte, q *Message, timeout time.Duration) (*Message, error) {
	conn, err := net.Dial("udp", addr)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(timeout))
	if _, err := conn.Write(wire); err != nil {
		return nil, err
	}
	buf := make([]byte, 65535)
	for {
		n, err := conn.Read(buf)
		if err != nil {
			return nil, err
		}
		resp, err := Unpack(buf[:n])
		if err != nil || c.check(resp, q) != nil {
			continue // ignore spoofed / garbled datagrams and keep waiting until the deadline
		}
		return resp, nil
	}
}

func (c *Client) tcp(addr string, wire []byte, q *Message, timeout time.Duration) (*Message, error) {
	conn, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(timeout))
	if err := writeFramed(conn, wire); err != nil {
		return nil, err
	}
	pkt, err := readFramed(conn, timeout)
	if err != nil {
		return nil, err
	}
	resp, err := Unpack(pkt)
	if err != nil {
		return nil, err
	}
	if err := c.check(resp, q); err != nil {
		return nil, err
	}
	return resp, nil
}

// Transfer performs an AXFR of zone from addr over TCP and returns the records
// between (and including) the bracketing SOAs, verifying the framing.
func (c *Client) Transfer(addr, zone string) ([]RR, error) {
	timeout := c.Timeout
	if timeout == 0 {
		timeout = 5 * time.Second
	}
	q := NewQuery(zone, TypeAXFR, false)
	wire, err := q.Pack()
	if err != nil {
		return nil, err
	}
	conn, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	if err := writeFramed(conn, wire); err != nil {
		return nil, err
	}
	var rrs []RR
	soas := 0
	for soas < 2 {
		pkt, err := readFramed(conn, timeout)
		if err != nil {
			return nil, fmt.Errorf("axfr: %w", err)
		}
		m, err := Unpack(pkt)
		if err != nil {
			return nil, err
		}
		if m.ID != q.ID {
			return nil, errors.New("axfr: id mismatch")
		}
		if m.Rcode != RcodeSuccess {
			return nil, fmt.Errorf("axfr refused: %s", m.Rcode)
		}
		for _, r := range m.Answer {
			rrs = append(rrs, r)
			if r.Type == TypeSOA {
				soas++
			}
			if soas == 2 {
				break
			}
		}
		if len(m.Answer) == 0 {
			return nil, errors.New("axfr: empty message before final SOA")
		}
	}
	if len(rrs) < 2 || rrs[0].Type != TypeSOA || rrs[len(rrs)-1].Type != TypeSOA {
		return nil, errors.New("axfr: stream not bracketed by SOA")
	}
	return rrs, nil
}
