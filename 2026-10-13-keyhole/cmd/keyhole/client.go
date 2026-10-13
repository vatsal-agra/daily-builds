package main

import (
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"strings"
	"time"

	"keyhole/pki"
	"keyhole/tls13"
)

func cmdClient(args []string) error {
	fs := newFlags("client")
	addr := fs.String("connect", "127.0.0.1:8443", "host:port to connect to")
	sni := fs.String("servername", "", "server name for SNI and certificate checks (default: host part of -connect)")
	ca := fs.String("ca", "", "PEM CA bundle to trust (default: system roots)")
	insecure := fs.Bool("insecure", false, "skip certificate verification")
	alpn := fs.String("alpn", "", "comma-separated ALPN protocols to offer")
	keylog := fs.String("keylog", "", "append NSS key log lines here")
	trace := fs.Bool("trace", false, "print each handshake message")
	certF := fs.String("cert", "", "client certificate PEM (mutual TLS)")
	keyF := fs.String("key", "", "client private key PEM")
	suites := fs.String("suites", "", "restrict cipher suites")
	groups := fs.String("groups", "", "restrict key-exchange groups: x25519,p256")
	path := fs.String("path", "/", "request path")
	resume := fs.Int("resume", 0, "after the first connection, open this many more using session tickets")
	rawReq := fs.String("send", "", "send this text instead of an HTTP GET (e.g. for echo servers)")
	keyUpdate := fs.Bool("key-update", false, "perform a KeyUpdate (requesting the peer's too) before the request")
	if err := parse(fs, args); err != nil {
		return err
	}
	host, _, err := net.SplitHostPort(*addr)
	if err != nil {
		return fmt.Errorf("-connect: %v", err)
	}
	if *sni == "" {
		*sni = host
	}
	cfg := &tls13.Config{ServerName: *sni, InsecureSkipVerify: *insecure, NextProtos: splitList(*alpn), SessionCache: tls13.NewSessionCache()}
	if !*insecure {
		if cfg.RootCAs, err = loadRoots(*ca); err != nil {
			return err
		}
	}
	if cfg.CipherSuites, err = parseSuites(*suites); err != nil {
		return err
	}
	if cfg.Groups, err = parseGroups(*groups); err != nil {
		return err
	}
	if (*certF == "") != (*keyF == "") {
		return errors.New("-cert and -key go together")
	}
	if *certF != "" {
		if cfg.ClientCertificate, err = pki.LoadCertificate(*certF, *keyF); err != nil {
			return err
		}
	}
	w, closeLog, err := keyLogWriter(*keylog)
	if err != nil {
		return err
	}
	defer closeLog()
	cfg.KeyLogWriter = w
	if *trace {
		cfg.Trace = tracer(os.Stdout)
	}
	for i := 0; i <= *resume; i++ {
		if i > 0 {
			fmt.Printf("\n--- connection %d (resumption attempt) ---\n", i+1)
		}
		if err := oneClientConn(*addr, cfg, *path, *rawReq, *keyUpdate && i == 0); err != nil {
			return err
		}
	}
	return nil
}

func oneClientConn(addr string, cfg *tls13.Config, path, send string, keyUpdate bool) error {
	raw, err := net.DialTimeout("tcp", addr, 10*time.Second)
	if err != nil {
		return err
	}
	defer raw.Close()
	raw.SetDeadline(time.Now().Add(30 * time.Second))
	c := tls13.Client(raw, cfg)
	if err := c.Handshake(); err != nil {
		return fmt.Errorf("handshake: %w", err)
	}
	fmt.Print("handshake complete\n" + describeState(c.ConnectionState()))
	if keyUpdate {
		if err := c.KeyUpdate(true); err != nil {
			return err
		}
	}
	req := send
	if req == "" {
		req = fmt.Sprintf("GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n", path, cfg.ServerName)
	}
	if _, err := io.WriteString(c, req); err != nil {
		return err
	}
	if send != "" {
		c.CloseWrite()
	}
	body, err := io.ReadAll(c)
	if err != nil {
		return fmt.Errorf("reading response: %w", err)
	}
	fmt.Println("---")
	fmt.Print(strings.TrimRight(string(body), "\n"), "\n")
	return nil
}
