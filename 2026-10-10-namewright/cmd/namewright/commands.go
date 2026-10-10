package main

import (
	"errors"
	"flag"
	"fmt"
	"net"
	"net/netip"
	"os"
	"os/signal"
	"sort"
	"strings"
	"syscall"
	"time"

	"namewright/dns"
	"namewright/miniverse"
)

type multiFlag []string

func (m *multiFlag) String() string     { return strings.Join(*m, ",") }
func (m *multiFlag) Set(v string) error { *m = append(*m, v); return nil }

func fail(f string, a ...any) int {
	fmt.Fprintf(os.Stderr, "namewright: "+f+"\n", a...)
	return 1
}

// realRoots are the IANA root servers a.root-servers.net and b.root-servers.net.
func realRoots() []dns.RootHint {
	return []dns.RootHint{
		{Name: "a.root-servers.net.", Addr: netip.MustParseAddr("198.41.0.4")},
		{Name: "b.root-servers.net.", Addr: netip.MustParseAddr("170.247.170.2")},
		{Name: "k.root-servers.net.", Addr: netip.MustParseAddr("193.0.14.129")},
	}
}

func waitForSignal() {
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, os.Interrupt, syscall.SIGTERM)
	<-ch
}

func parseCIDRs(list string) ([]netip.Prefix, error) {
	var out []netip.Prefix
	for _, s := range strings.Split(list, ",") {
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		p, err := netip.ParsePrefix(s)
		if err != nil {
			a, err2 := netip.ParseAddr(s)
			if err2 != nil {
				return nil, fmt.Errorf("bad CIDR/address %q", s)
			}
			p = netip.PrefixFrom(a, a.BitLen())
		}
		out = append(out, p)
	}
	return out, nil
}

func cmdServe(args []string) int {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	listen := fs.String("listen", "127.0.0.1:5353", "address to bind (UDP and TCP)")
	var zones multiFlag
	fs.Var(&zones, "zone", "origin=path/to/file.zone (repeatable)")
	axfr := fs.String("axfr-allow", "", "comma-separated CIDRs allowed to AXFR (default: none)")
	rate := fs.Float64("rate", 0, "per-client UDP queries/second limit (0 = unlimited)")
	burst := fs.Float64("burst", 20, "rate limit burst size")
	policy := fs.String("policy", "", "response-policy file (blocklist)")
	recursive := fs.Bool("recursive", false, "also act as a recursive resolver for non-local names")
	validate := fs.Bool("validate", false, "DNSSEC-validate recursive answers (needs -anchor)")
	anchor := fs.String("anchor", "", "trust anchor file: DNSKEY or DS records for the root")
	quiet := fs.Bool("q", false, "do not log queries")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	var zs []*dns.Zone
	for _, spec := range zones {
		origin, path, ok := strings.Cut(spec, "=")
		if !ok {
			return fail("-zone wants origin=path, got %q", spec)
		}
		src, err := os.ReadFile(path)
		if err != nil {
			return fail("%v", err)
		}
		z, err := dns.LoadZone(string(src), origin, path)
		if err != nil {
			return fail("%v", err)
		}
		for _, w := range z.Warnings {
			fmt.Fprintf(os.Stderr, "warning: %s: %s\n", path, w)
		}
		zs = append(zs, z)
	}
	if len(zs) == 0 && !*recursive {
		return fail("nothing to serve: give at least one -zone or -recursive")
	}
	srv := dns.NewServer(zs...)
	if !*quiet {
		srv.Logf = func(f string, a ...any) { fmt.Printf(time.Now().Format("15:04:05.000 ")+f+"\n", a...) }
	}
	if *axfr != "" {
		prefixes, err := parseCIDRs(*axfr)
		if err != nil {
			return fail("%v", err)
		}
		srv.AllowTransfer = func(a net.Addr) bool {
			ta, ok := a.(*net.TCPAddr)
			if !ok {
				return false
			}
			ip, _ := netip.AddrFromSlice(ta.IP)
			ip = ip.Unmap()
			for _, p := range prefixes {
				if p.Contains(ip) {
					return true
				}
			}
			return false
		}
	}
	if *rate > 0 {
		srv.Limiter = dns.NewRateLimiter(*rate, *burst)
	}
	if *policy != "" {
		src, err := os.ReadFile(*policy)
		if err != nil {
			return fail("%v", err)
		}
		p, err := dns.ParsePolicy(string(src))
		if err != nil {
			return fail("%v", err)
		}
		srv.Policy = p
	}
	if *recursive {
		r := dns.NewResolver(realRoots())
		if *validate {
			if err := loadAnchor(r, *anchor); err != nil {
				return fail("%v", err)
			}
		}
		srv.Resolver = r
	}
	if err := srv.Start(*listen); err != nil {
		return fail("%v", err)
	}
	fmt.Printf("namewright serving on %s (udp+tcp): %s\n", srv.Addr(), srv.Describe())
	waitForSignal()
	srv.Close()
	return 0
}

func cmdDig(args []string) int {
	server := "127.0.0.1:53"
	var name string
	typ := dns.TypeA
	tcp, dnssec, norec, short := false, false, false, false
	port := ""
	haveType := false
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case strings.HasPrefix(a, "@"):
			server = a[1:]
		case a == "-p" && i+1 < len(args):
			port = args[i+1]
			i++
		case a == "+tcp":
			tcp = true
		case a == "+dnssec":
			dnssec = true
		case a == "+norec":
			norec = true
		case a == "+short":
			short = true
		case strings.HasPrefix(a, "+"):
			return fail("unknown option %s", a)
		default:
			t, isType := dns.ParseType(a)
			switch {
			case isType && name != "" && !haveType:
				typ, haveType = t, true
			case isType && name == "" && !haveType && i+1 < len(args) && !strings.HasPrefix(args[i+1], "@") && !strings.HasPrefix(args[i+1], "+"):
				typ, haveType = t, true // "dig A example.com"
			case name == "":
				name = a
			default:
				return fail("unexpected argument %q", a)
			}
		}
	}
	if name == "" {
		return fail("usage: dig [@server[:port]] [-p port] name [type] [+tcp] [+dnssec] [+norec] [+short]")
	}
	if err := dns.ValidName(dns.CanonName(name)); err != nil {
		return fail("%v", err)
	}
	if _, _, err := net.SplitHostPort(server); err != nil {
		p := port
		if p == "" {
			p = "53"
		}
		server = net.JoinHostPort(strings.Trim(server, "[]"), p)
	}
	c := &dns.Client{Timeout: 3 * time.Second, Retries: 1, UDPSize: 1232, DO: dnssec, TCPOnly: tcp}
	start := time.Now()
	m, err := c.Exchange(server, name, typ, !norec)
	if err != nil {
		return fail("no usable answer from %s: %s", server, friendlyErr(err))
	}
	if short {
		for _, r := range m.Answer {
			fmt.Println(r.Data)
		}
		return 0
	}
	fmt.Print(m.Format())
	fmt.Printf("\n;; Query time: %d msec\n;; SERVER: %s\n", time.Since(start).Milliseconds(), server)
	return 0
}

func cmdCheck(args []string) int {
	fs := flag.NewFlagSet("check", flag.ContinueOnError)
	origin := fs.String("origin", "", "zone origin (required if the file has no $ORIGIN)")
	print := fs.Bool("print", false, "print the normalised zone")
	if err := fs.Parse(args); err != nil || fs.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: namewright check [-origin name] [-print] file.zone")
		return 2
	}
	path := fs.Arg(0)
	src, err := os.ReadFile(path)
	if err != nil {
		return fail("%v", err)
	}
	rrs, err := dns.ParseZone(string(src), *origin, path)
	if err != nil {
		return fail("%v", err)
	}
	org := *origin
	if org == "" {
		for _, r := range rrs {
			if r.Type == dns.TypeSOA {
				org = r.Name
			}
		}
	}
	z, err := dns.NewZone(org, rrs)
	if err != nil {
		return fail("%s: %v", path, err)
	}
	for _, w := range z.Warnings {
		fmt.Printf("warning: %s\n", w)
	}
	counts := map[dns.Type]int{}
	for _, r := range z.Records() {
		counts[r.Type]++
	}
	var ts []string
	for t, n := range counts {
		ts = append(ts, fmt.Sprintf("%s=%d", t, n))
	}
	sort.Strings(ts)
	fmt.Printf("zone %s OK: serial %d, %d records (%s)\n", z.Origin, z.SOA().Data.(dns.SOA).Serial, len(z.Records()), strings.Join(ts, " "))
	if *print {
		fmt.Print(z.String())
	}
	return 0
}

func cmdAXFR(args []string) int {
	if len(args) != 2 || !strings.HasPrefix(args[0], "@") {
		fmt.Fprintln(os.Stderr, "usage: namewright axfr @host:port zone")
		return 2
	}
	c := &dns.Client{Timeout: 10 * time.Second}
	rrs, err := c.Transfer(args[0][1:], args[1])
	if err != nil {
		return fail("%v", err)
	}
	for _, r := range rrs {
		fmt.Println(r)
	}
	fmt.Printf(";; %d records transferred\n", len(rrs))
	return 0
}

func loadWorld(dir string) (*miniverse.World, error) {
	return miniverse.Build(dir, nil)
}

func cmdResolve(args []string) int {
	fs := flag.NewFlagSet("resolve", flag.ContinueOnError)
	world := fs.String("world", "", "directory of mini-internet zone files (default: built-in copy)")
	real := fs.Bool("real", false, "use the real internet root servers instead of the mini internet")
	quiet := fs.Bool("quiet", false, "no trace, answer only")
	if err := fs.Parse(args); err != nil || fs.NArg() < 1 || fs.NArg() > 2 {
		fmt.Fprintln(os.Stderr, "usage: namewright resolve [-world dir | -real] [-quiet] name [type]")
		return 2
	}
	name := fs.Arg(0)
	typ := dns.TypeA
	if fs.NArg() == 2 {
		t, ok := dns.ParseType(fs.Arg(1))
		if !ok {
			return fail("unknown type %q", fs.Arg(1))
		}
		typ = t
	}
	var r *dns.Resolver
	if *real {
		r = dns.NewResolver(realRoots())
	} else {
		w, err := loadWorld(*world)
		if err != nil {
			return fail("%v", err)
		}
		defer w.Close()
		r = w.NewResolver()
	}
	if !*quiet {
		r.Trace = func(d int, m string) { fmt.Printf(";; %s%s\n", strings.Repeat("   ", d), m) }
	}
	resp, err := r.Resolve(name, typ)
	if err != nil {
		return fail("%v", err)
	}
	plural := "ies"
	if resp.Queries == 1 {
		plural = "y"
	}
	fmt.Printf("\n;; status: %s, %d upstream quer%s%s\n", resp.Rcode, resp.Queries, plural, map[bool]string{true: " (all from cache)", false: ""}[resp.Cached && resp.Queries == 0])
	if resp.Why != "" {
		fmt.Printf(";; reason: %s\n", resp.Why)
	}
	for _, rr := range resp.Answer {
		fmt.Println(rr)
	}
	for _, rr := range resp.Authority {
		fmt.Println(";; authority:", rr)
	}
	if resp.Rcode != dns.RcodeSuccess {
		return 1
	}
	return 0
}

func cmdTestnet(args []string) int {
	fs := flag.NewFlagSet("testnet", flag.ContinueOnError)
	world := fs.String("world", "", "directory of mini-internet zone files (default: built-in copy)")
	listen := fs.String("listen", "127.0.0.1:5353", "address of the recursive front end")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	w, err := loadWorld(*world)
	if err != nil {
		return fail("%v", err)
	}
	defer w.Close()
	front := dns.NewServer()
	front.Resolver = w.NewResolver()
	front.Logf = func(f string, a ...any) { fmt.Printf(time.Now().Format("15:04:05.000 ")+f+"\n", a...) }
	if err := front.Start(*listen); err != nil {
		return fail("%v", err)
	}
	defer front.Close()
	fmt.Println("mini internet is up:")
	for _, h := range w.Hosts {
		fmt.Printf("  %-22s %-15s -> %s  zones: %s\n", h.Name, h.IP, h.Srv.Addr(), strings.Join(h.Zones, ", "))
	}
	fmt.Printf("recursive resolver listening on %s — try: namewright dig @%s www.example.com A\n", front.Addr(), front.Addr())
	waitForSignal()
	return 0
}

func friendlyErr(err error) string {
	var ne net.Error
	switch {
	case strings.Contains(err.Error(), "connection refused"):
		return "connection refused (is a server listening there?)"
	case errors.As(err, &ne) && ne.Timeout():
		return "timed out"
	}
	return err.Error()
}
