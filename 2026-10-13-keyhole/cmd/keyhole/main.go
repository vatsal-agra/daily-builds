// Command keyhole is a TLS 1.3 swiss-army knife built on the from-scratch tls13 package:
// a server, a client, an HTTPS GET, a certificate generator and a decrypting TLS inspector.
package main

import (
	"fmt"
	"os"
	"strings"
)

const usage = `keyhole — TLS 1.3 from scratch

usage: keyhole <command> [flags]

commands:
  certgen   create a test CA plus server and client certificates
  server    TLS 1.3 server (HTTP status page or echo)
  client    connect, print the negotiated parameters, send a request
  get       fetch an https:// URL
  inspect   decrypting man-in-the-middle-free TLS inspector (proxy + key log)
  version

Run 'keyhole <command> -h' for flags.
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	var err error
	switch cmd {
	case "certgen":
		err = cmdCertgen(args)
	case "server":
		err = cmdServer(args)
	case "client":
		err = cmdClient(args)
	case "get":
		err = cmdGet(args)
	case "inspect":
		err = cmdInspect(args)
	case "version", "-v", "--version":
		fmt.Println("keyhole 1.0 (TLS 1.3, RFC 8446)")
	case "help", "-h", "--help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "keyhole: unknown command %q\n\n%s", cmd, usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "keyhole %s: %v\n", cmd, err)
		os.Exit(1)
	}
}

// splitList parses "a,b,c" flags, ignoring blanks.
func splitList(s string) []string {
	var out []string
	for _, p := range strings.Split(s, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}
