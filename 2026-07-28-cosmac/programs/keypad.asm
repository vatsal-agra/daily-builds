; keypad.asm -- draws the hex digit of whichever key was most recently
; pressed, large, in the center of the screen. Exercises FX0A (blocking
; key wait), FX29 (font-digit address lookup), and DRW using the CPU's
; built-in font set.
;
; V0 = last key pressed   V1, V2 = fixed draw position

wait_key:
        LD V0, K            ; block until a key is pressed; V0 = that key
        CLS
        LD F, V0             ; I = font sprite address for digit V0
        LD V1, 28
        LD V2, 12
        DRW V1, V2, 5
        JP wait_key
