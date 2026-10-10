// Command namewright is a DNS toolbox: authoritative server, recursive
// resolver, dig-like client, zone checker, AXFR client and DNSSEC signer.
package main

import (
	"fmt"
	"os"
)

const usage = `namewright — a from-scratch DNS stack

usage: namewright <command> [flags] [args]

commands:
  serve     run an authoritative (and optionally recursive) server
  dig       query a server, dig-style:   dig @127.0.0.1:5353 www.example.com A
  resolve   iterative resolution with trace through the built-in mini internet
  testnet   start the mini internet plus a recursive front end on loopback
  check     validate a zone file
  axfr      pull a whole zone over TCP
  sign      DNSSEC-sign a zone file
  keygen    generate a DNSSEC key pair
  version   print version

run 'namewright <command> -h' for flags.`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, usage)
		os.Exit(2)
	}
	cmds := map[string]func([]string) int{
		"serve": cmdServe, "dig": cmdDig, "resolve": cmdResolve, "testnet": cmdTestnet,
		"check": cmdCheck, "axfr": cmdAXFR, "sign": cmdSign, "keygen": cmdKeygen,
		"version": func([]string) int { fmt.Println("namewright 1.0"); return 0 },
	}
	if os.Args[1] == "-h" || os.Args[1] == "--help" || os.Args[1] == "help" {
		fmt.Println(usage)
		return
	}
	f, ok := cmds[os.Args[1]]
	if !ok {
		fmt.Fprintf(os.Stderr, "namewright: unknown command %q\n\n%s\n", os.Args[1], usage)
		os.Exit(2)
	}
	os.Exit(f(os.Args[2:]))
}
