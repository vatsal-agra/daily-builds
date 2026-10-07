package main

import (
	"encoding/json"
	"fmt"
	"math"
	"os"

	"dantzig/internal/model"
)

// cmdExport writes the model as float JSON (for cross-checking against other solvers).
func cmdExport(args []string) (int, error) {
	if len(args) != 1 {
		return 2, fmt.Errorf("usage: dantzig export <model.lp>")
	}
	m, err := loadModel(args[0])
	if err != nil {
		return 2, err
	}
	bound := func(v float64, _ float64) any {
		if math.IsInf(v, 0) {
			return nil
		}
		return v
	}
	type row struct {
		Name string    `json:"name"`
		Idx  []int     `json:"idx"`
		Val  []float64 `json:"val"`
		Lo   any       `json:"lo"`
		Hi   any       `json:"hi"`
	}
	out := struct {
		Maximize bool      `json:"maximize"`
		Const    float64   `json:"const"`
		Names    []string  `json:"names"`
		C        []float64 `json:"c"`
		Lo       []any     `json:"lo"`
		Hi       []any     `json:"hi"`
		Int      []bool    `json:"int"`
		Rows     []row     `json:"rows"`
	}{Maximize: m.Maximize, Const: model.Float(m.ObjConst)}
	for _, v := range m.Vars {
		out.Names = append(out.Names, v.Name)
		out.C = append(out.C, model.Float(v.Obj))
		lo, hi := math.Inf(-1), math.Inf(1)
		if v.Lo != nil {
			lo = model.Float(v.Lo)
		}
		if v.Hi != nil {
			hi = model.Float(v.Hi)
		}
		out.Lo = append(out.Lo, bound(lo, 0))
		out.Hi = append(out.Hi, bound(hi, 0))
		out.Int = append(out.Int, v.Int)
	}
	for _, r := range m.Rows {
		jr := row{Name: r.Name}
		for _, e := range r.Entries {
			jr.Idx = append(jr.Idx, e.J)
			jr.Val = append(jr.Val, model.Float(e.V))
		}
		lo, hi := math.Inf(-1), math.Inf(1)
		if r.Lo != nil {
			lo = model.Float(r.Lo)
		}
		if r.Hi != nil {
			hi = model.Float(r.Hi)
		}
		jr.Lo, jr.Hi = bound(lo, 0), bound(hi, 0)
		out.Rows = append(out.Rows, jr)
	}
	return 0, json.NewEncoder(os.Stdout).Encode(out)
}
