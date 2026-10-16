package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"dominion/report"
)

func cmdReport(args []string) {
	var lvl, regs int
	var outPath string
	_, file := parseFlags("report", args, func(fs *flag.FlagSet) {
		fs.IntVar(&lvl, "O", 2, "optimisation level 0-3")
		fs.IntVar(&regs, "regs", 12, "allocatable registers for the benchmark/asm panels")
		fs.StringVar(&outPath, "o", "", "output HTML file (default: <input>.report.html)")
	})
	if strings.HasSuffix(file, ".ir") {
		die("report: needs Dom source (.dom); the report replays the compilation from source")
	}
	src, err := os.ReadFile(file)
	if err != nil {
		die("%v", err)
	}
	out, err := report.Build(filepath.Base(file), string(src), lvl, regs)
	if err != nil {
		diagnose(file, string(src), err)
	}
	if outPath == "" {
		outPath = strings.TrimSuffix(file, filepath.Ext(file)) + ".report.html"
	}
	if err := os.WriteFile(outPath, []byte(out), 0o644); err != nil {
		die("%v", err)
	}
	fmt.Printf("wrote %s (%d KiB)\n", outPath, len(out)/1024)
}
