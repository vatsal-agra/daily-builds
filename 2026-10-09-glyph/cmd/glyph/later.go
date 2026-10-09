package main

import "errors"

var errLater = errors.New("not built yet")

func cmdSDF(a []string) error      { return errLater }
func cmdSubset(a []string) error   { return errLater }
func cmdLCD(a []string) error      { return errLater }
func cmdSpecimen(a []string) error { return errLater }
