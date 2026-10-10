package dns_test

import (
	"os"
	"testing"

	"namewright/dns"
)

func BenchmarkZoneLookup(b *testing.B) {
	z := loadExampleB(b)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		z.Lookup("www2.example.com.", dns.TypeA, false)
	}
}

func BenchmarkPackUnpack(b *testing.B) {
	z := loadExampleB(b)
	res := z.Lookup("example.com.", dns.TypeMX, false)
	m := &dns.Message{ID: 1, Response: true, Question: []dns.Question{{Name: "example.com.", Type: dns.TypeMX, Class: dns.ClassIN}}, Answer: res.Answer, Additional: res.Additional}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		w, _ := m.Pack()
		dns.Unpack(w)
	}
}

func BenchmarkServerHandle(b *testing.B) {
	z := loadExampleB(b)
	srv := dns.NewServer(z)
	req := dns.NewQuery("www.example.com.", dns.TypeA, false)
	req.SetEDNS(1232, false)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		resp, lim := srv.Handle(req, false, nil)
		resp.PackLimit(lim)
	}
}

func loadExampleB(b *testing.B) *dns.Zone {
	b.Helper()
	srcs, err := readFile("../miniverse/internet/example.com.zone")
	if err != nil {
		b.Fatal(err)
	}
	z, err := dns.LoadZone(srcs, "example.com.", "b")
	if err != nil {
		b.Fatal(err)
	}
	return z
}

func readFile(p string) (string, error) {
	bs, err := os.ReadFile(p)
	return string(bs), err
}
