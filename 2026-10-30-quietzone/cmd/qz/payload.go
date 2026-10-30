package main

import (
	"flag"
	"fmt"
	"path/filepath"
	"strings"

	"quietzone/qr"
)

func cmdPayload(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: qz payload wifi|mailto|vcard [options]   (pipe into: qz encode -o out.png -)")
	}
	kind, rest := args[0], args[1:]
	fs := flag.NewFlagSet("payload "+kind, flag.ContinueOnError)
	ssid := fs.String("ssid", "", "wifi: network name")
	pass := fs.String("pass", "", "wifi: password")
	auth := fs.String("auth", "WPA", "wifi: WPA, WEP or nopass")
	hidden := fs.Bool("hidden", false, "wifi: hidden network")
	to := fs.String("to", "", "mailto: recipient")
	subj := fs.String("subject", "", "mailto: subject")
	body := fs.String("body", "", "mailto: body")
	name := fs.String("name", "", "vcard: full name")
	phone := fs.String("phone", "", "vcard: phone")
	email := fs.String("email", "", "vcard: e-mail")
	org := fs.String("org", "", "vcard: organisation")
	if err := fs.Parse(rest); err != nil {
		return err
	}
	var s string
	var err error
	switch kind {
	case "wifi":
		s, err = qr.WiFiPayload(*ssid, *pass, *auth, *hidden)
	case "mailto":
		s, err = qr.MailtoPayload(*to, *subj, *body)
	case "vcard":
		s, err = qr.VCardPayload(*name, *phone, *email, *org)
	default:
		return fmt.Errorf("unknown payload type %q (wifi, mailto, vcard)", kind)
	}
	if err != nil {
		return err
	}
	fmt.Println(s)
	return nil
}

// partName inserts -N before the extension: out.png -> out-1.png.
func partName(path string, i int) string {
	ext := filepath.Ext(path)
	return fmt.Sprintf("%s-%d%s", strings.TrimSuffix(path, ext), i, ext)
}
