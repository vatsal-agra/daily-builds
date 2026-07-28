; selftest.asm -- an opcode self-test ROM. Runs a fixed sequence of
; checks against hand-computed expected values; on the first mismatch it
; jumps to `fail` (V8 marker = 0xFF, VE = which check number failed) and
; spins forever, otherwise it falls through every check to `success`
; (V8 marker = 0x01) and spins there. VF itself can't be the marker --
; it's the CPU's own flag register, clobbered by ADD/SUB/SHR throughout
; these very checks. `tests/test_integration.py` runs this ROM to
; completion and asserts it lands on `success` with V8 == 0x01.
;
; This is a behavioral cross-check independent of `tests/test_cpu.py`:
; those tests call `Chip8._execute` directly from Python, this ROM
; exercises the exact same opcodes only through the assembler -> real
; bytecode -> fetch/decode/execute path a real program uses.

        LD VE, 1
        ; check 1: ADD carry flag sets on overflow
        LD V0, 0xFF
        LD V1, 0x02
        ADD V0, V1
        SE V0, 0x01
        JP fail
        SE VF, 1
        JP fail

        LD VE, 2
        ; check 2: ADD does not set carry when it doesn't overflow
        LD V0, 0x10
        LD V1, 0x02
        ADD V0, V1
        SE V0, 0x12
        JP fail
        SE VF, 0
        JP fail

        LD VE, 3
        ; check 3: SUB borrow flag (VF=0) when it borrows
        LD V0, 0x02
        LD V1, 0x05
        SUB V0, V1
        SE V0, 0xFD
        JP fail
        SE VF, 0
        JP fail

        LD VE, 4
        ; check 4: SUB no-borrow flag (VF=1) when Vx >= Vy
        LD V0, 0x05
        LD V1, 0x02
        SUB V0, V1
        SE V0, 0x03
        JP fail
        SE VF, 1
        JP fail

        LD VE, 5
        ; check 5: AND / OR / XOR
        LD V0, 0xF0
        LD V1, 0x0F
        OR V0, V1
        SE V0, 0xFF
        JP fail
        LD V0, 0xF0
        LD V1, 0xFF
        AND V0, V1
        SE V0, 0xF0
        JP fail
        LD V0, 0xFF
        LD V1, 0x0F
        XOR V0, V1
        SE V0, 0xF0
        JP fail

        LD VE, 6
        ; check 6: SHR (COSMAC-legacy quirk: Vx = Vy, then shift)
        LD V0, 0x00
        LD V1, 0x03
        SHR V0, V1
        SE V0, 0x01
        JP fail
        SE VF, 1
        JP fail

        LD VE, 7
        ; check 7: SHL
        LD V0, 0x00
        LD V1, 0x81
        SHL V0, V1
        SE V0, 0x02
        JP fail
        SE VF, 1
        JP fail

        LD VE, 8
        ; check 8: BCD conversion of 156 -> memory[I..I+2] = 1,5,6
        LD V0, 156
        LD I, SCRATCH
        LD B, V0
        LD V2, [I]        ; loads V0=memory[I], V1=memory[I+1], V2=memory[I+2]
        SE V0, 1
        JP fail
        SE V1, 5
        JP fail
        SE V2, 6
        JP fail

        LD VE, 9
        ; check 9: register file store/load round trip through memory
        LD V0, 0x11
        LD V1, 0x22
        LD V2, 0x33
        LD I, SCRATCH
        LD [I], V2
        LD V0, 0
        LD V1, 0
        LD V2, 0
        LD I, SCRATCH
        LD V2, [I]
        SE V0, 0x11
        JP fail
        SE V1, 0x22
        JP fail
        SE V2, 0x33
        JP fail

        LD VE, 10
        ; check 10: skip instructions (SE/SNE, register and immediate forms)
        LD V0, 5
        LD V1, 5
        SE V0, V1
        JP fail            ; SE should have skipped this JP
        SNE V0, V1
        JP check10_ok
        JP fail
check10_ok:

        LD VE, 0
        LD V8, 0x01
        JP success

fail:
        LD V8, 0xFF
        JP fail

success:
        JP success

SCRATCH: DB 0, 0, 0
