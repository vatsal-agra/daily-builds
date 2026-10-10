package dns

import (
	"bytes"
	"encoding/hex"
	"net/netip"
	"strings"
	"testing"
)

func mustPack(t *testing.T, m *Message) []byte {
	t.Helper()
	b, err := m.Pack()
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// A hand-assembled query for www.example.com A IN, RD=1, id 0xbeef.
func TestKnownQueryBytes(t *testing.T) {
	want, _ := hex.DecodeString("beef0100" + "0001" + "0000" + "0000" + "0000" +
		"03777777" + "076578616d706c65" + "03636f6d00" + "0001" + "0001")
	m := &Message{ID: 0xbeef, RecursionDesired: true, Question: []Question{{"www.example.com.", TypeA, ClassIN}}}
	got := mustPack(t, m)
	if !bytes.Equal(got, want) {
		t.Fatalf("got  %x\nwant %x", got, want)
	}
	back, err := Unpack(want)
	if err != nil || back.ID != 0xbeef || !back.RecursionDesired || back.Question[0].Name != "www.example.com." {
		t.Fatalf("decode: %+v %v", back, err)
	}
}

func allRecords() []RR {
	return []RR{
		{"a.example.com.", TypeA, ClassIN, 300, A{netip.MustParseAddr("192.0.2.1")}},
		{"a.example.com.", TypeAAAA, ClassIN, 300, AAAA{netip.MustParseAddr("2001:db8::1")}},
		{"example.com.", TypeNS, ClassIN, 300, NS{"ns1.example.com."}},
		{"www.example.com.", TypeCNAME, ClassIN, 300, CNAME{"a.example.com."}},
		{"example.com.", TypeSOA, ClassIN, 300, SOA{"ns1.example.com.", "hostmaster.example.com.", 1, 2, 3, 4, 5}},
		{"example.com.", TypeMX, ClassIN, 300, MX{10, "mail.example.com."}},
		{"example.com.", TypeTXT, ClassIN, 300, TXT{[]string{"hello", "wor\"ld\\", "bin\x00\xff"}}},
		{"1.2.0.192.in-addr.arpa.", TypePTR, ClassIN, 300, PTR{"a.example.com."}},
		{"_sip._tcp.example.com.", TypeSRV, ClassIN, 300, SRV{1, 2, 5060, "sip.example.com."}},
		{"example.com.", TypeCAA, ClassIN, 300, CAA{0, "issue", "letsencrypt.org"}},
		{"example.com.", TypeDNSKEY, ClassIN, 300, DNSKEY{257, 3, 15, bytes.Repeat([]byte{7}, 32)}},
		{"example.com.", TypeDS, ClassIN, 300, DS{1234, 15, 2, bytes.Repeat([]byte{9}, 32)}},
		{"example.com.", TypeRRSIG, ClassIN, 300, RRSIG{TypeA, 15, 2, 300, 2000000000, 1000000000, 1234, "example.com.", []byte{1, 2, 3, 4}}},
		{"example.com.", TypeNSEC, ClassIN, 300, NSEC{"a.example.com.", []Type{TypeA, TypeNS, TypeSOA, TypeRRSIG, TypeNSEC, TypeCAA}}},
		{"x.example.com.", Type(65280), ClassIN, 300, Unknown{[]byte{1, 2, 3}}},
		{"empty.example.com.", Type(65281), ClassIN, 300, Unknown{nil}},
	}
}

func TestRoundTripAllTypes(t *testing.T) {
	m := &Message{ID: 7, Response: true, Authoritative: true, Question: []Question{{"a.example.com.", TypeANY, ClassIN}}, Answer: allRecords()}
	m.Authority = []RR{m.Answer[2]}
	m.Additional = []RR{m.Answer[0]}
	m.SetEDNS(1232, true)
	wire := mustPack(t, m)
	back, err := Unpack(wire)
	if err != nil {
		t.Fatal(err)
	}
	if len(back.Answer) != len(m.Answer) {
		t.Fatalf("answers %d != %d", len(back.Answer), len(m.Answer))
	}
	for i, r := range m.Answer {
		if !r.Equal(back.Answer[i]) || r.String() != back.Answer[i].String() {
			t.Errorf("record %d mismatch:\n  %s\n  %s", i, r, back.Answer[i])
		}
	}
	e, ok := back.GetEDNS()
	if !ok || !e.DO || e.UDPSize != 1232 {
		t.Errorf("edns lost: %+v %v", e, ok)
	}
	// second pass must be byte-identical (deterministic encoding)
	if again := mustPack(t, back); !bytes.Equal(again, wire) {
		t.Errorf("re-encode differs")
	}
}

func TestNameCompression(t *testing.T) {
	m := &Message{Response: true, Question: []Question{{"www.example.com.", TypeA, ClassIN}}}
	for i := 0; i < 10; i++ {
		m.Answer = append(m.Answer, RR{"www.example.com.", TypeA, ClassIN, 60, A{netip.AddrFrom4([4]byte{10, 0, 0, byte(i)})}})
	}
	wire := mustPack(t, m)
	// uncompressed would be 12+21 + 10*(17+4+10) ; compressed owner is 2 bytes
	if len(wire) > 12+21+10*(2+10+4) {
		t.Errorf("compression ineffective: %d bytes", len(wire))
	}
	if bytes.Count(wire, []byte("example")) != 1 {
		t.Errorf("name written more than once")
	}
	// case-insensitive suffix sharing
	m2 := &Message{Question: []Question{{"A.Example.COM.", TypeA, ClassIN}}, Answer: []RR{{"b.example.com.", TypeA, ClassIN, 1, A{netip.MustParseAddr("1.1.1.1")}}}}
	if w := mustPack(t, m2); bytes.Count(bytes.ToLower(w), []byte("example")) != 1 {
		t.Errorf("suffix not shared across case")
	}
	back, err := Unpack(wire)
	if err != nil || len(back.Answer) != 10 || back.Answer[9].Name != "www.example.com." {
		t.Fatalf("decode: %v", err)
	}
}

func TestMalformedNeverPanics(t *testing.T) {
	hdr := func(qd, an int) []byte {
		h := make([]byte, 12)
		h[5], h[7] = byte(qd), byte(an)
		return h
	}
	cases := map[string][]byte{
		"empty":           {},
		"short header":    {1, 2, 3},
		"self pointer":    append(hdr(1, 0), 0xC0, 12, 0, 1, 0, 1),
		"forward pointer": append(hdr(1, 0), 0xC0, 40, 0, 1, 0, 1),
		"pointer loop":    append(hdr(1, 0), 3, 'a', 'b', 'c', 0xC0, 12, 0, 1, 0, 1),
		"reserved label":  append(hdr(1, 0), 0x80, 0, 0, 1, 0, 1),
		"label past end":  append(hdr(1, 0), 60, 'a'),
		"huge count":      {0, 0, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF},
		"missing qtype":   append(hdr(1, 0), 0),
		"rdlen too big":   append(append(hdr(0, 1), 0, 0, 1, 0, 1, 0, 0, 0, 0), 0xFF, 0xFF),
		"A with 3 bytes":  append(append(hdr(0, 1), 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 3), 1, 2, 3),
		"A with 5 bytes":  append(append(hdr(0, 1), 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 5), 1, 2, 3, 4, 5),
		"txt overrun":     append(append(hdr(0, 1), 0, 0, 16, 0, 1, 0, 0, 0, 0, 0, 2), 9, 'a'),
		"name 300 bytes":  append(hdr(1, 0), append(bytes.Repeat([]byte{63, 'a'}, 0), longWire()...)...),
		"bad nsec bitmap": append(append(hdr(0, 1), 0, 0, 47, 0, 1, 0, 0, 0, 0, 0, 5), 0, 9, 9, 9, 9),
	}
	for name, pkt := range cases {
		if _, err := Unpack(pkt); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
}

func longWire() []byte {
	var b []byte
	for i := 0; i < 6; i++ {
		b = append(b, 62)
		b = append(b, bytes.Repeat([]byte{'a'}, 62)...)
	}
	return append(b, 0, 0, 1, 0, 1)
}

func TestEscapedLabels(t *testing.T) {
	m := &Message{Question: []Question{{`a\.b.example.com.`, TypeA, ClassIN}}}
	wire := mustPack(t, m)
	if wire[12] != 3 || string(wire[13:16]) != "a.b" {
		t.Fatalf("escaped dot not a single label: %x", wire[12:20])
	}
	back, err := Unpack(wire)
	if err != nil || back.Question[0].Name != `a\.b.example.com.` {
		t.Fatalf("round trip: %v %q", err, back.Question[0].Name)
	}
	if _, err := splitName(strings.Repeat("a", 64) + ".com."); err == nil {
		t.Error("64-byte label accepted")
	}
	if _, err := splitName("a..com."); err == nil {
		t.Error("empty label accepted")
	}
}

func TestPackLimitTruncates(t *testing.T) {
	m := &Message{ID: 1, Response: true, Question: []Question{{"big.example.com.", TypeTXT, ClassIN}}}
	for i := 0; i < 10; i++ {
		m.Answer = append(m.Answer, RR{"big.example.com.", TypeTXT, ClassIN, 60, TXT{[]string{strings.Repeat("x", 100)}}})
	}
	m.SetEDNS(1232, false)
	wire, err := m.PackLimit(512)
	if err != nil {
		t.Fatal(err)
	}
	if len(wire) > 512 {
		t.Fatalf("exceeds limit: %d", len(wire))
	}
	back, err := Unpack(wire)
	if err != nil {
		t.Fatal(err)
	}
	if !back.Truncated || len(back.Answer) >= 10 {
		t.Errorf("expected TC and partial answer, got tc=%v an=%d", back.Truncated, len(back.Answer))
	}
	full, _ := m.PackLimit(4096)
	back, _ = Unpack(full)
	if back.Truncated || len(back.Answer) != 10 {
		t.Errorf("unexpected truncation at 4096")
	}
	if _, ok := back.GetEDNS(); !ok {
		t.Errorf("OPT dropped")
	}
}

func TestLongTXTRejected(t *testing.T) {
	m := &Message{Answer: []RR{{"a.", TypeTXT, ClassIN, 1, TXT{[]string{strings.Repeat("x", 256)}}}}}
	if _, err := m.Pack(); err == nil {
		t.Error("256-byte character-string should fail")
	}
}

func TestNSECBitmapRoundTrip(t *testing.T) {
	in := []Type{TypeA, TypeMX, TypeRRSIG, TypeNSEC, 300, 1000, 65000}
	out, err := unpackBitmap(packBitmap(in))
	if err != nil || len(out) != len(in) {
		t.Fatalf("%v %v", out, err)
	}
	for i, ty := range []Type{TypeA, TypeMX, TypeRRSIG, TypeNSEC, 300, 1000, 65000} {
		if out[i] != ty {
			t.Errorf("bit %d: %v != %v", i, out[i], ty)
		}
	}
}

func TestCanonicalNameOrder(t *testing.T) {
	// RFC 4034 §6.1 example ordering
	order := []string{"example.", "a.example.", "yljkjljk.a.example.", "Z.a.example.", "zABC.a.EXAMPLE.", "z.example.", `\001.z.example.`, "*.z.example.", `\200.z.example.`}
	for i := 0; i+1 < len(order); i++ {
		if CompareNames(order[i], order[i+1]) >= 0 {
			t.Errorf("%s should sort before %s", order[i], order[i+1])
		}
	}
}
