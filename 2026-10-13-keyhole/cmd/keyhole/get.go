package main

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"strings"
	"time"

	"keyhole/tls13"
)

func cmdGet(args []string) error {
	fs := newFlags("get")
	ca := fs.String("ca", "", "PEM CA bundle to trust (default: system roots)")
	insecure := fs.Bool("insecure", false, "skip certificate verification")
	showHdr := fs.Bool("i", false, "include response headers in the output")
	trace := fs.Bool("trace", false, "print each handshake message")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 1 {
		return errors.New("usage: keyhole get [flags] https://host[:port]/path")
	}
	u, err := url.Parse(fs.Arg(0))
	if err != nil || u.Scheme != "https" || u.Hostname() == "" {
		return fmt.Errorf("%q is not an https:// URL", fs.Arg(0))
	}
	port := u.Port()
	if port == "" {
		port = "443"
	}
	cfg := &tls13.Config{ServerName: u.Hostname(), InsecureSkipVerify: *insecure}
	if !*insecure {
		if cfg.RootCAs, err = loadRoots(*ca); err != nil {
			return err
		}
	}
	if *trace {
		cfg.Trace = tracer(os.Stderr)
	}
	raw, err := net.DialTimeout("tcp", net.JoinHostPort(u.Hostname(), port), 10*time.Second)
	if err != nil {
		return err
	}
	defer raw.Close()
	raw.SetDeadline(time.Now().Add(30 * time.Second))
	c := tls13.Client(raw, cfg)
	if err := c.Handshake(); err != nil {
		return fmt.Errorf("TLS handshake: %w", err)
	}
	p := u.RequestURI()
	fmt.Fprintf(c, "GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: keyhole\r\nConnection: close\r\nAccept: */*\r\n\r\n", p, u.Host)
	br := bufio.NewReader(c)
	inHeader := true
	for {
		line, err := br.ReadString('\n')
		if inHeader {
			if *showHdr {
				fmt.Print(line)
			}
			if strings.TrimSpace(line) == "" {
				inHeader = false
			}
		} else {
			fmt.Print(line)
		}
		if err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}
	}
}
