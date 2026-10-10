package dns_test

import (
	"net"
	"strings"
	"testing"
	"time"

	"namewright/dns"
	"namewright/miniverse"
)

const internetDir = "../testdata/internet"

func world(t *testing.T) *miniverse.World {
	t.Helper()
	w, err := miniverse.Build(internetDir, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(w.Close)
	return w
}

func exch(t *testing.T, addr, name string, ty dns.Type, mod func(*dns.Client)) *dns.Message {
	t.Helper()
	c := &dns.Client{Timeout: 2 * time.Second, UDPSize: 1232}
	if mod != nil {
		mod(c)
	}
	m, err := c.Exchange(addr, name, ty, false)
	if err != nil {
		t.Fatalf("%s %s: %v", name, ty, err)
	}
	return m
}

func TestServerAuthoritativeAnswer(t *testing.T) {
	w := world(t)
	addr := w.Host("ns1.example.com").Srv.Addr()
	m := exch(t, addr, "www.example.com.", dns.TypeA, nil)
	if m.Rcode != dns.RcodeSuccess || !m.Authoritative || m.RecursionAvailable {
		t.Fatalf("flags: %+v", m)
	}
	if len(m.Answer) != 3 || m.Answer[0].Type != dns.TypeCNAME {
		t.Errorf("answer: %v", m.Answer)
	}
	if _, ok := m.GetEDNS(); !ok {
		t.Error("EDNS not echoed")
	}
}

func TestServerNXDomainAndRefused(t *testing.T) {
	w := world(t)
	addr := w.Host("ns1.example.com").Srv.Addr()
	m := exch(t, addr, "missing.example.com.", dns.TypeA, nil)
	if m.Rcode != dns.RcodeNXDomain || !m.Authoritative || len(m.Authority) != 1 {
		t.Errorf("nxdomain: %+v", m)
	}
	m = exch(t, addr, "www.google.com.", dns.TypeA, nil)
	if m.Rcode != dns.RcodeRefused || m.Authoritative {
		t.Errorf("out of zone must be REFUSED: %+v", m)
	}
}

func TestServerReferralHasGlueAndNoAA(t *testing.T) {
	w := world(t)
	m := exch(t, w.Host("a.gtld-servers.net").Srv.Addr(), "www.example.com.", dns.TypeA, nil)
	if m.Authoritative || m.Rcode != dns.RcodeSuccess || len(m.Answer) != 0 {
		t.Fatalf("referral flags: %+v", m)
	}
	if len(m.Authority) != 1 || m.Authority[0].Type != dns.TypeNS || len(m.Additional) < 2 { // glue + OPT
		t.Errorf("authority=%v additional=%v", m.Authority, m.Additional)
	}
}

func TestServerTruncationAndTCPFallback(t *testing.T) {
	w := world(t)
	addr := w.Host("ns1.example.com").Srv.Addr()
	// raw UDP with no EDNS: 512-byte limit, TC set
	c := &dns.Client{Timeout: 2 * time.Second}
	raw, err := net.Dial("udp", addr)
	if err != nil {
		t.Fatal(err)
	}
	defer raw.Close()
	q := dns.NewQuery("big.example.com.", dns.TypeTXT, false)
	wire, _ := q.Pack()
	raw.Write(wire)
	buf := make([]byte, 4096)
	raw.SetReadDeadline(time.Now().Add(2 * time.Second))
	n, err := raw.Read(buf)
	if err != nil {
		t.Fatal(err)
	}
	if n > 512 {
		t.Errorf("UDP response %d bytes exceeds 512", n)
	}
	m, err := dns.Unpack(buf[:n])
	if err != nil || !m.Truncated {
		t.Fatalf("expected TC, got %+v %v", m, err)
	}
	// client with no EDNS transparently falls back to TCP and gets everything
	full, err := c.Exchange(addr, "big.example.com.", dns.TypeTXT, false)
	if err != nil || full.Truncated || len(full.Answer) != 10 {
		t.Fatalf("tcp fallback: %v %+v", err, full)
	}
	// with EDNS 1232 the ~1100-byte answer fits in UDP... only if it does
	c2 := &dns.Client{Timeout: 2 * time.Second, UDPSize: 4096}
	m2, err := c2.Exchange(addr, "big.example.com.", dns.TypeTXT, false)
	if err != nil || len(m2.Answer) != 10 {
		t.Errorf("edns answer: %v", err)
	}
	if st := w.Host("ns1.example.com").Srv.Stats(); st["truncated"] < 1 {
		t.Errorf("stats: %v", st)
	}
}

func TestServerMalformedAndOddQueries(t *testing.T) {
	w := world(t)
	addr := w.Host("ns1.example.com").Srv.Addr()
	send := func(pkt []byte) []byte {
		c, _ := net.Dial("udp", addr)
		defer c.Close()
		c.Write(pkt)
		c.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
		buf := make([]byte, 2048)
		n, err := c.Read(buf)
		if err != nil {
			return nil
		}
		return buf[:n]
	}
	// garbage with a plausible header → FORMERR echoing the id
	g := []byte{0x12, 0x34, 0x01, 0x00, 0, 1, 0, 0, 0, 0, 0, 0, 0xFF, 0xFF, 0xFF}
	resp := send(g)
	if resp == nil || resp[0] != 0x12 || resp[1] != 0x34 || resp[3]&0xF != 1 {
		t.Errorf("garbage: %x", resp)
	}
	if send([]byte{1, 2, 3}) != nil {
		t.Error("tiny junk should be ignored")
	}
	// a response packet must never be answered (reflection loops)
	q := dns.NewQuery("example.com.", dns.TypeA, false)
	q.Response = true
	w2, _ := q.Pack()
	if send(w2) != nil {
		t.Error("answered a response")
	}
	// zero questions → FORMERR; unknown opcode → NOTIMP
	m := &dns.Message{ID: 5}
	wz, _ := m.Pack()
	if r, _ := dns.Unpack(send(wz)); r == nil || r.Rcode != dns.RcodeFormErr {
		t.Errorf("zero questions: %+v", r)
	}
	m = dns.NewQuery("example.com.", dns.TypeA, false)
	m.Opcode = 4 // NOTIFY
	wn, _ := m.Pack()
	if r, _ := dns.Unpack(send(wn)); r == nil || r.Rcode != dns.RcodeNotImp {
		t.Errorf("opcode: %+v", r)
	}
	// EDNS version 1 → BADVERS (ext rcode 1)
	m = dns.NewQuery("example.com.", dns.TypeA, false)
	m.Additional = []dns.RR{{Name: ".", Type: dns.TypeOPT, Class: 1232, TTL: 1 << 16, Data: dns.OPT{}}}
	wv, _ := m.Pack()
	if r, _ := dns.Unpack(send(wv)); r == nil || r.FullRcode() != 16 {
		t.Errorf("badvers: %+v", r)
	}
	// case-preserving echo of the question
	r := exch(t, addr, "WwW.ExAmPlE.CoM.", dns.TypeA, func(c *dns.Client) { c.Case0x20 = true })
	if len(r.Answer) == 0 {
		t.Error("mixed-case query unanswered")
	}
	// CHAOS identity
	cm := dns.NewQuery("version.bind.", dns.TypeTXT, false)
	cm.Question[0].Class = dns.ClassCH
	wc, _ := cm.Pack()
	if r, _ := dns.Unpack(send(wc)); r == nil || len(r.Answer) != 1 {
		t.Errorf("version.bind: %+v", r)
	}
}

func TestServerAXFR(t *testing.T) {
	w := world(t)
	srv := w.Host("ns1.example.com").Srv
	c := &dns.Client{Timeout: 3 * time.Second}
	rrs, err := c.Transfer(srv.Addr(), "example.com.")
	if err != nil {
		t.Fatal(err)
	}
	z := srv.Zone("example.com.")
	if rrs[0].Type != dns.TypeSOA || rrs[len(rrs)-1].Type != dns.TypeSOA || len(rrs) != len(z.Records())+1 {
		t.Errorf("axfr: %d records vs zone %d", len(rrs), len(z.Records()))
	}
	// the transferred records rebuild an identical zone
	z2, err := dns.NewZone("example.com.", rrs[:len(rrs)-1])
	if err != nil || z2.String() != z.String() {
		t.Errorf("rebuilt zone differs: %v", err)
	}
	// refused when not allowed, refused for non-apex, refused for unknown zones
	srv.AllowTransfer = nil
	if _, err := c.Transfer(srv.Addr(), "example.com."); err == nil || !strings.Contains(err.Error(), "REFUSED") {
		t.Errorf("transfer should be refused: %v", err)
	}
	srv.AllowTransfer = func(net.Addr) bool { return true }
	if _, err := c.Transfer(srv.Addr(), "nonexistent.example."); err == nil {
		t.Error("unknown zone transfer should fail")
	}
	// AXFR over UDP never works
	m := exch(t, srv.Addr(), "example.com.", dns.TypeAXFR, nil)
	if m.Rcode != dns.RcodeRefused {
		t.Errorf("udp axfr: %v", m.Rcode)
	}
}

func TestServerConcurrentLoad(t *testing.T) {
	w := world(t)
	addr := w.Host("ns1.example.com").Srv.Addr()
	done := make(chan error, 200)
	for i := 0; i < 200; i++ {
		go func() {
			c := &dns.Client{Timeout: 3 * time.Second, Retries: 2}
			m, err := c.Exchange(addr, "web.example.com.", dns.TypeA, false)
			if err == nil && len(m.Answer) != 2 {
				err = net.UnknownNetworkError("bad answer")
			}
			done <- err
		}()
	}
	for i := 0; i < 200; i++ {
		if err := <-done; err != nil {
			t.Fatal(err)
		}
	}
}
