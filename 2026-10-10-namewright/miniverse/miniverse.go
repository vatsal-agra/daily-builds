// Package miniverse builds a tiny working internet on loopback: a root, two
// TLDs and several second-level nameservers, all real DNS servers on real
// sockets. Fictitious nameserver addresses (198.51.100.0/24) are mapped to the
// loopback ports the servers actually bound.
package miniverse

import (
	"embed"
	"fmt"
	"io/fs"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"time"

	"namewright/dns"
)

//go:embed internet/*.zone
var embedded embed.FS

// Host is one nameserver in the world.
type Host struct {
	Name  string
	IP    netip.Addr
	Zones []string // zone file basenames without ".zone"
	Srv   *dns.Server
}

// World is a running mini internet.
type World struct {
	Hosts []*Host
	Roots []dns.RootHint
	ports map[netip.Addr]string

	// DNSSEC material, set by BuildSigned.
	Keys      map[string][2]*dns.Key // origin -> {KSK, ZSK}
	AnchorKey dns.DNSKEY             // root KSK (trust anchor)
	AnchorDS  dns.DS
}

// Layout is the default topology.
func Layout() []*Host {
	ip := netip.MustParseAddr
	return []*Host{
		{Name: "a.root-servers.net", IP: ip("198.51.100.1"), Zones: []string{"root"}},
		{Name: "a.gtld-servers.net", IP: ip("198.51.100.2"), Zones: []string{"com", "net"}},
		{Name: "ns1.example.com", IP: ip("198.51.100.10"), Zones: []string{"example.com"}},
		{Name: "ns.sub.example.com", IP: ip("198.51.100.11"), Zones: []string{"sub.example.com"}},
		{Name: "ns.dnshost.net", IP: ip("198.51.100.20"), Zones: []string{"dnshost.net", "glueless.com"}},
	}
}

func originOf(zn string) string {
	if zn == "root" {
		return "."
	}
	return zn + "."
}

func readZone(dir, zn string) (rrs []dns.RR, err error) {
	var src []byte
	path := filepath.Join(dir, zn+".zone")
	if dir == "" {
		path = "internet/" + zn + ".zone"
		src, err = fs.ReadFile(embedded, path)
	} else {
		src, err = os.ReadFile(path)
	}
	if err != nil {
		return nil, err
	}
	return dns.ParseZone(string(src), originOf(zn), path)
}

// Build loads zone files from dir (or the embedded copy when dir is "") and
// starts every server on 127.0.0.1. tweak, if non-nil, may rewrite each zone's
// records before the zone is built.
func Build(dir string, tweak func(origin string, rrs []dns.RR) []dns.RR) (*World, error) {
	recs := map[string][]dns.RR{}
	for _, h := range Layout() {
		for _, zn := range h.Zones {
			rrs, err := readZone(dir, zn)
			if err != nil {
				return nil, err
			}
			if tweak != nil {
				rrs = tweak(originOf(zn), rrs)
			}
			recs[originOf(zn)] = rrs
		}
	}
	return start(recs)
}

// SignOptions controls BuildSigned.
type SignOptions struct {
	Inception, Expiration time.Time // zero = now-1h .. now+30d
	// Tamper may rewrite a zone's final (signed) records, to simulate attacks and misconfiguration.
	Tamper func(origin string, rrs []dns.RR) []dns.RR
}

// signedZones are signed bottom-up so each parent can publish its child's DS.
// net., dnshost.net., glueless.com. and sub.example.com. stay unsigned on purpose:
// they are the "insecure island" cases.
var signedChain = []struct {
	zone, parent string
	ksk, zsk     uint8
}{
	{"example.com.", "com.", dns.AlgED25519, dns.AlgED25519},
	{"com.", ".", dns.AlgECDSAP256SHA256, dns.AlgECDSAP256SHA256},
	{".", "", dns.AlgED25519, dns.AlgECDSAP256SHA256},
}

// BuildSigned is Build with DNSSEC: root, com. and example.com. are signed and
// chained by DS records; the root KSK is exposed as the trust anchor.
func BuildSigned(dir string, opt SignOptions) (*World, error) { return buildSigned(dir, opt, nil) }

func buildSigned(dir string, opt SignOptions, overrideDS *dns.DS) (*World, error) {
	if opt.Inception.IsZero() {
		opt.Inception = time.Now().Add(-time.Hour)
	}
	if opt.Expiration.IsZero() {
		opt.Expiration = time.Now().Add(30 * 24 * time.Hour)
	}
	recs := map[string][]dns.RR{}
	for _, h := range Layout() {
		for _, zn := range h.Zones {
			rrs, err := readZone(dir, zn)
			if err != nil {
				return nil, err
			}
			recs[originOf(zn)] = rrs
		}
	}
	keys := map[string][2]*dns.Key{}
	for _, s := range signedChain {
		ksk, err := dns.GenerateKey(s.zone, s.ksk, true)
		if err != nil {
			return nil, err
		}
		zsk, err := dns.GenerateKey(s.zone, s.zsk, false)
		if err != nil {
			return nil, err
		}
		keys[s.zone] = [2]*dns.Key{ksk, zsk}
		signed, err := dns.SignZone(s.zone, recs[s.zone], dns.SignOptions{KSK: ksk, ZSK: zsk, Inception: opt.Inception, Expiration: opt.Expiration})
		if err != nil {
			return nil, fmt.Errorf("signing %s: %w", s.zone, err)
		}
		recs[s.zone] = signed
		if s.parent != "" {
			ds, err := ksk.DS(dns.DigestSHA256)
			if err != nil {
				return nil, err
			}
			if overrideDS != nil && s.zone == "example.com." {
				ds = *overrideDS
			}
			// the parent has not been signed yet (we go bottom-up): just add the DS
			recs[s.parent] = append(recs[s.parent], dns.RR{Name: s.zone, Type: dns.TypeDS, Class: dns.ClassIN, TTL: 3600, Data: ds})
		}
	}
	if opt.Tamper != nil {
		for o, r := range recs {
			recs[o] = opt.Tamper(o, r)
		}
	}
	w, err := start(recs)
	if err != nil {
		return nil, err
	}
	w.Keys = keys
	w.AnchorKey = keys["."][0].Public
	w.AnchorDS, _ = keys["."][0].DS(dns.DigestSHA256)
	return w, nil
}

func start(recs map[string][]dns.RR) (*World, error) {
	w := &World{ports: map[netip.Addr]string{}}
	for _, h := range Layout() {
		var zones []*dns.Zone
		for _, zn := range h.Zones {
			origin := originOf(zn)
			z, err := dns.NewZone(origin, recs[origin])
			if err != nil {
				w.Close()
				return nil, fmt.Errorf("zone %s: %w", origin, err)
			}
			zones = append(zones, z)
		}
		h.Srv = dns.NewServer(zones...)
		h.Srv.AllowTransfer = func(net.Addr) bool { return true }
		if err := h.Srv.Start("127.0.0.1:0"); err != nil {
			w.Close()
			return nil, err
		}
		w.Hosts = append(w.Hosts, h)
		w.ports[h.IP] = h.Srv.Addr()
		if h.Name == "a.root-servers.net" {
			w.Roots = append(w.Roots, dns.RootHint{Name: h.Name + ".", Addr: h.IP})
		}
	}
	return w, nil
}

// AddrMap is suitable for dns.Resolver.AddrMap.
func (w *World) AddrMap(ip netip.Addr) string {
	if a, ok := w.ports[ip]; ok {
		return a
	}
	return "127.0.0.1:1" // unrouted: connection refused immediately
}

// NewResolver returns a non-validating resolver wired to this world.
func (w *World) NewResolver() *dns.Resolver {
	r := dns.NewResolver(w.Roots)
	r.AddrMap = w.AddrMap
	return r
}

// NewValidatingResolver returns a resolver that validates against the root KSK.
func (w *World) NewValidatingResolver() *dns.Resolver {
	r := w.NewResolver()
	r.Validate = true
	r.AnchorKeys = []dns.DNSKEY{w.AnchorKey}
	return r
}

// Host returns the host with the given name.
func (w *World) Host(name string) *Host {
	for _, h := range w.Hosts {
		if h.Name == name {
			return h
		}
	}
	return nil
}

func (w *World) Close() {
	for _, h := range w.Hosts {
		if h.Srv != nil {
			h.Srv.Close()
		}
	}
}

// BuildSignedWithDS is BuildSigned, but com. publishes the given DS for
// example.com. instead of the real one (and is re-signed so the DS itself is
// validly signed). It models a delegation whose DS does not match the child.
func BuildSignedWithDS(dir string, ds dns.DS) (*World, error) {
	return buildSigned(dir, SignOptions{}, &ds)
}
