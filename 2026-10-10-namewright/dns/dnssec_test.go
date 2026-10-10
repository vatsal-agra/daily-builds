package dns_test

import (
	"crypto/rand"
	"strings"
	"testing"
	"time"

	"namewright/dns"
	"namewright/miniverse"
)

func rrsetA(owner string, ips ...string) []dns.RR {
	var out []dns.RR
	for _, ip := range ips {
		out = append(out, dns.RR{Name: owner, Type: dns.TypeA, Class: dns.ClassIN, TTL: 300, Data: dns.A{Addr: dns.MustAddr(ip)}})
	}
	return out
}

func newKey(t *testing.T, alg uint8, ksk bool) *dns.Key {
	t.Helper()
	k, err := dns.GenerateKey("example.com.", alg, ksk)
	if err != nil {
		t.Fatal(err)
	}
	return k
}

func TestSignVerifyRoundTrip(t *testing.T) {
	now := time.Now()
	for _, alg := range []uint8{dns.AlgED25519, dns.AlgECDSAP256SHA256} {
		k := newKey(t, alg, false)
		set := rrsetA("www.example.com.", "192.0.2.1", "192.0.2.2")
		sigRR, err := dns.SignRRset(k, "example.com.", set, now.Add(-time.Hour), now.Add(time.Hour))
		if err != nil {
			t.Fatal(err)
		}
		sig := sigRR.Data.(dns.RRSIG)
		if err := dns.VerifyRRSIG(sig, k.Public, set, now); err != nil {
			t.Fatalf("alg %d: %v", alg, err)
		}
		// RR order and owner case must not matter (canonical form)
		rev := []dns.RR{set[1], set[0]}
		rev[0].Name, rev[1].Name = "WWW.Example.COM.", "www.EXAMPLE.com."
		if err := dns.VerifyRRSIG(sig, k.Public, rev, now); err != nil {
			t.Errorf("alg %d: canonical ordering/case: %v", alg, err)
		}
		// any change must break it
		bad := rrsetA("www.example.com.", "192.0.2.1", "192.0.2.3")
		if err := dns.VerifyRRSIG(sig, k.Public, bad, now); err != dns.ErrSigInvalid {
			t.Errorf("alg %d: tampered data accepted: %v", alg, err)
		}
		sig2 := sig
		sig2.Signature = append([]byte(nil), sig.Signature...)
		sig2.Signature[5] ^= 1
		if err := dns.VerifyRRSIG(sig2, k.Public, set, now); err == nil {
			t.Errorf("alg %d: flipped signature bit accepted", alg)
		}
		other := newKey(t, alg, false)
		if err := dns.VerifyRRSIG(sig, other.Public, set, now); err == nil {
			t.Errorf("alg %d: wrong key accepted", alg)
		}
		if err := dns.VerifyRRSIG(sig, k.Public, set, now.Add(2*time.Hour)); err != dns.ErrSigExpired {
			t.Errorf("alg %d: expiry: %v", alg, err)
		}
		if err := dns.VerifyRRSIG(sig, k.Public, set, now.Add(-2*time.Hour)); err != dns.ErrSigNotYet {
			t.Errorf("alg %d: inception: %v", alg, err)
		}
		// changing the TTL does not matter (OrigTTL is signed, not the served TTL)
		aged := rrsetA("www.example.com.", "192.0.2.1", "192.0.2.2")
		aged[0].TTL, aged[1].TTL = 17, 17
		if err := dns.VerifyRRSIG(sig, k.Public, aged, now); err != nil {
			t.Errorf("alg %d: decremented TTL broke the signature: %v", alg, err)
		}
	}
}

func TestWildcardSignatureLabels(t *testing.T) {
	k := newKey(t, dns.AlgED25519, false)
	now := time.Now()
	wild := rrsetA("*.dev.example.com.", "192.0.2.99")
	sigRR, _ := dns.SignRRset(k, "example.com.", wild, now.Add(-time.Hour), now.Add(time.Hour))
	sig := sigRR.Data.(dns.RRSIG)
	if sig.Labels != 3 {
		t.Fatalf("labels field = %d, want 3 (wildcard label not counted)", sig.Labels)
	}
	expanded := rrsetA("anything.dev.example.com.", "192.0.2.99")
	if err := dns.VerifyRRSIG(sig, k.Public, expanded, now); err != nil {
		t.Errorf("synthesised answer must verify against the wildcard signature: %v", err)
	}
}

func TestDSAndKeyTag(t *testing.T) {
	k := newKey(t, dns.AlgED25519, true)
	ds, err := k.DS(dns.DigestSHA256)
	if err != nil || ds.KeyTag != k.Tag() || len(ds.Digest) != 32 {
		t.Fatalf("%+v %v", ds, err)
	}
	if !dns.DSMatches("example.com.", ds, k.Public) || !dns.DSMatches("EXAMPLE.com.", ds, k.Public) {
		t.Error("DS should match (case-insensitively)")
	}
	if dns.DSMatches("other.com.", ds, k.Public) {
		t.Error("DS must bind the owner name")
	}
	for _, dt := range []uint8{dns.DigestSHA1, dns.DigestSHA384} {
		if d, err := k.DS(dt); err != nil || !dns.DSMatches("example.com.", d, k.Public) {
			t.Errorf("digest %d: %v", dt, err)
		}
	}
	if _, err := k.DS(99); err == nil {
		t.Error("unknown digest accepted")
	}
	// private key persistence
	pemBytes, _ := k.MarshalPrivate()
	k2, err := dns.ParsePrivateKey("example.com.", k.Public, pemBytes)
	if err != nil {
		t.Fatal(err)
	}
	set := rrsetA("a.example.com.", "1.2.3.4")
	sig, _ := dns.SignRRset(k2, "example.com.", set, time.Now().Add(-time.Hour), time.Now().Add(time.Hour))
	if dns.VerifyRRSIG(sig.Data.(dns.RRSIG), k.Public, set, time.Now()) != nil {
		t.Error("reloaded key signs differently")
	}
	other := newKey(t, dns.AlgED25519, true)
	if _, err := dns.ParsePrivateKey("example.com.", other.Public, pemBytes); err == nil {
		t.Error("mismatched private/public key accepted")
	}
	if _, err := dns.GenerateKey("x.", 8, true); err == nil {
		t.Error("RSA generation should be refused")
	}
	_ = rand.Reader
}

func signedExample(t *testing.T, alg uint8) (*dns.Zone, []dns.RR, *dns.Key) {
	t.Helper()
	src := "$ORIGIN example.com.\n$TTL 300\n@ SOA ns h 1 3600 600 86400 120\n@ NS ns\nns A 192.0.2.53\nwww A 192.0.2.1\n*.w A 192.0.2.9\nsub NS ns.sub\nns.sub A 192.0.2.54\nd.e.f A 192.0.2.7\nsecure DS 1 13 2 AABB\n"
	rrs, err := dns.ParseZone(src, "", "t")
	if err != nil {
		t.Fatal(err)
	}
	ksk := newKey(t, alg, true)
	zsk := newKey(t, alg, false)
	signed, err := dns.SignZone("example.com.", rrs, dns.SignOptions{KSK: ksk, ZSK: zsk, Inception: time.Now().Add(-time.Hour), Expiration: time.Now().Add(time.Hour)})
	if err != nil {
		t.Fatal(err)
	}
	z, err := dns.NewZone("example.com.", signed)
	if err != nil {
		t.Fatal(err)
	}
	return z, signed, ksk
}

func TestSignZoneStructure(t *testing.T) {
	for _, alg := range []uint8{dns.AlgED25519, dns.AlgECDSAP256SHA256} {
		z, rrs, _ := signedExample(t, alg)
		if errs := dns.VerifyZone(z, time.Now()); len(errs) != 0 {
			t.Fatalf("alg %d: fresh zone fails verification: %v", alg, errs)
		}
		var nsecOwners []string
		for _, r := range rrs {
			if r.Type == dns.TypeNSEC {
				nsecOwners = append(nsecOwners, r.Name)
				d := r.Data.(dns.NSEC)
				has := func(ty dns.Type) bool {
					for _, x := range d.Types {
						if x == ty {
							return true
						}
					}
					return false
				}
				if !has(dns.TypeNSEC) || !has(dns.TypeRRSIG) {
					t.Errorf("%s NSEC bitmap lacks NSEC/RRSIG: %v", r.Name, d.Types)
				}
				if r.Name == "sub.example.com." && (has(dns.TypeA) || !has(dns.TypeNS) || has(dns.TypeSOA)) {
					t.Errorf("delegation NSEC bitmap wrong: %v", d.Types)
				}
				if r.Name == "example.com." && (!has(dns.TypeSOA) || !has(dns.TypeDNSKEY)) {
					t.Errorf("apex NSEC bitmap wrong: %v", d.Types)
				}
			}
			if strings.HasPrefix(r.Name, "ns.sub.") && r.Type != dns.TypeA {
				t.Errorf("glue has %s record", r.Type)
			}
		}
		for _, o := range nsecOwners {
			if o == "ns.sub.example.com." {
				t.Error("glue must not be in the NSEC chain")
			}
		}
		// the NS RRset at the delegation and glue are unsigned; DS at the cut is signed
		sigs := map[string]bool{}
		for _, r := range rrs {
			if r.Type == dns.TypeRRSIG {
				sigs[r.Name+"/"+r.Data.(dns.RRSIG).TypeCovered.String()] = true
			}
		}
		if sigs["sub.example.com./NS"] || sigs["ns.sub.example.com./A"] {
			t.Errorf("delegation NS / glue must not be signed")
		}
		for _, want := range []string{"example.com./SOA", "example.com./NS", "example.com./DNSKEY", "www.example.com./A", "secure.example.com./DS", "www.example.com./NSEC", "*.w.example.com./A"} {
			if !sigs[want] {
				t.Errorf("missing RRSIG %s", want)
			}
		}
	}
}

func TestVerifyZoneCatchesProblems(t *testing.T) {
	_, rrs, _ := signedExample(t, dns.AlgED25519)
	build := func(mod func([]dns.RR) []dns.RR) []error {
		cp := append([]dns.RR(nil), rrs...)
		z, err := dns.NewZone("example.com.", mod(cp))
		if err != nil {
			t.Fatal(err)
		}
		return dns.VerifyZone(z, time.Now())
	}
	// 1. modify data after signing
	errs := build(func(in []dns.RR) []dns.RR {
		for i := range in {
			if in[i].Name == "www.example.com." && in[i].Type == dns.TypeA {
				in[i].Data = dns.A{Addr: dns.MustAddr("6.6.6.6")}
			}
		}
		return in
	})
	if len(errs) == 0 {
		t.Error("modified A record not detected")
	}
	// 2. drop an RRSIG
	errs = build(func(in []dns.RR) []dns.RR {
		var out []dns.RR
		dropped := false
		for _, r := range in {
			if r.Type == dns.TypeRRSIG && r.Name == "www.example.com." && r.Data.(dns.RRSIG).TypeCovered == dns.TypeA && !dropped {
				dropped = true
				continue
			}
			out = append(out, r)
		}
		return out
	})
	if len(errs) == 0 {
		t.Error("missing RRSIG not detected")
	}
	// 3. break the NSEC chain
	errs = build(func(in []dns.RR) []dns.RR {
		for i := range in {
			if in[i].Type == dns.TypeNSEC && in[i].Name == "www.example.com." {
				d := in[i].Data.(dns.NSEC)
				d.Next = "zzz.example.com."
				in[i].Data = d
			}
		}
		return in
	})
	found := false
	for _, e := range errs {
		if strings.Contains(e.Error(), "NSEC points to") {
			found = true
		}
	}
	if !found {
		t.Errorf("broken NSEC chain not reported: %v", errs)
	}
	// 4. expired
	z, _ := dns.NewZone("example.com.", rrs)
	if errs := dns.VerifyZone(z, time.Now().Add(3*time.Hour)); len(errs) == 0 {
		t.Error("expired signatures not detected")
	}
}

func TestAuthoritativeServerDNSSECAnswers(t *testing.T) {
	z, _, _ := signedExample(t, dns.AlgED25519)
	srv := dns.NewServer(z)
	if err := srv.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	defer srv.Close()
	plain := &dns.Client{Timeout: time.Second, UDPSize: 4096}
	do := &dns.Client{Timeout: time.Second, UDPSize: 4096, DO: true}
	count := func(m *dns.Message, sec []dns.RR, ty dns.Type) int {
		n := 0
		for _, r := range sec {
			if r.Type == ty {
				n++
			}
		}
		return n
	}
	m, _ := plain.Exchange(srv.Addr(), "www.example.com.", dns.TypeA, false)
	if count(m, m.Answer, dns.TypeRRSIG) != 0 {
		t.Error("RRSIG sent without DO")
	}
	m, _ = do.Exchange(srv.Addr(), "www.example.com.", dns.TypeA, false)
	if count(m, m.Answer, dns.TypeRRSIG) != 1 || len(m.Answer) != 2 {
		t.Errorf("positive answer with DO: %v", m.Answer)
	}
	// NXDOMAIN: SOA + NSEC covering the name + NSEC covering the wildcard (or the same one), all signed
	m, _ = do.Exchange(srv.Addr(), "nope.example.com.", dns.TypeA, false)
	if m.Rcode != dns.RcodeNXDomain || count(m, m.Authority, dns.TypeSOA) != 1 || count(m, m.Authority, dns.TypeNSEC) < 1 || count(m, m.Authority, dns.TypeRRSIG) < 2 {
		t.Errorf("signed NXDOMAIN: %v", m.Authority)
	}
	// NODATA: matching NSEC
	m, _ = do.Exchange(srv.Addr(), "www.example.com.", dns.TypeMX, false)
	if m.Rcode != 0 || len(m.Answer) != 0 || count(m, m.Authority, dns.TypeNSEC) != 1 {
		t.Errorf("signed NODATA: %v", m.Authority)
	}
	// wildcard answer: carries NSEC proving the qname does not exist
	m, _ = do.Exchange(srv.Addr(), "q.w.example.com.", dns.TypeA, false)
	if len(m.Answer) != 2 || m.Answer[0].Name != "q.w.example.com." || count(m, m.Authority, dns.TypeNSEC) != 1 {
		t.Errorf("wildcard answer: %v / %v", m.Answer, m.Authority)
	}
	// referral to an unsigned child: NSEC proves no DS
	m, _ = do.Exchange(srv.Addr(), "x.sub.example.com.", dns.TypeA, false)
	if m.Authoritative || count(m, m.Authority, dns.TypeNS) != 1 || count(m, m.Authority, dns.TypeNSEC) != 1 {
		t.Errorf("insecure referral: %v", m.Authority)
	}
	// DNSKEY
	m, _ = do.Exchange(srv.Addr(), "example.com.", dns.TypeDNSKEY, false)
	if count(m, m.Answer, dns.TypeDNSKEY) != 2 || count(m, m.Answer, dns.TypeRRSIG) != 1 {
		t.Errorf("DNSKEY answer: %v", m.Answer)
	}
}

// ------------------------------------------------------------- validating resolver

func signedWorld(t *testing.T, opt miniverse.SignOptions) *miniverse.World {
	t.Helper()
	w, err := miniverse.BuildSigned("", opt)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(w.Close)
	return w
}

func TestValidatingResolverSecureAnswers(t *testing.T) {
	w := signedWorld(t, miniverse.SignOptions{})
	r := w.NewValidatingResolver()
	cases := []struct {
		name  string
		typ   dns.Type
		rcode dns.Rcode
		want  dns.SecStatus
	}{
		{"web.example.com.", dns.TypeA, dns.RcodeSuccess, dns.Secure},
		{"www2.example.com.", dns.TypeA, dns.RcodeSuccess, dns.Secure},         // CNAME chain
		{"nope.example.com.", dns.TypeA, dns.RcodeNXDomain, dns.Secure},        // NXDOMAIN with wildcard denial
		{"mail.example.com.", dns.TypeMX, dns.RcodeSuccess, dns.Secure},        // NODATA
		{"anything.dev.example.com.", dns.TypeA, dns.RcodeSuccess, dns.Secure}, // wildcard expansion
		{"b.c.example.com.", dns.TypeA, dns.RcodeSuccess, dns.Secure},          // empty non-terminal NODATA
		{"example.com.", dns.TypeDNSKEY, dns.RcodeSuccess, dns.Secure},
		{"example.com.", dns.TypeDS, dns.RcodeSuccess, dns.Secure},
		{"host.sub.example.com.", dns.TypeA, dns.RcodeSuccess, dns.Insecure}, // unsigned child of signed zone
		{"www.glueless.com.", dns.TypeA, dns.RcodeSuccess, dns.Insecure},
		{"ns.dnshost.net.", dns.TypeA, dns.RcodeSuccess, dns.Insecure},  // unsigned TLD, proven by root NSEC
		{"nosuch.nosuchtld.", dns.TypeA, dns.RcodeNXDomain, dns.Secure}, // signed root denies the TLD
	}
	for _, c := range cases {
		resp, err := r.Resolve(c.name, c.typ)
		if err != nil {
			t.Fatalf("%s %s: %v", c.name, c.typ, err)
		}
		if resp.Rcode != c.rcode || resp.Security != c.want {
			t.Errorf("%s %s: rcode=%s sec=%s why=%q; want %s %s", c.name, c.typ, resp.Rcode, resp.Security, resp.Why, c.rcode, c.want)
		}
	}
}

func TestValidationCacheKeepsStatus(t *testing.T) {
	w := signedWorld(t, miniverse.SignOptions{})
	r := w.NewValidatingResolver()
	first, _ := r.Resolve("web.example.com.", dns.TypeA)
	second, _ := r.Resolve("web.example.com.", dns.TypeA)
	if first.Security != dns.Secure || second.Security != dns.Secure || !second.Cached {
		t.Errorf("first=%+v second=%+v", first, second)
	}
	n1, _ := r.Resolve("ghost.example.com.", dns.TypeA)
	n2, _ := r.Resolve("ghost.example.com.", dns.TypeA)
	if n1.Security != dns.Secure || n2.Security != dns.Secure || !n2.Cached {
		t.Errorf("negative: %+v / %+v", n1, n2)
	}
}

func mapZone(origin string, fn func([]dns.RR) []dns.RR) func(string, []dns.RR) []dns.RR {
	return func(o string, rrs []dns.RR) []dns.RR {
		if o == origin {
			return fn(rrs)
		}
		return rrs
	}
}

func expectBogus(t *testing.T, w *miniverse.World, name string, typ dns.Type, wantWhy string) {
	t.Helper()
	r := w.NewValidatingResolver()
	resp, err := r.Resolve(name, typ)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Rcode != dns.RcodeServFail || resp.Security != dns.Bogus {
		t.Fatalf("%s %s: expected bogus SERVFAIL, got rcode=%s sec=%s answer=%v", name, typ, resp.Rcode, resp.Security, resp.Answer)
	}
	if !strings.Contains(resp.Why, wantWhy) {
		t.Errorf("%s: reason %q lacks %q", name, resp.Why, wantWhy)
	}
	// checking-disabled still gets the data, unvalidated and uncached
	cd, _ := r.ResolveCD(name, typ)
	if cd.Rcode == dns.RcodeServFail || cd.Security == dns.Secure {
		t.Errorf("CD query: %+v", cd)
	}
	again, _ := r.Resolve(name, typ)
	if again.Rcode != dns.RcodeServFail {
		t.Errorf("CD result leaked into the cache: %+v", again)
	}
}

func TestBogusTamperedSignature(t *testing.T) {
	w := signedWorld(t, miniverse.SignOptions{Tamper: mapZone("example.com.", func(rrs []dns.RR) []dns.RR {
		for i := range rrs {
			if rrs[i].Type == dns.TypeRRSIG && rrs[i].Name == "web.example.com." && rrs[i].Data.(dns.RRSIG).TypeCovered == dns.TypeA {
				s := rrs[i].Data.(dns.RRSIG)
				s.Signature = append([]byte(nil), s.Signature...)
				s.Signature[0] ^= 0xFF
				rrs[i].Data = s
			}
		}
		return rrs
	})})
	expectBogus(t, w, "web.example.com.", dns.TypeA, "does not verify")
	// other names in the same zone are unaffected
	r := w.NewValidatingResolver()
	if resp, _ := r.Resolve("mail.example.com.", dns.TypeA); resp.Security != dns.Secure {
		t.Errorf("collateral damage: %+v", resp)
	}
}

func TestBogusStrippedSignatures(t *testing.T) { // downgrade attack
	w := signedWorld(t, miniverse.SignOptions{Tamper: mapZone("example.com.", func(rrs []dns.RR) []dns.RR {
		var out []dns.RR
		for _, r := range rrs {
			if r.Type == dns.TypeRRSIG && r.Name == "web.example.com." {
				continue
			}
			out = append(out, r)
		}
		return out
	})})
	expectBogus(t, w, "web.example.com.", dns.TypeA, "no RRSIG")
}

func TestBogusExpiredSignatures(t *testing.T) {
	w := signedWorld(t, miniverse.SignOptions{Inception: time.Now().Add(-48 * time.Hour), Expiration: time.Now().Add(-24 * time.Hour)})
	expectBogus(t, w, "web.example.com.", dns.TypeA, "expired")
}

func TestBogusNotYetValid(t *testing.T) {
	w := signedWorld(t, miniverse.SignOptions{Inception: time.Now().Add(24 * time.Hour), Expiration: time.Now().Add(48 * time.Hour)})
	expectBogus(t, w, "web.example.com.", dns.TypeA, "not yet valid")
}

func TestBogusWrongDS(t *testing.T) {
	w := signedWorld(t, miniverse.SignOptions{Tamper: mapZone("com.", func(rrs []dns.RR) []dns.RR {
		for i := range rrs {
			if rrs[i].Type == dns.TypeDS && rrs[i].Name == "example.com." {
				d := rrs[i].Data.(dns.DS)
				d.Digest = append([]byte(nil), d.Digest...)
				d.Digest[0] ^= 1
				rrs[i].Data = d
			}
		}
		return rrs
	})})
	// the corrupted DS in com. is itself still validly signed? No: tampering happens after
	// signing, so this fails already at the DS RRset signature.
	expectBogus(t, w, "web.example.com.", dns.TypeA, "DS")
}

func TestBogusDSForUnknownKey(t *testing.T) {
	// a *validly signed* DS that does not match the child's keys: re-sign com. with a mismatching DS
	other, _ := dns.GenerateKey("example.com.", dns.AlgED25519, true)
	wrong, _ := other.DS(dns.DigestSHA256)
	w2 := signedWorldWithDS(t, wrong)
	expectBogus(t, w2, "web.example.com.", dns.TypeA, "matches its DS")
}

func TestBogusMissingNSECProof(t *testing.T) {
	w := signedWorld(t, miniverse.SignOptions{Tamper: mapZone("example.com.", func(rrs []dns.RR) []dns.RR {
		// a server that "forgets" NSEC records could otherwise forge NXDOMAIN
		var out []dns.RR
		for _, r := range rrs {
			if r.Type == dns.TypeNSEC || (r.Type == dns.TypeRRSIG && r.Data.(dns.RRSIG).TypeCovered == dns.TypeNSEC) {
				continue
			}
			out = append(out, r)
		}
		return out
	})})
	expectBogus(t, w, "nope.example.com.", dns.TypeA, "NSEC")
}

func TestBogusWrongTrustAnchor(t *testing.T) {
	w := signedWorld(t, miniverse.SignOptions{})
	r := w.NewValidatingResolver()
	evil, _ := dns.GenerateKey(".", dns.AlgED25519, true)
	r.AnchorKeys = []dns.DNSKEY{evil.Public}
	resp, _ := r.Resolve("web.example.com.", dns.TypeA)
	if resp.Rcode != dns.RcodeServFail || resp.Security != dns.Bogus {
		t.Errorf("%+v", resp)
	}
	// DS-form anchor works too
	r2 := w.NewResolver()
	r2.Validate = true
	r2.TrustAnchors = []dns.DS{w.AnchorDS}
	if resp, _ := r2.Resolve("web.example.com.", dns.TypeA); resp.Security != dns.Secure {
		t.Errorf("DS anchor: %+v", resp)
	}
	// validation without an anchor is a configuration error, not silent insecurity
	r3 := w.NewResolver()
	r3.Validate = true
	if _, err := r3.Resolve("web.example.com.", dns.TypeA); err != dns.ErrNoTrustAnchor {
		t.Errorf("want ErrNoTrustAnchor, got %v", err)
	}
}

func TestInsecureDelegationNeedsProof(t *testing.T) {
	// glueless.com. is unsigned and com. is signed: removing com's NSEC for it must be Bogus, not Insecure
	w := signedWorld(t, miniverse.SignOptions{Tamper: mapZone("com.", func(rrs []dns.RR) []dns.RR {
		var out []dns.RR
		for _, r := range rrs {
			if r.Type == dns.TypeNSEC && r.Name == "glueless.com." {
				continue
			}
			if r.Type == dns.TypeRRSIG && r.Name == "glueless.com." && r.Data.(dns.RRSIG).TypeCovered == dns.TypeNSEC {
				continue
			}
			out = append(out, r)
		}
		return out
	})})
	expectBogus(t, w, "www.glueless.com.", dns.TypeA, "")
}

func TestRecursiveServerADAndCD(t *testing.T) {
	w := signedWorld(t, miniverse.SignOptions{Tamper: mapZone("example.com.", func(rrs []dns.RR) []dns.RR {
		for i := range rrs {
			if rrs[i].Type == dns.TypeRRSIG && rrs[i].Name == "mail2.example.com." && rrs[i].Data.(dns.RRSIG).TypeCovered == dns.TypeA {
				s := rrs[i].Data.(dns.RRSIG)
				s.Signature = append([]byte(nil), s.Signature...)
				s.Signature[3] ^= 0x55
				rrs[i].Data = s
			}
		}
		return rrs
	})})
	front := dns.NewServer()
	front.Resolver = w.NewValidatingResolver()
	if err := front.Start("127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	defer front.Close()
	c := &dns.Client{Timeout: 3 * time.Second, UDPSize: 1232, DO: true}
	m, err := c.Exchange(front.Addr(), "mail.example.com.", dns.TypeA, true)
	if err != nil || !m.AuthenticData || m.Rcode != 0 {
		t.Fatalf("good name: AD=%v rcode=%v err=%v", m.AuthenticData, m.Rcode, err)
	}
	hasSig := false
	for _, r := range m.Answer {
		hasSig = hasSig || r.Type == dns.TypeRRSIG
	}
	if !hasSig {
		t.Error("DO client should receive RRSIGs")
	}
	plain := &dns.Client{Timeout: 3 * time.Second, UDPSize: 1232}
	m, _ = plain.Exchange(front.Addr(), "mail.example.com.", dns.TypeA, true)
	for _, r := range m.Answer {
		if r.Type == dns.TypeRRSIG {
			t.Error("RRSIG leaked to non-DO client")
		}
	}
	m, _ = c.Exchange(front.Addr(), "mail2.example.com.", dns.TypeA, true)
	if m.Rcode != dns.RcodeServFail || m.AuthenticData {
		t.Errorf("bogus answer must be SERVFAIL: %v", m.Rcode)
	}
	cd := &dns.Client{Timeout: 3 * time.Second, UDPSize: 1232, DO: true, CD: true}
	m, _ = cd.Exchange(front.Addr(), "mail2.example.com.", dns.TypeA, true)
	if m.Rcode != 0 || m.AuthenticData || len(m.Answer) == 0 {
		t.Errorf("CD query should return the data, not AD: rcode=%v ad=%v n=%d", m.Rcode, m.AuthenticData, len(m.Answer))
	}
	m, _ = c.Exchange(front.Addr(), "host.sub.example.com.", dns.TypeA, true)
	if m.Rcode != 0 || m.AuthenticData {
		t.Errorf("insecure answer: AD must be clear (rcode %v)", m.Rcode)
	}
}

func signedWorldWithDS(t *testing.T, ds dns.DS) *miniverse.World {
	t.Helper()
	w, err := miniverse.BuildSignedWithDS("", ds)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(w.Close)
	return w
}
