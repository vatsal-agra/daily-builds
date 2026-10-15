// Command dotmatrix is a Game Boy emulator, SM83 assembler and disassembler.
package main

import (
	"fmt"
	"os"
)

const usage = `dotmatrix — Game Boy emulator, assembler and disassembler

usage:
  dotmatrix asm   <file.s> [-o out.gb] [-sym out.sym]   assemble SM83 source into a ROM
  dotmatrix dis   <file.gb> [-from ADDR] [-len N]        disassemble ROM bytes
  dotmatrix info  <file.gb|file.s>                       print and validate the cartridge header
  dotmatrix run   <file.gb|file.s> [flags]               run headless
        -frames N        frames to run (default 60)
        -png FILE        write the final frame as PNG   -scale N  (default 3)
        -ascii           print the final frame as text
        -serial          print bytes sent over the link port
        -keys SPEC       scripted input, e.g. "10:start,12:-start,30:right" (frame:[-]button)
        -save FILE       battery RAM save file (loaded if present, written at exit)
        -until-serial S  stop early once the serial output contains S
  dotmatrix trace <file.gb|file.s> [-n N] [-from ADDR]   print an instruction trace
  dotmatrix test  <file.gb|file.s> [-frames N]           run a self-checking ROM; exit 0 on PASS

buttons: right left up down a b select start
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "asm":
		err = cmdAsm(os.Args[2:])
	case "dis":
		err = cmdDis(os.Args[2:])
	case "info":
		err = cmdInfo(os.Args[2:])
	case "run":
		err = cmdRun(os.Args[2:])
	case "trace":
		err = cmdTrace(os.Args[2:])
	case "test":
		err = cmdTest(os.Args[2:])
	case "-h", "--help", "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s", os.Args[1], usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
