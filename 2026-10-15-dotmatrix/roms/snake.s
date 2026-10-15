; snake.s — a complete Snake game for the Game Boy, written for Dotmatrix.
;
; D-pad steers, START begins / restarts. Eat food to grow and speed up; the
; walls and your own body are fatal. Reach length 100 to win.

	.title "SNAKE"

; ---- tile numbers -------------------------------------------------------
T_BLANK  equ 0
T_WALL   equ 1
T_BODY   equ 2
T_HEAD   equ 3
T_FOOD   equ 4
T_DIGIT0 equ 0x10          ; '0'..'9'
T_ALPHA  equ 0x20          ; 'A'..'Z'

WIN_LEN  equ 100
FIELD_W  equ 20
FIELD_H  equ 18

; ---- work RAM ---------------------------------------------------------------
	.org 0xC000
dir:        .ds 1          ; 0 right 1 left 2 up 3 down
ndir:       .ds 1          ; queued direction applied on the next move
hx:         .ds 1
hy:         .ds 1
headidx:    .ds 1
tailidx:    .ds 1
len:        .ds 1
score:      .ds 1
timer:      .ds 1          ; frames until next move
period:     .ds 1          ; frames per move
seed:       .ds 1
frames:     .ds 1
prevpad:    .ds 1
pad:        .ds 1
fx:         .ds 1
fy:         .ds 1
eating:     .ds 1
txt_x:      .ds 1
txt_y:      .ds 1
msg_lo:     .ds 1
msg_hi:     .ds 1
ring:       .ds 512

; ---- vectors / header ----------------------------------------------------------
	.org 0x100
	nop
	jp start
	.org 0x150

	.include "lib.inc"

start:
	di
	ld sp, 0xDFF0
	call wait_vbl
	xor a
	ldh [rLCDC], a            ; LCD off: free VRAM access
	call load_font
	ld a, 0xE4
	ldh [rBGP], a
	xor a
	ldh [rSCX], a
	ldh [rSCY], a
	ld [frames], a
	ld a, 0x37
	ld [seed], a

title:
	call clear_screen
	ld a, 0x91
	ldh [rLCDC], a            ; LCD on, BG on, tiles at 0x8000
	call wait_vbl
	ld hl, s_title
	ld d, 5
	ld e, 7
	call put_text
	ld hl, s_press
	ld d, 10
	ld e, 4
	call put_text
.wait_start:
	call wait_frame
	ld a, [frames]
	inc a
	ld [frames], a
	call read_pad
	bit 3, a                  ; START
	jr z, .wait_start
	ld a, [frames]
	ld b, a
	ld a, [seed]
	xor b
	ld [seed], a              ; entropy from how long the player waited

new_game:
	call wait_vbl
	call draw_field
	; initial snake: three cells, heading right, in the middle
	ld a, 0
	ld [dir], a
	ld [ndir], a
	ld [headidx], a
	ld [tailidx], a
	ld [score], a
	ld a, 3
	ld [len], a
	ld a, 12
	ld [period], a
	ld [timer], a
	ld a, 9
	ld [hy], a
	ld a, 8
	ld [hx], a
	; segments (8,9) (9,9) (10,9): tail first
	ld a, 8
	ld d, 9
	ld e, a
	call push_head
	ld a, 9
	ld [hx], a
	ld e, a
	ld d, 9
	call push_head
	ld a, 10
	ld [hx], a
	ld e, a
	ld d, 9
	call push_head
	call draw_snake_full
	call place_food
	call draw_score

play:
	call wait_frame
	ld a, [frames]
	inc a
	ld [frames], a
	call read_pad
	ld [pad], a
	call steer
	ld a, [timer]
	dec a
	ld [timer], a
	jr nz, play
	ld a, [period]
	ld [timer], a
	call step
	jr nz, play               ; Z set = dead / won
	call game_over
	jr new_game_or_title

new_game_or_title:
.wait_start:
	call wait_frame
	call read_pad
	bit 3, a
	jr z, .wait_start
	jp new_game

; ---- steering ---------------------------------------------------------------------
; A = pad. Updates ndir, refusing 180-degree turns relative to the current direction.
steer:
	ld b, a
	ld a, [dir]
	ld c, a
	bit 4, b
	jr z, .not_r
	ld a, c
	cp 1
	jr z, .done
	ld a, 0
	ld [ndir], a
	ret
.not_r:
	bit 5, b
	jr z, .not_l
	ld a, c
	or a
	jr z, .done
	ld a, 1
	ld [ndir], a
	ret
.not_l:
	bit 6, b
	jr z, .not_u
	ld a, c
	cp 3
	jr z, .done
	ld a, 2
	ld [ndir], a
	ret
.not_u:
	bit 7, b
	jr z, .done
	ld a, c
	cp 2
	jr z, .done
	ld a, 3
	ld [ndir], a
.done:
	ret

; ---- one game step ---------------------------------------------------------------------
; Returns Z clear (NZ) if the game continues, Z set if the snake died or won.
step:
	ld a, [ndir]
	ld [dir], a
	ld a, [hx]
	ld e, a
	ld a, [hy]
	ld d, a
	ld a, [dir]
	or a
	jr z, .right
	dec a
	jr z, .left
	dec a
	jr z, .up
	inc d                     ; down
	jr .moved
.right:
	inc e
	jr .moved
.left:
	dec e
	jr .moved
.up:
	dec d
.moved:
	; D,E = new head. Look at what is there.
	push de
	call tile_addr
	ld a, [hl]
	pop de
	cp T_FOOD
	jr nz, .no_food
	ld a, 1
	ld [eating], a
	jr .commit
.no_food:
	xor a
	ld [eating], a
	; the tail will vacate its cell this step, so moving into it is legal
	push de
	call erase_tail
	pop de
	push de
	call tile_addr
	ld a, [hl]
	pop de
	or a
	jr z, .commit
	jp .dead                  ; wall or body
.commit:
	; old head becomes body
	push de
	ld a, [hx]
	ld e, a
	ld a, [hy]
	ld d, a
	ld b, T_BODY
	call put_tile
	pop de
	ld a, e
	ld [hx], a
	ld a, d
	ld [hy], a
	call push_head
	ld b, T_HEAD
	call put_tile             ; D,E still the new head
	ld a, [eating]
	or a
	jr z, .ret_ok
	; ate: grow, score, speed up, new food
	ld a, [len]
	inc a
	ld [len], a
	ld a, [score]
	inc a
	ld [score], a
	cp WIN_LEN - 3
	jr nc, .won
	; speed: every 4 points shave a frame, floor 4
	and 3
	jr nz, .no_speed
	ld a, [period]
	cp 4
	jr z, .no_speed
	dec a
	ld [period], a
.no_speed:
	call draw_score
	call place_food
.ret_ok:
	or 1                      ; NZ: continue
	ret
.won:
	call draw_score
	ld a, 1
	ld [eating], a
	xor a                     ; Z: finished
	ld hl, s_win
	jr .finish
.dead:
	xor a
	ld hl, s_dead
.finish:
	; remember the message for game_over
	ld a, l
	ld [msg_lo], a
	ld a, h
	ld [msg_hi], a
	xor a
	ret                       ; Z set

; Remove the tail cell from the ring and from the screen.
erase_tail:
	ld a, [tailidx]
	ld c, a
	call ring_addr            ; HL -> (x,y) of tail
	ld a, [hl+]
	ld e, a
	ld d, [hl]
	ld b, T_BLANK
	call put_tile
	ld a, [tailidx]
	inc a
	ld [tailidx], a
	ret

; Append D,E to the ring as the new head.
push_head:
	ld a, [headidx]
	ld c, a
	push de
	call ring_addr
	pop de
	ld a, e
	ld [hl+], a
	ld [hl], d
	ld a, [headidx]
	inc a
	ld [headidx], a
	ret

; HL = &ring[C * 2]
ring_addr:
	ld l, c
	ld h, 0
	add hl, hl
	ld bc, ring
	add hl, bc
	ret

; ---- screen helpers ------------------------------------------------------------------------
; HL = 0x9800 + D*32 + E (preserves B, C, D, E)
tile_addr:
	ld h, 0
	ld l, d
	add hl, hl
	add hl, hl
	add hl, hl
	add hl, hl
	add hl, hl
	ld a, l
	add a, e
	ld l, a
	ld a, h
	adc a, high(MAP0)
	ld h, a
	ret

; Write tile B at (E,D). Waits for a safe VRAM window if the LCD is drawing.
put_tile:
	call tile_addr
.wait:
	ldh a, [rSTAT]
	and 2
	jr nz, .wait              ; modes 2 and 3 block VRAM
	ld [hl], b
	ret

wait_vbl:
.l:
	ldh a, [rLY]
	cp 144
	jr nz, .l
	ret

; Wait for the start of the next VBlank.
wait_frame:
.out:
	ldh a, [rLY]
	cp 144
	jr nc, .out               ; leave the current VBlank first
.in:
	ldh a, [rLY]
	cp 144
	jr nz, .in
	ret

clear_screen:
	xor a
	ldh [rLCDC], a
	ld hl, MAP0
	ld bc, 32 * 32
.clr:
	xor a
	ld [hl+], a
	dec bc
	ld a, b
	or c
	jr nz, .clr
	ret

; Rebuild the playfield: HUD row 0, walls around rows 1..17.
draw_field:
	xor a
	ldh [rLCDC], a            ; LCD off for the bulk write (only legal during VBlank)
	ld hl, MAP0
	ld bc, 32 * 32
.clr:
	xor a
	ld [hl+], a
	dec bc
	ld a, b
	or c
	jr nz, .clr
	; top and bottom walls
	ld e, 0
.hwall:
	ld d, 1
	push de
	call tile_addr
	ld [hl], T_WALL
	pop de
	ld d, FIELD_H - 1
	push de
	call tile_addr
	ld [hl], T_WALL
	pop de
	inc e
	ld a, e
	cp FIELD_W
	jr nz, .hwall
	; left and right walls
	ld d, 1
.vwall:
	ld e, 0
	push de
	call tile_addr
	ld [hl], T_WALL
	pop de
	ld e, FIELD_W - 1
	push de
	call tile_addr
	ld [hl], T_WALL
	pop de
	inc d
	ld a, d
	cp FIELD_H
	jr nz, .vwall
	; HUD label
	ld hl, s_score
	ld d, 0
	ld e, 1
	call put_text
	ld a, 0x91
	ldh [rLCDC], a
	ret

; Draw every ring cell (used once after resetting the snake).
draw_snake_full:
	ld a, [tailidx]
	ld c, a
.again:
	push bc
	call ring_addr
	ld a, [hl+]
	ld e, a
	ld d, [hl]
	ld b, T_BODY
	call put_tile
	pop bc
	inc c
	ld a, [headidx]
	cp c
	jr nz, .again
	; head tile on top
	ld a, [hx]
	ld e, a
	ld a, [hy]
	ld d, a
	ld b, T_HEAD
	jp put_tile

; Choose a random empty cell and draw food there.
place_food:
.try:
	call rand
	; x = 1 + rand % (FIELD_W - 2)
.modx:
	cp FIELD_W - 2
	jr c, .xok
	sub FIELD_W - 2
	jr .modx
.xok:
	inc a
	ld e, a
	call rand
.mody:
	cp FIELD_H - 3
	jr c, .yok
	sub FIELD_H - 3
	jr .mody
.yok:
	add a, 2
	ld d, a
	push de
	call tile_addr
	ld a, [hl]
	pop de
	or a
	jr nz, .try               ; occupied
	ld b, T_FOOD
	call put_tile
	ret

rand:
	ld a, [seed]
	ld b, a
	add a, a
	add a, a
	add a, b                  ; *5
	add a, 0x31
	ld [seed], a
	ld b, a
	ldh a, [rDIV]
	xor b
	ret

; Draw the 3-digit score at the HUD.
draw_score:
	ld a, [score]
	ld b, 0                   ; hundreds
.h:
	cp 100
	jr c, .hd
	sub 100
	inc b
	jr .h
.hd:
	ld c, 0                   ; tens
.t:
	cp 10
	jr c, .td
	sub 10
	inc c
	jr .t
.td:
	push af                   ; ones
	ld a, b
	add a, T_DIGIT0
	ld b, a
	ld e, 8
	ld d, 0
	call put_tile
	ld a, c
	add a, T_DIGIT0
	ld b, a
	ld e, 9
	ld d, 0
	call put_tile
	pop af
	add a, T_DIGIT0
	ld b, a
	ld e, 10
	ld d, 0
	jp put_tile

; Game over / win banner then final score.
game_over:
	ld a, [msg_lo]
	ld l, a
	ld a, [msg_hi]
	ld h, a
	ld d, 8
	ld e, 5
	call put_text
	ld hl, s_press
	ld d, 10
	ld e, 4
	call put_text
	ret

; Draw the NUL-terminated string at HL with its first character at (E,D).
; Characters: space, 0-9, A-Z. Waits for VRAM access per character.
put_text:
	ld a, d
	ld [txt_y], a
	ld a, e
	ld [txt_x], a
.next:
	ld a, [hl+]
	or a
	ret z
	cp ' '
	jr nz, .not_space
	ld b, T_BLANK
	jr .draw
.not_space:
	cp 'A'
	jr c, .digit
	sub 'A'
	add a, T_ALPHA
	ld b, a
	jr .draw
.digit:
	sub '0'
	add a, T_DIGIT0
	ld b, a
.draw:
	push hl
	ld a, [txt_x]
	ld e, a
	ld a, [txt_y]
	ld d, a
	call put_tile
	ld a, [txt_x]
	inc a
	ld [txt_x], a
	pop hl
	jr .next

; Read the joypad. Returns A: bit7 down, 6 up, 5 left, 4 right, 3 start, 2 select, 1 B, 0 A (1 = pressed).
read_pad:
	ld a, 0x20
	ldh [rP1], a
	ldh a, [rP1]
	ldh a, [rP1]
	cpl
	and 0x0F
	swap a
	ld b, a
	ld a, 0x10
	ldh [rP1], a
	ldh a, [rP1]
	ldh a, [rP1]
	ldh a, [rP1]
	cpl
	and 0x0F
	or b
	ld b, a
	ld a, 0x30
	ldh [rP1], a
	ld a, b
	ret

; Copy the 1bpp font into VRAM as 2bpp (colour 3) tiles.
load_font:
	ld hl, tiles_1bpp
	ld de, VRAM
	ld bc, tiles_end - tiles_1bpp
.copy:
	ld a, [hl+]
	ld [de], a
	inc de
	ld [de], a
	inc de
	dec bc
	ld a, b
	or c
	jr nz, .copy
	ret

s_title: .db "SNAKE", 0
s_press: .db "PRESS START", 0
s_score: .db "SCORE", 0
s_dead:  .db "GAME OVER", 0
s_win:   .db "YOU WIN", 0

; Tile order: 0 blank, 1 wall, 2 body, 3 head, 4 food, 5..15 unused,
; 0x10.. digits, 0x20.. letters.
tiles_1bpp:
	; 0 blank
	.db 0, 0, 0, 0, 0, 0, 0, 0
	; 1 wall (brick)
	.db %11111111, %10000001, %10111101, %10100101, %10100101, %10111101, %10000001, %11111111
	; 2 body
	.db %00000000, %01111110, %01111110, %01111110, %01111110, %01111110, %01111110, %00000000
	; 3 head
	.db %01111110, %11111111, %11011011, %11111111, %11111111, %11000011, %11111111, %01111110
	; 4 food
	.db %00001000, %00011100, %00111110, %01111111, %01111111, %00111110, %00011100, %00000000
	.ds 11 * 8, 0
	; 0x10 digits 0-9
	.db %00111100, %01100110, %01101110, %01110110, %01100110, %01100110, %00111100, 0
	.db %00011000, %00111000, %00011000, %00011000, %00011000, %00011000, %01111110, 0
	.db %00111100, %01100110, %00000110, %00001100, %00110000, %01100000, %01111110, 0
	.db %00111100, %01100110, %00000110, %00011100, %00000110, %01100110, %00111100, 0
	.db %00001100, %00011100, %00101100, %01001100, %01111110, %00001100, %00001100, 0
	.db %01111110, %01100000, %01111100, %00000110, %00000110, %01100110, %00111100, 0
	.db %00111100, %01100000, %01111100, %01100110, %01100110, %01100110, %00111100, 0
	.db %01111110, %00000110, %00001100, %00011000, %00110000, %00110000, %00110000, 0
	.db %00111100, %01100110, %01100110, %00111100, %01100110, %01100110, %00111100, 0
	.db %00111100, %01100110, %01100110, %00111110, %00000110, %00001100, %00111000, 0
	.ds 6 * 8, 0
	; 0x20 letters A-Z
	.db %00011000, %00111100, %01100110, %01100110, %01111110, %01100110, %01100110, 0     ; A
	.db %01111100, %01100110, %01100110, %01111100, %01100110, %01100110, %01111100, 0     ; B
	.db %00111100, %01100110, %01100000, %01100000, %01100000, %01100110, %00111100, 0     ; C
	.db %01111000, %01101100, %01100110, %01100110, %01100110, %01101100, %01111000, 0     ; D
	.db %01111110, %01100000, %01100000, %01111100, %01100000, %01100000, %01111110, 0     ; E
	.db %01111110, %01100000, %01100000, %01111100, %01100000, %01100000, %01100000, 0     ; F
	.db %00111100, %01100110, %01100000, %01101110, %01100110, %01100110, %00111110, 0     ; G
	.db %01100110, %01100110, %01100110, %01111110, %01100110, %01100110, %01100110, 0     ; H
	.db %00111100, %00011000, %00011000, %00011000, %00011000, %00011000, %00111100, 0     ; I
	.db %00011110, %00001100, %00001100, %00001100, %00001100, %01101100, %00111000, 0     ; J
	.db %01100110, %01101100, %01111000, %01110000, %01111000, %01101100, %01100110, 0     ; K
	.db %01100000, %01100000, %01100000, %01100000, %01100000, %01100000, %01111110, 0     ; L
	.db %01100011, %01110111, %01111111, %01101011, %01100011, %01100011, %01100011, 0     ; M
	.db %01100110, %01110110, %01111110, %01111110, %01101110, %01100110, %01100110, 0     ; N
	.db %00111100, %01100110, %01100110, %01100110, %01100110, %01100110, %00111100, 0     ; O
	.db %01111100, %01100110, %01100110, %01111100, %01100000, %01100000, %01100000, 0     ; P
	.db %00111100, %01100110, %01100110, %01100110, %01101010, %01100100, %00111010, 0     ; Q
	.db %01111100, %01100110, %01100110, %01111100, %01111000, %01101100, %01100110, 0     ; R
	.db %00111100, %01100110, %01100000, %00111100, %00000110, %01100110, %00111100, 0     ; S
	.db %01111110, %00011000, %00011000, %00011000, %00011000, %00011000, %00011000, 0     ; T
	.db %01100110, %01100110, %01100110, %01100110, %01100110, %01100110, %00111100, 0     ; U
	.db %01100110, %01100110, %01100110, %01100110, %01100110, %00111100, %00011000, 0     ; V
	.db %01100011, %01100011, %01100011, %01101011, %01111111, %01110111, %01100011, 0     ; W
	.db %01100110, %01100110, %00111100, %00011000, %00111100, %01100110, %01100110, 0     ; X
	.db %01100110, %01100110, %00111100, %00011000, %00011000, %00011000, %00011000, 0     ; Y
	.db %01111110, %00000110, %00001100, %00011000, %00110000, %01100000, %01111110, 0     ; Z
tiles_end:
