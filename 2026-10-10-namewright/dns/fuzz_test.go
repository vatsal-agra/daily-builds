package dns

import (
	"bytes"
	"testing"
)

// FuzzUnpack: decoding arbitrary bytes must never panic, and anything that
// decodes must re-encode to a message that decodes to the same records.
func FuzzUnpack(f *testing.F) {
	m := &Message{ID: 1, Response: true, Question: []Question{{"a.example.com.", TypeANY, ClassIN}}, Answer: allRecords()}
	m.SetEDNS(1232, true)
	wire, _ := m.Pack()
	f.Add(wire)
	q := &Message{ID: 9, Question: []Question{{"www.example.com.", TypeA, ClassIN}}}
	qw, _ := q.Pack()
	f.Add(qw)
	f.Add([]byte{})
	f.Add(bytes.Repeat([]byte{0xC0, 0x0C}, 30))
	f.Fuzz(func(t *testing.T, data []byte) {
		msg, err := Unpack(data)
		if err != nil {
			return
		}
		again, err := msg.Pack()
		if err != nil {
			// decoded names may legitimately be un-encodable only via limits we enforce symmetrically
			t.Fatalf("decoded message does not re-encode: %v", err)
		}
		msg2, err := Unpack(again)
		if err != nil {
			t.Fatalf("re-encoded message does not decode: %v", err)
		}
		if len(msg2.Answer) != len(msg.Answer) || len(msg2.Authority) != len(msg.Authority) || len(msg2.Additional) != len(msg.Additional) {
			t.Fatalf("section counts changed")
		}
		for i := range msg.Answer {
			if !msg.Answer[i].Equal(msg2.Answer[i]) {
				t.Fatalf("answer %d changed: %s vs %s", i, msg.Answer[i], msg2.Answer[i])
			}
		}
		_ = msg.Format()
	})
}

// FuzzZoneFile: arbitrary zone text must produce an error or records, never a panic.
func FuzzZoneFile(f *testing.F) {
	f.Add("$ORIGIN a.\n$TTL 1\n@ SOA n h ( 1 2 3 4 5 )\n@ TXT \"x\\\"y\" z\n")
	f.Add("\\# 3 abcdef")
	f.Fuzz(func(t *testing.T, src string) {
		rrs, err := ParseZone(src, "fuzz.", "f")
		if err != nil {
			return
		}
		for _, r := range rrs {
			_ = r.String()
		}
	})
}
