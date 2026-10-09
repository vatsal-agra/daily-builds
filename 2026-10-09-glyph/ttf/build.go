package ttf

import (
	"bytes"
	"fmt"
	"math"
	"sort"
	"unicode/utf16"
)

// GlyphSpec is one glyph to be written: an outline in font units and its advance.
type GlyphSpec struct {
	Outline Outline
	Advance int
}

// Spec describes a whole font for Build. Glyph 0 is .notdef.
type Spec struct {
	Family, Style string
	UnitsPerEm    int
	Ascent        int
	Descent       int // negative
	LineGap       int
	Glyphs        []GlyphSpec
	Cmap          map[rune]uint16
	Kern          map[[2]uint16]int
}

// Build serialises a Spec as a valid TrueType font (glyf outlines, cmap 4 [+12],
// kern format 0, correct table and whole-file checksums).
func Build(s Spec) ([]byte, error) {
	if s.UnitsPerEm < 16 || s.UnitsPerEm > 16384 {
		return nil, fmt.Errorf("unitsPerEm %d out of range", s.UnitsPerEm)
	}
	n := len(s.Glyphs)
	if n == 0 || n > 65535 {
		return nil, fmt.Errorf("need 1..65535 glyphs, have %d", n)
	}
	for r, g := range s.Cmap {
		if int(g) >= n || r < 0 || r > 0x10FFFF {
			return nil, fmt.Errorf("cmap entry U+%04X → glyph %d invalid", r, g)
		}
	}
	// glyf + loca
	var glyf bytes.Buffer
	offs := make([]int, n+1)
	var xMin, yMin, xMax, yMax int
	first := true
	maxPts, maxCont := 0, 0
	lsbs := make([]int, n)
	for i, g := range s.Glyphs {
		offs[i] = glyf.Len()
		enc, bb, ok, err := encodeGlyph(g.Outline)
		if err != nil {
			return nil, fmt.Errorf("glyph %d: %w", i, err)
		}
		if ok {
			glyf.Write(enc)
			for glyf.Len()%4 != 0 {
				glyf.WriteByte(0)
			}
			lsbs[i] = bb[0]
			if first {
				xMin, yMin, xMax, yMax, first = bb[0], bb[1], bb[2], bb[3], false
			} else {
				xMin, yMin, xMax, yMax = min(xMin, bb[0]), min(yMin, bb[1]), max(xMax, bb[2]), max(yMax, bb[3])
			}
			maxPts = max(maxPts, g.Outline.NumPoints())
			maxCont = max(maxCont, len(g.Outline.Contours))
		}
	}
	offs[n] = glyf.Len()
	long := glyf.Len() > 0x1FFFE
	var loca bytes.Buffer
	for _, o := range offs {
		if long {
			loca.Write(be32(o))
		} else {
			loca.Write(be16(o / 2))
		}
	}
	// hmtx (full metrics for every glyph keeps it simple and always valid)
	var hmtx bytes.Buffer
	maxAdv := 0
	for i, g := range s.Glyphs {
		if g.Advance < 0 || g.Advance > 0xFFFF {
			return nil, fmt.Errorf("glyph %d: advance %d out of range", i, g.Advance)
		}
		hmtx.Write(be16(g.Advance))
		hmtx.Write(be16(lsbs[i]))
		maxAdv = max(maxAdv, g.Advance)
	}
	head := make([]byte, 54)
	copy(head[0:], be32(0x00010000))
	copy(head[4:], be32(0x00010000)) // fontRevision 1.0
	copy(head[12:], be32(magicHead))
	copy(head[16:], be16(0x000B)) // flags: baseline at 0, lsb at x=0, ...
	copy(head[18:], be16(s.UnitsPerEm))
	copy(head[36:], be16(xMin&0xFFFF))
	copy(head[38:], be16(yMin&0xFFFF))
	copy(head[40:], be16(xMax&0xFFFF))
	copy(head[42:], be16(yMax&0xFFFF))
	copy(head[46:], be16(8)) // lowestRecPPEM
	copy(head[48:], be16(2)) // fontDirectionHint
	if long {
		copy(head[50:], be16(1))
	}
	hhea := make([]byte, 36)
	copy(hhea[0:], be32(0x00010000))
	copy(hhea[4:], be16(s.Ascent&0xFFFF))
	copy(hhea[6:], be16(s.Descent&0xFFFF))
	copy(hhea[8:], be16(s.LineGap&0xFFFF))
	copy(hhea[10:], be16(maxAdv))
	copy(hhea[34:], be16(n))
	maxp := make([]byte, 32)
	copy(maxp[0:], be32(0x00010000))
	copy(maxp[4:], be16(n))
	copy(maxp[6:], be16(maxPts))
	copy(maxp[8:], be16(maxCont))
	os2 := make([]byte, 78)
	copy(os2[4:], be16(400))                  // weight
	copy(os2[6:], be16(5))                    // width class
	copy(os2[30:], be16(0))                   // family class
	copy(os2[68:], be16(s.Ascent&0xFFFF))     // typo ascender
	copy(os2[70:], be16(s.Descent&0xFFFF))    // typo descender
	copy(os2[72:], be16(s.LineGap&0xFFFF))    // typo line gap
	copy(os2[74:], be16(max(s.Ascent, yMax))) // win ascent
	copy(os2[76:], be16(max(-s.Descent, -yMin)))
	post := make([]byte, 32)
	copy(post[0:], be32(0x00030000))
	tables := map[string][]byte{
		"head": head, "hhea": hhea, "maxp": maxp, "OS/2": os2, "post": post,
		"hmtx": hmtx.Bytes(), "loca": loca.Bytes(), "glyf": glyf.Bytes(),
		"cmap": buildCmap(s.Cmap), "name": buildName(s.Family, s.Style),
	}
	if len(s.Kern) > 0 {
		k, err := buildKern(s.Kern)
		if err != nil {
			return nil, err
		}
		tables["kern"] = k
	}
	return assemble(tables), nil
}

// encodeGlyph encodes a simple glyph; ok=false for an empty outline.
func encodeGlyph(o Outline) (enc []byte, bbox [4]int, ok bool, err error) {
	var pts []Point
	var ends []int
	for _, c := range o.Contours {
		if len(c) == 0 {
			continue
		}
		pts = append(pts, c...)
		ends = append(ends, len(pts)-1)
	}
	if len(pts) == 0 {
		return nil, bbox, false, nil
	}
	if len(ends) > 32767 || len(pts) > 65535 {
		return nil, bbox, false, fmt.Errorf("too many contours/points")
	}
	xs, ys := make([]int, len(pts)), make([]int, len(pts))
	bbox = [4]int{math.MaxInt32, math.MaxInt32, math.MinInt32, math.MinInt32}
	for i, p := range pts {
		if math.IsNaN(p.X) || math.IsNaN(p.Y) || math.Abs(p.X) > 32767 || math.Abs(p.Y) > 32767 {
			return nil, bbox, false, fmt.Errorf("coordinate (%v,%v) out of int16 range", p.X, p.Y)
		}
		xs[i], ys[i] = int(math.Round(p.X)), int(math.Round(p.Y))
		bbox = [4]int{min(bbox[0], xs[i]), min(bbox[1], ys[i]), max(bbox[2], xs[i]), max(bbox[3], ys[i])}
	}
	var b bytes.Buffer
	b.Write(be16(len(ends)))
	for _, v := range bbox {
		b.Write(be16(v & 0xFFFF))
	}
	for _, e := range ends {
		b.Write(be16(e))
	}
	b.Write(be16(0)) // no instructions
	flags := make([]byte, len(pts))
	var xb, yb bytes.Buffer
	px, py := 0, 0
	for i := range pts {
		var fl byte
		if pts[i].On {
			fl |= 1
		}
		dx, dy := xs[i]-px, ys[i]-py
		px, py = xs[i], ys[i]
		if dx < -32768 || dx > 32767 || dy < -32768 || dy > 32767 {
			// glyf stores each delta as int16; wrapping would silently corrupt the outline
			return nil, bbox, false, fmt.Errorf("point %d: delta (%d,%d) does not fit in int16", i, dx, dy)
		}
		fl |= coord(&xb, dx, 2, 16)
		fl |= coord(&yb, dy, 4, 32)
		flags[i] = fl
	}
	for i := 0; i < len(flags); {
		j := i
		for j+1 < len(flags) && flags[j+1] == flags[i] && j-i < 255 {
			j++
		}
		if j > i {
			b.WriteByte(flags[i] | 8)
			b.WriteByte(byte(j - i))
		} else {
			b.WriteByte(flags[i])
		}
		i = j + 1
	}
	b.Write(xb.Bytes())
	b.Write(yb.Bytes())
	return b.Bytes(), bbox, true, nil
}

// coord appends one coordinate delta in the most compact form and returns its flag bits.
func coord(b *bytes.Buffer, d int, shortBit, sameBit byte) byte {
	switch {
	case d == 0:
		return sameBit
	case d > 0 && d < 256:
		b.WriteByte(byte(d))
		return shortBit | sameBit
	case d < 0 && d > -256:
		b.WriteByte(byte(-d))
		return shortBit
	}
	b.Write(be16(d & 0xFFFF))
	return 0
}

func be16(v int) []byte { return []byte{byte(v >> 8), byte(v)} }
func be32(v int) []byte { return []byte{byte(v >> 24), byte(v >> 16), byte(v >> 8), byte(v)} }

func buildCmap(m map[rune]uint16) []byte {
	runes := make([]rune, 0, len(m))
	for r := range m {
		runes = append(runes, r)
	}
	sort.Slice(runes, func(i, j int) bool { return runes[i] < runes[j] })
	// format 4: group consecutive runes with consecutive glyphs into segments
	type seg struct{ start, end, delta int }
	var segs []seg
	hasAstral := false
	for _, r := range runes {
		if r > 0xFFFE {
			hasAstral = true
			continue
		}
		d := (int(m[r]) - int(r)) & 0xFFFF
		if k := len(segs) - 1; k >= 0 && segs[k].end == int(r)-1 && segs[k].delta == d {
			segs[k].end = int(r)
		} else {
			segs = append(segs, seg{int(r), int(r), d})
		}
	}
	segs = append(segs, seg{0xFFFF, 0xFFFF, 1})
	sc := len(segs)
	var f4 bytes.Buffer
	f4.Write(be16(4))
	f4.Write(be16(16 + 8*sc))
	f4.Write(be16(0))
	f4.Write(be16(2 * sc))
	sr := 1
	for sr*2 <= sc {
		sr *= 2
	}
	f4.Write(be16(2 * sr))
	es := 0
	for 1<<es < sr {
		es++
	}
	f4.Write(be16(es))
	f4.Write(be16(2*sc - 2*sr))
	for _, s := range segs {
		f4.Write(be16(s.end))
	}
	f4.Write(be16(0))
	for _, s := range segs {
		f4.Write(be16(s.start))
	}
	for _, s := range segs {
		f4.Write(be16(s.delta))
	}
	for range segs {
		f4.Write(be16(0))
	}
	type enc struct {
		plat, enc int
		data      []byte
	}
	subs := []enc{{3, 1, f4.Bytes()}}
	if hasAstral {
		var f12 bytes.Buffer
		var groups [][3]int
		for _, r := range runes {
			g := int(m[r])
			if k := len(groups) - 1; k >= 0 && groups[k][1] == int(r)-1 && groups[k][2]+int(r)-groups[k][0] == g {
				groups[k][1] = int(r)
			} else {
				groups = append(groups, [3]int{int(r), int(r), g})
			}
		}
		f12.Write(be16(12))
		f12.Write(be16(0))
		f12.Write(be32(16 + 12*len(groups)))
		f12.Write(be32(0))
		f12.Write(be32(len(groups)))
		for _, g := range groups {
			f12.Write(be32(g[0]))
			f12.Write(be32(g[1]))
			f12.Write(be32(g[2]))
		}
		subs = append(subs, enc{3, 10, f12.Bytes()}) // directory order: (3,1) before (3,10)
	}
	var out bytes.Buffer
	out.Write(be16(0))
	out.Write(be16(len(subs)))
	off := 4 + 8*len(subs)
	for _, s := range subs {
		out.Write(be16(s.plat))
		out.Write(be16(s.enc))
		out.Write(be32(off))
		off += len(s.data)
	}
	for _, s := range subs {
		out.Write(s.data)
	}
	return out.Bytes()
}

func buildName(family, style string) []byte {
	if family == "" {
		family = "Glyph"
	}
	if style == "" {
		style = "Regular"
	}
	full := family + " " + style
	ps := ""
	for _, r := range full {
		if r > 32 && r < 127 {
			ps += string(r)
		} else if r == ' ' {
			ps += "-"
		}
	}
	recs := []struct {
		id int
		s  string
	}{{1, family}, {2, style}, {4, full}, {6, ps}}
	var strs bytes.Buffer
	var hdr bytes.Buffer
	hdr.Write(be16(0))
	hdr.Write(be16(len(recs)))
	hdr.Write(be16(6 + 12*len(recs)))
	for _, r := range recs {
		u := utf16.Encode([]rune(r.s))
		hdr.Write(be16(3))
		hdr.Write(be16(1))
		hdr.Write(be16(0x409))
		hdr.Write(be16(r.id))
		hdr.Write(be16(2 * len(u)))
		hdr.Write(be16(strs.Len()))
		for _, c := range u {
			strs.Write(be16(int(c)))
		}
	}
	return append(hdr.Bytes(), strs.Bytes()...)
}

func buildKern(m map[[2]uint16]int) ([]byte, error) {
	type pr struct {
		l, r uint16
		v    int
	}
	var ps []pr
	for k, v := range m {
		if v == 0 {
			continue
		}
		if v < -32768 || v > 32767 {
			return nil, fmt.Errorf("kern value %d out of range", v)
		}
		ps = append(ps, pr{k[0], k[1], v})
	}
	if len(ps) == 0 {
		return nil, nil
	}
	if len(ps) > maxKernPairs { // 14 + 6n must fit the 16-bit subtable length
		return nil, fmt.Errorf("too many kern pairs (%d > 10920) for a format-0 subtable", len(ps))
	}
	sort.Slice(ps, func(i, j int) bool { return uint32(ps[i].l)<<16|uint32(ps[i].r) < uint32(ps[j].l)<<16|uint32(ps[j].r) })
	var b bytes.Buffer
	b.Write(be16(0))
	b.Write(be16(1))
	b.Write(be16(0))
	b.Write(be16(14 + 6*len(ps)))
	b.Write(be16(1)) // horizontal, format 0
	b.Write(be16(len(ps)))
	sr := 1
	for sr*2 <= len(ps) {
		sr *= 2
	}
	es := 0
	for 1<<es < sr {
		es++
	}
	b.Write(be16(sr * 6))
	b.Write(be16(es))
	b.Write(be16(len(ps)*6 - sr*6))
	for _, p := range ps {
		b.Write(be16(int(p.l)))
		b.Write(be16(int(p.r)))
		b.Write(be16(p.v & 0xFFFF))
	}
	return b.Bytes(), nil
}

// assemble lays out the sfnt: sorted directory, 4-byte padded tables, checksums,
// and head.checksumAdjustment.
func assemble(tables map[string][]byte) []byte {
	tags := make([]string, 0, len(tables))
	for t := range tables {
		tags = append(tags, t)
	}
	sort.Strings(tags)
	n := len(tags)
	sr := 1
	for sr*2 <= n {
		sr *= 2
	}
	es := 0
	for 1<<es < sr {
		es++
	}
	var out bytes.Buffer
	out.Write(be32(0x00010000))
	out.Write(be16(n))
	out.Write(be16(sr * 16))
	out.Write(be16(es))
	out.Write(be16(n*16 - sr*16))
	off := 12 + 16*n
	var body bytes.Buffer
	headOff := 0
	for _, t := range tags {
		d := tables[t]
		out.WriteString(t)
		out.Write(be32(int(Checksum(d))))
		out.Write(be32(off + body.Len()))
		out.Write(be32(len(d)))
		if t == "head" {
			headOff = off + body.Len()
		}
		body.Write(d)
		for body.Len()%4 != 0 {
			body.WriteByte(0)
		}
	}
	// the directory checksum for head was computed with adjustment = 0, as required
	out.Write(body.Bytes())
	b := out.Bytes()
	adj := 0xB1B0AFBA - Checksum(b)
	copy(b[headOff+8:], be32(int(adj)))
	return b
}

// Subset writes a new font containing .notdef plus the glyphs needed for text
// (composites are flattened into simple glyphs; kerning among kept glyphs is preserved).
func (f *Font) Subset(text string) ([]byte, error) {
	remap := map[uint16]uint16{0: 0}
	order := []uint16{0}
	cmap := map[rune]uint16{}
	for _, r := range text {
		if r < 0x20 && r != '\t' || r == 0x7f {
			continue
		}
		g := f.Index(r)
		if g == 0 {
			continue // unmapped: leave out; .notdef covers it
		}
		if _, ok := remap[g]; !ok {
			remap[g] = uint16(len(order))
			order = append(order, g)
		}
		cmap[r] = remap[g]
	}
	spec := Spec{
		Family: f.Name(1), Style: f.Name(2), UnitsPerEm: f.UnitsPerEm,
		Ascent: f.Ascent, Descent: f.Descent, LineGap: f.LineGap,
		Cmap: cmap, Kern: map[[2]uint16]int{},
	}
	for _, g := range order {
		o, err := f.Glyph(g)
		if err != nil {
			return nil, err
		}
		spec.Glyphs = append(spec.Glyphs, GlyphSpec{Outline: o, Advance: f.Advance(g)})
	}
	if f.HasKerning() {
		for _, l := range order {
			for _, r := range order {
				if k := f.Kerning(l, r); k != 0 {
					spec.Kern[[2]uint16{remap[l], remap[r]}] = k
				}
			}
		}
	}
	if len(spec.Kern) > maxKernPairs { // keep the strongest pairs that fit one format-0 subtable
		type kv struct {
			k [2]uint16
			v int
		}
		all := make([]kv, 0, len(spec.Kern))
		for k, v := range spec.Kern {
			all = append(all, kv{k, v})
		}
		sort.Slice(all, func(i, j int) bool {
			ai, aj := abs(all[i].v), abs(all[j].v)
			if ai != aj {
				return ai > aj
			}
			return uint32(all[i].k[0])<<16|uint32(all[i].k[1]) < uint32(all[j].k[0])<<16|uint32(all[j].k[1])
		})
		spec.Kern = map[[2]uint16]int{}
		for _, e := range all[:maxKernPairs] {
			spec.Kern[e.k] = e.v
		}
	}
	return Build(spec)
}

const maxKernPairs = 10920

func abs(v int) int {
	if v < 0 {
		return -v
	}
	return v
}
