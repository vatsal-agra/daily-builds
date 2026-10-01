package sketch

import (
	"errors"
	"fmt"
	"math/bits"
)

const (
	cuckooSlots   = 4
	cuckooMaxKick = 500
)

// Cuckoo is a cuckoo filter (Fan et al. 2014): partial-key cuckoo hashing with
// 16-bit fingerprints and 4-slot buckets. Unlike Bloom it supports Delete.
// Only delete items that were actually inserted; deleting a never-inserted
// item can remove another item's colliding fingerprint.
type Cuckoo struct {
	nb    uint64 // bucket count, power of two
	count uint64
	fp    []uint16 // nb*4 slots, 0 = empty
	rng   uint64   // deterministic kick randomness
}

// NewCuckoo sizes the table for about `capacity` items at ≤95% load.
func NewCuckoo(capacity int) (*Cuckoo, error) {
	if capacity < 1 || capacity > 1<<30 {
		return nil, fmt.Errorf("cuckoo: capacity %d out of range", capacity)
	}
	need := uint64(float64(capacity)/0.95/cuckooSlots) + 1
	nb := uint64(1) << uint(bits.Len64(need-1))
	if nb < 2 {
		nb = 2
	}
	return &Cuckoo{nb: nb, fp: make([]uint16, nb*cuckooSlots), rng: 0x2545F4914F6CDD1D}, nil
}

func (c *Cuckoo) Len() uint64         { return c.count }
func (c *Cuckoo) Capacity() uint64    { return c.nb * cuckooSlots }
func (c *Cuckoo) Bytes() int          { return len(c.fp) * 2 }
func (c *Cuckoo) LoadFactor() float64 { return float64(c.count) / float64(c.Capacity()) }

func (c *Cuckoo) locate(key []byte) (uint64, uint16) {
	h := Hash64(key, 0x51ed)
	f := uint16(h >> 48)
	if f == 0 {
		f = 1
	}
	return (h & 0xffffffff) & (c.nb - 1), f
}

func (c *Cuckoo) alt(i uint64, f uint16) uint64 {
	return (i ^ Mix64(uint64(f))) & (c.nb - 1)
}

func (c *Cuckoo) put(i uint64, f uint16) bool {
	b := c.fp[i*cuckooSlots : i*cuckooSlots+cuckooSlots]
	for s := range b {
		if b[s] == 0 {
			b[s] = f
			return true
		}
	}
	return false
}

func (c *Cuckoo) next() uint64 {
	c.rng ^= c.rng << 13
	c.rng ^= c.rng >> 7
	c.rng ^= c.rng << 17
	return c.rng
}

var ErrCuckooFull = errors.New("cuckoo: filter is full")

// Add inserts key. On ErrCuckooFull the filter is left exactly as it was.
func (c *Cuckoo) Add(key []byte) error {
	i1, f := c.locate(key)
	i2 := c.alt(i1, f)
	if c.put(i1, f) || c.put(i2, f) {
		c.count++
		return nil
	}
	type kick struct {
		bucket uint64
		slot   int
		old    uint16
	}
	var path []kick
	i := i1
	if c.next()&1 == 1 {
		i = i2
	}
	for n := 0; n < cuckooMaxKick; n++ {
		s := int(c.next() % cuckooSlots)
		pos := i*cuckooSlots + uint64(s)
		old := c.fp[pos]
		c.fp[pos] = f
		path = append(path, kick{i, s, old})
		f = old
		i = c.alt(i, f)
		if c.put(i, f) {
			c.count++
			return nil
		}
	}
	for j := len(path) - 1; j >= 0; j-- { // roll back
		k := path[j]
		c.fp[k.bucket*cuckooSlots+uint64(k.slot)] = k.old
	}
	return ErrCuckooFull
}

// AddUnique inserts key only if it is not already (probably) present, giving
// set semantics. A cuckoo filter holds at most 8 copies of one fingerprint, so
// streams with repeated keys must use this rather than Add. It reports whether
// the key was newly inserted.
func (c *Cuckoo) AddUnique(key []byte) (bool, error) {
	if c.Contains(key) {
		return false, nil
	}
	if err := c.Add(key); err != nil {
		return false, err
	}
	return true, nil
}

func (c *Cuckoo) has(i uint64, f uint16) int {
	for s := 0; s < cuckooSlots; s++ {
		if c.fp[i*cuckooSlots+uint64(s)] == f {
			return s
		}
	}
	return -1
}

func (c *Cuckoo) Contains(key []byte) bool {
	i1, f := c.locate(key)
	return c.has(i1, f) >= 0 || c.has(c.alt(i1, f), f) >= 0
}

// Delete removes one copy of key's fingerprint; reports whether one was found.
func (c *Cuckoo) Delete(key []byte) bool {
	i1, f := c.locate(key)
	for _, i := range [2]uint64{i1, c.alt(i1, f)} {
		if s := c.has(i, f); s >= 0 {
			c.fp[i*cuckooSlots+uint64(s)] = 0
			c.count--
			return true
		}
	}
	return false
}
