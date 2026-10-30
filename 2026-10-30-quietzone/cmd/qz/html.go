package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"

	"quietzone/qr"
)

type htmlData struct {
	Text     string       `json:"text"`
	Version  int          `json:"version"`
	N        int          `json:"n"`
	ECC      string       `json:"ecc"`
	Mask     int          `json:"mask"`
	Dark     string       `json:"dark"`  // N*N chars '0'/'1'
	Kinds    string       `json:"kinds"` // N*N digits, qr.Kind
	CW       []int        `json:"cw"`    // codeword index per module, -1 none
	Bit      []int        `json:"bit"`
	CWBlock  []int        `json:"cwBlock"`
	CWIsECC  []bool       `json:"cwIsEcc"`
	Blocks   [][3]int     `json:"blocks"` // dataLen, eccLen, correctable
	Segments []qr.SegInfo `json:"segments"`
	Pen      [8][4]int    `json:"pen"`
	Bits     [4]int       `json:"bits"` // used, capacity, pad, remainder
}

func cmdHTML(args []string) error {
	fs := flag.NewFlagSet("html", flag.ContinueOnError)
	eccS := fs.String("ecc", "Q", "error correction level")
	out := fs.String("o", "quietzone.html", "output file")
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
	page, _, err := buildExplorer(text, e)
	if err != nil {
		return err
	}
	return os.WriteFile(*out, []byte(page), 0o644)
}

// buildExplorer renders the self-contained explorer page for text at level e.
func buildExplorer(text string, e qr.ECC) (string, *qr.Code, error) {
	c, err := qr.EncodeText(text, qr.Options{ECC: e})
	if err != nil {
		return "", nil, err
	}
	ex := c.Explain()
	d := htmlData{Text: text, Version: c.Version, N: ex.Size, ECC: c.ECC.String(), Mask: c.Mask, Segments: ex.Segments, Pen: ex.Penalties,
		CWBlock: ex.CWBlock, CWIsECC: ex.CWIsECC, Bits: [4]int{ex.DataBits, ex.CapacityBits, ex.PadBits, ex.RemainderBits}}
	var dk, kd strings.Builder
	for y := 0; y < ex.Size; y++ {
		for x := 0; x < ex.Size; x++ {
			if c.Matrix.Get(x, y) {
				dk.WriteByte('1')
			} else {
				dk.WriteByte('0')
			}
			mi := ex.Modules[y*ex.Size+x]
			kd.WriteByte(byte('0' + mi.Kind))
			d.CW = append(d.CW, mi.CW)
			d.Bit = append(d.Bit, mi.Bit)
		}
	}
	d.Dark, d.Kinds = dk.String(), kd.String()
	for _, b := range ex.Blocks {
		d.Blocks = append(d.Blocks, [3]int{b.DataLen, b.ECCLen, b.Correctable})
	}
	js, _ := json.Marshal(d)
	page := strings.Replace(explorerHTML, "/*DATA*/null", string(js), 1)
	page = strings.Replace(page, "<!--TITLE-->", fmt.Sprintf("Quietzone — v%d-%s", c.Version, c.ECC), 1)
	return page, c, nil
}
