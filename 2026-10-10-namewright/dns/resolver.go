package dns

import (
	"errors"
	"fmt"
	"net"
	"net/netip"
	"sort"
	"strings"
	"sync"
	"time"
)

// RootHint names a root server and its address.
type RootHint struct {
	Name string
	Addr netip.Addr
}

// Response is the final result of a recursive resolution.
type Response struct {
	Name      string
	Type      Type
	Rcode     Rcode
	Answer    []RR // CNAME chain followed by the final RRset
	Authority []RR // SOA for negative answers
	Cached    bool // fully answered from cache, no network traffic
	Queries   int  // upstream queries sent
	Security  SecStatus
	Why       string // for bogus/servfail: reason
}

// Resolver is an iterative, caching, optionally DNSSEC-validating resolver.
type Resolver struct {
	Roots  []RootHint
	Cache  *Cache
	Client *Client
	// AddrMap turns a nameserver IP into a dialable "host:port". Default: ip:53.
	AddrMap func(netip.Addr) string
	// Trace receives a line per step (queries, referrals, cache hits).
	Trace func(depth int, msg string)

	MaxQueries int // per resolution
	MaxDepth   int // nested NS-address lookups
	MaxCNAME   int

	// DNSSEC
	Validate     bool
	TrustAnchors []DS // DS-style anchors for the root zone (or DNSKEY via AnchorKeys)
	AnchorKeys   []DNSKEY
	Now          func() time.Time

	mu       sync.Mutex
	inflight map[cacheKey]bool
	bad      map[string]time.Time // servers that recently failed
}

type resState struct {
	queries int
	trace   bool
}

var (
	ErrTooManyQueries = errors.New("resolver: query budget exhausted")
	ErrNoServers      = errors.New("resolver: no reachable nameservers")
)

func NewResolver(roots []RootHint) *Resolver {
	return &Resolver{
		Roots: roots, Cache: NewCache(),
		Client:     &Client{Timeout: 1500 * time.Millisecond, Retries: 1, UDPSize: 1232, Case0x20: true},
		MaxQueries: 64, MaxDepth: 8, MaxCNAME: 16, Now: time.Now,
		inflight: map[cacheKey]bool{}, bad: map[string]time.Time{},
	}
}

func (r *Resolver) tracef(depth int, f string, a ...any) {
	if r.Trace != nil {
		r.Trace(depth, fmt.Sprintf(f, a...))
	}
}

func (r *Resolver) addrOf(ip netip.Addr) string {
	if r.AddrMap != nil {
		return r.AddrMap(ip)
	}
	return net.JoinHostPort(ip.String(), "53")
}

// Resolve answers (name, type) recursively. It never panics on hostile input
// and always terminates within the configured query budget.
func (r *Resolver) Resolve(name string, t Type) (*Response, error) {
	if err := ValidName(name); err != nil {
		return nil, err
	}
	st := &resState{}
	resp, err := r.resolve(CanonName(name), t, 0, st)
	if resp != nil {
		resp.Queries = st.queries
	}
	return resp, err
}

func (r *Resolver) servfail(name string, t Type, why string) *Response {
	return &Response{Name: name, Type: t, Rcode: RcodeServFail, Why: why}
}

func (r *Resolver) resolve(name string, t Type, depth int, st *resState) (*Response, error) {
	orig := name
	resp := &Response{Name: orig, Type: t, Cached: true}
	seen := map[string]bool{}
	sec := Secure
	for hop := 0; hop <= r.MaxCNAME; hop++ {
		if seen[name] {
			return r.servfail(orig, t, "CNAME loop at "+name), nil
		}
		seen[name] = true
		before := st.queries
		step, err := r.step(name, t, depth, st)
		if err != nil {
			f := r.servfail(orig, t, err.Error())
			f.Answer = resp.Answer
			return f, nil
		}
		if st.queries != before {
			resp.Cached = false
		}
		resp.Answer = append(resp.Answer, step.rrs...)
		if step.sec < sec {
			sec = step.sec
		}
		switch step.kind {
		case kindAnswer:
			resp.Rcode, resp.Security = RcodeSuccess, sec
			return resp, nil
		case kindNegative:
			resp.Rcode, resp.Authority, resp.Security = step.rcode, step.soa, sec
			return resp, nil
		case kindCNAME:
			name = CanonName(step.rrs[len(step.rrs)-1].Data.(CNAME).Target)
			r.tracef(depth, "follow CNAME -> %s", name)
		case kindBogus:
			f := r.servfail(orig, t, step.why)
			f.Security = Bogus
			return f, nil
		}
	}
	return r.servfail(orig, t, "CNAME chain too long"), nil
}

type stepKind int

const (
	kindAnswer stepKind = iota
	kindCNAME
	kindNegative
	kindBogus
)

type stepResult struct {
	kind  stepKind
	rrs   []RR // records for the *first* name (and any in-response chain that ended in data)
	soa   []RR
	rcode Rcode
	sec   SecStatus
	why   string
}

// step produces the next piece of the answer for exactly (name, t): either the
// data, a CNAME to follow, or a negative result. It consults the cache first.
func (r *Resolver) step(name string, t Type, depth int, st *resState) (*stepResult, error) {
	if res, ok := r.fromCache(name, t, depth); ok {
		return res, nil
	}
	return r.iterate(name, t, depth, st)
}

func (r *Resolver) fromCache(name string, t Type, depth int) (*stepResult, bool) {
	if n, ok := r.Cache.GetNeg(name, t); ok {
		r.tracef(depth, "cache: negative %s %s (%s)", name, t, n.Rcode)
		return &stepResult{kind: kindNegative, rcode: n.Rcode, soa: n.SOA, sec: n.Security}, true
	}
	if rrs, sigs, sec, ok := r.Cache.Get(name, t); ok {
		r.tracef(depth, "cache: %s %s (%d records)", name, t, len(rrs))
		return &stepResult{kind: kindAnswer, rrs: withSigsIf(r.Validate, rrs, sigs), sec: sec}, true
	}
	if t != TypeCNAME {
		if rrs, sigs, sec, ok := r.Cache.Get(name, TypeCNAME); ok {
			r.tracef(depth, "cache: %s CNAME -> %s", name, rrs[0].Data.(CNAME).Target)
			return &stepResult{kind: kindCNAME, rrs: withSigsIf(r.Validate, rrs, sigs), sec: sec}, true
		}
	}
	return nil, false
}

func withSigsIf(on bool, rrs, sigs []RR) []RR {
	if !on || len(sigs) == 0 {
		return rrs
	}
	return append(append([]RR(nil), rrs...), sigs...)
}

// delegation is a set of nameservers for a zone cut.
type delegation struct {
	zone  string
	hosts []string
	addrs map[string][]netip.Addr
}

func (d *delegation) allAddrs() []netip.Addr {
	var out []netip.Addr
	for _, h := range d.hosts {
		out = append(out, d.addrs[h]...)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Is4() && !out[j].Is4() })
	return out
}

func (r *Resolver) rootDelegation() *delegation {
	d := &delegation{zone: ".", addrs: map[string][]netip.Addr{}}
	for _, h := range r.Roots {
		n := CanonName(h.Name)
		if _, ok := d.addrs[n]; !ok {
			d.hosts = append(d.hosts, n)
		}
		d.addrs[n] = append(d.addrs[n], h.Addr)
	}
	return d
}

// bestDelegation finds the deepest cached zone cut at or above name.
func (r *Resolver) bestDelegation(name string) *delegation {
	labels := Labels(name)
	for i := 0; i < len(labels); i++ {
		zone := joinLabels(labels[i:])
		ns, _, _, ok := r.Cache.Get(zone, TypeNS)
		if !ok {
			continue
		}
		d := &delegation{zone: zone, addrs: map[string][]netip.Addr{}}
		for _, n := range ns {
			h := CanonName(n.Data.(NS).Host)
			d.hosts = append(d.hosts, h)
			for _, at := range []Type{TypeA, TypeAAAA} {
				if as, _, _, ok := r.Cache.Get(h, at); ok {
					for _, a := range as {
						switch v := a.Data.(type) {
						case A:
							d.addrs[h] = append(d.addrs[h], v.Addr)
						case AAAA:
							d.addrs[h] = append(d.addrs[h], v.Addr)
						}
					}
				}
			}
		}
		return d
	}
	return r.rootDelegation()
}

// hostsNeedingAddrs lists NS hosts of d that have no known address.
func (d *delegation) missing() []string {
	var out []string
	for _, h := range d.hosts {
		if len(d.addrs[h]) == 0 {
			out = append(out, h)
		}
	}
	return out
}

func (r *Resolver) markBad(addr string) {
	r.mu.Lock()
	r.bad[addr] = r.Now().Add(10 * time.Second)
	r.mu.Unlock()
}

func (r *Resolver) isBad(addr string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	until, ok := r.bad[addr]
	if ok && r.Now().After(until) {
		delete(r.bad, addr)
		return false
	}
	return ok
}

// iterate walks the delegation tree for (name, t).
func (r *Resolver) iterate(name string, t Type, depth int, st *resState) (*stepResult, error) {
	if depth > r.MaxDepth {
		return nil, errors.New("nameserver lookup nested too deeply")
	}
	key := cacheKey{name, t}
	r.mu.Lock()
	if r.inflight[key] {
		r.mu.Unlock()
		return nil, fmt.Errorf("dependency loop resolving %s %s", name, t)
	}
	r.inflight[key] = true
	r.mu.Unlock()
	defer func() { r.mu.Lock(); delete(r.inflight, key); r.mu.Unlock() }()

	deleg := r.bestDelegation(name)
	for referrals := 0; referrals < 32; referrals++ {
		r.tracef(depth, "zone %s: %d nameserver(s)", deleg.zone, len(deleg.hosts))
		// glueless nameservers: resolve addresses on demand
		if len(deleg.allAddrs()) == 0 {
			for _, h := range deleg.missing() {
				if IsSubdomain(h, deleg.zone) && IsSubdomain(name, deleg.zone) && CompareNames(h, name) == 0 {
					continue
				}
				r.tracef(depth, "glueless NS %s: resolving address", h)
				sub, err := r.resolve(h, TypeA, depth+1, st)
				if err == nil && sub.Rcode == RcodeSuccess {
					for _, a := range sub.Answer {
						if v, ok := a.Data.(A); ok && CompareNames(a.Name, h) == 0 {
							deleg.addrs[h] = append(deleg.addrs[h], v.Addr)
						}
					}
				}
				if len(deleg.addrs[h]) > 0 {
					break
				}
			}
		}
		addrs := deleg.allAddrs()
		if len(addrs) == 0 {
			return nil, fmt.Errorf("no addresses for the nameservers of %s", deleg.zone)
		}
		var next *delegation
		answered := false
		var result *stepResult
		tried := 0
		for _, ip := range addrs {
			dial := r.addrOf(ip)
			if r.isBad(dial) && tried < len(addrs)-1 {
				continue
			}
			tried++
			if st.queries >= r.MaxQueries {
				return nil, ErrTooManyQueries
			}
			st.queries++
			r.tracef(depth, "query %s for %s %s", ip, name, t)
			msg, err := r.query(dial, name, t)
			if err != nil {
				r.tracef(depth, "  %s: %v", ip, err)
				r.markBad(dial)
				continue
			}
			res, nd, why := r.classify(msg, name, t, deleg, depth)
			switch {
			case res != nil:
				result, answered = res, true
			case nd != nil:
				next = nd
			default:
				r.tracef(depth, "  %s: %s", ip, why)
				if msg.Rcode == RcodeServFail || msg.Rcode == RcodeRefused {
					r.markBad(dial)
				}
				continue
			}
			break
		}
		if answered {
			return result, nil
		}
		if next == nil {
			return nil, fmt.Errorf("%w for %s (zone %s)", ErrNoServers, name, deleg.zone)
		}
		deleg = next
	}
	return nil, errors.New("too many referrals")
}

func (r *Resolver) query(dial, name string, t Type) (*Message, error) {
	c := *r.Client
	if r.Validate {
		c.DO = true
		if c.UDPSize == 0 {
			c.UDPSize = 1232
		}
	}
	return c.Exchange(dial, name, t, false)
}

// classify interprets a server response. Exactly one of (result, next) is
// non-nil on success; otherwise why explains the rejection.
func (r *Resolver) classify(m *Message, name string, t Type, cur *delegation, depth int) (*stepResult, *delegation, string) {
	if m.Rcode != RcodeSuccess && m.Rcode != RcodeNXDomain {
		return nil, nil, "rcode " + m.Rcode.String()
	}
	// 1. Collect the answer chain rooted at name (bailiwick/poison filter: any
	// record not on the chain is ignored).
	var chain []RR
	var sigs []RR
	for i := range m.Answer {
		m.Answer[i] = m.Answer[i].Lowered()
	}
	for i := range m.Authority {
		m.Authority[i] = m.Authority[i].Lowered()
	}
	for i := range m.Additional {
		m.Additional[i] = m.Additional[i].Lowered()
	}
	cur_ := name
	got := false
	for i := 0; i < 20 && !got; i++ {
		var cn *RR
		for j := range m.Answer {
			a := m.Answer[j]
			if CompareNames(a.Name, cur_) != 0 {
				continue
			}
			switch {
			case a.Type == t || t == TypeANY && a.Type != TypeRRSIG:
				chain = append(chain, a)
				got = true
			case a.Type == TypeCNAME && t != TypeCNAME && cn == nil:
				c := a
				cn = &c
			}
		}
		if got {
			break
		}
		if cn == nil {
			break
		}
		chain = append(chain, *cn)
		cur_ = CanonName(cn.Data.(CNAME).Target)
	}
	if len(chain) > 0 {
		owners := map[cacheKey]bool{}
		for _, c := range chain {
			owners[cacheKey{CanonName(c.Name), c.Type}] = true
		}
		for _, a := range m.Answer {
			if a.Type == TypeRRSIG && owners[cacheKey{CanonName(a.Name), a.Data.(RRSIG).TypeCovered}] {
				sigs = append(sigs, a)
			}
		}
		sec := Indeterminate
		if r.Validate {
			var why string
			sec, why = r.validateAnswer(m, chain, sigs, name, depth)
			if sec == Bogus {
				return &stepResult{kind: kindBogus, why: why}, nil, ""
			}
		}
		r.cacheChain(chain, sigs, sec)
		// the step result covers the first name; later hops are served via cache
		var first []RR
		fname := CanonName(chain[0].Name)
		for _, c := range chain {
			if CanonName(c.Name) == fname {
				first = append(first, c)
			}
		}
		for _, s := range sigs {
			if CanonName(s.Name) == fname && s.Data.(RRSIG).TypeCovered == first[0].Type {
				first = append(first, s)
			}
		}
		kind := kindAnswer
		if first[0].Type == TypeCNAME && t != TypeCNAME {
			kind = kindCNAME
		}
		if !r.Validate {
			first = stripSigs(first)
		}
		return &stepResult{kind: kind, rrs: first, sec: sec}, nil, ""
	}
	// 2. Negative answer from an authoritative server
	if m.Authoritative || m.Rcode == RcodeNXDomain {
		var soa []RR
		for _, a := range m.Authority {
			if a.Type == TypeSOA && IsSubdomain(name, a.Name) {
				soa = append(soa, a)
			}
		}
		hasNS := false
		for _, a := range m.Authority {
			if a.Type == TypeNS {
				hasNS = true
			}
		}
		if len(soa) > 0 || (m.Authoritative && !hasNS) {
			if m.Rcode == RcodeNXDomain && !m.Authoritative {
				return nil, nil, "non-authoritative NXDOMAIN"
			}
			sec := Indeterminate
			if r.Validate {
				var why string
				sec, why = r.validateNegative(m, name, t, depth)
				if sec == Bogus {
					return &stepResult{kind: kindBogus, why: why}, nil, ""
				}
			}
			if len(soa) > 0 {
				r.Cache.PutNeg(name, t, m.Rcode, soa, sec)
			}
			if r.Validate {
				soa = append(soa, selectSigs(m.Authority, TypeSOA)...)
			}
			return &stepResult{kind: kindNegative, rcode: m.Rcode, soa: soa, sec: sec}, nil, ""
		}
	}
	// 3. Referral
	if m.Rcode == RcodeNXDomain {
		return nil, nil, "NXDOMAIN without authority"
	}
	var ns []RR
	for _, a := range m.Authority {
		if a.Type == TypeNS && IsSubdomain(name, a.Name) && IsSubdomain(a.Name, cur.zone) && CompareNames(a.Name, cur.zone) != 0 {
			ns = append(ns, a)
		}
	}
	if len(ns) == 0 {
		return nil, nil, "lame: neither answer nor usable referral"
	}
	zone := CanonName(ns[0].Name)
	nd := &delegation{zone: zone, addrs: map[string][]netip.Addr{}}
	var nsset []RR
	for _, n := range ns {
		if CompareNames(n.Name, zone) != 0 {
			continue
		}
		nsset = append(nsset, n)
		nd.hosts = append(nd.hosts, CanonName(n.Data.(NS).Host))
	}
	if r.Validate {
		if bad := r.checkReferral(m, zone, cur, depth); bad != "" {
			return &stepResult{kind: kindBogus, why: bad}, nil, ""
		}
	}
	r.Cache.PutSet(nsset, nil, Indeterminate)
	// glue: in-bailiwick of the *responding* zone only
	glue := map[cacheKey][]RR{}
	for _, a := range m.Additional {
		if a.Type != TypeA && a.Type != TypeAAAA {
			continue
		}
		on := CanonName(a.Name)
		isNS := false
		for _, h := range nd.hosts {
			if h == on {
				isNS = true
			}
		}
		if !isNS || !IsSubdomain(on, cur.zone) {
			continue
		}
		k := cacheKey{on, a.Type}
		glue[k] = append(glue[k], a)
		switch v := a.Data.(type) {
		case A:
			nd.addrs[on] = append(nd.addrs[on], v.Addr)
		case AAAA:
			nd.addrs[on] = append(nd.addrs[on], v.Addr)
		}
	}
	for _, set := range glue {
		r.Cache.PutSet(set, nil, Indeterminate)
	}
	r.tracef(depth, "referral to %s (%s)", zone, strings.Join(nd.hosts, ", "))
	return nil, nd, ""
}

func stripSigs(in []RR) []RR {
	out := in[:0:0]
	for _, x := range in {
		if x.Type != TypeRRSIG {
			out = append(out, x)
		}
	}
	return out
}

func selectSigs(rrs []RR, covered Type) []RR {
	var out []RR
	for _, x := range rrs {
		if x.Type == TypeRRSIG && x.Data.(RRSIG).TypeCovered == covered {
			out = append(out, x)
		}
	}
	return out
}

// cacheChain stores each RRset of the validated chain separately.
func (r *Resolver) cacheChain(chain, sigs []RR, sec SecStatus) {
	sets := map[cacheKey][]RR{}
	var order []cacheKey
	for _, c := range chain {
		k := cacheKey{CanonName(c.Name), c.Type}
		if _, ok := sets[k]; !ok {
			order = append(order, k)
		}
		sets[k] = append(sets[k], c)
	}
	for _, k := range order {
		var ks []RR
		for _, s := range sigs {
			if CanonName(s.Name) == k.name && s.Data.(RRSIG).TypeCovered == k.t {
				ks = append(ks, s)
			}
		}
		r.Cache.PutSet(sets[k], ks, sec)
	}
}
