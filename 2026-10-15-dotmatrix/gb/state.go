package gb

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"reflect"
	"unsafe"
)

// Save states serialise every piece of mutable machine state with a small
// reflection-driven binary codec. Struct fields tagged `state:"-"` are
// skipped (ROM image, debugger hooks, audio capture buffers).

const stateMagic = "DMST"
const stateVersion = 1

type codec struct {
	buf []byte
	pos int
	rd  bool
	err error
}

func (c *codec) fail(format string, a ...any) {
	if c.err == nil {
		c.err = fmt.Errorf(format, a...)
	}
}

func (c *codec) u64(v uint64) uint64 {
	if c.rd {
		if c.pos+8 > len(c.buf) {
			c.fail("save state is truncated")
			return 0
		}
		v = binary.LittleEndian.Uint64(c.buf[c.pos:])
		c.pos += 8
		return v
	}
	c.buf = binary.LittleEndian.AppendUint64(c.buf, v)
	return v
}

// walk reads or writes v (which must be addressable) depending on c.rd.
func (c *codec) walk(v reflect.Value) {
	if c.err != nil {
		return
	}
	switch v.Kind() {
	case reflect.Bool:
		var b uint64
		if v.Bool() {
			b = 1
		}
		b = c.u64(b)
		if c.rd {
			v.SetBool(b != 0)
		}
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		x := c.u64(uint64(v.Int()))
		if c.rd {
			v.SetInt(int64(x))
		}
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		x := c.u64(v.Uint())
		if c.rd {
			v.SetUint(x)
		}
	case reflect.Float64, reflect.Float32:
		x := c.u64(math.Float64bits(v.Float()))
		if c.rd {
			v.SetFloat(math.Float64frombits(x))
		}
	case reflect.Array:
		if v.Type().Elem().Kind() == reflect.Uint8 {
			c.bytes(v)
			return
		}
		for i := 0; i < v.Len(); i++ {
			c.walk(v.Index(i))
		}
	case reflect.Slice:
		n := int(c.u64(uint64(v.Len())))
		if c.rd {
			if n < 0 || n > 1<<26 {
				c.fail("save state has an implausible slice length %d", n)
				return
			}
			v.Set(reflect.MakeSlice(v.Type(), n, n))
		}
		if v.Type().Elem().Kind() == reflect.Uint8 {
			c.bytes(v)
			return
		}
		for i := 0; i < n; i++ {
			c.walk(v.Index(i))
		}
	case reflect.Struct:
		t := v.Type()
		for i := 0; i < v.NumField(); i++ {
			if t.Field(i).Tag.Get("state") == "-" {
				continue
			}
			f := v.Field(i)
			if !f.CanSet() {
				f = reflect.NewAt(f.Type(), unsafe.Pointer(f.UnsafeAddr())).Elem()
			}
			c.walk(f)
		}
	default:
		c.fail("state codec cannot handle %s", v.Type())
	}
}

func (c *codec) bytes(v reflect.Value) {
	n := v.Len()
	if c.rd {
		if c.pos+n > len(c.buf) {
			c.fail("save state is truncated")
			return
		}
		reflect.Copy(v, reflect.ValueOf(c.buf[c.pos:c.pos+n]))
		c.pos += n
		return
	}
	tmp := make([]byte, n)
	reflect.Copy(reflect.ValueOf(tmp), v)
	c.buf = append(c.buf, tmp...)
}

func (g *GB) stateParts() []any {
	return []any{
		&g.CPU, &g.Timer, &g.PPU, &g.Joy, &g.dma, &g.serial, g.APU, g.Cart,
		&g.vram, &g.wram, &g.oam, &g.hram, &g.io, &g.ie, &g.ifl,
		&g.Cycles, &g.Frames, &g.lcdOffCycles,
	}
}

// cartID identifies the cartridge a state belongs to.
func (g *GB) cartID() uint64 {
	h := uint64(g.Cart.Info.GlobalChecksum)<<16 | uint64(g.Cart.Info.HeaderChecksum)<<8 | uint64(g.Cart.Info.Type)
	for _, b := range []byte(g.Cart.Info.Title) {
		h = h*1099511628211 ^ uint64(b)
	}
	return h
}

// SaveState serialises the whole machine.
func (g *GB) SaveState() []byte {
	c := &codec{}
	c.buf = append(c.buf, stateMagic...)
	c.buf = append(c.buf, stateVersion)
	c.u64(g.cartID())
	for _, p := range g.stateParts() {
		c.walk(reflect.ValueOf(p).Elem())
	}
	return c.buf
}

// LoadState restores a state produced by SaveState for the same cartridge.
// On error the machine is left untouched.
func (g *GB) LoadState(data []byte) error {
	if len(data) < 5 || string(data[:4]) != stateMagic {
		return errors.New("not a Dotmatrix save state (bad magic)")
	}
	if data[4] != stateVersion {
		return fmt.Errorf("unsupported save-state version %d (this build reads %d)", data[4], stateVersion)
	}
	// decode into a scratch machine first so a corrupt file cannot half-apply
	scratch := &GB{Cart: g.Cart.cloneForState(), APU: newAPU()}
	c := &codec{buf: data, pos: 5, rd: true}
	id := c.u64(0)
	if c.err == nil && id != g.cartID() {
		return errors.New("save state belongs to a different cartridge")
	}
	for _, p := range scratch.stateParts() {
		c.walk(reflect.ValueOf(p).Elem())
	}
	if c.err != nil {
		return c.err
	}
	if c.pos != len(data) {
		return fmt.Errorf("save state has %d trailing bytes", len(data)-c.pos)
	}
	if len(scratch.Cart.RAM) != len(g.Cart.RAM) {
		return errors.New("save state RAM size does not match the cartridge")
	}
	// commit
	pend, rec, recording, dbg := g.APU.pending, g.APU.recorded, g.APU.recording, g.Dbg
	g.CPU, g.Timer, g.PPU, g.Joy, g.dma, g.serial = scratch.CPU, scratch.Timer, scratch.PPU, scratch.Joy, scratch.dma, scratch.serial
	*g.APU = *scratch.APU
	g.APU.pending, g.APU.recorded, g.APU.recording = pend[:0], rec, recording
	g.APU.maxPending = SampleRate * 2 * 2
	rom, info := g.Cart.ROM, g.Cart.Info
	*g.Cart = *scratch.Cart
	g.Cart.ROM, g.Cart.Info = rom, info
	g.vram, g.wram, g.oam, g.hram, g.io, g.ie, g.ifl = scratch.vram, scratch.wram, scratch.oam, scratch.hram, scratch.io, scratch.ie, scratch.ifl
	g.Cycles, g.Frames, g.lcdOffCycles = scratch.Cycles, scratch.Frames, scratch.lcdOffCycles
	g.Dbg = dbg
	return nil
}

// cloneForState makes a Cart shell sharing the (immutable) ROM with a private RAM copy.
func (c *Cart) cloneForState() *Cart {
	n := *c
	n.RAM = make([]byte, len(c.RAM))
	return &n
}
