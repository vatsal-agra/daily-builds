package lp

import (
	"math"

	"dantzig/internal/exact"
	"dantzig/internal/model"
	"dantzig/internal/simplex"
)

var posInf = math.Inf(1)

func simplexNew(m *model.Model, box exact.Box) *simplex.Solver { return simplex.New(Build(m, box)) }
func floorf(v float64) int                                     { return int(math.Floor(v + 1e-9)) }
