package dns

import (
	"fmt"
	"net/netip"
	"strings"
	"sync"
	"time"
)

// RateLimiter is a per-client token bucket. Rate tokens per second, up to Burst.
type RateLimiter struct {
	Rate  float64
	Burst float64
	Now   func() time.Time

	mu      sync.Mutex
	buckets map[string]*bucket
}

type bucket struct {
	tokens float64
	last   time.Time
}

func NewRateLimiter(rate, burst float64) *RateLimiter {
	return &RateLimiter{Rate: rate, Burst: burst, Now: time.Now, buckets: map[string]*bucket{}}
}

// Allow consumes one token for client and reports whether the query may proceed.
func (l *RateLimiter) Allow(client string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.Now()
	b := l.buckets[client]
	if b == nil {
		if len(l.buckets) > 100000 { // bound memory under address-spoofing floods
			l.buckets = map[string]*bucket{}
		}
		b = &bucket{tokens: l.Burst, last: now}
		l.buckets[client] = b
	}
	b.tokens += now.Sub(b.last).Seconds() * l.Rate
	if b.tokens > l.Burst {
		b.tokens = l.Burst
	}
	b.last = now
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}

// Action is what a response-policy rule does to a matching query.
type Action int

const (
	ActNXDomain Action = iota // pretend the name does not exist
	ActNoData                 // pretend the name has no data of this type
	ActRedirect               // answer A/AAAA with a fixed address
)

type policyRule struct {
	pattern string // canonical name; leading "*." means the name and everything below
	action  Action
	addr    netip.Addr
}

// Policy is a small response-policy zone: blocklist-style overrides evaluated
// before normal lookup.
type Policy struct {
	rules []policyRule
	TTL   uint32
}

// ParsePolicy reads lines of: `<name|*.name> NXDOMAIN|NODATA|A <ip>|AAAA <ip>`.
func ParsePolicy(src string) (*Policy, error) {
	p := &Policy{TTL: 30}
	for i, line := range strings.Split(src, "\n") {
		if k := strings.IndexByte(line, '#'); k >= 0 {
			line = line[:k]
		}
		f := strings.Fields(line)
		if len(f) == 0 {
			continue
		}
		fail := func(m string) error { return fmt.Errorf("policy line %d: %s", i+1, m) }
		pat := f[0]
		wild := strings.HasPrefix(pat, "*.")
		base := pat
		if wild {
			base = pat[2:]
		}
		if err := ValidName(CanonName(base)); err != nil {
			return nil, fail(err.Error())
		}
		r := policyRule{pattern: CanonName(base)}
		if wild {
			r.pattern = "*." + r.pattern
		}
		if len(f) < 2 {
			return nil, fail("missing action")
		}
		switch strings.ToUpper(f[1]) {
		case "NXDOMAIN":
			r.action = ActNXDomain
		case "NODATA":
			r.action = ActNoData
		case "A", "AAAA":
			if len(f) != 3 {
				return nil, fail("redirect needs an address")
			}
			a, err := netip.ParseAddr(f[2])
			if err != nil {
				return nil, fail("bad address " + f[2])
			}
			if (strings.ToUpper(f[1]) == "A") != a.Is4() {
				return nil, fail("address family does not match record type")
			}
			r.action, r.addr = ActRedirect, a
		default:
			return nil, fail("unknown action " + f[1])
		}
		p.rules = append(p.rules, r)
	}
	return p, nil
}

// Apply returns (rcode, answers, hit) if a rule matches name.
func (p *Policy) Apply(name string, qt Type) (Rcode, []RR, bool) {
	for _, r := range p.rules {
		hit := false
		if strings.HasPrefix(r.pattern, "*.") {
			hit = IsSubdomain(name, r.pattern[2:])
		} else {
			hit = CompareNames(name, r.pattern) == 0
		}
		if !hit {
			continue
		}
		switch r.action {
		case ActNXDomain:
			return RcodeNXDomain, nil, true
		case ActNoData:
			return RcodeSuccess, nil, true
		case ActRedirect:
			if (qt == TypeA && r.addr.Is4()) || (qt == TypeAAAA && r.addr.Is6()) {
				var d RData = A{r.addr}
				if r.addr.Is6() {
					d = AAAA{r.addr}
				}
				return RcodeSuccess, []RR{{Name: name, Type: qt, Class: ClassIN, TTL: p.TTL, Data: d}}, true
			}
			return RcodeSuccess, nil, true
		}
	}
	return 0, nil, false
}
