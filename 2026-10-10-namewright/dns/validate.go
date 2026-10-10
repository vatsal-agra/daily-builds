package dns

import (
	"errors"
	"fmt"
	"sort"
	"time"
)

// ErrNoTrustAnchor is returned when validation is enabled without anchors.
var ErrNoTrustAnchor = errors.New("resolver: DNSSEC validation enabled but no trust anchor configured")

type zoneKeys struct {
	keys    []DNSKEY
	status  SecStatus
	why     string
	expires time.Time
}

func (r *Resolver) hasAnchor() bool { return len(r.TrustAnchors) > 0 || len(r.AnchorKeys) > 0 }

func (r *Resolver) validating(st *resState) bool { return r.Validate && !st.noValidate && st.raw == 0 }

func (r *Resolver) now() time.Time {
	if r.Now != nil {
		return r.Now()
	}
	return time.Now()
}

// rawFetch asks authoritative servers for (name, t) without caching or
// validating, returning the whole response message and the zone that
// answered. DS queries start at the parent side of the cut.
func (r *Resolver) rawFetch(name string, t Type, depth int, st *resState) (*Message, string, error) {
	st.raw++
	defer func() { st.raw-- }()
	res, err := r.iterate(name, t, depth+1, st)
	if err != nil {
		return nil, "", err
	}
	if res.kind != kindRaw {
		return nil, "", fmt.Errorf("unexpected resolver state fetching %s %s", name, t)
	}
	return res.raw, res.from, nil
}

func rrsOf(rrs []RR, owner string, t Type) []RR {
	var out []RR
	for _, x := range rrs {
		if x.Type == t && CompareNames(x.Name, owner) == 0 {
			out = append(out, x)
		}
	}
	return out
}

func sigsFor(rrs []RR, owner string, covered Type) []RR {
	var out []RR
	for _, x := range rrs {
		if x.Type == TypeRRSIG && CompareNames(x.Name, owner) == 0 && x.Data.(RRSIG).TypeCovered == covered {
			out = append(out, x)
		}
	}
	return out
}

// verifySet checks that rrset is signed by one of keys with signer == zone.
func (r *Resolver) verifySet(rrset, sigs []RR, keys []DNSKEY, zone string) error {
	if len(rrset) == 0 {
		return errors.New("empty RRset")
	}
	if len(sigs) == 0 {
		return fmt.Errorf("no RRSIG for %s %s", rrset[0].Name, rrset[0].Type)
	}
	var last error
	for _, s := range sigs {
		sig := s.Data.(RRSIG)
		if CompareNames(sig.SignerName, zone) != 0 {
			last = fmt.Errorf("RRSIG signer %s is not the zone %s", sig.SignerName, zone)
			continue
		}
		for _, k := range keys {
			if k.Algorithm != sig.Algorithm || KeyTag(k) != sig.KeyTag {
				continue
			}
			err := VerifyRRSIG(sig, k, rrset, r.now())
			if err == nil {
				return nil
			}
			last = err
		}
		if last == nil {
			last = fmt.Errorf("no DNSKEY with tag %d for signature", sig.KeyTag)
		}
	}
	return fmt.Errorf("%s %s: %v", rrset[0].Name, rrset[0].Type, last)
}

// zoneSecurity establishes the DNSSEC state of a zone and, when secure, the
// validated DNSKEY set: the chain of trust from the anchors down to it.
func (r *Resolver) zoneSecurity(zone string, depth int, st *resState) ([]DNSKEY, SecStatus, string) {
	zone = CanonName(zone)
	r.mu.Lock()
	if e, ok := r.keyCache[zone]; ok && r.now().Before(e.expires) {
		r.mu.Unlock()
		return e.keys, e.status, e.why
	}
	r.mu.Unlock()
	keys, status, why, ttl := r.computeZoneSecurity(zone, depth, st)
	if status != Bogus || ttl > 0 {
		r.mu.Lock()
		if r.keyCache == nil {
			r.keyCache = map[string]*zoneKeys{}
		}
		r.keyCache[zone] = &zoneKeys{keys, status, why, r.now().Add(ttl)}
		r.mu.Unlock()
	}
	return keys, status, why
}

func (r *Resolver) computeZoneSecurity(zone string, depth int, st *resState) ([]DNSKEY, SecStatus, string, time.Duration) {
	const shortTTL = 30 * time.Second
	bogus := func(f string, a ...any) ([]DNSKEY, SecStatus, string, time.Duration) {
		return nil, Bogus, fmt.Sprintf(f, a...), shortTTL
	}
	var candidates []DNSKEY // keys the DNSKEY RRset must be signed by
	if zone == "." {
		msg, _, err := r.rawFetch(".", TypeDNSKEY, depth, st)
		if err != nil {
			return bogus("cannot fetch root DNSKEY: %v", err)
		}
		set := rrsOf(msg.Answer, ".", TypeDNSKEY)
		for _, k := range set {
			key := k.Data.(DNSKEY)
			for _, a := range r.AnchorKeys {
				if a.Flags == key.Flags && a.Algorithm == key.Algorithm && string(a.PublicKey) == string(key.PublicKey) {
					candidates = append(candidates, key)
				}
			}
			for _, d := range r.TrustAnchors {
				if DSMatches(".", d, key) {
					candidates = append(candidates, key)
				}
			}
		}
		if len(candidates) == 0 {
			return bogus("root DNSKEY set contains no key matching the trust anchor")
		}
		if err := r.verifySet(set, sigsFor(msg.Answer, ".", TypeDNSKEY), candidates, "."); err != nil {
			return bogus("root DNSKEY RRset: %v", err)
		}
		return keysOf(set), Secure, "", ttlOf(set)
	}

	parent := r.bestDelegation(Parent(zone)).zone
	pkeys, pst, pwhy := r.zoneSecurity(parent, depth, st)
	switch pst {
	case Bogus:
		return bogus("%s", pwhy)
	case Insecure:
		return nil, Insecure, "", time.Minute
	}
	dsMsg, from, err := r.rawFetch(zone, TypeDS, depth, st)
	if err != nil {
		return bogus("cannot fetch DS for %s: %v", zone, err)
	}
	if CompareNames(from, parent) != 0 {
		// the DS was answered by a different zone than the one we validated
		pkeys, pst, pwhy = r.zoneSecurity(from, depth, st)
		if pst == Bogus {
			return bogus("%s", pwhy)
		}
		if pst == Insecure {
			return nil, Insecure, "", time.Minute
		}
		parent = from
	}
	dsSet := rrsOf(dsMsg.Answer, zone, TypeDS)
	if len(dsSet) == 0 {
		// must be provably absent: signed NSEC at the cut, NS present, DS and SOA absent
		nsec := rrsOf(dsMsg.Authority, zone, TypeNSEC)
		if len(nsec) == 0 {
			return bogus("%s: neither DS nor a proof of its absence was returned", zone)
		}
		if err := r.verifySet(nsec, sigsFor(dsMsg.Authority, zone, TypeNSEC), pkeys, parent); err != nil {
			return bogus("NSEC proving no DS: %v", err)
		}
		d := nsec[0].Data.(NSEC)
		if hasType(d.Types, TypeDS) || hasType(d.Types, TypeSOA) || !hasType(d.Types, TypeNS) {
			return bogus("NSEC at %s does not prove an insecure delegation", zone)
		}
		return nil, Insecure, "", time.Minute
	}
	if err := r.verifySet(dsSet, sigsFor(dsMsg.Answer, zone, TypeDS), pkeys, parent); err != nil {
		return bogus("DS RRset: %v", err)
	}
	var usable []DS
	for _, d := range dsSet {
		ds := d.Data.(DS)
		if SupportedAlgorithm(ds.Algorithm) && (ds.DigestType == DigestSHA256 || ds.DigestType == DigestSHA1 || ds.DigestType == DigestSHA384) {
			usable = append(usable, ds)
		}
	}
	if len(usable) == 0 {
		return nil, Insecure, "", time.Minute // RFC 4035 §5.2: unsupported algorithms ⇒ treat as unsigned
	}
	keyMsg, _, err := r.rawFetch(zone, TypeDNSKEY, depth, st)
	if err != nil {
		return bogus("cannot fetch DNSKEY for %s: %v", zone, err)
	}
	keySet := rrsOf(keyMsg.Answer, zone, TypeDNSKEY)
	for _, k := range keySet {
		key := k.Data.(DNSKEY)
		for _, ds := range usable {
			if DSMatches(zone, ds, key) {
				candidates = append(candidates, key)
			}
		}
	}
	if len(candidates) == 0 {
		return bogus("no DNSKEY of %s matches its DS record", zone)
	}
	if err := r.verifySet(keySet, sigsFor(keyMsg.Answer, zone, TypeDNSKEY), candidates, zone); err != nil {
		return bogus("DNSKEY RRset of %s: %v", zone, err)
	}
	return keysOf(keySet), Secure, "", ttlOf(keySet)
}

func keysOf(set []RR) []DNSKEY {
	var out []DNSKEY
	for _, s := range set {
		out = append(out, s.Data.(DNSKEY))
	}
	return out
}

func ttlOf(set []RR) time.Duration {
	ttl := set[0].TTL
	for _, s := range set {
		if s.TTL < ttl {
			ttl = s.TTL
		}
	}
	if ttl > 3600 {
		ttl = 3600
	}
	return time.Duration(ttl) * time.Second
}

func hasType(ts []Type, t Type) bool {
	for _, x := range ts {
		if x == t {
			return true
		}
	}
	return false
}

type rrsetKey struct {
	name string
	t    Type
}

// validateAnswer validates every RRset in chain, which the servers of zone returned.
func (r *Resolver) validateAnswer(m *Message, chain, sigs []RR, name, zone string, depth int, st *resState) (SecStatus, string) {
	keys, status, why := r.zoneSecurity(zone, depth, st)
	switch status {
	case Insecure:
		return Insecure, ""
	case Bogus:
		return Bogus, why
	}
	sets := map[rrsetKey][]RR{}
	var order []rrsetKey
	for _, c := range chain {
		k := rrsetKey{CanonName(c.Name), c.Type}
		if _, ok := sets[k]; !ok {
			order = append(order, k)
		}
		sets[k] = append(sets[k], c)
	}
	for _, k := range order {
		set := sets[k]
		ss := sigsFor(sigs, k.name, k.t)
		if err := r.verifySet(set, ss, keys, zone); err != nil {
			return Bogus, err.Error()
		}
		// wildcard-synthesised answer: the signature covers the wildcard owner, so
		// the response must also prove the queried name does not exist
		for _, s := range ss {
			if int(s.Data.(RRSIG).Labels) < NumLabels(k.name) {
				if why := r.proveNameAbsent(m, k.name, zone, keys); why != "" {
					return Bogus, "wildcard answer without valid proof: " + why
				}
				break
			}
		}
	}
	return Secure, ""
}

// validNSECs returns the signature-verified NSEC records in m.Authority.
func (r *Resolver) validNSECs(m *Message, zone string, keys []DNSKEY) ([]RR, string) {
	byOwner := map[string][]RR{}
	var owners []string
	for _, a := range m.Authority {
		if a.Type == TypeNSEC {
			o := CanonName(a.Name)
			if _, ok := byOwner[o]; !ok {
				owners = append(owners, o)
			}
			byOwner[o] = append(byOwner[o], a)
		}
	}
	var out []RR
	for _, o := range owners {
		if err := r.verifySet(byOwner[o], sigsFor(m.Authority, o, TypeNSEC), keys, zone); err != nil {
			return nil, err.Error()
		}
		out = append(out, byOwner[o]...)
	}
	return out, ""
}

func nsecCovers(owner, next, name string) bool {
	c1, c2 := CompareNames(owner, name), CompareNames(name, next)
	if CompareNames(owner, next) < 0 {
		return c1 < 0 && c2 < 0
	}
	return c1 < 0 || c2 < 0 // last record in the chain wraps to the apex
}

func commonSuffix(a, b string) string {
	al, bl := Labels(a), Labels(b)
	n := 0
	for n < len(al) && n < len(bl) && eqFold(al[len(al)-1-n], bl[len(bl)-1-n]) {
		n++
	}
	if n == 0 {
		return "."
	}
	return joinLabels(lowerAll(al[len(al)-n:]))
}

func lowerAll(ls [][]byte) [][]byte {
	out := make([][]byte, len(ls))
	for i, l := range ls {
		out[i] = lowerBytes(l)
	}
	return out
}

// proveNameAbsent checks that a validated NSEC covers name (it does not exist).
func (r *Resolver) proveNameAbsent(m *Message, name, zone string, keys []DNSKEY) string {
	nsecs, why := r.validNSECs(m, zone, keys)
	if why != "" {
		return why
	}
	for _, n := range nsecs {
		if nsecCovers(CanonName(n.Name), CanonName(n.Data.(NSEC).Next), name) {
			return ""
		}
	}
	return "no NSEC covers " + name
}

// validateNegative checks a signed NXDOMAIN / NODATA answer (RFC 4035 §5.4).
func (r *Resolver) validateNegative(m *Message, name string, t Type, zone string, depth int, st *resState) (SecStatus, string) {
	keys, status, why := r.zoneSecurity(zone, depth, st)
	switch status {
	case Insecure:
		return Insecure, ""
	case Bogus:
		return Bogus, why
	}
	soa := rrsOf(m.Authority, zone, TypeSOA)
	if len(soa) == 0 {
		return Bogus, "negative answer carries no SOA"
	}
	if err := r.verifySet(soa, sigsFor(m.Authority, zone, TypeSOA), keys, zone); err != nil {
		return Bogus, err.Error()
	}
	nsecs, why := r.validNSECs(m, zone, keys)
	if why != "" {
		return Bogus, why
	}
	if len(nsecs) == 0 {
		for _, a := range m.Authority {
			if a.Type == TypeNSEC3 {
				return Bogus, "NSEC3 denial of existence is not supported"
			}
		}
		return Bogus, "no NSEC records prove the negative answer"
	}
	find := func(owner string) *NSEC {
		for _, n := range nsecs {
			if CompareNames(n.Name, owner) == 0 {
				d := n.Data.(NSEC)
				return &d
			}
		}
		return nil
	}
	covering := func(n string) (owner string, d *NSEC) {
		for _, x := range nsecs {
			nd := x.Data.(NSEC)
			if nsecCovers(CanonName(x.Name), CanonName(nd.Next), n) {
				return CanonName(x.Name), &nd
			}
		}
		return "", nil
	}
	if m.Rcode == RcodeNXDomain {
		owner, d := covering(name)
		if d == nil {
			return Bogus, "NXDOMAIN without an NSEC covering " + name
		}
		ce := commonSuffix(name, owner)
		if c2 := commonSuffix(name, CanonName(d.Next)); NumLabels(c2) > NumLabels(ce) {
			ce = c2
		}
		wild := Join("*", ce)
		if ce == "." {
			wild = "*."
		}
		if w, _ := covering(wild); w == "" {
			return Bogus, "NXDOMAIN without an NSEC denying the wildcard " + wild
		}
		return Secure, ""
	}
	// NODATA
	if d := find(name); d != nil {
		if hasType(d.Types, t) || (t != TypeCNAME && hasType(d.Types, TypeCNAME)) {
			return Bogus, fmt.Sprintf("NSEC at %s says %s exists", name, t)
		}
		if t != TypeDS && hasType(d.Types, TypeNS) && !hasType(d.Types, TypeSOA) {
			return Bogus, "NODATA at a delegation point"
		}
		return Secure, ""
	}
	owner, d := covering(name)
	if d == nil {
		return Bogus, "NODATA without a matching or covering NSEC"
	}
	if IsSubdomain(CanonName(d.Next), name) && CompareNames(d.Next, name) != 0 {
		return Secure, "" // empty non-terminal: the next name lies below this one
	}
	ce := commonSuffix(name, owner)
	if c2 := commonSuffix(name, CanonName(d.Next)); NumLabels(c2) > NumLabels(ce) {
		ce = c2
	}
	wild := Join("*", ce)
	if ce == "." {
		wild = "*."
	}
	if wd := find(wild); wd != nil && !hasType(wd.Types, t) && !hasType(wd.Types, TypeCNAME) {
		return Secure, ""
	}
	return Bogus, "NODATA not proven by the NSEC records"
}

var _ = sort.Strings
