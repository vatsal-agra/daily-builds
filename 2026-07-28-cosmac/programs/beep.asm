; beep.asm -- four short beeps separated by silence. No display output at
; all; this program exists purely to exercise the sound timer (`ST`) so
; there's something real for `cosmac/wav.py` to render and for the browser
; UI's Web Audio beep to actually be heard driving. Each beep is 30 ticks
; (~0.5s at 60Hz), each pause 20 ticks (~0.33s).
;
; CHIP-8 has no opcode to *read* ST back into a register (FX18 writes it,
; nothing reads it) -- the standard idiom is to load DT and ST with the
; same value together and poll DT, since both timers tick down in lockstep
; at 60Hz.
;
; V0 = scratch   V1 = beeps remaining

        LD V1, 4
loop:
        LD V0, 30
        LD ST, V0
        LD DT, V0
wait_beep:
        LD V0, DT
        SE V0, 0
        JP wait_beep

        LD V0, 20
        LD DT, V0
wait_pause:
        LD V0, DT
        SE V0, 0
        JP wait_pause

        ADD V1, 0xFF
        SE V1, 0
        JP loop

halt:
        JP halt
