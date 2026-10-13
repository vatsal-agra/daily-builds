package tls13

import (
	"crypto/aes"
	"crypto/cipher"
	"io"
	"sync"
	"time"
)

// sessionState is what a server seals into a ticket.
type sessionState struct {
	suite      uint16
	created    time.Time
	ageAdd     uint32
	psk        []byte // resumption PSK already derived with this ticket's nonce
	serverName string
	alpn       string
}

func (s *sessionState) marshal() []byte {
	var b builder
	b.u8(1) // format version
	b.u16(s.suite)
	b.u32(uint32(s.created.Unix() >> 32))
	b.u32(uint32(s.created.Unix()))
	b.u32(s.ageAdd)
	b.vec8(func(b *builder) { b.raw(s.psk) })
	b.vec16(func(b *builder) { b.raw([]byte(s.serverName)) })
	b.vec8(func(b *builder) { b.raw([]byte(s.alpn)) })
	return b.b
}

func parseSessionState(b []byte) (*sessionState, bool) {
	p := newParser(b)
	if p.u8() != 1 {
		return nil, false
	}
	s := &sessionState{suite: p.u16()}
	hi, lo := p.u32(), p.u32()
	s.created = time.Unix(int64(hi)<<32|int64(lo), 0)
	s.ageAdd = p.u32()
	s.psk = p.vecBytes(1)
	s.serverName = string(p.vecBytes(2))
	s.alpn = string(p.vecBytes(1))
	return s, p.ok() && p.empty()
}

func sealTicket(key []byte, rnd io.Reader, st *sessionState) ([]byte, error) {
	blk, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	g, err := cipher.NewGCM(blk)
	if err != nil {
		return nil, err
	}
	nonce := make([]byte, g.NonceSize())
	if _, err := io.ReadFull(rnd, nonce); err != nil {
		return nil, err
	}
	return g.Seal(nonce, nonce, st.marshal(), []byte("keyhole ticket v1")), nil
}

func openTicket(key, ticket []byte) (*sessionState, bool) {
	blk, err := aes.NewCipher(key)
	if err != nil {
		return nil, false
	}
	g, err := cipher.NewGCM(blk)
	if err != nil || len(ticket) < g.NonceSize()+g.Overhead() {
		return nil, false
	}
	pt, err := g.Open(nil, ticket[:g.NonceSize()], ticket[g.NonceSize():], []byte("keyhole ticket v1"))
	if err != nil {
		return nil, false
	}
	return parseSessionState(pt)
}

// ClientSession is a resumption ticket held by a client.
type ClientSession struct {
	Ticket   []byte
	Suite    uint16
	PSK      []byte
	AgeAdd   uint32
	Received time.Time
	Lifetime time.Duration
	ALPN     string
}

// SessionCache stores client tickets by server name. Tickets are single-use (RFC 8446 §C.4).
type SessionCache struct {
	mu sync.Mutex
	m  map[string][]*ClientSession
}

func NewSessionCache() *SessionCache { return &SessionCache{m: map[string][]*ClientSession{}} }

func (c *SessionCache) Put(key string, s *ClientSession) {
	c.mu.Lock()
	defer c.mu.Unlock()
	l := append(c.m[key], s)
	if len(l) > 8 {
		l = l[len(l)-8:]
	}
	c.m[key] = l
}

// Take removes and returns the newest unexpired ticket for key.
func (c *SessionCache) Take(key string, now time.Time) *ClientSession {
	c.mu.Lock()
	defer c.mu.Unlock()
	l := c.m[key]
	for len(l) > 0 {
		s := l[len(l)-1]
		l = l[:len(l)-1]
		if now.Sub(s.Received) < s.Lifetime {
			c.m[key] = l
			return s
		}
	}
	c.m[key] = l
	return nil
}

// Len reports the number of cached tickets for key.
func (c *SessionCache) Len(key string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.m[key])
}
