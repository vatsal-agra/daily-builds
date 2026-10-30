package qr

import (
	"errors"
	"fmt"
	"sort"
	"strings"
)

// wifiEscape escapes the characters that are special in the WIFI: payload.
func wifiEscape(s string) string {
	r := strings.NewReplacer(`\`, `\\`, `;`, `\;`, `,`, `\,`, `:`, `\:`, `"`, `\"`)
	return r.Replace(s)
}

// WiFiPayload builds a "WIFI:" join-network string. auth is WPA, WEP or nopass.
func WiFiPayload(ssid, password, auth string, hidden bool) (string, error) {
	if ssid == "" {
		return "", errors.New("wifi: empty SSID")
	}
	switch strings.ToUpper(auth) {
	case "WPA", "WPA2", "WPA3", "WEP", "NOPASS":
	default:
		return "", fmt.Errorf("wifi: auth %q must be WPA, WEP or nopass", auth)
	}
	if strings.EqualFold(auth, "nopass") {
		password = ""
	} else if password == "" {
		return "", errors.New("wifi: password required unless auth is nopass")
	}
	a := strings.ToUpper(auth)
	if a == "WPA2" || a == "WPA3" {
		a = "WPA"
	}
	if a == "NOPASS" {
		a = "nopass"
	}
	s := "WIFI:T:" + a + ";S:" + wifiEscape(ssid) + ";"
	if password != "" {
		s += "P:" + wifiEscape(password) + ";"
	}
	if hidden {
		s += "H:true;"
	}
	return s + ";", nil
}

// ParseWiFi reverses WiFiPayload, honouring backslash escapes.
func ParseWiFi(s string) (ssid, password, auth string, hidden bool, err error) {
	if !strings.HasPrefix(s, "WIFI:") {
		return "", "", "", false, errors.New("wifi: missing WIFI: prefix")
	}
	body := s[5:]
	var field, key strings.Builder
	cur := &key
	haveKey := ""
	esc := false
	flush := func() {
		if haveKey == "" {
			return
		}
		v := field.String()
		switch haveKey {
		case "S":
			ssid = v
		case "P":
			password = v
		case "T":
			auth = v
		case "H":
			hidden = v == "true"
		}
	}
	for i := 0; i < len(body); i++ {
		c := body[i]
		switch {
		case esc:
			cur.WriteByte(c)
			esc = false
		case c == '\\':
			esc = true
		case c == ':' && cur == &key:
			haveKey = key.String()
			key.Reset()
			cur = &field
		case c == ';':
			flush()
			field.Reset()
			key.Reset()
			haveKey = ""
			cur = &key
		default:
			cur.WriteByte(c)
		}
	}
	if esc {
		return "", "", "", false, errors.New("wifi: dangling backslash")
	}
	if ssid == "" {
		return "", "", "", false, errors.New("wifi: no SSID")
	}
	return
}

// MailtoPayload builds a mailto: URI with percent-encoded subject/body.
func MailtoPayload(to, subject, body string) (string, error) {
	if !strings.Contains(to, "@") || strings.ContainsAny(to, " \n") {
		return "", fmt.Errorf("mailto: %q is not an address", to)
	}
	s := "mailto:" + to
	sep := "?"
	if subject != "" {
		s += sep + "subject=" + pctEncode(subject)
		sep = "&"
	}
	if body != "" {
		s += sep + "body=" + pctEncode(body)
	}
	return s, nil
}

func pctEncode(s string) string {
	var sb strings.Builder
	for _, b := range []byte(s) {
		if b >= 'A' && b <= 'Z' || b >= 'a' && b <= 'z' || b >= '0' && b <= '9' || strings.IndexByte("-_.~", b) >= 0 {
			sb.WriteByte(b)
		} else {
			fmt.Fprintf(&sb, "%%%02X", b)
		}
	}
	return sb.String()
}

// VCardPayload builds a minimal vCard 3.0 contact.
func VCardPayload(name, phone, email, org string) (string, error) {
	if name == "" {
		return "", errors.New("vcard: name required")
	}
	esc := strings.NewReplacer(`\`, `\\`, "\n", `\n`, ",", `\,`, ";", `\;`).Replace
	lines := []string{"BEGIN:VCARD", "VERSION:3.0", "FN:" + esc(name)}
	if org != "" {
		lines = append(lines, "ORG:"+esc(org))
	}
	if phone != "" {
		lines = append(lines, "TEL:"+esc(phone))
	}
	if email != "" {
		lines = append(lines, "EMAIL:"+esc(email))
	}
	lines = append(lines, "END:VCARD")
	return strings.Join(lines, "\n"), nil
}

// ---- Structured append -----------------------------------------------

// EncodeStructured splits data over `parts` symbols (2..16) linked by a
// structured-append header; scanners that support it can reassemble them.
func EncodeStructured(data []byte, parts int, opt Options) ([]*Code, error) {
	if parts < 2 || parts > 16 {
		return nil, errors.New("structured append needs 2..16 parts")
	}
	if len(data) < parts {
		return nil, errors.New("fewer bytes than parts")
	}
	var parity byte
	for _, b := range data {
		parity ^= b
	}
	var out []*Code
	size := (len(data) + parts - 1) / parts
	for i := 0; i < parts; i++ {
		lo, hi := min(i*size, len(data)), min((i+1)*size, len(data))
		hdr := Segment{Mode: ModeStructured, Index: i, Total: parts, Parity: parity}
		lo2, hi2 := opt.MinVersion, opt.MaxVersion
		if lo2 == 0 {
			lo2 = 1
		}
		if hi2 == 0 {
			hi2 = 40
		}
		var code *Code
		for v := lo2; v <= hi2; v++ {
			segs := append([]Segment{hdr}, OptimalSegments(data[lo:hi], v)...)
			if b := totalBits(segs, v); b >= 0 && b <= DataCodewords(v, opt.ECC)*8 {
				c, err := EncodeSegments(segs, v, opt)
				if err != nil {
					return nil, err
				}
				code = c
				break
			}
		}
		if code == nil {
			return nil, ErrTooLong
		}
		out = append(out, code)
	}
	return out, nil
}

// Reassemble joins decoded structured-append symbols (any order) and checks
// completeness, duplicates and the parity byte.
func Reassemble(rs []*Result) ([]byte, error) {
	if len(rs) == 0 {
		return nil, errors.New("no symbols")
	}
	total := -1
	var parity byte
	got := map[int]*Result{}
	for _, r := range rs {
		if r.SA == nil {
			return nil, errors.New("symbol without a structured-append header")
		}
		if total >= 0 && (r.SA.Total != total || r.SA.Parity != parity) {
			return nil, errors.New("symbols belong to different sequences")
		}
		total, parity = r.SA.Total, r.SA.Parity
		if _, dup := got[r.SA.Index]; dup {
			return nil, fmt.Errorf("duplicate part %d", r.SA.Index+1)
		}
		got[r.SA.Index] = r
	}
	if len(got) != total {
		var missing []int
		for i := 0; i < total; i++ {
			if _, ok := got[i]; !ok {
				missing = append(missing, i+1)
			}
		}
		sort.Ints(missing)
		return nil, fmt.Errorf("missing part(s) %v of %d", missing, total)
	}
	var data []byte
	for i := 0; i < total; i++ {
		data = append(data, got[i].Bytes...)
	}
	var p byte
	for _, b := range data {
		p ^= b
	}
	if p != parity {
		return nil, errors.New("parity mismatch: parts are corrupted or from different sources")
	}
	return data, nil
}
