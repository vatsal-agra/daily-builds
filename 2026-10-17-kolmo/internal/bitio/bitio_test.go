package bitio

import "testing"

func TestRoundTrip(t *testing.T) {
	w := &Writer{}
	w.WriteBits(5, 3)
	w.WriteBits(0x1ffff, 17)
	w.WriteBitsRev(0b110, 3)
	w.Align()
	w.WriteBytes([]byte{9, 8, 7})
	r := NewReader(w.Bytes())
	if v, _ := r.ReadBits(3); v != 5 {
		t.Fatal(v)
	}
	if v, _ := r.ReadBits(17); v != 0x1ffff {
		t.Fatal(v)
	}
	if v, _ := r.ReadBits(3); v != 0b011 {
		t.Fatalf("reversed bits: %b", v)
	}
	b, err := r.ReadBytes(3)
	if err != nil || b[0] != 9 || b[2] != 7 {
		t.Fatal(b, err)
	}
	if _, err := r.ReadBits(1); err != ErrEOF {
		t.Fatal("expected EOF")
	}
}
