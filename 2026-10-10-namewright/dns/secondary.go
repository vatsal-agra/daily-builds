package dns

import (
	"context"
	"fmt"
	"sync"
	"time"
)

// SerialGreater implements RFC 1982 serial-number arithmetic: a is newer than b.
func SerialGreater(a, b uint32) bool {
	return (a < b && b-a > 1<<31) || (a > b && a-b < 1<<31)
}

// Secondary keeps a local copy of a zone in sync with a primary using SOA
// polling and AXFR, and serves it from a Server. If the primary stays
// unreachable for longer than the SOA EXPIRE interval the zone is withdrawn,
// as RFC 1034 §4.3.5 requires.
type Secondary struct {
	Origin  string
	Primary string // host:port
	Server  *Server
	Client  *Client
	Now     func() time.Time
	Logf    func(format string, args ...any)

	mu          sync.Mutex
	serial      uint32
	haveZone    bool
	lastSuccess time.Time
	refresh     time.Duration
	retry       time.Duration
	expire      time.Duration
	next        time.Time
}

func NewSecondary(origin, primary string, srv *Server) *Secondary {
	return &Secondary{Origin: CanonName(origin), Primary: primary, Server: srv,
		Client: &Client{Timeout: 3 * time.Second, Retries: 1, UDPSize: 1232}, Now: time.Now}
}

func (s *Secondary) logf(f string, a ...any) {
	if s.Logf != nil {
		s.Logf(f, a...)
	}
}

// Serial returns the serial currently served (0, false if nothing loaded).
func (s *Secondary) Serial() (uint32, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.serial, s.haveZone
}

// Refresh runs one SOA check and transfers the zone if the primary is newer.
// It reports whether new data was loaded.
func (s *Secondary) Refresh() (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := s.Now()
	updated, err := s.refreshLocked(now)
	if err != nil {
		s.next = now.Add(orDefault(s.retry, 30*time.Second))
		if s.haveZone && s.expire > 0 && now.Sub(s.lastSuccess) > s.expire {
			s.Server.RemoveZone(s.Origin)
			s.haveZone = false
			s.logf("zone %s expired after %s without contacting the primary: no longer served", s.Origin, s.expire)
		}
		return false, err
	}
	s.next = now.Add(orDefault(s.refresh, time.Hour))
	return updated, nil
}

func orDefault(d, def time.Duration) time.Duration {
	if d <= 0 {
		return def
	}
	return d
}

func (s *Secondary) refreshLocked(now time.Time) (bool, error) {
	resp, err := s.Client.Exchange(s.Primary, s.Origin, TypeSOA, false)
	if err != nil {
		return false, fmt.Errorf("SOA query to %s: %w", s.Primary, err)
	}
	if resp.Rcode != RcodeSuccess || !resp.Authoritative {
		return false, fmt.Errorf("primary answered %s (aa=%v) for the SOA of %s", resp.Rcode, resp.Authoritative, s.Origin)
	}
	var soa *SOA
	for _, r := range resp.Answer {
		if d, ok := r.Data.(SOA); ok && CompareNames(r.Name, s.Origin) == 0 {
			soa = &d
		}
	}
	if soa == nil {
		return false, fmt.Errorf("primary returned no SOA for %s", s.Origin)
	}
	s.refresh = time.Duration(soa.Refresh) * time.Second
	s.retry = time.Duration(soa.Retry) * time.Second
	s.expire = time.Duration(soa.Expire) * time.Second
	if s.haveZone && !SerialGreater(soa.Serial, s.serial) {
		s.lastSuccess = now
		if SerialGreater(s.serial, soa.Serial) {
			s.logf("primary serial %d is behind ours (%d): ignoring", soa.Serial, s.serial)
		}
		return false, nil
	}
	rrs, err := s.Client.Transfer(s.Primary, s.Origin)
	if err != nil {
		return false, err
	}
	z, err := NewZone(s.Origin, rrs[:len(rrs)-1]) // drop the closing SOA
	if err != nil {
		return false, fmt.Errorf("transferred zone is invalid: %w", err)
	}
	newSerial := z.SOA().Data.(SOA).Serial
	s.Server.SetZone(z)
	s.serial, s.haveZone, s.lastSuccess = newSerial, true, now
	s.logf("zone %s loaded from %s: serial %d, %d records", s.Origin, s.Primary, newSerial, len(rrs)-1)
	return true, nil
}

// Run refreshes on the schedule given by the SOA timers until ctx is cancelled.
func (s *Secondary) Run(ctx context.Context) {
	for {
		if _, err := s.Refresh(); err != nil {
			s.logf("refresh of %s failed: %v", s.Origin, err)
		}
		s.mu.Lock()
		wait := s.next.Sub(s.Now())
		s.mu.Unlock()
		if wait < time.Second {
			wait = time.Second
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
	}
}
