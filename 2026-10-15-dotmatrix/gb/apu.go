package gb

// APU register file (full synthesis arrives in a later phase).
type APU struct {
	regs [0x30]byte
}

func newAPU() *APU      { return &APU{} }
func (a *APU) reset()   {}
func (a *APU) tick(int) {}
func (a *APU) read(addr uint16) byte {
	return a.regs[addr-0xFF10]
}
func (a *APU) write(addr uint16, v byte) {
	a.regs[addr-0xFF10] = v
}
