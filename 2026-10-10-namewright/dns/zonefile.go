package dns

import (
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"net/netip"
	"sort"
	"strconv"
	"strings"
)

// ParseError is a zone-file syntax error with its source position.
type ParseError struct {
	File string
	Line int
	Msg  string
}

func (e *ParseError) Error() string {
	f := e.File
	if f == "" {
		f = "zone"
	}
	return fmt.Sprintf("%s:%d: %s", f, e.Line, e.Msg)
}

type token struct {
	text   string
	quoted bool
}

type logicalLine struct {
	no     int
	indent bool // line began with whitespace: owner omitted
	tokens []token
}

// lex splits master-file text into logical lines, resolving comments, quoted
// strings and parenthesised continuation.
func lex(src string, file string) ([]logicalLine, error) {
	var out []logicalLine
	var cur *logicalLine
	depth := 0
	line := 1
	i := 0
	n := len(src)
	startLine := func() {
		if cur == nil {
			cur = &logicalLine{no: line}
		}
	}
	flush := func() {
		if cur != nil && len(cur.tokens) > 0 {
			out = append(out, *cur)
		}
		cur = nil
	}
	atLineStart := true
	for i < n {
		c := src[i]
		switch {
		case c == '\n':
			line++
			i++
			if depth == 0 {
				flush()
				atLineStart = true
			}
		case c == '\r':
			i++
		case c == ' ' || c == '\t':
			if atLineStart && depth == 0 {
				startLine()
				cur.indent = true
				atLineStart = false
			}
			i++
		case c == ';':
			for i < n && src[i] != '\n' {
				i++
			}
		case c == '(':
			startLine()
			atLineStart = false
			depth++
			i++
		case c == ')':
			if depth == 0 {
				return nil, &ParseError{file, line, "unbalanced ')'"}
			}
			depth--
			i++
		case c == '"':
			startLine()
			atLineStart = false
			start := line
			i++
			var sb strings.Builder
			closed := false
			for i < n {
				d := src[i]
				if d == '\\' && i+1 < n {
					sb.WriteByte(d)
					sb.WriteByte(src[i+1])
					if src[i+1] == '\n' {
						line++
					}
					i += 2
					continue
				}
				if d == '"' {
					closed = true
					i++
					break
				}
				if d == '\n' {
					line++
				}
				sb.WriteByte(d)
				i++
			}
			if !closed {
				return nil, &ParseError{file, start, "unterminated quoted string"}
			}
			cur.tokens = append(cur.tokens, token{sb.String(), true})
		default:
			startLine()
			if atLineStart {
				atLineStart = false
			}
			start := i
			for i < n {
				d := src[i]
				if d == '\\' && i+1 < n {
					i += 2
					continue
				}
				if d == ' ' || d == '\t' || d == '\n' || d == '\r' || d == ';' || d == '(' || d == ')' || d == '"' {
					break
				}
				i++
			}
			cur.tokens = append(cur.tokens, token{src[start:i], false})
		}
	}
	if depth != 0 {
		return nil, &ParseError{file, line, "unbalanced '(' at end of file"}
	}
	flush()
	return out, nil
}

// ParseTTL accepts plain seconds or BIND units: 1h30m, 2d, 1w.
func ParseTTL(s string) (uint32, error) {
	if s == "" {
		return 0, fmt.Errorf("empty TTL")
	}
	if allDigits(s) {
		v, err := strconv.ParseUint(s, 10, 32)
		if err != nil {
			return 0, fmt.Errorf("TTL %q out of range", s)
		}
		return uint32(v), nil
	}
	var total uint64
	num := ""
	for i := 0; i < len(s); i++ {
		c := s[i]
		if isDigit(c) {
			num += string(c)
			continue
		}
		if num == "" {
			return 0, fmt.Errorf("bad TTL %q", s)
		}
		v, err := strconv.ParseUint(num, 10, 32)
		if err != nil {
			return 0, fmt.Errorf("bad TTL %q", s)
		}
		switch c | 0x20 {
		case 's':
		case 'm':
			v *= 60
		case 'h':
			v *= 3600
		case 'd':
			v *= 86400
		case 'w':
			v *= 604800
		default:
			return 0, fmt.Errorf("bad TTL unit %q in %q", string(c), s)
		}
		total += v
		num = ""
	}
	if num != "" || total > 0xFFFFFFFF {
		return 0, fmt.Errorf("bad TTL %q", s)
	}
	return uint32(total), nil
}

func allDigits(s string) bool {
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		if !isDigit(s[i]) {
			return false
		}
	}
	return true
}

// unescapeChars resolves \X and \DDD in a character-string token.
func unescapeChars(s string) (string, error) {
	if !strings.Contains(s, "\\") {
		return s, nil
	}
	var out []byte
	for i := 0; i < len(s); i++ {
		if s[i] != '\\' {
			out = append(out, s[i])
			continue
		}
		i++
		if i >= len(s) {
			return "", fmt.Errorf("dangling backslash")
		}
		if isDigit(s[i]) {
			if i+2 >= len(s) || !isDigit(s[i+1]) || !isDigit(s[i+2]) {
				return "", fmt.Errorf("bad \\DDD escape")
			}
			v := int(s[i]-'0')*100 + int(s[i+1]-'0')*10 + int(s[i+2]-'0')
			if v > 255 {
				return "", fmt.Errorf("escape out of range")
			}
			out = append(out, byte(v))
			i += 2
		} else {
			out = append(out, s[i])
		}
	}
	return string(out), nil
}

type zoneState struct {
	origin    string
	ttl       uint32
	haveTTL   bool
	lastTTL   uint32
	haveLast  bool
	owner     string
	haveOwner bool
}

// ParseZone parses master-file text into resource records. origin is the
// initial $ORIGIN (may be empty if the file sets one before use).
func ParseZone(src, origin, file string) ([]RR, error) {
	src = strings.TrimPrefix(src, "\ufeff")
	lines, err := lex(src, file)
	if err != nil {
		return nil, err
	}
	st := &zoneState{}
	if origin != "" {
		if err := ValidName(origin); err != nil {
			return nil, &ParseError{file, 0, "bad origin: " + err.Error()}
		}
		st.origin = CanonName(origin)
	}
	var rrs []RR
	for _, ln := range lines {
		perr := func(f string, a ...any) error { return &ParseError{file, ln.no, fmt.Sprintf(f, a...)} }
		first := ln.tokens[0]
		if !first.quoted && strings.HasPrefix(first.text, "$") && !ln.indent {
			switch strings.ToUpper(first.text) {
			case "$ORIGIN":
				if len(ln.tokens) != 2 {
					return nil, perr("$ORIGIN takes exactly one name")
				}
				n, err := st.absName(ln.tokens[1].text)
				if err != nil {
					return nil, perr("%v", err)
				}
				st.origin = n
			case "$TTL":
				if len(ln.tokens) != 2 {
					return nil, perr("$TTL takes exactly one value")
				}
				v, err := ParseTTL(ln.tokens[1].text)
				if err != nil {
					return nil, perr("%v", err)
				}
				st.ttl, st.haveTTL = v, true
			case "$INCLUDE", "$GENERATE":
				return nil, perr("%s is not supported", strings.ToUpper(first.text))
			default:
				return nil, perr("unknown directive %s", first.text)
			}
			continue
		}
		rr, err := st.parseRR(ln)
		if err != nil {
			return nil, perr("%v", err)
		}
		rrs = append(rrs, rr)
	}
	return rrs, nil
}

func (st *zoneState) absName(s string) (string, error) {
	if s == "@" {
		if st.origin == "" {
			return "", fmt.Errorf("'@' used but no $ORIGIN is set")
		}
		return st.origin, nil
	}
	if strings.HasSuffix(s, ".") && !escapedDot(s) {
		if err := ValidName(s); err != nil {
			return "", err
		}
		return CanonName(s), nil
	}
	if st.origin == "" {
		return "", fmt.Errorf("relative name %q but no $ORIGIN is set", s)
	}
	full := Join(s, st.origin)
	if err := ValidName(full); err != nil {
		return "", err
	}
	return CanonName(full), nil
}

func (st *zoneState) parseRR(ln logicalLine) (RR, error) {
	var rr RR
	toks := ln.tokens
	if ln.indent {
		if !st.haveOwner {
			return rr, fmt.Errorf("record with no owner and no previous owner")
		}
		rr.Name = st.owner
	} else {
		n, err := st.absName(toks[0].text)
		if err != nil {
			return rr, err
		}
		rr.Name = n
		st.owner, st.haveOwner = n, true
		toks = toks[1:]
	}
	rr.Class = ClassIN
	haveTTL, haveClass := false, false
	for len(toks) > 0 && !toks[0].quoted {
		t := toks[0].text
		if !haveTTL && isDigit(t[0]) {
			v, err := ParseTTL(t)
			if err != nil {
				return rr, err
			}
			rr.TTL, haveTTL = v, true
			toks = toks[1:]
			continue
		}
		if !haveClass {
			switch strings.ToUpper(t) {
			case "IN":
				rr.Class, haveClass = ClassIN, true
				toks = toks[1:]
				continue
			case "CH":
				rr.Class, haveClass = ClassCH, true
				toks = toks[1:]
				continue
			}
		}
		break
	}
	if len(toks) == 0 {
		return rr, fmt.Errorf("missing record type")
	}
	typ, ok := ParseType(toks[0].text)
	if !ok {
		return rr, fmt.Errorf("unknown record type %q", toks[0].text)
	}
	rr.Type = typ
	toks = toks[1:]
	if haveTTL {
		st.lastTTL, st.haveLast = rr.TTL, true
	} else if st.haveTTL {
		rr.TTL = st.ttl
	} else if st.haveLast {
		rr.TTL = st.lastTTL
	} else {
		return rr, fmt.Errorf("no TTL: set $TTL or give the first record an explicit TTL")
	}
	data, err := st.parseRData(typ, toks)
	if err != nil {
		return rr, fmt.Errorf("%s: %v", typ, err)
	}
	rr.Data = data
	return rr, nil
}

func (st *zoneState) parseRData(t Type, toks []token) (RData, error) {
	// RFC 3597 generic form works for every type
	if len(toks) >= 2 && !toks[0].quoted && toks[0].text == `\#` {
		n, err := strconv.Atoi(toks[1].text)
		if err != nil || n < 0 {
			return nil, fmt.Errorf("bad generic rdata length")
		}
		var hx string
		for _, tk := range toks[2:] {
			hx += tk.text
		}
		raw, err := hex.DecodeString(hx)
		if err != nil || len(raw) != n {
			return nil, fmt.Errorf("generic rdata hex does not match declared length %d", n)
		}
		sub := &parser{msg: raw}
		d, err := unpackRData(t, sub, len(raw))
		if err != nil {
			return nil, err
		}
		if sub.off != len(raw) {
			return nil, fmt.Errorf("trailing bytes in generic rdata")
		}
		return d, nil
	}
	need := func(n int) error {
		if len(toks) != n {
			return fmt.Errorf("expected %d fields, got %d", n, len(toks))
		}
		return nil
	}
	u := func(i int, bits int) (uint64, error) {
		v, err := strconv.ParseUint(toks[i].text, 10, bits)
		if err != nil {
			return 0, fmt.Errorf("field %d (%q) is not a valid %d-bit number", i+1, toks[i].text, bits)
		}
		return v, nil
	}
	switch t {
	case TypeA:
		if err := need(1); err != nil {
			return nil, err
		}
		a, err := netip.ParseAddr(toks[0].text)
		if err != nil || !a.Is4() {
			return nil, fmt.Errorf("%q is not an IPv4 address", toks[0].text)
		}
		return A{a}, nil
	case TypeAAAA:
		if err := need(1); err != nil {
			return nil, err
		}
		a, err := netip.ParseAddr(toks[0].text)
		if err != nil || !a.Is6() || a.Is4In6() {
			return nil, fmt.Errorf("%q is not an IPv6 address", toks[0].text)
		}
		return AAAA{a}, nil
	case TypeNS, TypeCNAME, TypePTR:
		if err := need(1); err != nil {
			return nil, err
		}
		n, err := st.absName(toks[0].text)
		if err != nil {
			return nil, err
		}
		switch t {
		case TypeNS:
			return NS{n}, nil
		case TypeCNAME:
			return CNAME{n}, nil
		}
		return PTR{n}, nil
	case TypeMX:
		if err := need(2); err != nil {
			return nil, err
		}
		p, err := u(0, 16)
		if err != nil {
			return nil, err
		}
		n, err := st.absName(toks[1].text)
		if err != nil {
			return nil, err
		}
		return MX{uint16(p), n}, nil
	case TypeTXT:
		if len(toks) == 0 {
			return nil, fmt.Errorf("needs at least one string")
		}
		var ss []string
		for _, tk := range toks {
			s, err := unescapeChars(tk.text)
			if err != nil {
				return nil, err
			}
			if len(s) > 255 {
				return nil, fmt.Errorf("string of %d bytes exceeds 255; split it into several strings", len(s))
			}
			ss = append(ss, s)
		}
		return TXT{ss}, nil
	case TypeSOA:
		if err := need(7); err != nil {
			return nil, err
		}
		var s SOA
		var err error
		if s.MName, err = st.absName(toks[0].text); err != nil {
			return nil, err
		}
		if s.RName, err = st.absName(toks[1].text); err != nil {
			return nil, err
		}
		for i, f := range []*uint32{&s.Serial, &s.Refresh, &s.Retry, &s.Expire, &s.Minimum} {
			v, err := ParseTTL(toks[2+i].text)
			if err != nil {
				return nil, err
			}
			*f = v
		}
		return s, nil
	case TypeSRV:
		if err := need(4); err != nil {
			return nil, err
		}
		var s SRV
		for i, f := range []*uint16{&s.Priority, &s.Weight, &s.Port} {
			v, err := u(i, 16)
			if err != nil {
				return nil, err
			}
			*f = uint16(v)
		}
		var err error
		s.Target, err = st.absName(toks[3].text)
		return s, err
	case TypeCAA:
		if err := need(3); err != nil {
			return nil, err
		}
		fl, err := u(0, 8)
		if err != nil {
			return nil, err
		}
		val, err := unescapeChars(toks[2].text)
		if err != nil {
			return nil, err
		}
		return CAA{uint8(fl), strings.ToLower(toks[1].text), val}, nil
	case TypeDNSKEY:
		if len(toks) < 4 {
			return nil, fmt.Errorf("expected flags protocol algorithm key")
		}
		fl, err := u(0, 16)
		if err != nil {
			return nil, err
		}
		pr, err := u(1, 8)
		if err != nil {
			return nil, err
		}
		al, err := u(2, 8)
		if err != nil {
			return nil, err
		}
		var b64 string
		for _, tk := range toks[3:] {
			b64 += tk.text
		}
		key, err := base64.StdEncoding.DecodeString(b64)
		if err != nil {
			return nil, fmt.Errorf("bad base64 key: %v", err)
		}
		return DNSKEY{uint16(fl), uint8(pr), uint8(al), key}, nil
	case TypeDS:
		if len(toks) < 4 {
			return nil, fmt.Errorf("expected keytag algorithm digesttype digest")
		}
		kt, err := u(0, 16)
		if err != nil {
			return nil, err
		}
		al, err := u(1, 8)
		if err != nil {
			return nil, err
		}
		dt, err := u(2, 8)
		if err != nil {
			return nil, err
		}
		var hx string
		for _, tk := range toks[3:] {
			hx += tk.text
		}
		dg, err := hex.DecodeString(hx)
		if err != nil {
			return nil, fmt.Errorf("bad hex digest: %v", err)
		}
		return DS{uint16(kt), uint8(al), uint8(dt), dg}, nil
	case TypeRRSIG:
		if len(toks) < 9 {
			return nil, fmt.Errorf("expected 9+ fields")
		}
		tc, ok := ParseType(toks[0].text)
		if !ok {
			return nil, fmt.Errorf("unknown covered type %q", toks[0].text)
		}
		var s RRSIG
		s.TypeCovered = tc
		al, err := u(1, 8)
		if err != nil {
			return nil, err
		}
		lb, err := u(2, 8)
		if err != nil {
			return nil, err
		}
		ot, err := u(3, 32)
		if err != nil {
			return nil, err
		}
		ex, err := u(4, 32)
		if err != nil {
			return nil, err
		}
		in, err := u(5, 32)
		if err != nil {
			return nil, err
		}
		kt, err := u(6, 16)
		if err != nil {
			return nil, err
		}
		s.Algorithm, s.Labels, s.OrigTTL, s.Expiration, s.Inception, s.KeyTag =
			uint8(al), uint8(lb), uint32(ot), uint32(ex), uint32(in), uint16(kt)
		if s.SignerName, err = st.absName(toks[7].text); err != nil {
			return nil, err
		}
		var b64 string
		for _, tk := range toks[8:] {
			b64 += tk.text
		}
		if s.Signature, err = base64.StdEncoding.DecodeString(b64); err != nil {
			return nil, fmt.Errorf("bad base64 signature: %v", err)
		}
		return s, nil
	case TypeNSEC:
		if len(toks) < 1 {
			return nil, fmt.Errorf("expected next-name and type list")
		}
		n, err := st.absName(toks[0].text)
		if err != nil {
			return nil, err
		}
		var ts []Type
		for _, tk := range toks[1:] {
			ty, ok := ParseType(tk.text)
			if !ok {
				return nil, fmt.Errorf("unknown type %q in bitmap", tk.text)
			}
			ts = append(ts, ty)
		}
		sort.Slice(ts, func(i, j int) bool { return ts[i] < ts[j] })
		return NSEC{n, ts}, nil
	}
	return nil, fmt.Errorf("no presentation parser for type %s (use the \\# generic form)", t)
}
