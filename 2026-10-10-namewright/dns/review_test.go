package dns_test

// Regression tests for defects found in the adversarial review (see REVIEW.md).
// Each of these failed against the phase-2 code.

import (
	"errors"
	"fmt"
	"net"
	"net/netip"
	"strings"
	"sync"
	"testing"
	"time"

	"namewright/dns"
)

// R1: the loop-detection set was global to the Resolver, so two concurrent
// lookups of the same name made each other fail with a "dependency loop".
func TestReviewConcurrentIdenticalResolves(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	var wg sync.WaitGroup
	var mu sync.Mutex
	var bad []string
	for i := 0; i < 40; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			resp, err := r.Resolve("blog.example.com.", dns.TypeA)
			if err != nil || resp.Rcode != dns.RcodeSuccess {
				mu.Lock()
				bad = append(bad, fmt.Sprintf("%v %+v", err, resp))
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	if len(bad) > 0 {
		t.Fatalf("%d/40 concurrent resolutions failed, e.g. %s", len(bad), bad[0])
	}
}

// R2: if every known server of a zone had recently failed, none was tried at all.
func TestReviewAllServersMarkedBadStillTried(t *testing.T) {
	w := world(t)
	root := w.Host("a.root-servers.net")
	addr := root.Srv.Addr()
	r := dns.NewResolver([]dns.RootHint{
		{Name: "a.root-servers.net.", Addr: netip.MustParseAddr("198.51.100.1")},
		{Name: "b.root-servers.net.", Addr: netip.MustParseAddr("198.51.100.99")},
	})
	r.Client.Timeout = 200 * time.Millisecond
	r.Client.Retries = 0
	r.AddrMap = func(ip netip.Addr) string {
		if ip.String() == "198.51.100.99" {
			return addr
		}
		return w.AddrMap(ip)
	}
	root.Srv.Close() // both root addresses now dead
	if resp, _ := r.Resolve("web.example.com.", dns.TypeA); resp.Rcode != dns.RcodeServFail {
		t.Fatalf("expected SERVFAIL while root is down, got %v", resp.Rcode)
	}
	if err := root.Srv.Start(addr); err != nil { // root comes back on the same port
		t.Fatal(err)
	}
	resp, _ := r.Resolve("web.example.com.", dns.TypeA)
	if resp.Rcode != dns.RcodeSuccess {
		t.Fatalf("resolver refused to retry servers it had marked bad: %+v", resp)
	}
}

// (suspected, then refuted) empty non-terminals deeper than one level: kept as a guard.
func TestReviewDeepEmptyNonTerminal(t *testing.T) {
	z, err := dns.LoadZone("$ORIGIN z.org.\n$TTL 1\n@ SOA n h 1 1 1 1 1\n@ NS n\nn A 1.1.1.1\nx.y.k A 1.1.1.1\ny.k A 1.1.1.2", "z.org.", "t")
	if err != nil {
		t.Fatal(err)
	}
	if r := z.Lookup("k.z.org.", dns.TypeA, false); r.Rcode != dns.RcodeSuccess {
		t.Errorf("k.z.org. has descendants, must be NODATA not %v", r.Rcode)
	}
	z2, _ := dns.LoadZone("$ORIGIN z.org.\n$TTL 1\n@ SOA n h 1 1 1 1 1\n@ NS n\nn A 1.1.1.1\nw.x.y.k A 1.1.1.1\ny.k A 1.1.1.2", "z.org.", "t")
	if r := z2.Lookup("k.z.org.", dns.TypeA, false); r.Rcode != dns.RcodeSuccess {
		t.Errorf("ENT above an existing node must still be an ENT, got %v", r.Rcode)
	}
	if r := z2.Lookup("x.y.k.z.org.", dns.TypeA, false); r.Rcode != dns.RcodeSuccess || len(r.Answer) != 0 {
		t.Errorf("x.y.k is an ENT: %v", r.Rcode)
	}
}

// R4: servers that do not preserve question case failed the 0x20 check and
// were declared dead; the resolver must fall back to a plain query.
func TestReviewCase0x20Fallback(t *testing.T) {
	w := world(t)
	real := w.Host("ns1.example.com").Srv
	lc, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer lc.Close()
	go func() {
		buf := make([]byte, 2048)
		for {
			n, a, err := lc.ReadFrom(buf)
			if err != nil {
				return
			}
			q, err := dns.Unpack(buf[:n])
			if err != nil || len(q.Question) != 1 {
				continue
			}
			res := real.Zone("example.com.").Lookup(q.Question[0].Name, q.Question[0].Type, false)
			m := &dns.Message{ID: q.ID, Response: true, Authoritative: res.Authoritative, Rcode: res.Rcode,
				Answer: res.Answer, Authority: res.Authority,
				Question: []dns.Question{{Name: strings.ToLower(q.Question[0].Name), Type: q.Question[0].Type, Class: dns.ClassIN}}}
			b, _ := m.Pack()
			lc.WriteTo(b, a)
		}
	}()
	r := w.NewResolver()
	exampleIP := netip.MustParseAddr("198.51.100.10")
	base := r.AddrMap
	r.AddrMap = func(ip netip.Addr) string {
		if ip == exampleIP {
			return lc.LocalAddr().String()
		}
		return base(ip)
	}
	r.Client.Timeout = 500 * time.Millisecond
	resp, _ := r.Resolve("web.example.com.", dns.TypeA)
	if resp.Rcode != dns.RcodeSuccess || len(resp.Answer) != 2 {
		t.Fatalf("case-folding server broke resolution: %+v", resp)
	}
}

// R5: RFC 2181 §5.4.1 — unauthenticated glue must not displace data that came
// from an authoritative answer.
func TestReviewCacheTrustRanking(t *testing.T) {
	c := dns.NewCache()
	auth := dns.RR{Name: "ns.example.", Type: dns.TypeA, Class: dns.ClassIN, TTL: 3600, Data: dns.A{Addr: netip.MustParseAddr("192.0.2.1")}}
	glue := auth
	glue.Data = dns.A{Addr: netip.MustParseAddr("6.6.6.6")}
	c.PutSetTrust([]dns.RR{auth}, nil, dns.Indeterminate, dns.TrustAnswer)
	c.PutSetTrust([]dns.RR{glue}, nil, dns.Indeterminate, dns.TrustGlue)
	got, _, _, _ := c.Get("ns.example.", dns.TypeA)
	if got[0].Data.String() != "192.0.2.1" {
		t.Errorf("glue overwrote authoritative data: %v", got[0])
	}
	// but equal-or-higher trust replaces, and glue fills an empty slot
	newer := auth
	newer.Data = dns.A{Addr: netip.MustParseAddr("192.0.2.2")}
	c.PutSetTrust([]dns.RR{newer}, nil, dns.Indeterminate, dns.TrustAnswer)
	if got, _, _, _ = c.Get("ns.example.", dns.TypeA); got[0].Data.String() != "192.0.2.2" {
		t.Errorf("same-rank update ignored")
	}
}

// R6: unlimited TCP connections let one client exhaust goroutines/fds.
func TestReviewTCPConnectionCap(t *testing.T) {
	z, _ := dns.LoadZone("$ORIGIN a.\n$TTL 1\n@ SOA n h 1 1 1 1 1\n@ NS n\nn A 1.1.1.1", "a.", "t")
	srv := dns.NewServer(z)
	srv.MaxTCPConns = 2
	if err := srv.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	defer srv.Close()
	var held []net.Conn
	defer func() {
		for _, c := range held {
			c.Close()
		}
	}()
	for i := 0; i < 2; i++ {
		c, err := net.Dial("tcp", srv.Addr())
		if err != nil {
			t.Fatal(err)
		}
		held = append(held, c)
	}
	time.Sleep(100 * time.Millisecond)
	c3, err := net.Dial("tcp", srv.Addr())
	if err != nil {
		t.Fatal(err)
	}
	defer c3.Close()
	c3.SetReadDeadline(time.Now().Add(time.Second))
	_, rerr := c3.Read(make([]byte, 1))
	var ne net.Error
	if rerr == nil || (errors.As(rerr, &ne) && ne.Timeout()) {
		t.Errorf("third connection should be closed by the server, got %v", rerr)
	}
	// a slot frees up when a holder disconnects
	held[0].Close()
	time.Sleep(100 * time.Millisecond)
	cl := &dns.Client{Timeout: time.Second, TCPOnly: true}
	if _, err := cl.Exchange(srv.Addr(), "n.a.", dns.TypeA, false); err != nil {
		t.Errorf("slot not released: %v", err)
	}
}

// R7: a hostile primary could stream an endless AXFR.
func TestReviewAXFRRecordCap(t *testing.T) {
	var sb strings.Builder
	sb.WriteString("$ORIGIN big.\n$TTL 1\n@ SOA n h 1 1 1 1 1\n@ NS n\nn A 1.1.1.1\n")
	for i := 0; i < 2000; i++ {
		fmt.Fprintf(&sb, "h%d A 10.0.%d.%d\n", i, i/250, i%250)
	}
	z, err := dns.LoadZone(sb.String(), "big.", "t")
	if err != nil {
		t.Fatal(err)
	}
	srv := dns.NewServer(z)
	srv.AllowTransfer = func(net.Addr) bool { return true }
	if err := srv.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	defer srv.Close()
	c := &dns.Client{Timeout: 3 * time.Second, MaxTransferRecords: 100}
	if _, err := c.Transfer(srv.Addr(), "big."); err == nil || !strings.Contains(err.Error(), "limit") {
		t.Errorf("transfer over the cap must fail, got %v", err)
	}
	c.MaxTransferRecords = 0 // default cap is generous
	rrs, err := c.Transfer(srv.Addr(), "big.")
	if err != nil || len(rrs) != 2004 {
		t.Errorf("large legit transfer: %d %v", len(rrs), err)
	}
}

// R8: a DS query at a zone cut must be answered by the parent even when the
// same server also hosts the child.
func TestReviewDSAnsweredByParentWhenCoHosted(t *testing.T) {
	parent, _ := dns.LoadZone("$ORIGIN p.\n$TTL 60\n@ SOA n h 1 1 1 1 5\n@ NS n\nn A 1.1.1.1\nc NS ns.c.p.\nns.c A 1.1.1.2", "p.", "t")
	child, _ := dns.LoadZone("$ORIGIN c.p.\n$TTL 60\n@ SOA ns h 1 1 1 1 5\n@ NS ns\nns A 1.1.1.2", "c.p.", "t")
	srv := dns.NewServer(parent, child)
	if err := srv.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	defer srv.Close()
	c := &dns.Client{Timeout: time.Second}
	m, err := c.Exchange(srv.Addr(), "c.p.", dns.TypeDS, false)
	if err != nil {
		t.Fatal(err)
	}
	if m.Rcode != dns.RcodeSuccess || len(m.Authority) != 1 || m.Authority[0].Name != "p." {
		t.Errorf("DS must come from the parent zone (SOA p.): %v", m.Authority)
	}
}

// R9: NSEC type lists parsed from text were kept unsorted in presentation.
func TestReviewNSECTypesSorted(t *testing.T) {
	rrs, err := dns.ParseZone("$ORIGIN a.\n$TTL 1\n@ NSEC b. TXT A RRSIG NS", "", "t")
	if err != nil {
		t.Fatal(err)
	}
	if got := rrs[0].Data.String(); got != "b.a. A NS TXT RRSIG" && got != "b. A NS TXT RRSIG" {
		t.Errorf("types not sorted: %s", got)
	}
}

// R10: a UTF-8 BOM at the start of a zone file made the first record fail.
func TestReviewBOM(t *testing.T) {
	if _, err := dns.ParseZone("\xef\xbb\xbf$ORIGIN a.\n$TTL 1\n@ A 1.1.1.1\n", "", "bom"); err != nil {
		t.Errorf("BOM rejected: %v", err)
	}
}

// R11: IPv4-mapped IPv6 sources must share one rate-limit bucket with the plain IPv4 form.
func TestReviewRateLimiterUnmaps(t *testing.T) {
	now := time.Unix(0, 0)
	l := dns.NewRateLimiter(1, 1)
	l.Now = func() time.Time { return now }
	if !l.Allow("192.0.2.1") {
		t.Fatal("first query must pass")
	}
	if l.Allow("::ffff:192.0.2.1") {
		t.Error("mapped form got a fresh bucket")
	}
	now = now.Add(1500 * time.Millisecond)
	if !l.Allow("192.0.2.1") {
		t.Error("bucket should refill after 1.5s")
	}
}

// R12: Close() blocked until idle TCP clients timed out (10s) instead of dropping them.
func TestReviewCloseDoesNotWaitForIdleTCP(t *testing.T) {
	z, _ := dns.LoadZone("$ORIGIN a.\n$TTL 1\n@ SOA n h 1 1 1 1 1\n@ NS n\nn A 1.1.1.1", "a.", "t")
	srv := dns.NewServer(z)
	if err := srv.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	c, err := net.Dial("tcp", srv.Addr())
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	time.Sleep(50 * time.Millisecond)
	done := make(chan struct{})
	go func() { srv.Close(); close(done) }()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Close hung on an idle TCP connection")
	}
}

// R13: names written with \DDD escapes must match the same name arriving on the wire.
func TestReviewEscapedNameEquivalence(t *testing.T) {
	z, err := dns.LoadZone("$ORIGIN e.\n$TTL 1\n@ SOA n h 1 1 1 1 1\n@ NS n\nn A 1.1.1.1\n\\097bc A 2.2.2.2\nx\\.y A 3.3.3.3", "e.", "t")
	if err != nil {
		t.Fatal(err)
	}
	if r := z.Lookup("abc.e.", dns.TypeA, false); len(r.Answer) != 1 {
		t.Errorf(`\097bc should be the name "abc": rcode %v`, r.Rcode)
	}
	if r := z.Lookup(`X\.Y.e.`, dns.TypeA, false); len(r.Answer) != 1 {
		t.Errorf("escaped dot label lookup failed")
	}
	if dns.CanonName(`\065BC.E`) != "abc.e." {
		t.Errorf("CanonName: %q", dns.CanonName(`\065BC.E`))
	}
}

// R3: if a zone's NS set is cached but the glue for its in-bailiwick
// nameservers is gone (shorter glue TTL, eviction, or a concurrent resolver
// caching the NS set a moment before its glue), resolution deadlocked: the
// nameserver's address can only be found by asking that nameserver.
func TestReviewLostGlueFallsBackToParent(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	if resp, _ := r.Resolve("web.example.com.", dns.TypeA); resp.Rcode != dns.RcodeSuccess {
		t.Fatalf("warmup: %+v", resp)
	}
	r.Cache.Delete("ns1.example.com.", dns.TypeA)
	r.Cache.Delete("web.example.com.", dns.TypeA)
	resp, _ := r.Resolve("web.example.com.", dns.TypeA)
	if resp.Rcode != dns.RcodeSuccess || len(resp.Answer) != 2 {
		t.Fatalf("lost glue wedged the resolver: %+v", resp)
	}
}

// R14: a burst of identical client queries must collapse into one upstream walk.
func TestReviewSingleflight(t *testing.T) {
	w := world(t)
	r := w.NewResolver()
	var wg sync.WaitGroup
	for i := 0; i < 40; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r.Resolve("www.example.com.", dns.TypeA)
		}()
	}
	wg.Wait()
	root := w.Host("a.root-servers.net").Srv.Stats()["queries"]
	if root > 3 {
		t.Errorf("root saw %d queries for 40 identical concurrent lookups; want coalescing", root)
	}
}

// R16: RRSIG TTLs were "harmonised" across different covered types, so a 600s A
// RRset was served with a 300s signature TTL. Each RRSIG must carry its RRset's TTL.
func TestReviewRRSIGTTLMatchesCoveredRRset(t *testing.T) {
	z, _, _ := signedExample(t, dns.AlgED25519)
	for _, r := range z.Records() {
		if r.Type != dns.TypeRRSIG {
			continue
		}
		sig := r.Data.(dns.RRSIG)
		if r.TTL != sig.OrigTTL {
			t.Errorf("%s RRSIG(%s) TTL %d != original TTL %d", r.Name, sig.TypeCovered, r.TTL, sig.OrigTTL)
		}
	}
}
