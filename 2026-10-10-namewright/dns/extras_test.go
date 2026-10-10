package dns_test

import (
	"fmt"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	"namewright/dns"
)

func zoneWithSerial(t *testing.T, serial uint32, extra string) *dns.Zone {
	t.Helper()
	src := fmt.Sprintf("$ORIGIN sec.test.\n$TTL 60\n@ SOA ns h %d 600 120 3600 30\n@ NS ns\nns A 192.0.2.1\n%s", serial, extra)
	z, err := dns.LoadZone(src, "sec.test.", "t")
	if err != nil {
		t.Fatal(err)
	}
	return z
}

func TestSerialArithmetic(t *testing.T) {
	cases := []struct {
		a, b uint32
		want bool
	}{{2, 1, true}, {1, 2, false}, {1, 1, false}, {0, 0xFFFFFFFF, true}, {0xFFFFFFFF, 0, false}, {5, 5 + 1<<31, false}, {1 << 31, 0, false}}
	for _, c := range cases {
		if got := dns.SerialGreater(c.a, c.b); got != c.want {
			t.Errorf("SerialGreater(%d,%d)=%v want %v", c.a, c.b, got, c.want)
		}
	}
}

func TestSecondaryFollowsPrimary(t *testing.T) {
	primary := dns.NewServer(zoneWithSerial(t, 10, "www A 192.0.2.80\n"))
	primary.AllowTransfer = func(net.Addr) bool { return true }
	if err := primary.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	defer primary.Close()
	replica := dns.NewServer()
	if err := replica.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	defer replica.Close()
	now := time.Unix(1_800_000_000, 0)
	sec := dns.NewSecondary("sec.test.", primary.Addr(), replica)
	sec.Now = func() time.Time { return now }
	c := &dns.Client{Timeout: time.Second}

	ask := func() *dns.Message {
		m, err := c.Exchange(replica.Addr(), "www.sec.test.", dns.TypeA, false)
		if err != nil {
			t.Fatal(err)
		}
		return m
	}
	if m := ask(); m.Rcode != dns.RcodeRefused {
		t.Fatalf("before first transfer the replica must refuse: %v", m.Rcode)
	}
	if up, err := sec.Refresh(); !up || err != nil {
		t.Fatalf("first refresh: %v %v", up, err)
	}
	if m := ask(); m.Rcode != 0 || !m.Authoritative || len(m.Answer) != 1 {
		t.Fatalf("replica answer: %+v", m)
	}
	if up, _ := sec.Refresh(); up {
		t.Error("unchanged serial must not trigger a transfer")
	}
	// primary publishes a new version
	primary.SetZone(zoneWithSerial(t, 11, "www A 192.0.2.81\nnew A 192.0.2.82\n"))
	if up, err := sec.Refresh(); !up || err != nil {
		t.Fatalf("refresh after update: %v %v", up, err)
	}
	if m := ask(); m.Answer[0].Data.String() != "192.0.2.81" {
		t.Errorf("replica did not pick up the new data: %v", m.Answer)
	}
	if s, ok := sec.Serial(); s != 11 || !ok {
		t.Errorf("serial %d %v", s, ok)
	}
	// a primary that goes backwards is ignored
	primary.SetZone(zoneWithSerial(t, 5, "www A 6.6.6.6\n"))
	if up, _ := sec.Refresh(); up {
		t.Error("serial regression accepted")
	}
	if m := ask(); m.Answer[0].Data.String() != "192.0.2.81" {
		t.Errorf("regressed data served: %v", m.Answer)
	}
	// primary dies: replica keeps serving until EXPIRE (3600s), then withdraws the zone
	primary.Close()
	now = now.Add(1800 * time.Second)
	if _, err := sec.Refresh(); err == nil {
		t.Error("expected an error with the primary down")
	}
	if m := ask(); m.Rcode != 0 {
		t.Errorf("zone withdrawn too early: %v", m.Rcode)
	}
	now = now.Add(2000 * time.Second) // 3800s since the last success > expire
	sec.Refresh()
	if m := ask(); m.Rcode != dns.RcodeRefused {
		t.Errorf("zone must be withdrawn after EXPIRE, got %v", m.Rcode)
	}
}

func TestSecondaryRefusedTransfer(t *testing.T) {
	primary := dns.NewServer(zoneWithSerial(t, 1, ""))
	if err := primary.Start("127.0.0.1:0"); err != nil { // AllowTransfer nil: AXFR denied
		t.Fatal(err)
	}
	defer primary.Close()
	sec := dns.NewSecondary("sec.test.", primary.Addr(), dns.NewServer())
	if _, err := sec.Refresh(); err == nil || !strings.Contains(err.Error(), "REFUSED") {
		t.Errorf("want a refused-transfer error, got %v", err)
	}
	if _, ok := sec.Serial(); ok {
		t.Error("nothing should be loaded")
	}
}

func TestRateLimitingOnServer(t *testing.T) {
	z := zoneWithSerial(t, 1, "")
	srv := dns.NewServer(z)
	var clk struct {
		sync.Mutex
		t time.Time
	}
	clk.t = time.Unix(0, 0)
	srv.Limiter = dns.NewRateLimiter(2, 3)
	srv.Limiter.Now = func() time.Time { clk.Lock(); defer clk.Unlock(); return clk.t }
	if err := srv.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	defer srv.Close()
	c := &dns.Client{Timeout: 300 * time.Millisecond}
	answered, dropped := 0, 0
	for i := 0; i < 8; i++ {
		if _, err := c.Exchange(srv.Addr(), "ns.sec.test.", dns.TypeA, false); err == nil {
			answered++
		} else {
			dropped++
		}
	}
	if answered != 3 || dropped != 5 {
		t.Errorf("burst of 3 expected: answered=%d dropped=%d", answered, dropped)
	}
	if srv.Stats()["rate-limited"] != 5 {
		t.Errorf("stats: %v", srv.Stats())
	}
	clk.Lock()
	clk.t = clk.t.Add(time.Second) // 2 tokens refill
	clk.Unlock()
	ok := 0
	for i := 0; i < 4; i++ {
		if _, err := c.Exchange(srv.Addr(), "ns.sec.test.", dns.TypeA, false); err == nil {
			ok++
		}
	}
	if ok != 2 {
		t.Errorf("after refill expected 2 answers, got %d", ok)
	}
	// TCP is not rate limited (it cannot be spoofed)
	tcp := &dns.Client{Timeout: time.Second, TCPOnly: true}
	if _, err := tcp.Exchange(srv.Addr(), "ns.sec.test.", dns.TypeA, false); err != nil {
		t.Errorf("TCP should bypass the UDP limiter: %v", err)
	}
}

func TestResponsePolicy(t *testing.T) {
	p, err := dns.ParsePolicy(`
# blocklist
ads.example.   NXDOMAIN
*.tracker.test. NXDOMAIN
quiet.test.    NODATA
portal.test.   A 10.1.1.1
portal6.test.  AAAA fd00::1
`)
	if err != nil {
		t.Fatal(err)
	}
	z := zoneWithSerial(t, 1, "ads A 1.2.3.4\n")
	srv := dns.NewServer(z)
	srv.Policy = p
	if err := srv.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	defer srv.Close()
	c := &dns.Client{Timeout: time.Second}
	q := func(n string, ty dns.Type) *dns.Message {
		m, err := c.Exchange(srv.Addr(), n, ty, false)
		if err != nil {
			t.Fatal(err)
		}
		return m
	}
	if m := q("ads.example.", dns.TypeA); m.Rcode != dns.RcodeNXDomain {
		t.Errorf("exact block: %v", m.Rcode)
	}
	if m := q("x.y.tracker.test.", dns.TypeA); m.Rcode != dns.RcodeNXDomain {
		t.Errorf("wildcard block: %v", m.Rcode)
	}
	if m := q("tracker.test.", dns.TypeA); m.Rcode != dns.RcodeNXDomain {
		t.Errorf("wildcard rule includes the apex: %v", m.Rcode)
	}
	if m := q("quiet.test.", dns.TypeA); m.Rcode != 0 || len(m.Answer) != 0 {
		t.Errorf("nodata: %+v", m)
	}
	if m := q("PORTAL.test.", dns.TypeA); len(m.Answer) != 1 || m.Answer[0].Data.String() != "10.1.1.1" {
		t.Errorf("redirect (case-insensitive): %v", m.Answer)
	}
	if m := q("portal.test.", dns.TypeAAAA); m.Rcode != 0 || len(m.Answer) != 0 {
		t.Errorf("redirect for the other family is NODATA: %+v", m)
	}
	if m := q("portal6.test.", dns.TypeAAAA); len(m.Answer) != 1 {
		t.Errorf("v6 redirect: %v", m.Answer)
	}
	if m := q("ns.sec.test.", dns.TypeA); len(m.Answer) != 1 {
		t.Errorf("unrelated names untouched: %+v", m)
	}
	for _, bad := range []string{"x.test.", "x.test. BOGUS", "x.test. A", "x.test. A nonsense", "x.test. A ::1", "x.test. AAAA 1.2.3.4", "a..b. NXDOMAIN"} {
		if _, err := dns.ParsePolicy(bad); err == nil {
			t.Errorf("policy %q should be rejected", bad)
		}
	}
}
