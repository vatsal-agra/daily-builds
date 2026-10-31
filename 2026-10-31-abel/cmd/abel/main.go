// Command abel is a REPL / one-shot front end to the cas package.
package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"strings"

	"abel/cas"
)

func main() {
	expr := flag.String("e", "", "evaluate one expression and exit")
	file := flag.String("f", "", "run a script file (one command per line, # comments)")
	flag.Parse()
	sess := cas.NewSession()

	run := func(line string, echo bool) bool {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			return true
		}
		if echo {
			fmt.Println(">>> " + line)
		}
		out, err := sess.Eval(line)
		if err != nil {
			fmt.Println("error: " + err.Error())
			return false
		}
		for _, l := range out {
			fmt.Println(l)
		}
		return true
	}

	switch {
	case *expr != "":
		if !run(*expr, false) {
			os.Exit(1)
		}
	case *file != "":
		f, err := os.Open(*file)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		defer f.Close()
		failed := 0
		sc := bufio.NewScanner(f)
		for sc.Scan() {
			if !run(sc.Text(), true) {
				failed++
			}
			if strings.TrimSpace(sc.Text()) != "" && !strings.HasPrefix(strings.TrimSpace(sc.Text()), "#") {
				fmt.Println()
			}
		}
		if failed > 0 {
			os.Exit(1)
		}
	default:
		fmt.Println("Abel — exact computer algebra. Type help for commands, quit to leave.")
		sc := bufio.NewScanner(os.Stdin)
		for {
			fmt.Print("abel> ")
			if !sc.Scan() {
				fmt.Println()
				return
			}
			line := strings.TrimSpace(sc.Text())
			if line == "quit" || line == "exit" {
				return
			}
			run(line, false)
		}
	}
}
