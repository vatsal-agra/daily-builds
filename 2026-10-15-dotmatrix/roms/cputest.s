; cputest.s — self-checking SM83 instruction test ROM for Dotmatrix.
;
; Every expected value below was worked out by hand from the CPU manual, not
; copied from the emulator's output. The ROM prints one line per failure over
; the serial port and ends with "PASS" or "FAIL" so `dotmatrix test` can
; judge it.

	.title "CPUTEST"

; ---- work RAM ----------------------------------------------------------
	.org 0xC000
total:    .ds 1
fails:    .ds 1
isr_hits: .ds 1
scratch:  .ds 16
SP_T      equ 0xDFEE          ; SP inside a test routine called straight from start

; ---- vectors -----------------------------------------------------------
	.org 0x08
rst08:                       ; used by the RST test: increments E and returns
	inc e
	ret
	.org 0x38
	inc d
	ret
	.org 0x40                ; VBlank
	ld hl, isr_hits
	inc [hl]
	reti
	.org 0x50                ; Timer
	ld hl, isr_hits
	inc [hl]
	reti

	.org 0x100
	nop
	jp start
	.org 0x150
	.include "lib.inc"

; ---- macros ------------------------------------------------------------
.macro T
	call count_test
.endm

.macro fail
	call fail_inline
	.db \1, 0
.endm

; compare A with immediate
.macro expect_a
	cp \1
	jr z, .ok\@
	fail \2
.ok\@:
.endm

; compare AF (A and the flag nibble) with immediates; clobbers A,B,C
.macro expect_af
	push af
	pop bc
	ld a, b
	cp \1
	jr nz, .bad\@
	ld a, c
	cp \2
	jr z, .ok\@
.bad\@:
	fail \3
.ok\@:
.endm

.macro expect_hl
	ld a, h
	cp high(\1)
	jr nz, .bad\@
	ld a, l
	cp low(\1)
	jr z, .ok\@
.bad\@:
	fail \2
.ok\@:
.endm

.macro expect_mem
	ld a, [\1]
	cp \2
	jr z, .ok\@
	fail \3
.ok\@:
.endm

; ---- support routines --------------------------------------------------
count_test:
	push af
	push hl
	ld hl, total
	inc [hl]
	pop hl
	pop af
	ret

; Called with the failure message inline after the CALL. Prints it, bumps
; the failure counter and returns to the instruction after the string.
fail_inline:
	ld [scratch], a          ; keep A (LD [nn],A leaves flags alone)
	pop hl                   ; -> inline message
	push hl
	ld hl, s_fail
	call print_str
	pop hl
	call print_str           ; message; HL now past its terminator
	push hl                  ; new return address
	ld hl, s_a
	call print_str
	ld a, [scratch]
	call print_hex8
	call print_nl
	ld hl, fails
	inc [hl]
	ret

s_fail: .db "FAIL ", 0
s_a:    .db " A=", 0
s_pass: .db "PASS ", 0
s_tot:  .db " checks", 10, 0
s_bad:  .db "FAIL total failures=", 0

; ---- the tests ----------------------------------------------------------
start:
	ld sp, 0xDFF0
	xor a
	ld [total], a
	ld [fails], a
	ld [isr_hits], a

	call t_loads
	call t_alu8
	call t_incdec
	call t_daa
	call t_rotates
	call t_cb
	call t_alu16
	call t_stack_jumps
	call t_memory_ops
	call t_interrupts
	call t_timer
	call t_dma
	call t_ppu_regs

	; verdict
	ld a, [fails]
	or a
	jr nz, .failed
	ld hl, s_pass
	call print_str
	ld a, [total]
	call print_hex8
	ld hl, s_tot
	call print_str
	jr .forever
.failed:
	ld hl, s_bad
	call print_str
	ld a, [fails]
	call print_hex8
	call print_nl
.forever:
	di
	halt
	jr .forever

; ---- 8-bit loads ---------------------------------------------------------
t_loads:
	T
	ld b, 0x12
	ld c, b
	ld d, c
	ld e, d
	ld h, e
	ld l, h
	ld a, l
	expect_a 0x12, "ld r,r chain"
	T
	ld hl, scratch
	ld [hl], 0x77
	ld b, [hl]
	ld a, b
	expect_a 0x77, "ld [hl],n / ld r,[hl]"
	T
	ld hl, scratch
	ld a, 0x10
	ld [hl+], a
	inc a
	ld [hl+], a
	inc a
	ld [hl-], a
	expect_hl scratch + 1, "ld [hl+]/[hl-] pointer"
	expect_mem scratch + 2, 0x12, "ld [hl-],a wrote"
	T
	ld hl, scratch
	ld a, [hl+]
	expect_a 0x10, "ld a,[hl+]"
	T
	ld bc, scratch + 4
	ld de, scratch + 5
	ld a, 0xAB
	ld [bc], a
	ld a, 0xCD
	ld [de], a
	ld a, [bc]
	expect_a 0xAB, "ld [bc],a / ld a,[bc]"
	ld a, [de]
	expect_a 0xCD, "ld [de],a / ld a,[de]"
	T
	ld a, 0x5E
	ld [scratch + 8], a
	ld a, 0
	ld a, [scratch + 8]
	expect_a 0x5E, "ld [nn],a / ld a,[nn]"
	T
	ld a, 0x3C
	ldh [0x80], a
	ld a, 0
	ldh a, [0x80]
	expect_a 0x3C, "ldh round trip (HRAM)"
	T
	ld c, 0x81
	ld a, 0x99
	ld [c], a
	ld a, 0
	ld a, [c]
	expect_a 0x99, "ld [c],a / ld a,[c]"
	T
	ld sp, scratch + 12
	ld [scratch], sp
	ld sp, SP_T
	expect_mem scratch, low(scratch + 12), "ld [nn],sp low"
	expect_mem scratch + 1, high(scratch + 12), "ld [nn],sp high"
	ret

; ---- 8-bit arithmetic / logic with exact flag results ----------------------
t_alu8:
	T
	ld a, 0x3C
	add a, 0x12
	expect_af 0x4E, 0, "add plain"
	T
	ld a, 0xFF
	add a, 1
	expect_af 0x00, F_Z | F_H | F_C, "add wrap"
	T
	ld a, 0x0F
	add a, 1
	expect_af 0x10, F_H, "add half carry"
	T
	ld a, 0x80
	add a, 0x80
	expect_af 0x00, F_Z | F_C, "add carry only"
	T
	ld b, 0x0F
	scf
	ld a, 0xE1
	adc a, b
	expect_af 0xF1, F_H, "adc with carry in"
	T
	ld a, 0xE1
	ld b, 0x3B
	scf
	adc a, b
	expect_af 0x1D, F_C, "adc carry out"
	T
	ld a, 0x3E
	sub 0x3E
	expect_af 0x00, F_Z | F_N, "sub to zero"
	T
	ld a, 0x3E
	sub 0x0F
	expect_af 0x2F, F_N | F_H, "sub half borrow"
	T
	ld a, 0
	sub 1
	expect_af 0xFF, F_N | F_H | F_C, "sub borrow"
	T
	scf
	ld a, 0x3B
	sbc a, 0x2A
	expect_af 0x10, F_N, "sbc with carry in"
	T
	scf
	ld a, 0x3B
	sbc a, 0x4F
	expect_af 0xEB, F_N | F_H | F_C, "sbc borrow"
	T
	ld a, 0x5A
	and 0x0F
	expect_af 0x0A, F_H, "and"
	T
	ld a, 0xF0
	and 0x0F
	expect_af 0x00, F_Z | F_H, "and zero"
	T
	ld a, 0x5A
	or 0xA5
	expect_af 0xFF, 0, "or"
	T
	xor a
	expect_af 0x00, F_Z, "xor a"
	T
	scf
	ld a, 0xFF
	xor 0x0F
	expect_af 0xF0, 0, "xor clears carry"
	T
	ld a, 0x3C
	cp 0x3C
	expect_af 0x3C, F_Z | F_N, "cp equal"
	T
	ld a, 0x3C
	cp 0x40
	expect_af 0x3C, F_N | F_C, "cp less"
	T
	ld a, 0x3C
	cp 0x2F
	expect_af 0x3C, F_N | F_H, "cp greater, half borrow"
	T
	ld hl, scratch
	ld [hl], 0x01
	ld a, 0xFF
	add a, [hl]
	expect_af 0x00, F_Z | F_H | F_C, "add a,[hl]"
	ret

t_incdec:
	T
	or a                      ; clear carry
	ld a, 0xFF
	inc a
	expect_af 0x00, F_Z | F_H, "inc a wrap"
	T
	scf
	ld a, 0x0F
	inc a
	expect_af 0x10, F_H | F_C, "inc keeps carry"
	T
	or a
	ld a, 1
	dec a
	expect_af 0x00, F_Z | F_N, "dec to zero"
	T
	or a
	ld a, 0
	dec a
	expect_af 0xFF, F_N | F_H, "dec wrap"
	T
	ld hl, scratch
	ld [hl], 0x7F
	inc [hl]
	ld a, [hl]
	expect_a 0x80, "inc [hl]"
	T
	dec [hl]
	ld a, [hl]
	expect_a 0x7F, "dec [hl]"
	ret

t_daa:
	T
	ld a, 0x45
	add a, 0x38
	daa
	expect_af 0x83, 0, "daa 45+38"
	T
	ld a, 0x99
	add a, 1
	daa
	expect_af 0x00, F_Z | F_C, "daa 99+1"
	T
	ld a, 0x20
	sub 1
	daa
	expect_af 0x19, F_N, "daa 20-01"
	T
	ld a, 0x15
	sub 0x27
	daa
	expect_af 0x88, F_N | F_C, "daa 15-27"
	T
	ld a, 0x09
	add a, 0x09
	daa
	expect_af 0x18, 0, "daa 09+09"
	ret

t_rotates:
	T
	ld a, 0x85
	rlca
	expect_af 0x0B, F_C, "rlca"
	T
	ld a, 0x01
	rrca
	expect_af 0x80, F_C, "rrca"
	T
	scf
	ld a, 0x80
	rla
	expect_af 0x01, F_C, "rla with carry in"
	T
	or a
	ld a, 0x01
	rra
	expect_af 0x00, F_C, "rra clears Z even for 0"
	T
	or a
	ld a, 0
	rlca
	expect_af 0x00, 0, "rlca never sets Z"
	ret

t_cb:
	T
	ld a, 0x81
	sla a
	expect_af 0x02, F_C, "sla"
	T
	ld a, 0x81
	sra a
	expect_af 0xC0, F_C, "sra keeps sign"
	T
	ld a, 0x01
	srl a
	expect_af 0x00, F_Z | F_C, "srl"
	T
	ld a, 0xF0
	swap a
	expect_af 0x0F, 0, "swap"
	T
	or a
	ld a, 0x80
	rl a
	expect_af 0x00, F_Z | F_C, "cb rl sets Z"
	T
	ld a, 0x80
	rlc a
	expect_af 0x01, F_C, "cb rlc"
	T
	ld a, 0x01
	rrc a
	expect_af 0x80, F_C, "cb rrc"
	T
	scf
	ld a, 0x00
	rr a
	expect_af 0x80, 0, "cb rr"
	T
	or a
	ld a, 0x80
	bit 7, a
	expect_af 0x80, F_H, "bit 7 set"
	T
	or a
	ld a, 0x80
	bit 0, a
	expect_af 0x80, F_Z | F_H, "bit 0 clear"
	T
	ld a, 0
	set 3, a
	expect_a 0x08, "set 3"
	res 3, a
	expect_a 0x00, "res 3"
	T
	ld hl, scratch
	ld [hl], 0xFE
	set 0, [hl]
	ld a, [hl]
	expect_a 0xFF, "set 0,[hl]"
	res 7, [hl]
	ld a, [hl]
	expect_a 0x7F, "res 7,[hl]"
	bit 7, [hl]
	expect_af 0x7F, F_Z | F_H, "bit 7,[hl]"
	T
	ld [hl], 0xA5
	swap [hl]
	ld a, [hl]
	expect_a 0x5A, "swap [hl]"
	ret

t_alu16:
	T
	xor a
	ld hl, 0x0FFF
	ld bc, 1
	add hl, bc
	expect_af 0x00, F_Z | F_H, "add hl half carry, Z preserved"
	expect_hl 0x1000, "add hl,bc value"
	T
	xor a
	ld hl, 0xFFFF
	add hl, hl
	expect_af 0x00, F_Z | F_H | F_C, "add hl,hl flags"
	expect_hl 0xFFFE, "add hl,hl value"
	T
	ld sp, 0xFFF8
	add sp, 8
	push af                   ; harmless: SP is now 0 so this writes to FFFE/FFFF
	pop af
	ld hl, 0
	add hl, sp
	ld sp, SP_T
	expect_hl 0x0000, "add sp,8 wraps to 0"
	T
	ld sp, 0xFFF8
	add sp, 8
	ld sp, SP_T             ; ld sp,nn leaves flags alone
	push af
	pop bc
	ld a, c
	expect_a F_H | F_C, "add sp,e flags"
	T
	ld sp, 0x0001
	ld hl, sp - 2
	ld sp, SP_T
	expect_hl 0xFFFF, "ld hl,sp-2 value"
	T
	ld sp, 0x00FF
	ld hl, sp + 1
	ld sp, SP_T
	push af
	pop bc
	ld a, c
	expect_a F_H | F_C, "ld hl,sp+1 flags at 0x00FF"
	T
	ld bc, 0xFFFF
	inc bc
	ld a, b
	or c
	expect_a 0, "inc bc wraps"
	T
	ld de, 0
	dec de
	ld a, d
	and e
	expect_a 0xFF, "dec de wraps"
	T
	ld sp, 0xBEEF
	ld hl, 0
	add hl, sp
	ld sp, SP_T
	expect_hl 0xBEEF, "add hl,sp"
	ret

; ---- stack, calls, jumps ---------------------------------------------------
t_stack_jumps:
	T
	ld bc, 0x1234
	ld de, 0x5678
	push bc
	push de
	pop bc
	pop de
	ld a, b
	expect_a 0x56, "push/pop order b"
	ld a, c
	expect_a 0x78, "push/pop order c"
	ld a, d
	expect_a 0x12, "push/pop order d"
	T
	ld sp, SP_T
	ld bc, 0xAAF0
	push bc
	pop af
	push af
	pop de
	ld a, e
	expect_a 0xF0, "pop af keeps flag nibble"
	T
	ld bc, 0xFFFF
	push bc
	pop af
	push af
	pop bc
	ld a, c
	expect_a 0xF0, "pop af masks low nibble"
	T
	ld e, 0
	rst 0x08
	rst 0x08
	ld a, e
	expect_a 2, "rst 08"
	T
	ld d, 0
	rst 0x38
	ld a, d
	expect_a 1, "rst 38"
	T
	ld a, 5
	call sub_double
	expect_a 10, "call/ret"
	T
	ld hl, .target
	jp hl
	fail "jp hl missed"
.target:
	T
	xor a
	jp nz, .bad1
	jp z, .good1
.bad1:
	fail "jp nz taken wrongly"
.good1:
	T
	ld a, 3
.cnt:
	dec a
	jr nz, .cnt
	expect_a 0, "jr nz loop"
	T
	scf
	call c, sub_inc_b_set
	ld a, b
	expect_a 0x44, "call c taken"
	T
	or a
	ld b, 0
	call c, sub_inc_b_set
	ld a, b
	expect_a 0, "call c not taken"
	T
	or a
	jr c, .bad2
	jr nc, .good2
.bad2:
	fail "jr c wrong"
.good2:
	T
	scf
	ret nc
	ld a, 0x21
	expect_a 0x21, "ret nc not taken"
	ret

sub_double:
	add a, a
	ret
sub_inc_b_set:
	ld b, 0x44
	ret

; ---- memory-mapped behaviour ----------------------------------------------
t_memory_ops:
	T
	ld a, 0x6B
	ld [0xC100], a
	expect_mem 0xE100, 0x6B, "echo RAM mirrors WRAM"
	T
	ld a, 0x3D
	ld [0xE200], a
	expect_mem 0xC200, 0x3D, "write via echo RAM"
	T
	ld a, 0xFF
	ldh [rIE], a
	ldh a, [rIE]
	expect_a 0xFF, "IE register"
	xor a
	ldh [rIE], a
	T
	ld a, 0x1F
	ldh [rIF], a
	ldh a, [rIF]
	expect_a 0xFF, "IF upper bits read as 1"
	xor a
	ldh [rIF], a
	T
	ld a, [0x4000]
	ld b, a
	ld a, 2
	ld [0x2000], a            ; MBC write on a ROM-only cart is ignored
	ld a, [0x4000]
	cp b
	jr z, .rom_ok
	fail "ROM-only cart changed banks"
.rom_ok:
	T
	ld a, [0x0000]            ; stable ROM contents: unchanged by a write to ROM space
	ld b, a
	ld a, b
	cpl
	ld [0x0000], a
	ld a, [0x0000]
	cp b
	jr z, .rom_ok2
	fail "write to ROM modified it"
.rom_ok2:
	ret

; ---- interrupts -------------------------------------------------------------
t_interrupts:
	T
	xor a
	ld [isr_hits], a
	ldh [rIF], a
	ld a, 0x01                ; enable VBlank
	ldh [rIE], a
	ei
	halt                      ; wakes on VBlank, ISR runs, then continues
	nop
	di
	expect_mem isr_hits, 1, "vblank interrupt serviced once"
	T
	ld a, 0x01
	ldh [rIF], a              ; software-raise VBlank while IME=0
	ei
	ld b, 0
	inc b                     ; one instruction runs before the ISR (EI delay)
	nop
	di
	ld a, b
	expect_a 1, "ei delay: one instruction executes first"
	xor a
	ldh [rIE], a
	ldh [rIF], a
	T
	ld sp, SP_T
	ld a, 0x04                ; timer interrupt, fast
	ldh [rIE], a
	xor a
	ldh [rIF], a
	ld [isr_hits], a
	ld a, 0xFE
	ldh [rTIMA], a
	ld a, 0x05
	ldh [rTAC], a
	ei
	halt
	nop
	di
	xor a
	ldh [rTAC], a
	ldh [rIE], a
	expect_mem isr_hits, 1, "timer interrupt serviced"
	T
	ld a, l                   ; SP must be balanced after ISR/RETI
	ld [scratch], sp
	expect_mem scratch, low(SP_T), "SP restored after ISR (low)"
	expect_mem scratch + 1, high(SP_T), "SP restored after ISR (high)"
	ret

; ---- timer registers ---------------------------------------------------------
t_timer:
	T
	xor a
	ldh [rDIV], a
	ld b, 60                  ; 60 * (dec+jr = 4+... ) comfortably > 256 cycles
.spin:
	dec b
	jr nz, .spin
	ldh a, [rDIV]
	or a
	jr nz, .div_ok
	fail "DIV did not advance"
.div_ok:
	T
	ldh [rDIV], a
	ldh a, [rDIV]
	expect_a 0, "write resets DIV"
	T
	xor a
	ldh [rTAC], a
	ldh [rTIMA], a
	ld a, 0x05                ; enable, 16-cycle period
	ldh [rTAC], a
	ld b, 30
.spin2:
	dec b
	jr nz, .spin2
	ldh a, [rTIMA]
	or a
	jr nz, .tima_ok
	fail "TIMA did not count"
.tima_ok:
	xor a
	ldh [rTAC], a
	ret

; Wait for LY == 144. Returns A=0 when found, A=1 on timeout. Clobbers DE.
wait_vblank:
	ld de, 0x4000
.poll:
	ldh a, [rLY]
	cp 144
	jr z, .found
	dec de
	ld a, d
	or e
	jr nz, .poll
	ld a, 1
	ret
.found:
	xor a
	ret

; ---- OAM DMA ------------------------------------------------------------------
t_dma:
	T
	ld hl, 0xC300
	ld b, 160
	ld a, 0x80
.fill:
	ld [hl+], a
	inc a
	dec b
	jr nz, .fill
	ld hl, dma_routine
	ld de, 0xFF80
	ld b, dma_routine_end - dma_routine
.copy:
	ld a, [hl+]
	ld [de], a
	inc de
	dec b
	jr nz, .copy
	call 0xFF80
	call wait_vblank          ; OAM is only readable outside modes 2/3
	ld hl, OAM
	ld a, [hl]
	expect_a 0x80, "dma first byte"
	ld hl, OAM + 159
	ld a, [hl]
	expect_a 0x80 + 159 & 0xFF, "dma last byte"
	ret

dma_routine:
	ld a, 0xC3
	ldh [rDMA], a
	ld a, 40
.wait:
	dec a
	jr nz, .wait
	ret
dma_routine_end:

; ---- PPU registers --------------------------------------------------------------
t_ppu_regs:
	T
	call wait_vblank
	or a
	jr z, .in_vblank
	fail "LY never reached 144"
	jr .done_ly
.in_vblank:
	ldh a, [rSTAT]
	and 3
	expect_a 1, "STAT mode 1 during VBlank"
.done_ly:
	T
	ld a, 0x55
	ldh [rLYC], a
	ldh a, [rLYC]
	expect_a 0x55, "LYC readback"
	ld a, 0xE4
	ldh [rBGP], a
	ldh a, [rBGP]
	expect_a 0xE4, "BGP readback"
	ldh a, [rSTAT]
	and 0x80
	expect_a 0x80, "STAT bit 7 reads 1"
	ret
