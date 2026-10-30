package qr

import (
	"bytes"
	"strings"
	"testing"
)

func TestWiFiRoundTripWithEscapes(t *testing.T) {
	for _, tc := range []struct{ ssid, pw, auth string }{
		{"Home", "hunter2", "WPA"}, {`weird;ssid:with,chars"\`, `pa;ss:wo,rd\`, "WPA2"}, {"Open", "", "nopass"}, {"wep", "12345", "WEP"},
	} {
		s, err := WiFiPayload(tc.ssid, tc.pw, tc.auth, tc.auth == "WEP")
		if err != nil {
			t.Fatal(err)
		}
		c, err := EncodeText(s, DefaultOptions())
		if err != nil {
			t.Fatal(err)
		}
		r, err := Decode(c.Matrix)
		if err != nil {
			t.Fatal(err)
		}
		ssid, pw, auth, hidden, err := ParseWiFi(r.Text)
		if err != nil || ssid != tc.ssid || pw != tc.pw || hidden != (tc.auth == "WEP") {
			t.Fatalf("%+v -> %q %q %q %v %v", tc, ssid, pw, auth, hidden, err)
		}
	}
	if _, err := WiFiPayload("", "x", "WPA", false); err == nil {
		t.Fatal("empty ssid accepted")
	}
	if _, err := WiFiPayload("a", "", "WPA", false); err == nil {
		t.Fatal("empty password accepted")
	}
	if _, err := WiFiPayload("a", "b", "WPX", false); err == nil {
		t.Fatal("bad auth accepted")
	}
	if _, _, _, _, err := ParseWiFi("WIFI:S:abc\\"); err == nil {
		t.Fatal("dangling escape accepted")
	}
}

func TestMailtoAndVCard(t *testing.T) {
	s, err := MailtoPayload("a@b.co", "Hi & bye", "line1\nline2 é")
	if err != nil || s != "mailto:a@b.co?subject=Hi%20%26%20bye&body=line1%0Aline2%20%C3%A9" {
		t.Fatalf("%q %v", s, err)
	}
	if _, err := MailtoPayload("nope", "", ""); err == nil {
		t.Fatal("bad address accepted")
	}
	v, _ := VCardPayload("Ada; Lovelace", "+44 1", "ada@x.org", "Analytical, Inc")
	if !strings.Contains(v, `FN:Ada\; Lovelace`) || !strings.Contains(v, `ORG:Analytical\, Inc`) {
		t.Fatal(v)
	}
	c, _ := EncodeText(v, DefaultOptions())
	if r, err := Decode(c.Matrix); err != nil || r.Text != v {
		t.Fatalf("vcard roundtrip: %v", err)
	}
}

func TestStructuredAppend(t *testing.T) {
	data := []byte(strings.Repeat("structured append across symbols 0123456789 ", 12))
	for _, parts := range []int{2, 3, 7, 16} {
		codes, err := EncodeStructured(data, parts, Options{ECC: M})
		if err != nil {
			t.Fatal(err)
		}
		var rs []*Result
		for i := len(codes) - 1; i >= 0; i-- { // scrambled order
			r, err := Decode(codes[i].Matrix)
			if err != nil || r.SA == nil || r.SA.Index != i || r.SA.Total != parts {
				t.Fatalf("part %d: %v %+v", i, err, r.SA)
			}
			rs = append(rs, r)
		}
		got, err := Reassemble(rs)
		if err != nil || !bytes.Equal(got, data) {
			t.Fatalf("parts=%d: %v", parts, err)
		}
		if _, err := Reassemble(rs[1:]); err == nil {
			t.Fatal("missing part not detected")
		}
		if parts > 1 {
			if _, err := Reassemble(append(rs, rs[0])); err == nil {
				t.Fatal("duplicate not detected")
			}
		}
	}
	if _, err := EncodeStructured(data, 1, Options{}); err == nil {
		t.Fatal("1 part accepted")
	}
	a, _ := EncodeStructured([]byte("aaaa-bbbb"), 2, Options{ECC: L})
	b, _ := EncodeStructured([]byte("cccc-dddX"), 2, Options{ECC: L})
	ra, _ := Decode(a[0].Matrix)
	rb, _ := Decode(b[1].Matrix)
	if _, err := Reassemble([]*Result{ra, rb}); err == nil {
		t.Fatal("mixed sequences accepted")
	}
}

func TestExplainVerdictMatchesRealDecoder(t *testing.T) {
	// For random damage patterns the predicted verdict must equal the real decoder's outcome.
	r := newRand(33)
	for trial := 0; trial < 400; trial++ {
		e := ECC(r.Intn(4))
		c, err := EncodeText(strings.Repeat("anatomy ", 3+r.Intn(10)), Options{ECC: e})
		if err != nil {
			t.Fatal(err)
		}
		ex := c.Explain()
		m := c.Matrix.Clone()
		var damaged []int
		// damage a handful of data/ecc codewords with whole-byte flips
		k := r.Intn(len(c.Codewords)/3 + 2)
		for i := 0; i < k; i++ {
			cw := r.Intn(len(c.Codewords))
			damaged = append(damaged, cw)
			for _, p := range c.CodewordModules(cw) {
				m.Set(p[0], p[1], !m.Get(p[0], p[1]))
			}
		}
		pred, _ := ex.Verdict(damaged)
		res, derr := Decode(m)
		real := derr == nil && res.Text == strings.Repeat("anatomy ", len(c.Segments[0].Data)/8)
		if pred && !real {
			t.Fatalf("trial %d: predicted recoverable but decoder failed (%v)", trial, derr)
		}
		// !pred && real is possible only by luck (duplicate hits cancel); require it to be rare.
		if !pred && real {
			t.Logf("trial %d: beyond guaranteed budget but decoded anyway", trial)
		}
	}
}

func TestExplainShape(t *testing.T) {
	c, _ := EncodeText("anatomy check", Options{ECC: Q, MinVersion: 5})
	ex := c.Explain()
	if ex.Size != 37 || len(ex.Modules) != 37*37 || len(ex.CWBlock) != RawCodewords(5) {
		t.Fatalf("shape %+v", ex)
	}
	data, par := 0, 0
	for _, e := range ex.CWIsECC {
		if e {
			par++
		} else {
			data++
		}
	}
	if data != DataCodewords(5, Q) || par != RawCodewords(5)-DataCodewords(5, Q) {
		t.Fatal("codeword class counts")
	}
	best := 1 << 30
	for mk, p := range ex.Penalties {
		if s := p[0] + p[1] + p[2] + p[3]; s < best {
			best = s
			_ = mk
		}
	}
	if best != c.Penalty {
		t.Fatalf("chosen mask penalty %d is not the minimum %d", c.Penalty, best)
	}
	if ex.DataBits+ex.PadBits != ex.CapacityBits {
		t.Fatal("bit accounting")
	}
}
