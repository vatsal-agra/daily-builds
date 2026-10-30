package main

import (
	"bytes"
	"encoding/hex"
	"flag"
	"fmt"
	"image"
	"image/png"
	"math/rand"
	"os"
	"sort"
	"strconv"
	"strings"

	"quietzone/qr"
	"quietzone/scan"
	"quietzone/sim"
)

func parseHex(s string) ([]byte, error) {
	s = strings.NewReplacer(" ", "", ":", "", "\n", "").Replace(s)
	b, err := hex.DecodeString(s)
	if err != nil {
		return nil, fmt.Errorf("bad hex: %v", err)
	}
	return b, nil
}

func cmdRS(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: qz rs encode|decode|demo ...")
	}
	sub, rest := args[0], args[1:]
	fs := flag.NewFlagSet("rs "+sub, flag.ContinueOnError)
	ecc := fs.Int("ecc", 10, "number of parity bytes")
	erase := fs.String("erase", "", "decode: comma-separated byte indices known to be bad (erasures)")
	k := fs.Int("k", 16, "demo: data bytes")
	nerr := fs.Int("errors", 3, "demo: unknown errors to inject")
	ner := fs.Int("erasures", 0, "demo: known erasures to inject")
	seed := fs.Int64("seed", 1, "demo: random seed")
	if err := fs.Parse(rest); err != nil {
		return err
	}
	if *ecc < 1 || *ecc > 254 {
		return fmt.Errorf("-ecc must be 1..254")
	}
	switch sub {
	case "encode":
		if fs.NArg() != 1 {
			return fmt.Errorf("usage: qz rs encode -ecc N HEXDATA")
		}
		d, err := parseHex(fs.Arg(0))
		if err != nil {
			return err
		}
		if len(d)+*ecc > 255 {
			return fmt.Errorf("data+parity must be at most 255 bytes")
		}
		fmt.Println(hex.EncodeToString(qr.RSEncode(d, *ecc)))
	case "decode":
		if fs.NArg() != 1 {
			return fmt.Errorf("usage: qz rs decode -ecc N [-erase i,j] HEX(data+parity)")
		}
		msg, err := parseHex(fs.Arg(0))
		if err != nil {
			return err
		}
		var er []int
		for _, p := range strings.Split(*erase, ",") {
			if p = strings.TrimSpace(p); p != "" {
				n, err := strconv.Atoi(p)
				if err != nil {
					return fmt.Errorf("bad erasure index %q", p)
				}
				er = append(er, n)
			}
		}
		res, err := qr.RSDecode(msg, *ecc, er)
		if err != nil {
			return err
		}
		fmt.Printf("corrected %d byte(s) at %v\n%s\n", len(res.Positions), res.Positions, hex.EncodeToString(msg[:len(msg)-*ecc]))
	case "demo":
		if *k+*ecc > 255 || *nerr+*ner > *k+*ecc {
			return fmt.Errorf("-k + -ecc must be <= 255 and damage cannot exceed the block")
		}
		rng := rand.New(rand.NewSource(*seed))
		data := make([]byte, *k)
		rng.Read(data)
		block := append(append([]byte(nil), data...), qr.RSEncode(data, *ecc)...)
		bad := append([]byte(nil), block...)
		perm := rng.Perm(len(bad))
		var er []int
		for _, p := range perm[:*ner] {
			bad[p] ^= byte(1 + rng.Intn(255))
			er = append(er, p)
		}
		sort.Ints(er)
		var ep []int
		for _, p := range perm[*ner : *ner+*nerr] {
			bad[p] ^= byte(1 + rng.Intn(255))
			ep = append(ep, p)
		}
		sort.Ints(ep)
		fmt.Printf("RS(%d,%d) over GF(256): corrects 2·errors + erasures ≤ %d\n", len(block), *k, *ecc)
		fmt.Printf("sent     %s\nreceived %s\n", hex.EncodeToString(block), hex.EncodeToString(bad))
		fmt.Printf("injected %d unknown error(s) at %v and %d known erasure(s) at %v  (cost %d of %d)\n", *nerr, ep, *ner, er, 2**nerr+*ner, *ecc)
		res, err := qr.RSDecode(bad, *ecc, er)
		if err != nil {
			fmt.Println("decode: FAILED —", err)
			return nil
		}
		fmt.Printf("decode:  repaired %d byte(s) at %v\n", len(res.Positions), res.Positions)
		fmt.Printf("restored %s\nidentical to sent: %v\n", hex.EncodeToString(bad), bytes.Equal(bad, block))
	default:
		return fmt.Errorf("unknown rs subcommand %q", sub)
	}
	return nil
}

func cmdExplain(args []string) error {
	fs := flag.NewFlagSet("explain", flag.ContinueOnError)
	eccS := fs.String("ecc", "M", "error correction level")
	ver := fs.Int("v", 0, "force version")
	showMap := fs.Bool("map", false, "print the module-role map")
	if err := fs.Parse(args); err != nil {
		return err
	}
	e, ok := qr.ParseECC(*eccS)
	if !ok {
		return fmt.Errorf("bad -ecc %q", *eccS)
	}
	text, err := textArg(fs)
	if err != nil {
		return err
	}
	opt := qr.Options{ECC: e}
	if *ver != 0 {
		opt.MinVersion, opt.MaxVersion = *ver, *ver
	}
	c, err := qr.EncodeText(text, opt)
	if err != nil {
		return err
	}
	ex := c.Explain()
	fmt.Printf("Version %d  (%d×%d modules)   ECC %v   mask %d\n", ex.Version, ex.Size, ex.Size, ex.ECC, ex.Mask)
	fmt.Println("\nSegments")
	for _, s := range ex.Segments {
		fmt.Printf("  %-18s %5d chars %6d bits\n", s.Mode, s.Chars, s.Bits)
	}
	fmt.Printf("  stream: %d bits used + %d bits terminator/padding = %d bit capacity (%d data codewords)\n", ex.DataBits, ex.PadBits, ex.CapacityBits, ex.CapacityBits/8)
	fmt.Printf("\nReed–Solomon blocks (%d codewords total, %d remainder bits)\n", ex.TotalCodewords, ex.RemainderBits)
	fmt.Printf("  %-6s %6s %6s %12s\n", "block", "data", "ecc", "repairs ≤")
	for i, b := range ex.Blocks {
		fmt.Printf("  %-6d %6d %6d %7d byte(s)\n", i, b.DataLen, b.ECCLen, b.Correctable)
	}
	fmt.Println("\nMask penalties (lower wins)")
	fmt.Printf("  %-5s %6s %6s %6s %6s %8s\n", "mask", "N1", "N2", "N3", "N4", "total")
	for mk, p := range ex.Penalties {
		tot := p[0] + p[1] + p[2] + p[3]
		mark := ""
		if mk == ex.Mask {
			mark = "  ← chosen"
		}
		fmt.Printf("  %-5d %6d %6d %6d %6d %8d%s\n", mk, p[0], p[1], p[2], p[3], tot, mark)
	}
	if *showMap {
		letters := map[qr.Kind]byte{qr.KFinder: 'F', qr.KSeparator: '.', qr.KTiming: 'T', qr.KAlign: 'A', qr.KFormat: 'f', qr.KVersion: 'v', qr.KDark: 'K'}
		fmt.Println("\nModule roles  (F finder, T timing, A alignment, f format, v version, K dark module, d data, e parity)")
		for y := 0; y < ex.Size; y++ {
			var sb strings.Builder
			for x := 0; x < ex.Size; x++ {
				mi := ex.Modules[y*ex.Size+x]
				ch := letters[mi.Kind]
				if mi.Kind == qr.KData {
					ch = 'd'
					if mi.CW >= 0 && ex.CWIsECC[mi.CW] {
						ch = 'e'
					} else if mi.CW < 0 {
						ch = '-'
					}
				}
				sb.WriteByte(ch)
				sb.WriteByte(' ')
			}
			fmt.Println(" ", sb.String())
		}
	}
	return nil
}

func cmdDamage(args []string) error {
	fs := flag.NewFlagSet("damage", flag.ContinueOnError)
	eccS := fs.String("ecc", "Q", "error correction level")
	flips := fs.Int("flips", 20, "number of random modules to flip")
	where := fs.String("where", "data", "damage region: data (codeword area only) or any (including finders, format info)")
	logo := fs.Float64("logo", 0, "blank a centred square covering this fraction of the width (e.g. 0.2)")
	seed := fs.Int64("seed", 1, "random seed")
	sweep := fs.Bool("sweep", false, "measure how many random flips each ECC level survives")
	trials := fs.Int("trials", 40, "sweep: Monte-Carlo trials per level")
	if err := fs.Parse(args); err != nil {
		return err
	}
	e, ok := qr.ParseECC(*eccS)
	if !ok {
		return fmt.Errorf("bad -ecc %q", *eccS)
	}
	text, err := textArg(fs)
	if err != nil {
		return err
	}
	if *flips < 0 || *logo < 0 || *logo > 0.9 || (*where != "data" && *where != "any") {
		return fmt.Errorf("-flips must be >= 0, -logo in [0,0.9], -where data|any")
	}
	if *sweep {
		return damageSweep(text, *seed, *trials)
	}
	c, err := qr.EncodeText(text, qr.Options{ECC: e})
	if err != nil {
		return err
	}
	ex := c.Explain()
	rng := rand.New(rand.NewSource(*seed))
	m := c.Matrix.Clone()
	hit := map[int]bool{}
	cwAt := map[[2]int]int{}
	for cw := 0; cw < ex.TotalCodewords; cw++ {
		for _, p := range c.CodewordModules(cw) {
			cwAt[p] = cw
		}
	}
	var pool [][2]int
	for y := 0; y < m.N; y++ {
		for x := 0; x < m.N; x++ {
			if _, isData := cwAt[[2]int{x, y}]; isData || *where == "any" {
				pool = append(pool, [2]int{x, y})
			}
		}
	}
	if *flips > len(pool) {
		*flips = len(pool)
	}
	for _, i := range rng.Perm(len(pool))[:*flips] {
		p := pool[i]
		m.Set(p[0], p[1], !m.Get(p[0], p[1]))
		if cw, ok := cwAt[p]; ok {
			hit[cw] = true
		}
	}
	var erased *qr.Matrix
	if *logo > 0 {
		erased = qr.NewMatrix(m.N)
		side := int(float64(m.N) * *logo)
		lo := (m.N - side) / 2
		for y := lo; y < lo+side; y++ {
			for x := lo; x < lo+side; x++ {
				if cw, ok := cwAt[[2]int{x, y}]; ok {
					hit[cw] = true
				}
				m.Set(x, y, false) // the logo paints light over everything beneath it
				erased.Set(x, y, true)
			}
		}
		fmt.Printf("logo: %d×%d modules (%.1f%% of the area) blanked at the centre\n", side, side, 100*float64(side*side)/float64(m.N*m.N))
	}
	var damaged []int
	for cw := range hit {
		damaged = append(damaged, cw)
	}
	sort.Ints(damaged)
	pred, per := ex.Verdict(damaged)
	fmt.Printf("v%d-%v: %d module flip(s) → %d of %d codewords damaged\n", c.Version, c.ECC, *flips, len(damaged), ex.TotalCodewords)
	fmt.Print("per-block damage / repair capacity:")
	for b, n := range per {
		fmt.Printf("  b%d %d/%d", b, n, ex.Blocks[b].Correctable)
	}
	fmt.Printf("\nguaranteed recoverable (no erasure hints): %v\n", pred)
	try := func(label string, opt qr.DecodeOptions) {
		r, err := qr.DecodeWith(m, opt)
		switch {
		case err != nil:
			fmt.Printf("%-28s FAILED: %v\n", label, err)
		case r.Text != text:
			fmt.Printf("%-28s MISDECODED (%q)\n", label, r.Text)
		default:
			fmt.Printf("%-28s OK  (%d codeword(s) repaired, %d erasures used)\n", label, r.ByteErrors, r.ErasuresUsed)
		}
	}
	try("decode (errors only):", qr.DecodeOptions{})
	if erased != nil {
		try("decode (logo as erasures):", qr.DecodeOptions{Erased: erased})
	}
	return nil
}

func damageSweep(text string, seed int64, trials int) error {
	hi, err := qr.EncodeText(text, qr.Options{ECC: qr.H})
	if err != nil {
		return err
	}
	v := hi.Version
	fmt.Printf("payload %q fits version %d at every level; random flips in the data area, %d trials per level\n", truncate(text, 30), v, trials)
	fmt.Printf("%-5s %8s %14s %14s %12s\n", "ECC", "modules", "median flips", "min flips", "% of data")
	for e := qr.L; e <= qr.H; e++ {
		c, err := qr.EncodeText(text, qr.Options{ECC: e, MinVersion: v, MaxVersion: v})
		if err != nil {
			return err
		}
		var pool [][2]int
		for cw := 0; cw < qr.RawCodewords(v); cw++ {
			pool = append(pool, c.CodewordModules(cw)...)
		}
		var maxes []int
		for t := 0; t < trials; t++ {
			rng := rand.New(rand.NewSource(seed + int64(t)))
			perm := rng.Perm(len(pool))
			survives := func(k int) bool {
				m := c.Matrix.Clone()
				for _, i := range perm[:k] {
					p := pool[i]
					m.Set(p[0], p[1], !m.Get(p[0], p[1]))
				}
				r, err := qr.DecodeWith(m, qr.DecodeOptions{NoTranspose: true})
				return err == nil && r.Text == text
			}
			lo, hiK := 0, len(pool) // largest k that survives (monotone in expectation)
			for lo < hiK {
				mid := (lo + hiK + 1) / 2
				if survives(mid) {
					lo = mid
				} else {
					hiK = mid - 1
				}
			}
			maxes = append(maxes, lo)
		}
		sort.Ints(maxes)
		med := maxes[len(maxes)/2]
		fmt.Printf("%-5v %8d %14d %14d %11.1f%%\n", e, c.Matrix.N*c.Matrix.N, med, maxes[0], 100*float64(med)/float64(len(pool)))
	}
	return nil
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}

func cmdDistort(args []string) error {
	fs := flag.NewFlagSet("distort", flag.ContinueOnError)
	roll := fs.Float64("roll", 0, "in-plane rotation, degrees")
	tx := fs.Float64("tiltx", 0, "tilt about the horizontal axis, degrees")
	ty := fs.Float64("tilty", 0, "tilt about the vertical axis, degrees")
	blur := fs.Float64("blur", 0, "Gaussian blur sigma in pixels")
	noise := fs.Float64("noise", 0, "Gaussian noise sigma (grey levels)")
	salt := fs.Float64("salt", 0, "salt-and-pepper probability")
	jq := fs.Int("jpeg", 0, "re-encode as JPEG at this quality (1-100)")
	light := fs.Float64("light", 0, "uneven lighting strength 0..1")
	mirror := fs.Bool("mirror", false, "mirror horizontally")
	logo := fs.Float64("logo", 0, "paint a centred square of this width fraction")
	margin := fs.Float64("margin", 0.1, "background margin around the warped image")
	seed := fs.Int64("seed", 1, "random seed")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 2 {
		return fmt.Errorf("usage: qz distort [options] IN.png OUT.png")
	}
	img, err := loadImage(fs.Arg(0))
	if err != nil {
		return err
	}
	g := toGray(img)
	rng := rand.New(rand.NewSource(*seed))
	if *logo > 0 {
		g = sim.Logo(g, g.Bounds(), *logo, 128)
	}
	g = sim.Warp(g, sim.Pose{Roll: *roll, TiltX: *tx, TiltY: *ty, Mirror: *mirror, Margin: *margin}, 235)
	g = sim.Blur(g, *blur)
	if *light > 0 {
		g = sim.Lighting(g, *light, *light/2, 30)
	}
	if *noise > 0 || *salt > 0 {
		g = sim.Noise(g, *noise, *salt, rng)
	}
	if *jq > 0 {
		if *jq > 100 {
			return fmt.Errorf("-jpeg quality is 1..100")
		}
		if g, err = sim.JPEG(g, *jq); err != nil {
			return err
		}
	}
	f, err := os.Create(fs.Arg(1))
	if err != nil {
		return err
	}
	defer f.Close()
	return png.Encode(f, g)
}

func toGray(img image.Image) *image.Gray {
	gr := scan.FromImage(img)
	out := image.NewGray(image.Rect(0, 0, gr.W, gr.H))
	copy(out.Pix, gr.Pix)
	return out
}
