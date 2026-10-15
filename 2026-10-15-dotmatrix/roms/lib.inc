; lib.inc — shared constants, serial output helpers and test macros for the
; Dotmatrix demo/test ROMs. Include from the top of a ROM source file.

rP1     equ 0x00
rSB     equ 0x01
rSC     equ 0x02
rDIV    equ 0x04
rTIMA   equ 0x05
rTMA    equ 0x06
rTAC    equ 0x07
rIF     equ 0x0F
rLCDC   equ 0x40
rSTAT   equ 0x41
rSCY    equ 0x42
rSCX    equ 0x43
rLY     equ 0x44
rLYC    equ 0x45
rDMA    equ 0x46
rBGP    equ 0x47
rOBP0   equ 0x48
rOBP1   equ 0x49
rWY     equ 0x4A
rWX     equ 0x4B
rIE     equ 0xFF

F_Z     equ 0x80
F_N     equ 0x40
F_H     equ 0x20
F_C     equ 0x10

VRAM    equ 0x8000
MAP0    equ 0x9800
MAP1    equ 0x9C00
OAM     equ 0xFE00

; Print character in A over the serial port (blocks until sent).
; Clobbers A.
print_char:
	ldh [rSB], a
	ld a, 0x81
	ldh [rSC], a
.wait:
	ldh a, [rSC]
	bit 7, a
	jr nz, .wait
	ret

; Print NUL-terminated string at HL. Returns with HL just past the terminator.
print_str:
	ld a, [hl+]
	or a
	ret z
	call print_char
	jr print_str

; Print A as two hex digits. Clobbers A, B.
print_hex8:
	ld b, a
	swap a
	call print_nibble
	ld a, b
print_nibble:
	and 0x0F
	cp 10
	jr c, .digit
	add a, 'A' - 10
	jp print_char
.digit:
	add a, '0'
	jp print_char

print_nl:
	ld a, 10
	jp print_char
