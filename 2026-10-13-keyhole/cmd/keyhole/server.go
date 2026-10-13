package main

import (
	"bufio"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"strings"
	"time"

	"keyhole/pki"
	"keyhole/tls13"
)

func cmdServer(args []string) error {
	fs := newFlags("server")
	listen := fs.String("listen", "127.0.0.1:8443", "address to listen on")
	cert := fs.String("cert", "", "PEM certificate chain (required)")
	key := fs.String("key", "", "PEM private key (required)")
	clientCA := fs.String("client-ca", "", "PEM CA bundle: request and verify client certificates")
	require := fs.Bool("require-client-cert", false, "with -client-ca: abort if the client sends no certificate")
	alpn := fs.String("alpn", "http/1.1", "comma-separated ALPN protocols")
	keylog := fs.String("keylog", "", "append NSS key log lines here (for Wireshark / keyhole inspect)")
	trace := fs.Bool("trace", false, "print each handshake message")
	mode := fs.String("mode", "http", "http (status page) or echo")
	suites := fs.String("suites", "", "restrict cipher suites, in preference order")
	groups := fs.String("groups", "", "restrict key-exchange groups: x25519,p256")
	noTickets := fs.Bool("no-tickets", false, "do not issue session tickets")
	if err := parse(fs, args); err != nil {
		return err
	}
	if *cert == "" || *key == "" {
		return errors.New("-cert and -key are required (create them with 'keyhole certgen')")
	}
	c, err := pki.LoadCertificate(*cert, *key)
	if err != nil {
		return err
	}
	cfg := &tls13.Config{Certificates: []tls13.Certificate{*c}, NextProtos: splitList(*alpn), NoTickets: *noTickets}
	if cfg.CipherSuites, err = parseSuites(*suites); err != nil {
		return err
	}
	if cfg.Groups, err = parseGroups(*groups); err != nil {
		return err
	}
	if *clientCA != "" {
		if cfg.ClientCAs, err = pki.LoadPool(*clientCA); err != nil {
			return err
		}
		cfg.ClientAuth = tls13.RequestClientCert
		if *require {
			cfg.ClientAuth = tls13.RequireClientCert
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
	l, err := net.Listen("tcp", *listen)
	if err != nil {
		return err
	}
	fmt.Printf("keyhole server listening on %s (%s mode)\n", l.Addr(), *mode)
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	go func() { <-sig; l.Close() }()
	for {
		raw, err := l.Accept()
		if err != nil {
			return nil
		}
		go serve(raw, cfg, *mode)
	}
}

func serve(raw net.Conn, cfg *tls13.Config, mode string) {
	defer raw.Close()
	raw.SetDeadline(time.Now().Add(30 * time.Second))
	c := tls13.Server(raw, cfg)
	if err := c.Handshake(); err != nil {
		fmt.Printf("%s: handshake failed: %v\n", raw.RemoteAddr(), err)
		return
	}
	st := c.ConnectionState()
	fmt.Printf("%s: %s %s %s resumed=%v\n", raw.RemoteAddr(), tls13.SuiteName(st.CipherSuite), tls13.GroupName(st.KeyShareGroup), st.ServerName, st.DidResume)
	if mode == "echo" {
		io.Copy(c, c)
		c.Close()
		return
	}
	br := bufio.NewReader(c)
	reqLine, err := br.ReadString('\n')
	if err != nil {
		return
	}
	for { // drain headers
		l, err := br.ReadString('\n')
		if err != nil || strings.TrimSpace(l) == "" {
			break
		}
	}
	body := "keyhole says hello over TLS 1.3\n\n" + describeState(st) + "  request         " + strings.TrimSpace(reqLine) + "\n"
	if len(st.PeerCertificates) > 0 {
		body += "  client cert     " + clientName(st.PeerCertificates) + "\n"
	}
	fmt.Fprintf(c, "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s", len(body), body)
	c.Close()
}

func clientName(cs []*x509.Certificate) string { return cs[0].Subject.String() }
