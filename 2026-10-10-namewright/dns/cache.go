package dns

import (
	"sync"
	"time"
)

type cacheKey struct {
	name string
	t    Type
}

// anyType is the key used for whole-name (NXDOMAIN) negative entries.
const nxKey Type = 0xFFFE

type posEntry struct {
	rrs      []RR
	sigs     []RR
	stored   time.Time
	expires  time.Time
	Security SecStatus
	trust    Trust
}

// Neg is a cached negative answer (RFC 2308).
type Neg struct {
	Rcode    Rcode
	SOA      []RR
	Security SecStatus
	expires  time.Time
	stored   time.Time
}

// Cache is a TTL-honouring RRset cache with negative caching.
type Cache struct {
	Now        func() time.Time
	MaxTTL     uint32 // clamp on positive TTLs
	MaxNegTTL  uint32
	MaxEntries int

	mu  sync.Mutex
	pos map[cacheKey]*posEntry
	neg map[cacheKey]*Neg

	Hits, Misses int
}

func NewCache() *Cache {
	return &Cache{Now: time.Now, MaxTTL: 86400, MaxNegTTL: 3600, MaxEntries: 20000,
		pos: map[cacheKey]*posEntry{}, neg: map[cacheKey]*Neg{}}
}

func (c *Cache) Len() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.pos) + len(c.neg)
}

func (c *Cache) evictLocked() {
	if len(c.pos)+len(c.neg) < c.MaxEntries {
		return
	}
	now := c.Now()
	for k, e := range c.pos {
		if !now.Before(e.expires) {
			delete(c.pos, k)
		}
	}
	for k, e := range c.neg {
		if !now.Before(e.expires) {
			delete(c.neg, k)
		}
	}
	for k := range c.pos { // still full: drop arbitrary entries
		if len(c.pos)+len(c.neg) < c.MaxEntries*9/10 {
			break
		}
		delete(c.pos, k)
	}
}

// PutSet stores one RRset (all same owner and type) and its signatures.
// The set TTL is the minimum across records. A zero TTL is not cached.
func (c *Cache) PutSet(rrs []RR, sigs []RR, sec SecStatus) {
	c.PutSetTrust(rrs, sigs, sec, TrustAnswer)
}

// PutSetTrust is PutSet with an RFC 2181 §5.4.1 trust rank: data from a
// lower-ranked source (glue) never replaces unexpired higher-ranked data.
func (c *Cache) PutSetTrust(rrs []RR, sigs []RR, sec SecStatus, tr Trust) {
	if len(rrs) == 0 {
		return
	}
	ttl := rrs[0].TTL
	for _, r := range rrs {
		if r.TTL < ttl {
			ttl = r.TTL
		}
	}
	if ttl > c.MaxTTL {
		ttl = c.MaxTTL
	}
	if ttl == 0 {
		return
	}
	now := c.Now()
	k := cacheKey{CanonName(rrs[0].Name), rrs[0].Type}
	set := make([]RR, len(rrs))
	copy(set, rrs)
	c.mu.Lock()
	defer c.mu.Unlock()
	if old := c.pos[k]; old != nil && old.trust > tr && now.Before(old.expires) {
		return
	}
	c.evictLocked()
	c.pos[k] = &posEntry{rrs: set, sigs: append([]RR(nil), sigs...), stored: now,
		expires: now.Add(time.Duration(ttl) * time.Second), Security: sec, trust: tr}
	delete(c.neg, k)
	delete(c.neg, cacheKey{k.name, nxKey})
}

// Get returns a copy of the RRset with TTLs decremented by age.
func (c *Cache) Get(name string, t Type) (rrs []RR, sigs []RR, sec SecStatus, ok bool) {
	k := cacheKey{CanonName(name), t}
	c.mu.Lock()
	defer c.mu.Unlock()
	e := c.pos[k]
	if e == nil {
		c.Misses++
		return nil, nil, 0, false
	}
	now := c.Now()
	if !now.Before(e.expires) {
		delete(c.pos, k)
		c.Misses++
		return nil, nil, 0, false
	}
	c.Hits++
	remain := uint32(e.expires.Sub(now) / time.Second)
	if remain == 0 {
		remain = 1
	}
	fix := func(in []RR) []RR {
		out := make([]RR, len(in))
		for i, r := range in {
			if r.TTL > remain {
				r.TTL = remain
			}
			out[i] = r
		}
		return out
	}
	return fix(e.rrs), fix(e.sigs), e.Security, true
}

// PutNeg caches a negative answer. For NXDOMAIN, t is ignored (applies to the whole name).
func (c *Cache) PutNeg(name string, t Type, rcode Rcode, soa []RR, sec SecStatus) {
	if len(soa) == 0 {
		return
	}
	ttl := uint32(0xFFFFFFFF)
	for _, r := range soa {
		if r.Type != TypeSOA {
			continue
		}
		ttl = r.TTL
		if m := r.Data.(SOA).Minimum; m < ttl {
			ttl = m
		}
	}
	if ttl == 0xFFFFFFFF || ttl == 0 {
		return
	}
	if ttl > c.MaxNegTTL {
		ttl = c.MaxNegTTL
	}
	now := c.Now()
	k := cacheKey{CanonName(name), t}
	if rcode == RcodeNXDomain {
		k.t = nxKey
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.evictLocked()
	c.neg[k] = &Neg{Rcode: rcode, SOA: append([]RR(nil), soa...), expires: now.Add(time.Duration(ttl) * time.Second), stored: now, Security: sec}
}

// GetNeg looks for a negative entry covering (name, t).
func (c *Cache) GetNeg(name string, t Type) (*Neg, bool) {
	name = CanonName(name)
	c.mu.Lock()
	defer c.mu.Unlock()
	now := c.Now()
	for _, k := range []cacheKey{{name, t}, {name, nxKey}} {
		n := c.neg[k]
		if n == nil {
			continue
		}
		if !now.Before(n.expires) {
			delete(c.neg, k)
			continue
		}
		c.Hits++
		out := *n
		remain := uint32(n.expires.Sub(now) / time.Second)
		out.SOA = append([]RR(nil), n.SOA...)
		for i := range out.SOA {
			if out.SOA[i].TTL > remain {
				out.SOA[i].TTL = remain
			}
		}
		return &out, true
	}
	c.Misses++
	return nil, false
}

// Delete removes the positive and negative entries for (name, t).
func (c *Cache) Delete(name string, t Type) {
	k := cacheKey{CanonName(name), t}
	c.mu.Lock()
	delete(c.pos, k)
	delete(c.neg, k)
	c.mu.Unlock()
}

// Flush drops everything.
func (c *Cache) Flush() {
	c.mu.Lock()
	c.pos = map[cacheKey]*posEntry{}
	c.neg = map[cacheKey]*Neg{}
	c.mu.Unlock()
}

type Trust int

const (
	TrustGlue   Trust = 1
	TrustAnswer Trust = 2
)
