package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"sable"
)

func cmdReport(args []string) error {
	fs := flag.NewFlagSet("report", flag.ContinueOnError)
	var c common
	c.register(fs)
	outPath := fs.String("o", "", "output file (default: <input>.html)")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	name, src, err := readSource(fs)
	if err != nil {
		return err
	}
	cfg, err := c.config()
	if err != nil {
		return err
	}
	page, err := sable.Report(filepath.Base(name), src, cfg)
	if err != nil {
		return showError(name, src, err)
	}
	out := *outPath
	if out == "" {
		if name == "<stdin>" {
			out = "report.html"
		} else {
			out = strings.TrimSuffix(name, filepath.Ext(name)) + ".html"
		}
	}
	if err := os.WriteFile(out, []byte(page), 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%d KB)\n", out, len(page)/1024)
	return nil
}
