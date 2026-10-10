package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"namewright/dns"
)

func algByName(s string) (uint8, bool) {
	switch strings.ToLower(s) {
	case "ed25519", "15":
		return dns.AlgED25519, true
	case "ecdsap256sha256", "ecdsap256", "ecdsa", "13":
		return dns.AlgECDSAP256SHA256, true
	}
	return 0, false
}

func cmdKeygen(args []string) int {
	fs := flag.NewFlagSet("keygen", flag.ContinueOnError)
	zone := fs.String("zone", "", "zone the key belongs to (required)")
	algS := fs.String("alg", "ed25519", "ed25519 or ecdsap256")
	ksk := fs.Bool("ksk", false, "create a key-signing key (SEP flag)")
	out := fs.String("out", ".", "output directory")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	alg, ok := algByName(*algS)
	if *zone == "" || !ok {
		fmt.Fprintln(os.Stderr, "usage: namewright keygen -zone example.com. [-alg ed25519|ecdsap256] [-ksk] [-out dir]")
		return 2
	}
	if err := dns.ValidName(dns.CanonName(*zone)); err != nil {
		return fail("%v", err)
	}
	k, err := dns.GenerateKey(*zone, alg, *ksk)
	if err != nil {
		return fail("%v", err)
	}
	base := filepath.Join(*out, fmt.Sprintf("K%s+%03d+%05d", k.Owner, alg, k.Tag()))
	if err := os.WriteFile(base+".key", []byte(k.RR(3600).String()+"\n"), 0o644); err != nil {
		return fail("%v", err)
	}
	pem, err := k.MarshalPrivate()
	if err != nil {
		return fail("%v", err)
	}
	if err := os.WriteFile(base+".private", pem, 0o600); err != nil {
		return fail("%v", err)
	}
	fmt.Println(base)
	if *ksk {
		ds, _ := k.DS(dns.DigestSHA256)
		fmt.Printf("DS record for the parent zone:\n%s\t3600\tIN\tDS\t%s\n", k.Owner, ds)
	}
	return 0
}

func loadKey(base, owner string) (*dns.Key, error) {
	pubTxt, err := os.ReadFile(base + ".key")
	if err != nil {
		return nil, err
	}
	rrs, err := dns.ParseZone(string(pubTxt), owner, base+".key")
	if err != nil || len(rrs) != 1 || rrs[0].Type != dns.TypeDNSKEY {
		return nil, fmt.Errorf("%s.key must hold exactly one DNSKEY record (%v)", base, err)
	}
	pem, err := os.ReadFile(base + ".private")
	if err != nil {
		return nil, err
	}
	return dns.ParsePrivateKey(owner, rrs[0].Data.(dns.DNSKEY), pem)
}

func cmdSign(args []string) int {
	fs := flag.NewFlagSet("sign", flag.ContinueOnError)
	origin := fs.String("origin", "", "zone origin (required)")
	kskB := fs.String("ksk", "", "KSK path without .key/.private (required)")
	zskB := fs.String("zsk", "", "ZSK path (optional; KSK signs everything if omitted)")
	days := fs.Int("days", 30, "signature validity in days")
	out := fs.String("o", "", "output file (default: stdout)")
	if err := fs.Parse(args); err != nil || fs.NArg() != 1 || *origin == "" || *kskB == "" {
		fmt.Fprintln(os.Stderr, "usage: namewright sign -origin example.com. -ksk Kexample.com.+015+12345 [-zsk ...] [-days 30] [-o signed.zone] unsigned.zone")
		return 2
	}
	src, err := os.ReadFile(fs.Arg(0))
	if err != nil {
		return fail("%v", err)
	}
	rrs, err := dns.ParseZone(string(src), *origin, fs.Arg(0))
	if err != nil {
		return fail("%v", err)
	}
	ksk, err := loadKey(*kskB, *origin)
	if err != nil {
		return fail("KSK: %v", err)
	}
	var zsk *dns.Key
	if *zskB != "" {
		if zsk, err = loadKey(*zskB, *origin); err != nil {
			return fail("ZSK: %v", err)
		}
	}
	now := time.Now()
	signed, err := dns.SignZone(*origin, rrs, dns.SignOptions{KSK: ksk, ZSK: zsk,
		Inception: now.Add(-time.Hour), Expiration: now.Add(time.Duration(*days) * 24 * time.Hour)})
	if err != nil {
		return fail("%v", err)
	}
	z, err := dns.NewZone(*origin, signed)
	if err != nil {
		return fail("%v", err)
	}
	if errs := dns.VerifyZone(z, now); len(errs) > 0 {
		for _, e := range errs {
			fmt.Fprintln(os.Stderr, "self-check:", e)
		}
		return fail("signed zone failed its own verification")
	}
	text := z.String()
	if *out == "" {
		fmt.Print(text)
	} else if err := os.WriteFile(*out, []byte(text), 0o644); err != nil {
		return fail("%v", err)
	} else {
		fmt.Fprintf(os.Stderr, "signed %s: %d records, keys %d (KSK)%s, valid %d days\n", z.Origin, len(z.Records()), ksk.Tag(),
			map[bool]string{true: fmt.Sprintf(" + %d (ZSK)", func() uint16 { return zsk.Tag() }()), false: ""}[zsk != nil], *days)
	}
	return 0
}

func cmdVerify(args []string) int {
	fs := flag.NewFlagSet("verify", flag.ContinueOnError)
	origin := fs.String("origin", "", "zone origin (required)")
	if err := fs.Parse(args); err != nil || fs.NArg() != 1 || *origin == "" {
		fmt.Fprintln(os.Stderr, "usage: namewright verify -origin example.com. signed.zone")
		return 2
	}
	src, err := os.ReadFile(fs.Arg(0))
	if err != nil {
		return fail("%v", err)
	}
	z, err := dns.LoadZone(string(src), *origin, fs.Arg(0))
	if err != nil {
		return fail("%v", err)
	}
	errs := dns.VerifyZone(z, time.Now())
	for _, e := range errs {
		fmt.Println("FAIL:", e)
	}
	if len(errs) > 0 {
		return 1
	}
	fmt.Printf("zone %s verifies: every RRset is signed by a DNSKEY in the zone and the NSEC chain is complete\n", z.Origin)
	return 0
}

// loadAnchor reads DNSKEY and/or DS records (zone-file syntax) naming the root's trust anchors.
func loadAnchor(r *dns.Resolver, path string) error {
	if path == "" {
		return fmt.Errorf("-validate needs -anchor <file with the root DNSKEY or DS record>")
	}
	src, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	rrs, err := dns.ParseZone(string(src), ".", path)
	if err != nil {
		return err
	}
	for _, rr := range rrs {
		switch d := rr.Data.(type) {
		case dns.DNSKEY:
			r.AnchorKeys = append(r.AnchorKeys, d)
		case dns.DS:
			r.TrustAnchors = append(r.TrustAnchors, d)
		}
	}
	if len(r.AnchorKeys)+len(r.TrustAnchors) == 0 {
		return fmt.Errorf("%s contains no DNSKEY or DS records", path)
	}
	r.Validate = true
	return nil
}
