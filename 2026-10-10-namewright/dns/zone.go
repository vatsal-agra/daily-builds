package dns

import (
	"fmt"
	"sort"
	"strings"
)

type node struct {
	rrsets map[Type][]RR
}

// Zone is an in-memory authoritative zone.
type Zone struct {
	Origin   string
	nodes    map[string]*node
	ents     map[string]bool // empty non-terminals
	sorted   []string        // names owning data, canonical DNSSEC order
	Warnings []string
	Signed   bool
}

// NewZone validates records and builds a zone. Hard errors (no SOA, CNAME
// conflicts, out-of-zone data) are returned; softer findings are kept in
// Warnings.
func NewZone(origin string, rrs []RR) (*Zone, error) {
	origin = CanonName(origin)
	if err := ValidName(origin); err != nil {
		return nil, err
	}
	z := &Zone{Origin: origin, nodes: map[string]*node{}, ents: map[string]bool{}}
	for _, r := range rrs {
		name := CanonName(r.Name)
		if !IsSubdomain(name, origin) {
			return nil, fmt.Errorf("%s %s is outside zone %s", r.Name, r.Type, origin)
		}
		if r.Class != ClassIN {
			return nil, fmt.Errorf("%s %s: only class IN is supported", r.Name, r.Type)
		}
		r.Name = name
		n := z.nodes[name]
		if n == nil {
			n = &node{rrsets: map[Type][]RR{}}
			z.nodes[name] = n
		}
		dup := false
		for _, e := range n.rrsets[r.Type] {
			if e.Equal(r) {
				dup = true
				break
			}
		}
		if dup {
			z.Warnings = append(z.Warnings, fmt.Sprintf("duplicate record %s %s ignored", name, r.Type))
			continue
		}
		n.rrsets[r.Type] = append(n.rrsets[r.Type], r)
		if r.Type == TypeRRSIG || r.Type == TypeNSEC {
			z.Signed = true
		}
	}
	apex := z.nodes[origin]
	if apex == nil || len(apex.rrsets[TypeSOA]) != 1 {
		return nil, fmt.Errorf("zone %s must have exactly one SOA record at the apex", origin)
	}
	if len(apex.rrsets[TypeNS]) == 0 {
		z.Warnings = append(z.Warnings, "zone has no NS records at the apex")
	}
	for name, n := range z.nodes {
		if cn := n.rrsets[TypeCNAME]; len(cn) > 0 {
			if len(cn) > 1 {
				return nil, fmt.Errorf("%s has multiple CNAME records", name)
			}
			for t := range n.rrsets {
				if t != TypeCNAME && t != TypeRRSIG && t != TypeNSEC {
					return nil, fmt.Errorf("%s has a CNAME and also %s data", name, t)
				}
			}
		}
		// TTL harmonisation within RRsets (RFC 2181 §5.2)
		for t, set := range n.rrsets {
			min := set[0].TTL
			mixed := false
			for _, r := range set {
				if r.TTL != set[0].TTL {
					mixed = true
				}
				if r.TTL < min {
					min = r.TTL
				}
			}
			if mixed {
				z.Warnings = append(z.Warnings, fmt.Sprintf("%s %s RRset has differing TTLs; using %d", name, t, min))
				for i := range set {
					set[i].TTL = min
				}
			}
		}
	}
	// delegation sanity: non-address data below a cut is occluded
	for name, n := range z.nodes {
		if name == origin {
			continue
		}
		if cut := z.findCut(name); cut != "" && cut != name {
			for t := range n.rrsets {
				if t != TypeA && t != TypeAAAA {
					return nil, fmt.Errorf("%s %s is below the delegation at %s (only glue A/AAAA allowed)", name, t, cut)
				}
			}
		}
	}
	// empty non-terminals and sorted name list
	for name := range z.nodes {
		z.sorted = append(z.sorted, name)
		for p := Parent(name); IsSubdomain(p, origin) && p != origin && z.nodes[p] == nil; p = Parent(p) {
			z.ents[p] = true
		}
	}
	sort.Slice(z.sorted, func(i, j int) bool { return CompareNames(z.sorted[i], z.sorted[j]) < 0 })
	return z, nil
}

// LoadZone parses master-file text and builds a zone.
func LoadZone(src, origin, file string) (*Zone, error) {
	rrs, err := ParseZone(src, origin, file)
	if err != nil {
		return nil, err
	}
	return NewZone(origin, rrs)
}

// findCut returns the closest delegation point at or above name (never the apex).
func (z *Zone) findCut(name string) string {
	labels := Labels(name)
	olen := NumLabels(z.Origin)
	for i := 0; i < len(labels)-olen; i++ {
		anc := joinLabels(labels[i:])
		if n := z.nodes[anc]; n != nil && len(n.rrsets[TypeNS]) > 0 {
			return anc
		}
	}
	return ""
}

func (z *Zone) SOA() RR { return z.nodes[z.Origin].rrsets[TypeSOA][0] }

// Records returns every record, apex SOA first, others in canonical order.
func (z *Zone) Records() []RR {
	var out []RR
	soa := z.SOA()
	out = append(out, soa)
	for _, name := range z.sorted {
		n := z.nodes[name]
		var types []int
		for t := range n.rrsets {
			types = append(types, int(t))
		}
		sort.Ints(types)
		for _, t := range types {
			for _, r := range n.rrsets[Type(t)] {
				if r.Type == TypeSOA {
					continue
				}
				out = append(out, r)
			}
		}
	}
	return out
}

// Result is the outcome of an authoritative lookup.
type Result struct {
	Rcode         Rcode
	Authoritative bool
	Answer        []RR
	Authority     []RR
	Additional    []RR
}

func (z *Zone) rrset(name string, t Type) []RR {
	if n := z.nodes[name]; n != nil {
		return n.rrsets[t]
	}
	return nil
}

func (z *Zone) sigs(name string, covered Type) []RR {
	var out []RR
	for _, r := range z.rrset(name, TypeRRSIG) {
		if r.Data.(RRSIG).TypeCovered == covered {
			out = append(out, r)
		}
	}
	return out
}

// withSigs returns the RRset plus (if do) its covering signatures, renamed to owner.
func (z *Zone) withSigs(name, owner string, t Type, do bool) []RR {
	set := z.rrset(name, t)
	out := make([]RR, 0, len(set))
	for _, r := range set {
		r.Name = owner
		out = append(out, r)
	}
	if do {
		for _, s := range z.sigs(name, t) {
			s.Name = owner
			out = append(out, s)
		}
	}
	return out
}

func (z *Zone) negSOA(do bool) []RR {
	soa := z.SOA()
	d := soa.Data.(SOA)
	if d.Minimum < soa.TTL {
		soa.TTL = d.Minimum
	}
	out := []RR{soa}
	if do {
		for _, s := range z.sigs(z.Origin, TypeSOA) {
			if d.Minimum < s.TTL {
				s.TTL = d.Minimum
			}
			out = append(out, s)
		}
	}
	return out
}

// nsecCovering returns the NSEC RRset (with sigs) whose span contains name.
func (z *Zone) nsecCovering(name string, do bool) []RR {
	if !z.Signed {
		return nil
	}
	var owner string
	for _, n := range z.sorted {
		if len(z.nodes[n].rrsets[TypeNSEC]) == 0 {
			continue
		}
		if CompareNames(n, name) <= 0 {
			owner = n
		}
	}
	if owner == "" {
		return nil
	}
	return z.withSigs(owner, owner, TypeNSEC, do)
}

func (z *Zone) nsecAt(name string, do bool) []RR {
	if z.nodes[name] == nil || len(z.nodes[name].rrsets[TypeNSEC]) == 0 {
		return nil
	}
	return z.withSigs(name, name, TypeNSEC, do)
}

// Lookup answers a query authoritatively per RFC 1034 §4.3.2 and RFC 4592.
// qname must be at or below the zone origin. If do is set and the zone is
// signed, RRSIG and NSEC records are included.
func (z *Zone) Lookup(qname string, qtype Type, do bool) *Result {
	res := &Result{Authoritative: true}
	name := CanonName(qname)
	do = do && z.Signed
	seen := map[string]bool{}
	for hop := 0; hop < 16; hop++ {
		if !IsSubdomain(name, z.Origin) || seen[name] {
			break
		}
		seen[name] = true
		next := z.step(name, qname, qtype, do, res)
		if next == "" {
			break
		}
		name = next
	}
	z.addAdditional(res, do)
	return res
}

// step resolves one name; it returns the next name to chase if a CNAME was followed.
func (z *Zone) step(name, orig string, qtype Type, do bool, res *Result) string {
	if cut := z.findCut(name); cut != "" && !(qtype == TypeDS && cut == name) {
		res.Authority = append(res.Authority, z.withSigs(cut, cut, TypeNS, false)...)
		if ds := z.rrset(cut, TypeDS); len(ds) > 0 {
			res.Authority = append(res.Authority, z.withSigs(cut, cut, TypeDS, do)...)
		} else if do {
			res.Authority = append(res.Authority, z.nsecAt(cut, do)...)
		}
		if len(res.Answer) == 0 {
			res.Authoritative = false
		}
		return ""
	}
	n := z.nodes[name]
	owner := name
	synth := false
	if n == nil && !z.ents[name] {
		// closest encloser, then wildcard
		enc := Parent(name)
		for IsSubdomain(enc, z.Origin) && z.nodes[enc] == nil && !z.ents[enc] {
			enc = Parent(enc)
		}
		wild := Join("*", enc)
		if enc == "." {
			wild = "*."
		}
		if wn := z.nodes[wild]; wn != nil {
			n, synth, owner = wn, true, wild
		}
		if !synth {
			res.Rcode = RcodeNXDomain
			res.Authority = append(res.Authority, z.negSOA(do)...)
			if do {
				res.Authority = append(res.Authority, z.nsecCovering(name, do)...)
				if wc := z.nsecCovering(wild, do); len(wc) > 0 && !sameFirstOwner(wc, res.Authority) {
					res.Authority = append(res.Authority, wc...)
				}
			}
			return ""
		}
	}
	emit := func(t Type) []RR {
		src := z.withSigs(owner, name, t, do)
		return src
	}
	if n == nil { // empty non-terminal
		res.Authority = append(res.Authority, z.negSOA(do)...)
		if do {
			res.Authority = append(res.Authority, z.nsecCovering(name, do)...)
		}
		return ""
	}
	if qtype == TypeANY {
		var types []int
		for t := range n.rrsets {
			if t != TypeRRSIG {
				types = append(types, int(t))
			}
		}
		sort.Ints(types)
		for _, t := range types {
			res.Answer = append(res.Answer, emit(Type(t))...)
		}
		return ""
	}
	if cn := n.rrsets[TypeCNAME]; len(cn) > 0 && qtype != TypeCNAME && qtype != TypeNSEC && qtype != TypeRRSIG {
		res.Answer = append(res.Answer, emit(TypeCNAME)...)
		return CanonName(cn[0].Data.(CNAME).Target)
	}
	if len(n.rrsets[qtype]) > 0 {
		res.Answer = append(res.Answer, emit(qtype)...)
		if synth && do {
			res.Authority = append(res.Authority, z.nsecCovering(name, do)...)
		}
		return ""
	}
	// NODATA
	res.Authority = append(res.Authority, z.negSOA(do)...)
	if do {
		if synth {
			res.Authority = append(res.Authority, z.nsecAt(owner, do)...)
			res.Authority = append(res.Authority, z.nsecCovering(name, do)...)
		} else {
			res.Authority = append(res.Authority, z.nsecAt(name, do)...)
		}
	}
	return ""
}

func sameFirstOwner(a, b []RR) bool {
	for _, x := range a {
		if x.Type != TypeNSEC {
			continue
		}
		for _, y := range b {
			if y.Type == TypeNSEC && CompareNames(x.Name, y.Name) == 0 {
				return true
			}
		}
	}
	return false
}

// addAdditional performs additional-section processing: glue for referrals and
// address records for NS/MX/SRV targets held in this zone.
func (z *Zone) addAdditional(res *Result, do bool) {
	have := map[string]bool{}
	add := func(target string) {
		target = CanonName(target)
		if !IsSubdomain(target, z.Origin) || have[target] {
			return
		}
		have[target] = true
		for _, t := range []Type{TypeA, TypeAAAA} {
			for _, r := range z.rrset(target, t) {
				res.Additional = append(res.Additional, r)
			}
		}
	}
	scan := func(rrs []RR, types ...Type) {
		for _, r := range rrs {
			for _, t := range types {
				if r.Type != t {
					continue
				}
				switch d := r.Data.(type) {
				case NS:
					add(d.Host)
				case MX:
					add(d.Host)
				case SRV:
					add(d.Target)
				}
			}
		}
	}
	scan(res.Answer, TypeNS, TypeMX, TypeSRV)
	if !res.Authoritative {
		scan(res.Authority, TypeNS)
	}
}

// String lists the zone in presentation format.
func (z *Zone) String() string {
	var sb strings.Builder
	for _, r := range z.Records() {
		sb.WriteString(r.String())
		sb.WriteByte('\n')
	}
	return sb.String()
}
