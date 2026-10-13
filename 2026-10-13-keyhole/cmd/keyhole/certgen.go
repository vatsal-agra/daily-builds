package main

import (
	"fmt"
	"net"
	"os"
	"path/filepath"

	"keyhole/pki"
)

func cmdCertgen(args []string) error {
	fs := newFlags("certgen")
	dir := fs.String("dir", "pki", "output directory")
	hosts := fs.String("host", "localhost,127.0.0.1", "comma-separated DNS names / IPs for the server certificate")
	kt := fs.String("key", "ecdsa-p256", "server key type: ecdsa-p256, ecdsa-p384, ed25519, rsa2048")
	if err := parse(fs, args); err != nil {
		return err
	}
	if err := os.MkdirAll(*dir, 0o755); err != nil {
		return err
	}
	ca, err := pki.NewCA("Keyhole Demo CA", "ecdsa-p256")
	if err != nil {
		return err
	}
	opts := pki.Options{CommonName: "keyhole server", KeyType: *kt}
	for _, h := range splitList(*hosts) {
		if ip := net.ParseIP(h); ip != nil {
			opts.IPs = append(opts.IPs, ip)
		} else {
			opts.DNSNames = append(opts.DNSNames, h)
		}
	}
	if len(opts.DNSNames)+len(opts.IPs) == 0 {
		return fmt.Errorf("-host needs at least one name")
	}
	srv, _, err := ca.Issue(opts)
	if err != nil {
		return err
	}
	cli, _, err := ca.Issue(pki.Options{CommonName: "keyhole client", KeyType: "ecdsa-p256", Client: true})
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(*dir, "ca.pem"), pki.EncodeCertPEM(ca.DER), 0o644); err != nil {
		return err
	}
	if err := pki.WriteFiles(filepath.Join(*dir, "server.pem"), filepath.Join(*dir, "server.key"), srv); err != nil {
		return err
	}
	if err := pki.WriteFiles(filepath.Join(*dir, "client.pem"), filepath.Join(*dir, "client.key"), cli); err != nil {
		return err
	}
	fmt.Printf("wrote %s/{ca.pem,server.pem,server.key,client.pem,client.key}\n", *dir)
	fmt.Printf("server certificate: %s key, valid for %v\n", *kt, splitList(*hosts))
	return nil
}
