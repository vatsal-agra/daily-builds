package main

import (
	"fmt"
	"io"
)

func cmdPushFold(a []string, o io.Writer) error { return fmt.Errorf("pushfold: coming in phase 4") }
func cmdReport(a []string, o io.Writer) error   { return fmt.Errorf("report: coming in phase 4") }
