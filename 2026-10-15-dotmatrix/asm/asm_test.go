package asm

import (
	"bytes"
	"fmt"
	"strings"
	"testing"
)

func mustAsm(t *testing.T, src string) *Result {
	t.Helper()
	r, err := Assemble("t.s", src, Options{NoHeader: true})
	if err != nil {
		t.Fatalf("assemble failed: %v\n%s", err, src)
	}
	return r
}

func TestBasicEncodings(t *testing.T) {
	cases := []struct {
		src  string
		want []byte
	}{
		{"nop", []byte{0}},
		{"ld a, 5", []byte{0x3E, 5}},
		{"ld b, c", []byte{0x41}},
		{"ld [hl], 0x12", []byte{0x36, 0x12}},
		{"ld hl, 0x1234", []byte{0x21, 0x34, 0x12}},
		{"ld [hl+], a", []byte{0x22}},
		{"ld [hli], a", []byte{0x22}},
		{"ld a, [hld]", []byte{0x3A}},
		{"ldi a, [hl]", []byte{0x2A}},
		{"ldh [$FF40], a", []byte{0xE0, 0x40}},
		{"ldh a, [0x44]", []byte{0xF0, 0x44}},
		{"ld [$C000], a", []byte{0xEA, 0x00, 0xC0}},
		{"ld a, [$C000]", []byte{0xFA, 0x00, 0xC0}},
		{"ld [$C000], sp", []byte{0x08, 0x00, 0xC0}},
		{"add a, b", []byte{0x80}},
		{"add b", []byte{0x80}},
		{"sub a, b", []byte{0x90}},
		{"sub b", []byte{0x90}},
		{"cp 7", []byte{0xFE, 7}},
		{"xor a", []byte{0xAF}},
		{"add sp, -2", []byte{0xE8, 0xFE}},
		{"ld hl, sp+4", []byte{0xF8, 4}},
		{"ld hl, sp-1", []byte{0xF8, 0xFF}},
		{"add hl, bc", []byte{0x09}},
		{"jp hl", []byte{0xE9}},
		{"jp nz, $1234", []byte{0xC2, 0x34, 0x12}},
		{"jp c, $1234", []byte{0xDA, 0x34, 0x12}},
		{"ret c", []byte{0xD8}},
		{"call $0150", []byte{0xCD, 0x50, 0x01}},
		{"rst $38", []byte{0xFF}},
		{"rst 8", []byte{0xCF}},
		{"bit 7, h", []byte{0xCB, 0x7C}},
		{"set 0, [hl]", []byte{0xCB, 0xC6}},
		{"res 3, a", []byte{0xCB, 0x9F}},
		{"swap a", []byte{0xCB, 0x37}},
		{"srl b", []byte{0xCB, 0x38}},
		{"stop", []byte{0x10, 0x00}},
		{"ld a, [c]", []byte{0xF2}},
		{"ld [c], a", []byte{0xE2}},
		{"ld sp, hl", []byte{0xF9}},
		{"push af", []byte{0xF5}},
		{"pop bc", []byte{0xC1}},
		{"LD A, 'x'", []byte{0x3E, 'x'}},
		{"ld a, high($1234)", []byte{0x3E, 0x12}},
		{"ld a, 1 << 3 | 1", []byte{0x3E, 9}},
		{"ld a, (2 + 3) * 4", []byte{0x3E, 20}},
		{"ld a, %1010", []byte{0x3E, 10}},
		{"ld a, 0ffh", []byte{0x3E, 0xFF}},
		{"ld a, -1", []byte{0x3E, 0xFF}},
	}
	for _, c := range cases {
		r := mustAsm(t, c.src)
		got := bytes.TrimRight(r.ROM, "\x00")
		if len(c.want) > 0 && c.want[len(c.want)-1] == 0 {
			got = r.ROM[:len(c.want)]
		}
		if !bytes.Equal(got, c.want) {
			t.Errorf("%q: got % X want % X", c.src, got, c.want)
		}
	}
}

func TestLabelsAndJR(t *testing.T) {
	r := mustAsm(t, `
start:
	ld a, 3
.loop:
	dec a
	jr nz, .loop
	jr start
	jp end
end:
	nop
`)
	want := []byte{0x3E, 3, 0x3D, 0x20, 0xFD, 0x18, 0xF9, 0xC3, 0x0A, 0x00, 0x00}
	if !bytes.Equal(r.ROM[:len(want)], want) {
		t.Errorf("got % X want % X", r.ROM[:len(want)], want)
	}
	if r.Symbols["start.loop"] != 2 || r.Symbols["end"] != 10 {
		t.Errorf("symbols: %v", r.Symbols)
	}
}

func TestForwardEqu(t *testing.T) {
	r := mustAsm(t, `
	ld a, Q
Q equ P + 1
P = 4
`)
	if r.ROM[1] != 5 {
		t.Fatalf("forward equ: got %d", r.ROM[1])
	}
}

func TestDirectives(t *testing.T) {
	r := mustAsm(t, `
	.org 0x10
	.db 1, 2, "hi", 'z'
	.dw 0x1234, lbl
lbl:
	.ds 3, 0xAA
	.org 0xC000
ram1: .ds 2
ram2: .ds 1
	.org 0x40
	ld a, [ram2]
`)
	want := []byte{1, 2, 'h', 'i', 'z', 0x34, 0x12, 0x19, 0, 0xAA, 0xAA, 0xAA}
	if !bytes.Equal(r.ROM[0x10:0x10+len(want)], want) {
		t.Errorf("got % X want % X", r.ROM[0x10:0x10+len(want)], want)
	}
	if r.Symbols["ram2"] != 0xC002 {
		t.Errorf("ram2 = %#x", r.Symbols["ram2"])
	}
	if !bytes.Equal(r.ROM[0x40:0x43], []byte{0xFA, 0x02, 0xC0}) {
		t.Errorf("ld a,[ram2] = % X", r.ROM[0x40:0x43])
	}
}

func TestMacrosAndRept(t *testing.T) {
	r := mustAsm(t, `
.macro twice
	\1
	\1
.endm
.macro dly
	ld b, \1
.l\@:
	dec b
	jr nz, .l\@
.endm
	twice inc a
	dly 3
	dly 4
	.rept 3
	nop
	.endr
`)
	want := []byte{0x3C, 0x3C, 0x06, 3, 0x05, 0x20, 0xFD, 0x06, 4, 0x05, 0x20, 0xFD, 0, 0, 0}
	if !bytes.Equal(r.ROM[:len(want)], want) {
		t.Errorf("got % X want % X", r.ROM[:len(want)], want)
	}
}

func TestBanks(t *testing.T) {
	r, err := Assemble("t.s", `
	.org 0
	nop
	.bank 2
	.db 0x77
	.bank 1
	.db 0x66
`, Options{NoHeader: true})
	if err != nil {
		t.Fatal(err)
	}
	if r.ROM[0] != 0 || r.ROM[0x4000] != 0x66 || r.ROM[0x8000] != 0x77 {
		t.Errorf("bank layout wrong: %X %X %X", r.ROM[0], r.ROM[0x4000], r.ROM[0x8000])
	}
}

func TestHeader(t *testing.T) {
	r, err := Assemble("t.s", `
	.title "HELLO"
	.cart 1
	.org 0x100
	nop
	jp main
	.org 0x150
main:
	halt
`, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if len(r.ROM) != 0x8000 {
		t.Fatalf("size %d", len(r.ROM))
	}
	if !bytes.Equal(r.ROM[0x104:0x108], []byte{0xCE, 0xED, 0x66, 0x66}) || string(r.ROM[0x134:0x139]) != "HELLO" || r.ROM[0x147] != 1 {
		t.Errorf("header wrong")
	}
	var x byte
	for i := 0x134; i <= 0x14C; i++ {
		x = x - r.ROM[i] - 1
	}
	if x != r.ROM[0x14D] {
		t.Errorf("bad header checksum")
	}
}

func TestErrors(t *testing.T) {
	bad := map[string]string{
		"ld a, hl":                         "no form",
		"ld a, 300":                        "8 bits",
		"jr nowhere":                       "undefined symbol",
		"foo a":                            "unknown instruction",
		"x:\nx:\n nop":                     "already defined",
		"jr far\n.ds 200\nfar:":            "jr target",
		".org 0x100\nnop\n.org 0x100\nnop": "overlapping",
		"bit 8, a":                         "no form",
		"ld a, (1":                         "missing",
		".db 256":                          "does not fit",
		"ld [hl], [hl]":                    "no form",
		"push sp":                          "no form",
		".bogus":                           "unknown directive",
		"ld a, 1 / 0":                      "division by zero",
		"c:":                               "reserved",
		"ldh [$FE00], a":                   "ldh address",
	}
	for src, want := range bad {
		_, err := Assemble("t.s", src, Options{NoHeader: true})
		if err == nil {
			t.Errorf("%q: expected error containing %q, got none", src, want)
			continue
		}
		if !strings.Contains(err.Error(), want) {
			t.Errorf("%q: error %q does not contain %q", src, err, want)
		}
	}
}

// Every one of the 501 defined opcodes must round-trip: assemble the
// disassembly of a synthetic encoding and get the same bytes back.
func TestRoundTripAllOpcodes(t *testing.T) {
	count := 0
	for i := range Templates {
		tm := &Templates[i]
		var enc []byte
		if tm.CB {
			enc = []byte{0xCB, tm.Opcode}
		} else {
			enc = []byte{tm.Opcode}
		}
		for len(enc) < tm.Size {
			enc = append(enc, byte(0x21+len(enc)*7)) // arbitrary non-trivial operand bytes
		}
		if tm.HasImp {
			enc[1] = tm.Implicit
		}
		mem := append(append([]byte{}, enc...), 0, 0, 0)
		pc := uint16(0x0200)
		read := func(a uint16) byte {
			i := int(a) - int(pc)
			if i >= 0 && i < len(mem) {
				return mem[i]
			}
			return 0
		}
		txt, n := Disassemble(read, pc)
		if n != tm.Size {
			t.Errorf("%s: length %d != %d", txt, n, tm.Size)
			continue
		}
		src := fmt.Sprintf(".org 0x200\n%s\n", txt)
		r, err := Assemble("rt.s", src, Options{NoHeader: true})
		if err != nil {
			t.Errorf("%q (op %X cb=%v): %v", txt, tm.Opcode, tm.CB, err)
			continue
		}
		if got := r.ROM[0x200 : 0x200+n]; !bytes.Equal(got, enc) {
			t.Errorf("%q: got % X want % X", txt, got, enc)
		}
		count++
	}
	if count != 500 {
		t.Errorf("round-tripped %d opcodes, want 500", count)
	}
}

func TestIllegalOpcodesDisassemble(t *testing.T) {
	for _, op := range []byte{0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD} {
		txt, n := Disassemble(func(uint16) byte { return op }, 0)
		if n != 1 || !strings.HasPrefix(txt, "db $") {
			t.Errorf("op %02X: %q %d", op, txt, n)
		}
	}
}
