package main

import (
	"errors"

	"namewright/dns"
)

func cmdSign(args []string) int                     { return fail("not yet") }
func cmdKeygen(args []string) int                   { return fail("not yet") }
func loadAnchor(r *dns.Resolver, path string) error { return errors.New("not yet") }
