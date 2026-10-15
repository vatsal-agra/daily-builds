//go:build js && wasm

// Command wasm exposes the emulator core and assembler to the browser as
// window.dotmatrix. It is built with GOOS=js GOARCH=wasm (see web/build.sh).
package main

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"syscall/js"

	"dotmatrix/asm"
	"dotmatrix/gb"
	"dotmatrix/roms"
)

var (
	machine *gb.GB
	symbols map[string]int
	rgba    = make([]byte, gb.ScreenW*gb.ScreenH*4)
)

func jsonResult(v any) any {
	b, _ := json.Marshal(v)
	return string(b)
}

func fail(err error) any { return jsonResult(map[string]any{"ok": false, "error": err.Error()}) }

func start(rom []byte, syms map[string]int) any {
	cart, err := gb.NewCart(rom)
	if err != nil {
		return fail(err)
	}
	machine = gb.New(cart)
	machine.Dbg = gb.NewDebugger()
	symbols = syms
	h := cart.Info
	return jsonResult(map[string]any{"ok": true, "title": h.Title, "type": h.TypeName, "size": len(rom), "headerOK": h.HeaderOK})
}

func main() {
	api := map[string]any{}

	// examples() -> JSON list of example file names
	api["examples"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		ents, _ := roms.FS.ReadDir(".")
		var names []string
		for _, e := range ents {
			if strings.HasSuffix(e.Name(), ".asm") {
				names = append(names, e.Name())
			}
		}
		sort.Strings(names)
		return jsonResult(names)
	})

	// exampleSource(name) -> source text ("" if unknown)
	api["exampleSource"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		b, err := roms.FS.ReadFile(args[0].String())
		if err != nil {
			return ""
		}
		return string(b)
	})

	// assemble(source) -> JSON {ok, error, size, ...}; on success the ROM is loaded and running
	api["assemble"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		res, err := asm.Assemble("editor.s", args[0].String(), asm.Options{
			Include: func(p string) (string, error) {
				b, err := roms.FS.ReadFile(p)
				return string(b), err
			},
		})
		if err != nil {
			var list asm.ErrorList
			out := map[string]any{"ok": false, "error": err.Error()}
			if l, ok := err.(asm.ErrorList); ok {
				list = l
				var lines []int
				for _, e := range list {
					lines = append(lines, e.Loc.Line)
				}
				out["lines"] = lines
			}
			return jsonResult(out)
		}
		return start(res.ROM, res.Symbols)
	})

	// loadROM(Uint8Array) -> JSON
	api["loadROM"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		buf := make([]byte, args[0].Get("length").Int())
		js.CopyBytesToGo(buf, args[0])
		return start(buf, nil)
	})

	// frame(Uint8ClampedArray) runs one frame, copies RGBA into the array. Returns "" or an error message.
	api["frame"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if machine == nil {
			return "no ROM loaded"
		}
		msg := ""
		if err := machine.RunFrame(); err != nil {
			msg = err.Error()
		}
		machine.FrameRGBA(rgba)
		if len(args) > 0 {
			js.CopyBytesToJS(args[0], rgba)
		}
		return msg
	})

	api["setButton"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if machine != nil {
			machine.SetButton(args[0].Int(), args[1].Bool())
		}
		return nil
	})

	// audio() -> Uint8Array of interleaved little-endian int16 stereo samples since the last call
	api["audio"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if machine == nil {
			return js.Global().Get("Uint8Array").New(0)
		}
		s := machine.APU.Drain()
		b := make([]byte, len(s)*2)
		for i, v := range s {
			b[2*i], b[2*i+1] = byte(v), byte(uint16(v)>>8)
		}
		out := js.Global().Get("Uint8Array").New(len(b))
		js.CopyBytesToJS(out, b)
		return out
	})

	// state() -> JSON snapshot for the debugger panel
	api["state"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if machine == nil {
			return jsonResult(nil)
		}
		r := machine.Regs()
		st := machine.APU.Status()
		return jsonResult(map[string]any{
			"a": r.A, "f": r.F, "b": r.B, "c": r.C, "d": r.D, "e": r.E, "h": r.H, "l": r.L,
			"sp": r.SP, "pc": r.PC, "ime": r.IME, "halted": r.Halted,
			"ly": machine.Peek(0xFF44), "lcdc": machine.Peek(0xFF40), "stat": machine.Peek(0xFF41),
			"if": machine.Peek(0xFF0F), "ie": machine.Peek(0xFFFF),
			"frames": machine.Frames, "cycles": machine.Cycles, "audio": st,
			"serial": string(machine.Serial),
		})
	})

	// disasm(addr, n) -> JSON [{addr,text,bytes,label}]
	api["disasm"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if machine == nil {
			return jsonResult([]any{})
		}
		byAddr := map[int]string{}
		for n, a := range symbols {
			if _, dup := byAddr[a]; !dup || len(n) < len(byAddr[a]) {
				byAddr[a] = n
			}
		}
		a, n := uint16(args[0].Int()), args[1].Int()
		var out []map[string]any
		for i := 0; i < n; i++ {
			txt, ln := asm.Disassemble(machine.Peek, a)
			var raw []string
			for k := 0; k < ln; k++ {
				raw = append(raw, fmt.Sprintf("%02X", machine.Peek(a+uint16(k))))
			}
			out = append(out, map[string]any{"addr": a, "text": txt, "bytes": strings.Join(raw, " "), "label": byAddr[int(a)]})
			a += uint16(ln)
		}
		return jsonResult(out)
	})

	// peek(addr, len) -> Uint8Array
	api["peek"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		n := args[1].Int()
		b := make([]byte, n)
		if machine != nil {
			for i := range b {
				b[i] = machine.Peek(uint16(args[0].Int() + i))
			}
		}
		out := js.Global().Get("Uint8Array").New(n)
		js.CopyBytesToJS(out, b)
		return out
	})

	// step() executes one instruction; returns "" or a message
	api["step"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if machine == nil {
			return "no ROM loaded"
		}
		machine.Dbg.ResumeFromStop()
		if err := machine.StepChecked(); err != nil {
			return err.Error()
		}
		machine.FrameRGBA(rgba)
		if len(args) > 0 {
			js.CopyBytesToJS(args[0], rgba)
		}
		return ""
	})

	api["setBreakpoints"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if machine == nil {
			return nil
		}
		for _, b := range append([]*gb.Breakpoint(nil), machine.Dbg.Breaks...) {
			machine.Dbg.Delete(b.ID)
		}
		var addrs []int
		json.Unmarshal([]byte(args[0].String()), &addrs)
		for _, a := range addrs {
			machine.Dbg.AddBreak(uint16(a), nil)
		}
		return nil
	})

	// resolve(name) -> address or -1
	api["resolve"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if a, ok := symbols[args[0].String()]; ok {
			return a
		}
		return -1
	})

	api["saveState"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if machine == nil {
			return js.Global().Get("Uint8Array").New(0)
		}
		b := machine.SaveState()
		out := js.Global().Get("Uint8Array").New(len(b))
		js.CopyBytesToJS(out, b)
		return out
	})

	api["loadState"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if machine == nil {
			return "no ROM loaded"
		}
		buf := make([]byte, args[0].Get("length").Int())
		js.CopyBytesToGo(buf, args[0])
		if err := machine.LoadState(buf); err != nil {
			return err.Error()
		}
		return ""
	})

	api["reset"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		if machine != nil {
			cart, err := gb.NewCart(machine.Cart.ROM)
			if err == nil {
				d := machine.Dbg
				machine = gb.New(cart)
				machine.Dbg = d
			}
		}
		return nil
	})

	// vram() -> Uint8Array(8192) plus palette byte for the tile viewer
	api["vram"] = js.FuncOf(func(this js.Value, args []js.Value) any {
		b := make([]byte, 0x2000)
		if machine != nil {
			for i := range b {
				b[i] = machine.Peek(uint16(0x8000 + i))
			}
		}
		out := js.Global().Get("Uint8Array").New(len(b))
		js.CopyBytesToJS(out, b)
		return out
	})

	obj := js.Global().Get("Object").New()
	for k, v := range api {
		obj.Set(k, v)
	}
	js.Global().Set("dotmatrix", obj)
	js.Global().Get("document").Call("dispatchEvent", js.Global().Get("CustomEvent").New("dotmatrix-ready"))
	select {}
}
