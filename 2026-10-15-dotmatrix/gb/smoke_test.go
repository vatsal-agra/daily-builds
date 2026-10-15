package gb

import "testing"

func TestSmokeSerial(t *testing.T) {
	g := build(t, `
	ld hl, msg
.next:
	ld a, [hl+]
	or a
	jr z, .done
	ldh [0x01], a
	ld a, 0x81
	ldh [0x02], a
.wait:
	ldh a, [0x02]
	bit 7, a
	jr nz, .wait
	jr .next
.done:
	halt
msg: .db "Hi!", 0
`)
	runUntilHalt(t, g, 1_000_000)
	if string(g.Serial) != "Hi!" {
		t.Fatalf("serial = %q", g.Serial)
	}
}
