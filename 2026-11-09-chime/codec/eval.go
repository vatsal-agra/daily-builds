package codec

// Result is one codec configuration encoded, decoded and measured.
type Result struct {
	Name  string
	File  []byte
	Stats *Stats
	Dec   *Audio
	M     *Metrics
}

// Run encodes a with p, decodes it back and measures it.
func Run(name string, a *Audio, p Params) (*Result, error) {
	file, st, err := Encode(a, p)
	if err != nil {
		return nil, err
	}
	dec, err := Decode(file)
	if err != nil {
		return nil, err
	}
	m, err := Compare(a, dec)
	if err != nil {
		return nil, err
	}
	return &Result{Name: name, File: file, Stats: st, Dec: dec, M: m}, nil
}

// Shootout runs the perceptual codec and the flat baseline at the same bitrate.
func Shootout(a *Audio, p Params) (perceptual, flat *Result, err error) {
	p.Flat = false
	perceptual, err = Run("chime", a, p)
	if err != nil {
		return
	}
	fp := p
	fp.Flat = true
	fp.Kbps = perceptual.Stats.Kbps // identical rate (flat search lands within a hair below)
	flat, err = Run("flat", a, fp)
	return
}
