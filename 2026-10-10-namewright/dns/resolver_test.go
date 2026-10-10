package dns_test

import (
	"net"
	"net/netip"
	"strings"
	"testing"
	"time"

	"namewright/dns"
)

func TestResolverFullWalk(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	var trace []string
	r.Trace = func(d int, m string) { trace = append(trace, strings.Repeat(" ", d)+m) }
	resp, err := r.Resolve("web.example.com.", dns.TypeA)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Rcode != dns.RcodeSuccess || len(resp.Answer) != 2 || resp.Queries != 3 {
		t.Fatalf("resp=%+v\n%s", resp, strings.Join(trace, "\n"))
	}
	joined := strings.Join(trace, "\n")
	for _, want := range []string{"referral to com.", "referral to example.com."} {
		if !strings.Contains(joined, want) {
			t.Errorf("trace missing %q:\n%s", want, joined)
		}
	}
}

func TestResolverCNAMEAcrossZones(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	// blog.example.com CNAME blog.glueless.com (different zone, different server, glueless NS)
	resp, err := r.Resolve("blog.example.com.", dns.TypeA)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Rcode != dns.RcodeSuccess || len(resp.Answer) != 2 || resp.Answer[0].Type != dns.TypeCNAME ||
		resp.Answer[1].Data.String() != "192.0.2.201" {
		t.Fatalf("%+v", resp)
	}
}

func TestResolverGluelessDelegation(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	var trace []string
	r.Trace = func(d int, m string) { trace = append(trace, m) }
	resp, _ := r.Resolve("www.glueless.com.", dns.TypeA)
	if resp.Rcode != dns.RcodeSuccess || len(resp.Answer) != 1 || resp.Answer[0].Data.String() != "192.0.2.200" {
		t.Fatalf("%+v", resp)
	}
	if !strings.Contains(strings.Join(trace, "\n"), "glueless NS ns.dnshost.net.") {
		t.Errorf("did not resolve NS address: %v", trace)
	}
}

func TestResolverCachingAndNegativeCaching(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	now := time.Unix(1_800_000_000, 0)
	r.Cache.Now = func() time.Time { return now }
	r.Now = r.Cache.Now
	first, _ := r.Resolve("mail.example.com.", dns.TypeA)
	if first.Cached || first.Queries == 0 {
		t.Fatalf("first: %+v", first)
	}
	second, _ := r.Resolve("mail.example.com.", dns.TypeA)
	if !second.Cached || second.Queries != 0 {
		t.Errorf("second should be cached: %+v", second)
	}
	// sibling in same zone needs only one query thanks to the cached delegation
	sib, _ := r.Resolve("mail2.example.com.", dns.TypeA)
	if sib.Queries != 1 {
		t.Errorf("delegation not reused: %d queries", sib.Queries)
	}
	// TTLs count down
	now = now.Add(1000 * time.Second)
	aged, _ := r.Resolve("mail.example.com.", dns.TypeA)
	if !aged.Cached || aged.Answer[0].TTL != 2600 {
		t.Errorf("aged TTL: %+v", aged.Answer)
	}
	// expiry forces a refetch
	now = now.Add(3000 * time.Second)
	exp, _ := r.Resolve("mail.example.com.", dns.TypeA)
	if exp.Cached {
		t.Errorf("expired entry served from cache")
	}
	// negative caching: NXDOMAIN applies to every type, lasts min(SOA ttl, minimum)=300s
	nx, _ := r.Resolve("ghost.example.com.", dns.TypeA)
	if nx.Rcode != dns.RcodeNXDomain || len(nx.Authority) == 0 {
		t.Fatalf("nx: %+v", nx)
	}
	nx2, _ := r.Resolve("ghost.example.com.", dns.TypeTXT)
	if !nx2.Cached || nx2.Rcode != dns.RcodeNXDomain {
		t.Errorf("NXDOMAIN not cached across types: %+v", nx2)
	}
	nd, _ := r.Resolve("mail.example.com.", dns.TypeMX)
	nd2, _ := r.Resolve("mail.example.com.", dns.TypeMX)
	if nd.Rcode != dns.RcodeSuccess || len(nd.Answer) != 0 || !nd2.Cached {
		t.Errorf("NODATA caching: %+v / %+v", nd, nd2)
	}
	now = now.Add(301 * time.Second)
	nx3, _ := r.Resolve("ghost.example.com.", dns.TypeA)
	if nx3.Cached {
		t.Errorf("negative entry outlived its TTL")
	}
}

func TestResolverWildcardAndDelegatedChild(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	resp, _ := r.Resolve("foo.dev.example.com.", dns.TypeA)
	if len(resp.Answer) != 1 || resp.Answer[0].Name != "foo.dev.example.com." {
		t.Errorf("wildcard: %+v", resp)
	}
	resp, _ = r.Resolve("host.sub.example.com.", dns.TypeA)
	if resp.Rcode != dns.RcodeSuccess || len(resp.Answer) != 1 || resp.Answer[0].Data.String() != "192.0.2.111" {
		t.Errorf("sub delegation: %+v", resp)
	}
	resp, _ = r.Resolve("example.com.", dns.TypeMX)
	if len(resp.Answer) != 2 {
		t.Errorf("mx: %+v", resp)
	}
}

func TestResolverCNAMELoop(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	resp, err := r.Resolve("loop1.glueless.com.", dns.TypeA)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Rcode != dns.RcodeServFail || !strings.Contains(resp.Why, "loop") {
		t.Errorf("want SERVFAIL loop, got %+v", resp)
	}
}

func TestResolverNXDomainTypes(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	resp, _ := r.Resolve("nothere.glueless.com.", dns.TypeA)
	if resp.Rcode != dns.RcodeNXDomain {
		t.Errorf("%+v", resp)
	}
	resp, _ = r.Resolve("nothere.nosuchtld.", dns.TypeA)
	if resp.Rcode != dns.RcodeNXDomain {
		t.Errorf("nonexistent TLD: %+v", resp)
	}
}

func TestResolverSurvivesDeadServerAndFailsOverNone(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	r.Client.Timeout = 200 * time.Millisecond
	r.Client.Retries = 0
	w.Host("ns1.example.com").Srv.Close()
	resp, err := r.Resolve("web.example.com.", dns.TypeA)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Rcode != dns.RcodeServFail {
		t.Errorf("dead authority should SERVFAIL: %+v", resp)
	}
}

// A hostile nameserver for evil.test that sneaks unrelated records into every response.
func TestResolverRejectsPoisoning(t *testing.T) {
	w := world(t)
	evil, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer evil.Close()
	go func() {
		buf := make([]byte, 2048)
		for {
			n, a, err := evil.ReadFrom(buf)
			if err != nil {
				return
			}
			q, err := dns.Unpack(buf[:n])
			if err != nil {
				continue
			}
			resp := &dns.Message{ID: q.ID, Response: true, Authoritative: true, Question: q.Question}
			ip := func(s string) dns.RData { return dns.A{Addr: netip.MustParseAddr(s)} }
			resp.Answer = []dns.RR{
				{Name: q.Question[0].Name, Type: dns.TypeA, Class: dns.ClassIN, TTL: 300, Data: ip("6.6.6.6")},
				{Name: "www.example.com.", Type: dns.TypeA, Class: dns.ClassIN, TTL: 300, Data: ip("6.6.6.6")},
			}
			resp.Authority = []dns.RR{{Name: "example.com.", Type: dns.TypeNS, Class: dns.ClassIN, TTL: 300, Data: dns.NS{Host: "ns.evil.test."}}}
			resp.Additional = []dns.RR{{Name: "ns1.example.com.", Type: dns.TypeA, Class: dns.ClassIN, TTL: 300, Data: ip("6.6.6.6")}}
			b, _ := resp.Pack()
			evil.WriteTo(b, a)
		}
	}()
	r := w.NewResolver()
	evilIP := netip.MustParseAddr("203.0.113.66")
	r.AddrMap = func(ip netip.Addr) string {
		if ip == evilIP {
			return evil.LocalAddr().String()
		}
		return w.AddrMap(ip)
	}
	// make evil.test's delegation point at the hostile server through the cache
	r.Cache.PutSet([]dns.RR{{Name: "evil.test.", Type: dns.TypeNS, Class: dns.ClassIN, TTL: 3600, Data: dns.NS{Host: "ns.evil.test."}}}, nil, dns.Indeterminate)
	r.Cache.PutSet([]dns.RR{{Name: "ns.evil.test.", Type: dns.TypeA, Class: dns.ClassIN, TTL: 3600, Data: dns.A{Addr: evilIP}}}, nil, dns.Indeterminate)
	resp, _ := r.Resolve("x.evil.test.", dns.TypeA)
	if resp.Rcode != dns.RcodeSuccess || len(resp.Answer) != 1 || resp.Answer[0].Name != "x.evil.test." {
		t.Fatalf("evil answer for its own name should pass: %+v", resp)
	}
	// none of the smuggled records may have reached the cache
	good, _ := r.Resolve("www.example.com.", dns.TypeA)
	for _, a := range good.Answer {
		if a.Data.String() == "6.6.6.6" {
			t.Fatalf("cache poisoned: %v", good.Answer)
		}
	}
	if good.Answer[len(good.Answer)-1].Data.String() != "192.0.2.80" && good.Answer[len(good.Answer)-1].Data.String() != "192.0.2.81" {
		t.Errorf("unexpected answer %v", good.Answer)
	}
	if ns, _, _, ok := r.Cache.Get("example.com.", dns.TypeNS); ok && ns[0].Data.String() == "ns.evil.test." {
		t.Error("NS poisoned")
	}
}

func TestResolverQueryBudget(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	r.MaxQueries = 2
	resp, _ := r.Resolve("web.example.com.", dns.TypeA)
	if resp.Rcode != dns.RcodeServFail || !strings.Contains(resp.Why, "budget") {
		t.Errorf("budget: %+v", resp)
	}
}

func TestRecursiveServerFrontend(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	front := dns.NewServer()
	front.Resolver = r
	if err := front.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	defer front.Close()
	c := &dns.Client{Timeout: 3 * time.Second, UDPSize: 1232}
	m, err := c.Exchange(front.Addr(), "www.example.com.", dns.TypeA, true)
	if err != nil {
		t.Fatal(err)
	}
	if !m.RecursionAvailable || m.Rcode != dns.RcodeSuccess || len(m.Answer) != 3 || m.Authoritative {
		t.Errorf("%+v", m)
	}
	m, _ = c.Exchange(front.Addr(), "nope.example.com.", dns.TypeA, true)
	if m.Rcode != dns.RcodeNXDomain || len(m.Authority) != 1 {
		t.Errorf("nxdomain via recursor: %+v", m)
	}
	m, _ = c.Exchange(front.Addr(), "www.example.com.", dns.TypeA, false)
	if m.Rcode != dns.RcodeRefused {
		t.Errorf("RD=0 must be refused by a pure recursor: %v", m.Rcode)
	}
}
