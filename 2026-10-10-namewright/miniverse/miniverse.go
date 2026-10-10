// Package miniverse builds a tiny working internet on loopback: a root, two
// TLDs and several second-level nameservers, all real DNS servers on real
// sockets. Fictitious nameserver addresses (198.51.100.0/24) are mapped to the
// loopback ports the servers actually bound.
package miniverse

import (
	"fmt"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"strings"

	"namewright/dns"
)

// Host is one nameserver in the world.
type Host struct {
	Name  string
	IP    netip.Addr
	Zones []string // zone file basenames without ".zone"
	Srv   *dns.Server
}

type World struct {
	Hosts []*Host
	Roots []dns.RootHint
	ports map[netip.Addr]string
}

// Layout is the default topology; zone files live in dir.
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

// Build loads zone files from dir and starts every server on 127.0.0.1.
// tweak, if non-nil, may modify each zone's records before the zone is built
// (used to insert DNSSEC material).
func Build(dir string, tweak func(origin string, rrs []dns.RR) []dns.RR) (*World, error) {
	w := &World{ports: map[netip.Addr]string{}}
	for _, h := range Layout() {
		var zones []*dns.Zone
		for _, zn := range h.Zones {
			path := filepath.Join(dir, zn+".zone")
			src, err := os.ReadFile(path)
			if err != nil {
				w.Close()
				return nil, err
			}
			origin := zn + "."
			if zn == "root" {
				origin = "."
			}
			rrs, err := dns.ParseZone(string(src), origin, path)
			if err != nil {
				w.Close()
				return nil, err
			}
			if tweak != nil {
				rrs = tweak(origin, rrs)
			}
			z, err := dns.NewZone(origin, rrs)
			if err != nil {
				w.Close()
				return nil, fmt.Errorf("%s: %w", path, err)
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
		if strings.HasPrefix(h.Name, "a.root") {
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

// NewResolver returns a resolver wired to this world.
func (w *World) NewResolver() *dns.Resolver {
	r := dns.NewResolver(w.Roots)
	r.AddrMap = w.AddrMap
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
