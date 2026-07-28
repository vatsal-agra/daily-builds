; maze.asm -- the classic "1-instruction maze" tiling demo, generalized
; to a full raster loop instead of the traditional single-opcode party
; trick, so it's readable. Tiles the 64x32 screen with 8x8-pixel diagonal
; tiles, picking "/" or "\" at random for each cell -- the resulting
; connected-looking maze pattern is an emergent property of the two tile
; shapes always meeting edge-to-edge, not anything explicitly planned.
;
; V0 = tile x (0,8,16,...,56)   V1 = tile y (0,8,16,24)
; V2 = random tile selector (0 or 8, used as a byte offset into the two
;      8-byte tile sprites stored back to back at TILES)
; V3 = scratch

        LD V0, 0
        LD V1, 0
row_loop:
col_loop:
        RND V2, 0x08        ; V2 = 0 or 8 (only bit 3 of the random byte survives)
        LD I, TILES
        ADD I, V2
        DRW V0, V1, 8

        ADD V0, 8
        LD V3, V0
        SE V3, 64
        JP col_loop

        LD V0, 0
        ADD V1, 8
        LD V3, V1
        SE V3, 32
        JP row_loop

halt:
        JP halt

TILES:  DB 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01   ; "\"
        DB 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80   ; "/"
