package dns

import (
	"os"
	"strings"
	"testing"
)

func loadExample(t *testing.T) *Zone {
	t.Helper()
	src, err := os.ReadFile("../miniverse/internet/example.com.zone")
	if err != nil {
		t.Fatal(err)
	}
	z, err := LoadZone(string(src), "example.com.", "example.com.zone")
	if err != nil {
		t.Fatal(err)
	}
	return z
}

func names(rrs []RR) []string {
	var o []string
	for _, r := range rrs {
		o = append(o, r.Name+" "+r.Type.String())
	}
	return o
}

func TestLookupExact(t *testing.T) {
	z := loadExample(t)
	r := z.Lookup("web.example.com.", TypeA, false)
	if r.Rcode != RcodeSuccess || !r.Authoritative || len(r.Answer) != 2 {
		t.Fatalf("%+v", r)
	}
	if r.Answer[0].TTL != 600 {
		t.Errorf("ttl %d", r.Answer[0].TTL)
	}
}

func TestLookupCNAMEChain(t *testing.T) {
	z := loadExample(t)
	r := z.Lookup("www2.example.com.", TypeA, false)
	got := strings.Join(names(r.Answer), ",")
	want := "www2.example.com. CNAME,www.example.com. CNAME,web.example.com. A,web.example.com. A"
	if got != want {
		t.Fatalf("got %s", got)
	}
	// asking for the CNAME itself must not chase
	r = z.Lookup("www.example.com.", TypeCNAME, false)
	if len(r.Answer) != 1 || r.Answer[0].Type != TypeCNAME {
		t.Errorf("CNAME query: %v", names(r.Answer))
	}
	// out-of-zone target: only the CNAME is returned
	r = z.Lookup("blog.example.com.", TypeA, false)
	if len(r.Answer) != 1 || r.Rcode != RcodeSuccess {
		t.Errorf("blog: %v", names(r.Answer))
	}
}

func TestLookupNegative(t *testing.T) {
	z := loadExample(t)
	r := z.Lookup("nope.example.com.", TypeA, false)
	if r.Rcode != RcodeNXDomain || len(r.Answer) != 0 || len(r.Authority) != 1 || r.Authority[0].Type != TypeSOA {
		t.Fatalf("nxdomain: %+v", r)
	}
	if r.Authority[0].TTL != 300 { // min(soa ttl 3600, minimum 300)
		t.Errorf("negative TTL %d", r.Authority[0].TTL)
	}
	r = z.Lookup("web.example.com.", TypeMX, false)
	if r.Rcode != RcodeSuccess || len(r.Answer) != 0 || len(r.Authority) != 1 {
		t.Fatalf("nodata: %+v", r)
	}
}

func TestEmptyNonTerminal(t *testing.T) {
	z := loadExample(t)
	for _, n := range []string{"b.c.example.com.", "c.example.com."} {
		r := z.Lookup(n, TypeA, false)
		if r.Rcode != RcodeSuccess || len(r.Answer) != 0 {
			t.Errorf("%s should be NODATA, got rcode %v", n, r.Rcode)
		}
	}
	if r := z.Lookup("a.b.c.example.com.", TypeA, false); len(r.Answer) != 1 {
		t.Errorf("deep name")
	}
	if r := z.Lookup("z.b.c.example.com.", TypeA, false); r.Rcode != RcodeNXDomain {
		t.Errorf("sibling of ENT child should be NXDOMAIN")
	}
}

func TestWildcard(t *testing.T) {
	z := loadExample(t)
	r := z.Lookup("anything.dev.example.com.", TypeA, false)
	if len(r.Answer) != 1 || r.Answer[0].Name != "anything.dev.example.com." {
		t.Fatalf("synthesis: %v", names(r.Answer))
	}
	if r := z.Lookup("a.b.deeper.dev.example.com.", TypeA, false); len(r.Answer) != 1 || r.Answer[0].Name != "a.b.deeper.dev.example.com." {
		t.Errorf("multi-label wildcard match: %v", names(r.Answer))
	}
	// wildcard exists but not for this type: NODATA, not NXDOMAIN
	r = z.Lookup("x.dev.example.com.", TypeMX, false)
	if r.Rcode != RcodeSuccess || len(r.Answer) != 0 {
		t.Errorf("wildcard nodata: %+v", r)
	}
	// explicit name wins over wildcard for types it lacks too
	r = z.Lookup("fixed.dev.example.com.", TypeA, false)
	if r.Rcode != RcodeSuccess || len(r.Answer) != 0 {
		t.Errorf("explicit node must shadow wildcard: %v", names(r.Answer))
	}
	// the wildcard owner itself is not a match for its parent
	if r := z.Lookup("dev.example.com.", TypeA, false); r.Rcode != RcodeSuccess || len(r.Answer) != 0 {
		t.Errorf("dev.example.com. is an empty non-terminal: %+v", r)
	}
}

func TestDelegation(t *testing.T) {
	z := loadExample(t)
	for _, q := range []string{"sub.example.com.", "host.sub.example.com.", "deep.host.sub.example.com."} {
		r := z.Lookup(q, TypeA, false)
		if r.Authoritative || len(r.Answer) != 0 {
			t.Errorf("%s: referral must clear AA", q)
		}
		if len(r.Authority) != 1 || r.Authority[0].Type != TypeNS || r.Authority[0].Name != "sub.example.com." {
			t.Errorf("%s authority: %v", q, names(r.Authority))
		}
		if len(r.Additional) != 1 || r.Additional[0].Name != "ns.sub.example.com." {
			t.Errorf("%s glue: %v", q, names(r.Additional))
		}
	}
}

func TestAdditionalProcessing(t *testing.T) {
	z := loadExample(t)
	r := z.Lookup("example.com.", TypeMX, false)
	if len(r.Answer) != 2 {
		t.Fatal(names(r.Answer))
	}
	got := strings.Join(names(r.Additional), ",")
	if !strings.Contains(got, "mail.example.com. A") || !strings.Contains(got, "mail2.example.com. AAAA") {
		t.Errorf("MX additional: %s", got)
	}
}

func TestANY(t *testing.T) {
	z := loadExample(t)
	r := z.Lookup("mail2.example.com.", TypeANY, false)
	if len(r.Answer) != 2 {
		t.Errorf("%v", names(r.Answer))
	}
}

func TestZoneValidation(t *testing.T) {
	bad := []struct{ src, want string }{
		{"$ORIGIN a.\n$TTL 1\n@ NS x.a.\nx A 1.1.1.1", "SOA"},
		{"$ORIGIN a.\n$TTL 1\n@ SOA n h 1 1 1 1 1\nw CNAME @\nw A 1.1.1.1", "CNAME and also"},
		{"$ORIGIN a.\n$TTL 1\n@ SOA n h 1 1 1 1 1\nw CNAME @\nw CNAME x", "multiple CNAME"},
		{"$ORIGIN a.\n$TTL 1\n@ SOA n h 1 1 1 1 1\nfoo.b. A 1.1.1.1", "outside zone"},
		{"$ORIGIN a.\n$TTL 1\n@ SOA n h 1 1 1 1 1\nd NS ns.d\nns.d A 1.1.1.1\nx.d TXT \"occluded\"", "below the delegation"},
		{"$ORIGIN a.\n$TTL 1\n@ SOA n h 1 1 1 1 1\n@ SOA n h 2 1 1 1 1", "exactly one SOA"},
	}
	for _, c := range bad {
		_, err := LoadZone(c.src, "a.", "v")
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%q: got %v want %q", c.src, err, c.want)
		}
	}
	z, err := LoadZone("$ORIGIN a.\n$TTL 1\n@ SOA n h 1 1 1 1 1\nw 10 A 1.1.1.1\nw 20 A 1.1.1.2\nw 20 A 1.1.1.2", "a.", "v")
	if err != nil {
		t.Fatal(err)
	}
	if len(z.Warnings) != 3 || z.Lookup("w.a.", TypeA, false).Answer[1].TTL != 10 {
		t.Errorf("warnings=%v", z.Warnings)
	}
}

func TestCaseInsensitiveLookup(t *testing.T) {
	z := loadExample(t)
	if r := z.Lookup("WEB.Example.COM.", TypeA, false); len(r.Answer) != 2 {
		t.Error("case-insensitive lookup failed")
	}
}
