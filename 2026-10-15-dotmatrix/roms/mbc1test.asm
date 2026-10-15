; mbc1test.asm — MBC1 + battery RAM self-test and persistence demo.
;
; Checks ROM bank switching across four banks, the bank-0 -> bank-1 quirk,
; cartridge RAM enable/disable and RAM banking, then bumps a boot counter that
; lives in battery-backed RAM. Run it twice with `-save file.sav` and the
; counter in the output goes 1, 2, ...

	.title "MBC1TEST"
	.cart 3                  ; MBC1 + RAM + BATTERY
	.ramsize 3               ; 32 KiB RAM (4 banks)

	.org 0xC000
fails: .ds 1

	.org 0x100
	nop
	jp start
	.org 0x150
	.include "lib.inc"

; each switchable bank starts with a marker byte at 0x4000
	.bank 1
	.db 0xB1
	.bank 2
	.db 0xB2
	.bank 3
	.db 0xB3
	.bank 0
	.org 0x200

start:
	ld sp, 0xDFF0
	xor a
	ld [fails], a

	; --- ROM banking ---------------------------------------------------
	ld a, 1
	ld [0x2000], a
	ld a, [0x4000]
	cp 0xB1
	jr z, .b1
	call bad_rom
.b1:
	ld a, 2
	ld [0x2000], a
	ld a, [0x4000]
	cp 0xB2
	jr z, .b2
	call bad_rom
.b2:
	ld a, 3
	ld [0x2000], a
	ld a, [0x4000]
	cp 0xB3
	jr z, .b3
	call bad_rom
.b3:
	xor a
	ld [0x2000], a            ; bank 0 selects bank 1
	ld a, [0x4000]
	cp 0xB1
	jr z, .b0
	call bad_rom
.b0:

	; --- RAM disabled reads 0xFF -----------------------------------------
	ld a, [0xA000]
	cp 0xFF
	jr z, .ramoff
	call bad_ram
.ramoff:

	; --- RAM enable + banking ------------------------------------------------
	ld a, 0x0A
	ld [0x0000], a
	ld a, 1
	ld [0x6000], a            ; mode 1: RAM bank select active
	ld b, 0
.wr:
	ld a, b
	ld [0x4000], a            ; select RAM bank b
	ld a, 0x50
	add a, b
	ld [0xA100], a            ; write a bank-specific value
	inc b
	ld a, b
	cp 4
	jr nz, .wr
	ld b, 0
.rd:
	ld a, b
	ld [0x4000], a
	ld a, [0xA100]
	ld c, a
	ld a, 0x50
	add a, b
	cp c
	jr z, .rdok
	call bad_ram
.rdok:
	inc b
	ld a, b
	cp 4
	jr nz, .rd

	; --- boot counter in battery RAM (bank 0, offset 0) ------------------------------
	xor a
	ld [0x4000], a
	ld a, [0xA000]
	inc a
	ld [0xA000], a
	ld [0xA001], a            ; keep a copy to print after the loop clobbers registers
	ld hl, s_boot
	call print_str
	ld a, [0xA001]
	call print_hex8
	call print_nl

	ld a, [fails]
	or a
	jr nz, .failed
	ld hl, s_pass
	call print_str
	jr .done
.failed:
	ld hl, s_fail
	call print_str
.done:
	call print_nl
	di
.halt:
	halt
	jr .halt

bad_rom:
	ld hl, s_badrom
	jr report
bad_ram:
	ld hl, s_badram
report:
	call print_str
	ld a, [fails]
	inc a
	ld [fails], a
	ret

s_boot:   .db "BOOTS=", 0
s_pass:   .db "PASS", 0
s_fail:   .db "FAIL total", 0
s_badrom: .db "bad ROM bank", 10, 0
s_badram: .db "bad RAM", 10, 0
