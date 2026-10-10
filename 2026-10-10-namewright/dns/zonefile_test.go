package dns

import (
	"strings"
	"testing"
)

func TestZoneFileFeatures(t *testing.T) {
	src := `
$ORIGIN example.org.
$TTL 2h
@ IN SOA ns hostmaster ( 1 ; serial
        1h30m 15m 2w
        300 )
  IN NS ns
ns A 192.0.2.1
   AAAA ::1
www 30 IN CNAME ns
mixed IN 45 TXT "a b" c "d;e" "q\"uote" \065\066
mx IN MX 5 @
$ORIGIN sub.example.org.
x A 10.0.0.1
abs.other.net. A 10.0.0.2
`
	rrs, err := ParseZone(src, "", "t.zone")
	if err != nil {
		t.Fatal(err)
	}
	get := func(name string, ty Type) RR {
		for _, r := range rrs {
			if r.Name == name && r.Type == ty {
				return r
			}
		}
		t.Fatalf("missing %s %s", name, ty)
		return RR{}
	}
	soa := get("example.org.", TypeSOA)
	d := soa.Data.(SOA)
	if d.MName != "ns.example.org." || d.RName != "hostmaster.example.org." || d.Refresh != 5400 || d.Retry != 900 || d.Expire != 1209600 || d.Minimum != 300 {
		t.Errorf("soa: %+v", d)
	}
	if soa.TTL != 7200 {
		t.Errorf("$TTL not applied: %d", soa.TTL)
	}
	if get("example.org.", TypeNS).Data.(NS).Host != "ns.example.org." {
		t.Error("owner omission after SOA")
	}
	if get("ns.example.org.", TypeAAAA).Name != "ns.example.org." {
		t.Error("owner inheritance")
	}
	if get("www.example.org.", TypeCNAME).TTL != 30 {
		t.Error("explicit TTL")
	}
	txt := get("mixed.example.org.", TypeTXT)
	if txt.TTL != 45 {
		t.Errorf("ttl after class: %d", txt.TTL)
	}
	got := txt.Data.(TXT).Strings
	want := []string{"a b", "c", "d;e", `q"uote`, "AB"}
	if len(got) != len(want) {
		t.Fatalf("txt %q", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("txt[%d]=%q want %q", i, got[i], want[i])
		}
	}
	if get("mx.example.org.", TypeMX).Data.(MX).Host != "example.org." {
		t.Error("@ in rdata")
	}
	if get("x.sub.example.org.", TypeA).Name != "x.sub.example.org." {
		t.Error("$ORIGIN switch")
	}
	get("abs.other.net.", TypeA)
}

func TestZoneFileErrors(t *testing.T) {
	cases := []struct{ src, want string }{
		{"$ORIGIN a.\n@ 60 A 1.2.3", "IPv4"},
		{"$ORIGIN a.\n@ 60 A 1.2.3.4 extra", "expected 1 fields"},
		{"$ORIGIN a.\n@ 60 BOGUS x", "unknown record type"},
		{"$ORIGIN a.\n@ A 1.2.3.4", "no TTL"},
		{"@ 60 A 1.2.3.4", "no $ORIGIN"},
		{"$ORIGIN a.\n@ 60 TXT \"unterminated", "unterminated"},
		{"$ORIGIN a.\n@ 60 SOA ( x y", "unbalanced"},
		{"$ORIGIN a.\n@ 60 MX hi mail", "16-bit"},
		{"$ORIGIN a.\n@ 60 A 1.2.3.4\n\n\n$BOGUS x", "unknown directive"},
		{"$ORIGIN a.\n$INCLUDE f", "not supported"},
		{"$ORIGIN a.\na..b. 60 A 1.2.3.4", "empty label"},
		{"$ORIGIN a.\n@ 60 AAAA 192.0.2.1", "IPv6"},
		{"$ORIGIN a.\n@ 99999999999 A 1.2.3.4", "TTL"},
		{"$ORIGIN a.\n@ 60 TXT " + `"` + strings.Repeat("x", 300) + `"`, "exceeds 255"},
	}
	for _, c := range cases {
		_, err := ParseZone(c.src, "", "e.zone")
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%q: got %v, want error containing %q", c.src, err, c.want)
		}
	}
	// errors carry line numbers
	_, err := ParseZone("$ORIGIN a.\n\n\n@ 60 A nope", "", "f.zone")
	if pe, ok := err.(*ParseError); !ok || pe.Line != 4 || pe.File != "f.zone" {
		t.Errorf("want line 4 error, got %#v", err)
	}
}

func TestGenericRData(t *testing.T) {
	rrs, err := ParseZone("$ORIGIN a.\n$TTL 1\nx TYPE65280 \\# 3 010203\ny A \\# 4 c0000201\nz TYPE65281 \\# 0", "", "g")
	if err != nil {
		t.Fatal(err)
	}
	if string(rrs[0].Data.(Unknown).Raw) != "\x01\x02\x03" || rrs[0].Type != 65280 {
		t.Errorf("unknown: %+v", rrs[0])
	}
	if rrs[1].Data.(A).Addr.String() != "192.0.2.1" {
		t.Errorf("generic A: %v", rrs[1].Data)
	}
	if rrs[0].Data.String() != `\# 3 010203` || rrs[2].Data.String() != `\# 0` {
		t.Errorf("presentation: %s / %s", rrs[0].Data, rrs[2].Data)
	}
	if _, err := ParseZone("$ORIGIN a.\n$TTL 1\nx TYPE65280 \\# 4 0102", "", "g"); err == nil {
		t.Error("length mismatch accepted")
	}
}

func TestZoneRoundTripThroughPresentation(t *testing.T) {
	// print every record, re-parse it, expect an identical zone
	for _, r := range allRecords() {
		line := r.String()
		got, err := ParseZone(line, ".", "rt")
		if err != nil {
			t.Errorf("reparse %q: %v", line, err)
			continue
		}
		if len(got) != 1 || !got[0].Equal(r) {
			t.Errorf("round trip mismatch for %q -> %v", line, got)
		}
	}
}

func TestParseTTL(t *testing.T) {
	ok := map[string]uint32{"0": 0, "60": 60, "1m": 60, "1h30m": 5400, "2d": 172800, "1w1d1h1m1s": 694861, "1H": 3600}
	for in, want := range ok {
		if got, err := ParseTTL(in); err != nil || got != want {
			t.Errorf("%s: %d %v", in, got, err)
		}
	}
	for _, in := range []string{"", "h", "1x", "1h30", "-5", "99999999999", "1.5h"} {
		if _, err := ParseTTL(in); err == nil {
			t.Errorf("%q should fail", in)
		}
	}
}
