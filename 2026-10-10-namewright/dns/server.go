package dns

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	maxUDPLegacy   = 512
	serverUDPLimit = 1232 // flag-day-2020 recommendation
)

// Server is an authoritative DNS server over UDP and TCP.
type Server struct {
	mu     sync.RWMutex
	zones  map[string]*Zone
	udp    *net.UDPConn
	tcp    net.Listener
	wg     sync.WaitGroup
	closed chan struct{}

	// Logf, if set, receives one line per query.
	Logf func(format string, args ...any)
	// AllowTransfer decides whether AXFR is served to a client. Nil denies all.
	AllowTransfer func(remote net.Addr) bool
	// Limiter, if set, is consulted before answering over UDP.
	Limiter *RateLimiter
	// Policy, if set, can override answers (response-policy zone).
	Policy *Policy
	// Resolver, if set, turns the server into a recursive resolver for names
	// outside its authoritative zones (queries with RD set).
	Resolver *Resolver
	// MaxTCPConns bounds concurrent TCP connections (0 = 1024).
	MaxTCPConns int

	connMu sync.Mutex
	conns  map[net.Conn]struct{}

	statMu sync.Mutex
	stats  map[string]int
}

func NewServer(zones ...*Zone) *Server {
	s := &Server{zones: map[string]*Zone{}, closed: make(chan struct{}), stats: map[string]int{}}
	for _, z := range zones {
		s.zones[z.Origin] = z
	}
	return s
}

// SetZone adds or replaces a zone atomically.
func (s *Server) SetZone(z *Zone) {
	s.mu.Lock()
	s.zones[z.Origin] = z
	s.mu.Unlock()
}

// RemoveZone stops serving a zone.
func (s *Server) RemoveZone(origin string) {
	s.mu.Lock()
	delete(s.zones, CanonName(origin))
	s.mu.Unlock()
}

func (s *Server) Zone(origin string) *Zone {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.zones[CanonName(origin)]
}

// Stats returns a copy of the counters (queries, rcodes, truncated, ...).
func (s *Server) Stats() map[string]int {
	s.statMu.Lock()
	defer s.statMu.Unlock()
	out := make(map[string]int, len(s.stats))
	for k, v := range s.stats {
		out[k] = v
	}
	return out
}

func (s *Server) count(k string) {
	s.statMu.Lock()
	s.stats[k]++
	s.statMu.Unlock()
}

func (s *Server) logf(f string, a ...any) {
	if s.Logf != nil {
		s.Logf(f, a...)
	}
}

// findZone returns the zone with the longest origin containing name.
func (s *Server) findZone(name string) *Zone {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var best *Zone
	for o, z := range s.zones {
		if IsSubdomain(name, o) && (best == nil || len(o) > len(best.Origin)) {
			best = z
		}
	}
	return best
}

// Start binds UDP and TCP on addr (e.g. "127.0.0.1:0") and serves in the background.
func (s *Server) Start(addr string) error {
	var lastErr error
	for try := 0; try < 20; try++ {
		ua, err := net.ResolveUDPAddr("udp", addr)
		if err != nil {
			return err
		}
		uc, err := net.ListenUDP("udp", ua)
		if err != nil {
			return err
		}
		ta := uc.LocalAddr().(*net.UDPAddr)
		tl, err := net.Listen("tcp", ta.String())
		if err != nil {
			uc.Close()
			lastErr = err
			if ua.Port != 0 {
				return err
			}
			continue // random port was taken for TCP: roll again
		}
		s.udp, s.tcp = uc, tl
		s.wg.Add(2)
		go s.serveUDP()
		go s.serveTCP()
		return nil
	}
	return lastErr
}

// Addr returns the bound host:port.
func (s *Server) Addr() string { return s.udp.LocalAddr().String() }

func (s *Server) Close() {
	select {
	case <-s.closed:
		return
	default:
		close(s.closed)
	}
	s.udp.Close()
	s.tcp.Close()
	s.connMu.Lock()
	for c := range s.conns {
		c.Close() // unblock handlers waiting on idle clients
	}
	s.connMu.Unlock()
	s.wg.Wait()
}

func (s *Server) serveUDP() {
	defer s.wg.Done()
	sem := make(chan struct{}, 512)
	buf := make([]byte, 65535)
	for {
		n, addr, err := s.udp.ReadFromUDPAddrPort(buf)
		if err != nil {
			return
		}
		pkt := append([]byte(nil), buf[:n]...)
		select {
		case sem <- struct{}{}:
		default:
			s.count("dropped-overload")
			continue
		}
		s.wg.Add(1)
		go func() {
			defer s.wg.Done()
			defer func() { <-sem }()
			if s.Limiter != nil && !s.Limiter.Allow(addr.Addr().String()) {
				s.count("rate-limited")
				return
			}
			resp := s.handlePacket(pkt, net.UDPAddrFromAddrPort(addr), false)
			if resp != nil {
				s.udp.WriteToUDPAddrPort(resp, addr)
			}
		}()
	}
}

func (s *Server) serveTCP() {
	defer s.wg.Done()
	limit := s.MaxTCPConns
	if limit <= 0 {
		limit = 1024
	}
	slots := make(chan struct{}, limit)
	for {
		c, err := s.tcp.Accept()
		if err != nil {
			return
		}
		select {
		case slots <- struct{}{}:
		default:
			s.count("tcp-rejected")
			c.Close()
			continue
		}
		s.connMu.Lock()
		if s.conns == nil {
			s.conns = map[net.Conn]struct{}{}
		}
		s.conns[c] = struct{}{}
		s.connMu.Unlock()
		s.wg.Add(1)
		go func() {
			defer s.wg.Done()
			defer func() { <-slots }()
			defer func() {
				s.connMu.Lock()
				delete(s.conns, c)
				s.connMu.Unlock()
				c.Close()
			}()
			s.tcpConn(c)
		}()
	}
}

func readFramed(c net.Conn, idle time.Duration) ([]byte, error) {
	c.SetReadDeadline(time.Now().Add(idle))
	var l [2]byte
	if _, err := io.ReadFull(c, l[:]); err != nil {
		return nil, err
	}
	n := binary.BigEndian.Uint16(l[:])
	if n == 0 {
		return nil, errors.New("zero-length frame")
	}
	buf := make([]byte, n)
	if _, err := io.ReadFull(c, buf); err != nil {
		return nil, err
	}
	return buf, nil
}

func writeFramed(c net.Conn, msg []byte) error {
	if len(msg) > 0xFFFF {
		return errors.New("message too large for TCP framing")
	}
	out := make([]byte, 2+len(msg))
	binary.BigEndian.PutUint16(out, uint16(len(msg)))
	copy(out[2:], msg)
	c.SetWriteDeadline(time.Now().Add(10 * time.Second))
	_, err := c.Write(out)
	return err
}

func (s *Server) tcpConn(c net.Conn) {
	for {
		select {
		case <-s.closed:
			return
		default:
		}
		pkt, err := readFramed(c, 10*time.Second)
		if err != nil {
			return
		}
		req, perr := Unpack(pkt)
		if perr == nil && len(req.Question) == 1 && req.Question[0].Type == TypeAXFR && !req.Response {
			s.serveAXFR(c, req)
			continue
		}
		resp := s.handlePacket(pkt, c.RemoteAddr(), true)
		if resp == nil {
			return
		}
		if writeFramed(c, resp) != nil {
			return
		}
	}
}

func (s *Server) serveAXFR(c net.Conn, req *Message) {
	q := req.Question[0]
	z := s.Zone(q.Name)
	reply := func(rc Rcode, rrs []RR, first bool) []byte {
		m := &Message{ID: req.ID, Response: true, Authoritative: true, Rcode: rc, Answer: rrs}
		if first {
			m.Question = req.Question
		}
		b, _ := m.Pack()
		return b
	}
	if z == nil || z.Origin != CanonName(q.Name) {
		s.count("axfr-refused")
		writeFramed(c, reply(RcodeRefused, nil, true))
		return
	}
	if s.AllowTransfer == nil || !s.AllowTransfer(c.RemoteAddr()) {
		s.count("axfr-refused")
		s.logf("%s AXFR %s REFUSED (transfer not allowed)", c.RemoteAddr(), q.Name)
		writeFramed(c, reply(RcodeRefused, nil, true))
		return
	}
	recs := z.Records()
	recs = append(recs, z.SOA())
	var batch []RR
	size := 0
	first := true
	flush := func() bool {
		if len(batch) == 0 {
			return true
		}
		ok := writeFramed(c, reply(RcodeSuccess, batch, first)) == nil
		first = false
		batch, size = nil, 0
		return ok
	}
	for _, r := range recs {
		batch = append(batch, r)
		size += 40 + len(canonRData(r))
		if size > 16000 && !flush() {
			return
		}
	}
	flush()
	s.count("axfr")
	s.logf("%s AXFR %s %d records", c.RemoteAddr(), z.Origin, len(recs))
}

// handlePacket decodes a request and returns the encoded response (nil = no reply).
func (s *Server) handlePacket(pkt []byte, remote net.Addr, tcp bool) []byte {
	s.count("queries")
	req, err := Unpack(pkt)
	if err != nil {
		if len(pkt) >= 12 && pkt[2]&0x80 == 0 { // looks like a query: answer FORMERR
			s.count("formerr")
			m := &Message{ID: binary.BigEndian.Uint16(pkt), Response: true, Rcode: RcodeFormErr}
			b, _ := m.Pack()
			return b
		}
		return nil
	}
	if req.Response {
		return nil // never answer responses
	}
	resp, limit := s.Handle(req, tcp, remote)
	var out []byte
	if tcp {
		out, err = resp.Pack()
	} else {
		out, err = resp.PackLimit(limit)
	}
	if err != nil {
		s.logf("pack error: %v", err)
		m := &Message{ID: req.ID, Response: true, Rcode: RcodeServFail, Question: req.Question}
		out, _ = m.Pack()
	}
	if !tcp && len(out) > 2 && out[2]&(flagTC>>8) != 0 {
		s.count("truncated")
	}
	return out
}

// Handle produces the response message for a parsed request and the UDP size limit to apply.
func (s *Server) Handle(req *Message, tcp bool, remote net.Addr) (*Message, int) {
	resp := &Message{
		ID: req.ID, Response: true, Opcode: req.Opcode,
		RecursionDesired: req.RecursionDesired, CheckingDisabled: req.CheckingDisabled,
		Question: req.Question,
	}
	limit := maxUDPLegacy
	edns, hasEDNS := req.GetEDNS()
	if hasEDNS {
		resp.SetEDNS(serverUDPLimit, edns.DO)
		limit = int(edns.UDPSize)
		if limit < maxUDPLegacy {
			limit = maxUDPLegacy
		}
		if limit > serverUDPLimit {
			limit = serverUDPLimit
		}
	}
	finish := func(rc Rcode) (*Message, int) {
		resp.Rcode = rc
		s.count(rc.String())
		if s.Logf != nil && len(req.Question) > 0 {
			q := req.Question[0]
			s.logf("%s %s %s %s -> %s an=%d au=%d ad=%d aa=%v", remote, q.Name, q.Class, q.Type, rc,
				len(resp.Answer), len(resp.Authority), len(resp.Additional), resp.Authoritative)
		}
		return resp, limit
	}
	if hasEDNS && edns.Version != 0 {
		resp.setExtRcode(1) // BADVERS
		return finish(0)
	}
	if req.Opcode != 0 {
		return finish(RcodeNotImp)
	}
	if len(req.Question) != 1 {
		return finish(RcodeFormErr)
	}
	q := req.Question[0]
	if err := ValidName(q.Name); err != nil {
		return finish(RcodeFormErr)
	}
	// CHAOS-class identity queries
	if q.Class == ClassCH {
		n := CanonName(q.Name)
		if q.Type == TypeTXT && (n == "version.bind." || n == "id.server.") {
			resp.Authoritative = true
			text := "namewright"
			resp.Answer = []RR{{Name: q.Name, Type: TypeTXT, Class: ClassCH, TTL: 0, Data: TXT{[]string{text}}}}
			return finish(RcodeSuccess)
		}
		return finish(RcodeRefused)
	}
	if q.Class != ClassIN && q.Class != ClassANY {
		return finish(RcodeRefused)
	}
	if q.Type == TypeAXFR || q.Type == 251 {
		if tcp {
			return finish(RcodeRefused)
		}
		return finish(RcodeRefused) // transfers are TCP-only
	}
	if q.Type == TypeOPT {
		return finish(RcodeFormErr)
	}
	name := CanonName(q.Name)
	if s.Policy != nil {
		if rc, rrs, hit := s.Policy.Apply(name, q.Type); hit {
			resp.Authoritative = true
			resp.Answer = rrs
			s.count("policy-hit")
			return finish(rc)
		}
	}
	z := s.findZone(name)
	if z != nil && q.Type == TypeDS && z.Origin == name && name != "." {
		// DS lives on the parent side of the zone cut
		z = s.findZone(Parent(name))
	}
	if z == nil {
		if s.Resolver == nil || !req.RecursionDesired {
			resp.RecursionAvailable = s.Resolver != nil
			return finish(RcodeRefused)
		}
		resp.RecursionAvailable = true
		var rr *Response
		var err error
		if req.CheckingDisabled {
			rr, err = s.Resolver.ResolveCD(name, q.Type)
		} else {
			rr, err = s.Resolver.Resolve(name, q.Type)
		}
		if err != nil {
			return finish(RcodeServFail)
		}
		answer := rr.Answer
		if !(hasEDNS && edns.DO) {
			answer = stripSigs(answer)
		}
		resp.Answer, resp.Authority = answer, rr.Authority
		if !(hasEDNS && edns.DO) {
			resp.Authority = stripSigs(resp.Authority)
		}
		resp.AuthenticData = rr.Security == Secure && (edns.DO || req.AuthenticData)
		return finish(rr.Rcode)
	}
	resp.RecursionAvailable = s.Resolver != nil
	res := z.Lookup(name, q.Type, hasEDNS && edns.DO)
	resp.Authoritative = res.Authoritative
	resp.Answer, resp.Authority = res.Answer, res.Authority
	resp.Additional = append(resp.Additional, res.Additional...)
	// A zone-wide minimum so clients can cache; nothing further to do for rcode.
	return finish(res.Rcode)
}

// Describe returns a human summary of loaded zones.
func (s *Server) Describe() string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var names []string
	for o, z := range s.zones {
		names = append(names, fmt.Sprintf("%s (serial %d, %d records%s)", o, z.SOA().Data.(SOA).Serial, len(z.Records()), map[bool]string{true: ", signed", false: ""}[z.Signed]))
	}
	sort.Strings(names)
	return strings.Join(names, "; ")
}
