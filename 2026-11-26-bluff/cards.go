package main

import (
	"fmt"
	"math/bits"
	"strings"
)

// Cards are ints 0..51: rank = c/4 (0 = deuce … 12 = ace), suit = c%4 (c d h s).
const rankChars = "23456789TJQKA"
const suitChars = "cdhs"

func mkCard(rank, suit int) int { return rank*4 + suit }

// CardString renders a card like "As".
func CardString(c int) string { return string(rankChars[c/4]) + string(suitChars[c%4]) }

// ParseCard parses "As", "td", ...
func ParseCard(s string) (int, error) {
	if len(s) != 2 {
		return 0, fmt.Errorf("bad card %q", s)
	}
	r := strings.IndexByte(rankChars, byte(strings.ToUpper(s)[0]))
	su := strings.IndexByte(suitChars, byte(strings.ToLower(s)[1]))
	if r < 0 || su < 0 {
		return 0, fmt.Errorf("bad card %q", s)
	}
	return mkCard(r, su), nil
}

// ParseCards parses a run of cards: "AsKd7h" or "As Kd 7h" or "As,Kd".
func ParseCards(s string) ([]int, error) {
	s = strings.NewReplacer(" ", "", ",", "").Replace(s)
	if len(s)%2 != 0 {
		return nil, fmt.Errorf("bad card list %q", s)
	}
	var out []int
	seen := uint64(0)
	for i := 0; i < len(s); i += 2 {
		c, err := ParseCard(s[i : i+2])
		if err != nil {
			return nil, err
		}
		if seen>>uint(c)&1 == 1 {
			return nil, fmt.Errorf("duplicate card %s", CardString(c))
		}
		seen |= 1 << uint(c)
		out = append(out, c)
	}
	return out, nil
}

// Hand categories.
const (
	HighCard = iota
	OnePair
	TwoPair
	Trips
	Straight
	Flush
	FullHouse
	Quads
	StraightFlush
)

var categoryNames = [...]string{"High card", "Pair", "Two pair", "Three of a kind", "Straight", "Flush", "Full house", "Four of a kind", "Straight flush"}

// CategoryOf extracts the category from a score.
func CategoryOf(score uint32) int { return int(score >> 20) }

// straightTop returns the top rank of the best straight in a 13-bit rank mask, or -1.
// The wheel (A-2-3-4-5) has top rank 3 (the five).
func straightTop(mask uint32) int {
	// add ace as low card at bit 13 equivalent: replicate bit 12 into position -1 by shifting
	m := mask<<1 | (mask >> 12 & 1)
	for top := 13; top >= 4; top-- { // in shifted space bit index = rank+1
		w := uint32(0x1F) << uint(top-4)
		if m&w == w {
			return top - 1
		}
	}
	return -1
}

// build packs head (nh ranks already shifted in) followed by the nk highest ranks of mask,
// left-aligned into five nibbles.
func build(head uint32, nh int, mask uint32, nk int) uint32 {
	s := head
	n := nh
	for r := 12; r >= 0 && nk > 0; r-- {
		if mask>>uint(r)&1 == 1 {
			s = s<<4 | uint32(r)
			n++
			nk--
		}
	}
	return s << uint(4*(5-n))
}

// Eval scores 5 to 7 cards; higher is better. Equal scores tie. It does not allocate.
func Eval(cards []int) uint32 {
	var cnt [13]uint8
	var suitMask [4]uint32
	var suitCnt [4]uint8
	var all uint32
	for _, c := range cards {
		r, s := c>>2, c&3
		cnt[r]++
		suitMask[s] |= 1 << uint(r)
		suitCnt[s]++
		all |= 1 << uint(r)
	}
	for s := 0; s < 4; s++ {
		if suitCnt[s] >= 5 {
			if top := straightTop(suitMask[s]); top >= 0 {
				return uint32(StraightFlush)<<20 | build(uint32(top), 1, 0, 0)
			}
			return uint32(Flush)<<20 | build(0, 0, suitMask[s], 5)
		}
	}
	quad, t1, t2, p1, p2 := -1, -1, -1, -1, -1
	for r := 12; r >= 0; r-- {
		switch cnt[r] {
		case 4:
			if quad < 0 {
				quad = r
			}
		case 3:
			if t1 < 0 {
				t1 = r
			} else if t2 < 0 {
				t2 = r
			}
		case 2:
			if p1 < 0 {
				p1 = r
			} else if p2 < 0 {
				p2 = r
			}
		}
	}
	switch {
	case quad >= 0:
		return uint32(Quads)<<20 | build(uint32(quad), 1, all&^(1<<uint(quad)), 1)
	case t1 >= 0 && (t2 >= 0 || p1 >= 0):
		second := t2
		if p1 > second {
			second = p1
		}
		return uint32(FullHouse)<<20 | build(uint32(t1)<<4|uint32(second), 2, 0, 0)
	}
	if top := straightTop(all); top >= 0 {
		return uint32(Straight)<<20 | build(uint32(top), 1, 0, 0)
	}
	switch {
	case t1 >= 0:
		return uint32(Trips)<<20 | build(uint32(t1), 1, all&^(1<<uint(t1)), 2)
	case p2 >= 0:
		return uint32(TwoPair)<<20 | build(uint32(p1)<<4|uint32(p2), 2, all&^(1<<uint(p1)|1<<uint(p2)), 1)
	case p1 >= 0:
		return uint32(OnePair)<<20 | build(uint32(p1), 1, all&^(1<<uint(p1)), 3)
	}
	return uint32(HighCard)<<20 | build(0, 0, all, 5)
}

// DescribeScore gives a human-readable hand name.
func DescribeScore(s uint32) string {
	cat := CategoryOf(s)
	r := func(i int) string { return string(rankChars[(s>>uint(4*(4-i)))&0xF]) }
	switch cat {
	case StraightFlush:
		if r(0) == "A" {
			return "Royal flush"
		}
		return "Straight flush, " + r(0) + " high"
	case Quads:
		return "Four " + r(0) + "s"
	case FullHouse:
		return "Full house, " + r(0) + "s full of " + r(1) + "s"
	case Flush:
		return "Flush, " + r(0) + " high"
	case Straight:
		return "Straight, " + r(0) + " high"
	case Trips:
		return "Three " + r(0) + "s"
	case TwoPair:
		return "Two pair, " + r(0) + "s and " + r(1) + "s"
	case OnePair:
		return "Pair of " + r(0) + "s"
	}
	return "High card " + r(0)
}

func popcount(x uint64) int { return bits.OnesCount64(x) }
