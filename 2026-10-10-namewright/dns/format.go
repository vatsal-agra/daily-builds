package dns

import (
	"fmt"
	"strings"
)

// Format renders a message in a dig-like layout.
func (m *Message) Format() string {
	var sb strings.Builder
	opcode := "QUERY"
	if m.Opcode != 0 {
		opcode = fmt.Sprintf("OPCODE%d", m.Opcode)
	}
	var fl []string
	for _, f := range []struct {
		on bool
		n  string
	}{{m.Response, "qr"}, {m.Authoritative, "aa"}, {m.Truncated, "tc"}, {m.RecursionDesired, "rd"},
		{m.RecursionAvailable, "ra"}, {m.AuthenticData, "ad"}, {m.CheckingDisabled, "cd"}} {
		if f.on {
			fl = append(fl, f.n)
		}
	}
	rc := fmt.Sprint(Rcode(m.FullRcode() & 0xFF))
	if m.FullRcode() == 16 {
		rc = "BADVERS"
	}
	fmt.Fprintf(&sb, ";; ->>HEADER<<- opcode: %s, status: %s, id: %d\n", opcode, rc, m.ID)
	nOPT := 0
	for _, r := range m.Additional {
		if r.Type == TypeOPT {
			nOPT++
		}
	}
	fmt.Fprintf(&sb, ";; flags: %s; QUERY: %d, ANSWER: %d, AUTHORITY: %d, ADDITIONAL: %d\n",
		strings.Join(fl, " "), len(m.Question), len(m.Answer), len(m.Authority), len(m.Additional))
	if e, ok := m.GetEDNS(); ok {
		do := ""
		if e.DO {
			do = " do"
		}
		fmt.Fprintf(&sb, "\n;; OPT PSEUDOSECTION:\n; EDNS: version: %d, flags:%s; udp: %d\n", e.Version, do, e.UDPSize)
	}
	if len(m.Question) > 0 {
		sb.WriteString("\n;; QUESTION SECTION:\n")
		for _, q := range m.Question {
			fmt.Fprintf(&sb, ";%s\t%s\t%s\n", q.Name, q.Class, q.Type)
		}
	}
	sec := func(title string, rrs []RR) {
		var out []string
		for _, r := range rrs {
			if r.Type != TypeOPT {
				out = append(out, r.String())
			}
		}
		if len(out) > 0 {
			fmt.Fprintf(&sb, "\n;; %s SECTION:\n%s\n", title, strings.Join(out, "\n"))
		}
	}
	sec("ANSWER", m.Answer)
	sec("AUTHORITY", m.Authority)
	sec("ADDITIONAL", m.Additional)
	return sb.String()
}
