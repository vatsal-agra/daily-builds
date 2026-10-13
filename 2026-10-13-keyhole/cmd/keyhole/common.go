package main

import (
	"crypto/x509"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"keyhole/pki"
	"keyhole/tls13"
)

var useColor = func() bool {
	st, err := os.Stderr.Stat()
	return err == nil && st.Mode()&os.ModeCharDevice != 0 && os.Getenv("NO_COLOR") == ""
}()

func paint(code, s string) string {
	if !useColor {
		return s
	}
	return "\033[" + code + "m" + s + "\033[0m"
}

// tracer prints handshake events as they happen.
func tracer(w io.Writer) func(tls13.TraceEvent) {
	t0 := time.Now()
	return func(e tls13.TraceEvent) {
		if e.Kind == "record" {
			return
		}
		arrow := " "
		switch e.Dir {
		case "send":
			arrow = paint("36", "→")
		case "recv":
			arrow = paint("35", "←")
		}
		line := fmt.Sprintf("%6.1fms %s %-8s %s", float64(e.At.Sub(t0).Microseconds())/1000, arrow, e.Kind, paint("1", e.Name))
		if e.Detail != "" {
			line += "  " + e.Detail
		}
		fmt.Fprintln(w, line)
	}
}

func keyLogWriter(path string) (io.Writer, func(), error) {
	if path == "" {
		return nil, func() {}, nil
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, nil, err
	}
	return f, func() { f.Close() }, nil
}

func parseSuites(s string) ([]uint16, error) {
	var out []uint16
	for _, n := range splitList(s) {
		found := false
		for _, id := range []uint16{tls13.TLS_AES_128_GCM_SHA256, tls13.TLS_AES_256_GCM_SHA384, tls13.TLS_CHACHA20_POLY1305_SHA256} {
			full := tls13.SuiteName(id)
			if strings.EqualFold(n, full) || strings.EqualFold("TLS_"+n, full) {
				out = append(out, id)
				found = true
			}
		}
		if !found {
			return nil, fmt.Errorf("unknown cipher suite %q (try AES_128_GCM_SHA256, AES_256_GCM_SHA384, CHACHA20_POLY1305_SHA256)", n)
		}
	}
	return out, nil
}

func parseGroups(s string) ([]uint16, error) {
	var out []uint16
	for _, n := range splitList(s) {
		switch strings.ToLower(n) {
		case "x25519":
			out = append(out, tls13.X25519)
		case "p256", "secp256r1", "p-256":
			out = append(out, tls13.CurveP256)
		default:
			return nil, fmt.Errorf("unknown group %q (x25519, p256)", n)
		}
	}
	return out, nil
}

func describeState(st tls13.ConnectionState) string {
	var b strings.Builder
	fmt.Fprintf(&b, "  version         TLS 1.3\n")
	fmt.Fprintf(&b, "  cipher suite    %s\n", tls13.SuiteName(st.CipherSuite))
	fmt.Fprintf(&b, "  key exchange    %s%s\n", tls13.GroupName(st.KeyShareGroup), map[bool]string{true: "  (after HelloRetryRequest)"}[st.HelloRetryRequest])
	if st.DidResume {
		fmt.Fprintf(&b, "  session         resumed with PSK (no certificate exchanged)\n")
	} else {
		fmt.Fprintf(&b, "  session         full handshake, %s\n", tls13.SigAlgName(st.SignatureAlgorithm))
	}
	if st.ServerName != "" {
		fmt.Fprintf(&b, "  server name     %s\n", st.ServerName)
	}
	if st.NegotiatedProtocol != "" {
		fmt.Fprintf(&b, "  ALPN            %s\n", st.NegotiatedProtocol)
	}
	for i, c := range st.PeerCertificates {
		fmt.Fprintf(&b, "  peer cert %d     %s  (issuer %s, expires %s)\n", i, c.Subject, c.Issuer, c.NotAfter.Format("2006-01-02"))
	}
	return b.String()
}

// loadRoots reads a PEM bundle, or returns the system pool when path is empty.
func loadRoots(path string) (*x509.CertPool, error) {
	if path == "" {
		return x509.SystemCertPool()
	}
	return pki.LoadPool(path)
}

func newFlags(name string) *flag.FlagSet {
	fs := flag.NewFlagSet("keyhole "+name, flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	return fs
}

func parse(fs *flag.FlagSet, args []string) error {
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			os.Exit(0)
		}
		return err
	}
	if fs.NArg() > 0 && fs.Name() != "keyhole get" {
		return fmt.Errorf("unexpected argument %q", fs.Arg(0))
	}
	return nil
}
