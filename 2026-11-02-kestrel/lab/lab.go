// Package lab runs Monte-Carlo filter experiments: the statistical proof that a filter is honest.
package lab

import (
	"fmt"
	"math"

	"kestrel/filter"
	"kestrel/mat"
	"kestrel/metrics"
	"kestrel/model"
	"kestrel/stat"
)

// Config describes a single-target Monte-Carlo consistency experiment.
type Config struct {
	Filter string // kf | ekf | ukf
	Sensor string // cartesian | radar
	Runs   int
	Steps  int
	Dt     float64
	Q      float64 // true process-noise intensity (also given to the filter)
	Seed   int64
	Alpha  float64 // test significance (default 0.05)
	// radar geometry
	StartRange float64 // metres, bearing 40° from a sensor at the origin
	SigR, SigB float64
	SigCart    float64
	MismatchQ  float64 // if >0, the FILTER uses this Q instead of the truth's (to show failure)
}

// Report is the outcome.
type Report struct {
	Cfg       Config
	NEES, NIS metrics.Consistency
	NEESFrac  float64 // fraction of time steps whose run-averaged NEES lies in bounds
	NISFrac   float64
	PosRMSE   float64
	MeanNEESk []float64 // run-averaged NEES at each step
	MeanNISk  []float64
}

func (c *Config) defaults() error {
	if c.Alpha == 0 {
		c.Alpha = 0.05
	}
	if c.Runs < 2 || c.Steps < 2 {
		return fmt.Errorf("lab: need Runs>=2 and Steps>=2")
	}
	if c.Dt <= 0 || c.Q <= 0 {
		return fmt.Errorf("lab: Dt and Q must be positive")
	}
	if c.Filter == "kf" && c.Sensor == "radar" {
		return fmt.Errorf("lab: the linear KF cannot process radar (polar) measurements — that is the point of the EKF/UKF")
	}
	if c.StartRange == 0 {
		c.StartRange = 8000
	}
	if c.SigR == 0 {
		c.SigR = 25
	}
	if c.SigB == 0 {
		c.SigB = 0.4 * math.Pi / 180
	}
	if c.SigCart == 0 {
		c.SigCart = 30
	}
	return nil
}

// Consistency simulates Runs independent CV targets (drawn from the true process-noise law),
// filters each with the chosen filter, and tests NEES (state error) and NIS (innovations).
func Consistency(c Config) (*Report, error) {
	if err := c.defaults(); err != nil {
		return nil, err
	}
	trueMot := model.NewCV(c.Q, 4)
	filtQ := c.Q
	if c.MismatchQ > 0 {
		filtQ = c.MismatchQ
	}
	filtMot := model.NewCV(filtQ, 4)
	var mm model.Meas
	switch c.Sensor {
	case "cartesian":
		mm = model.NewCartesian(0, 2, c.SigCart)
	case "radar":
		mm = model.NewRadar(0, 2, 0, 0, c.SigR, c.SigB)
	default:
		return nil, fmt.Errorf("lab: unknown sensor %q (cartesian|radar)", c.Sensor)
	}
	rng := stat.NewRNG(c.Seed)
	b := 40 * math.Pi / 180
	mean0 := mat.Vec(c.StartRange*math.Cos(b), 150, c.StartRange*math.Sin(b), -120)
	p0 := mat.Diag(200*200, 20*20, 200*200, 20*20)
	nees := make([][]float64, c.Steps) // [step][run]
	nis := make([][]float64, c.Steps)
	var se float64
	var nse int
	for r := 0; r < c.Runs; r++ {
		truth, err := rng.MVN(mean0, p0)
		if err != nil {
			return nil, err
		}
		est0, err := rng.MVN(truth, p0) // initial estimate error is drawn from P0 => consistent start
		if err != nil {
			return nil, err
		}
		var f filter.Filter
		switch c.Filter {
		case "kf":
			f = filter.NewKF(filtMot, est0, p0)
		case "ekf":
			f = filter.NewEKF(filtMot, est0, p0)
		case "ukf":
			f = filter.NewUKF(filtMot, est0, p0)
		default:
			return nil, fmt.Errorf("lab: unknown filter %q (kf|ekf|ukf)", c.Filter)
		}
		for k := 0; k < c.Steps; k++ {
			// truth evolves with the TRUE process noise
			w, err := rng.MVN(mat.New(4, 1), trueMot.Q(truth, c.Dt))
			if err != nil {
				return nil, err
			}
			truth = trueMot.F(c.Dt).Mul(truth).Add(w)
			if err := f.Predict(c.Dt); err != nil {
				return nil, err
			}
			v, err := rng.MVN(mat.New(2, 1), mm.R())
			if err != nil {
				return nil, err
			}
			z := mm.H(truth).Add(v)
			if rm, ok := mm.(*model.Radar); ok {
				z.D[1] = stat.WrapAngle(z.D[1])
				_ = rm
			}
			pred, err := f.Measure(mm)
			if err != nil {
				return nil, err
			}
			res, err := f.Correct(mm, pred, z)
			if err != nil {
				return nil, err
			}
			e := f.X().Sub(truth)
			d2, _, err := filter.Mahalanobis(e, f.P())
			if err != nil {
				return nil, err
			}
			nees[k] = append(nees[k], d2)
			nis[k] = append(nis[k], res.NIS)
			se += e.D[0]*e.D[0] + e.D[2]*e.D[2]
			nse++
		}
	}
	var err error
	rep := &Report{Cfg: c, PosRMSE: math.Sqrt(se / float64(nse))}
	var allN, allI []float64
	inN, inI := 0, 0
	for k := 0; k < c.Steps; k++ {
		cn, err := metrics.ConsistencyTest(nees[k], 4, c.Alpha)
		if err != nil {
			return nil, err
		}
		ci, err := metrics.ConsistencyTest(nis[k], 2, c.Alpha)
		if err != nil {
			return nil, err
		}
		rep.MeanNEESk = append(rep.MeanNEESk, cn.Mean)
		rep.MeanNISk = append(rep.MeanNISk, ci.Mean)
		if cn.Consistent {
			inN++
		}
		if ci.Consistent {
			inI++
		}
		allN = append(allN, nees[k]...)
		allI = append(allI, nis[k]...)
	}
	rep.NEESFrac = float64(inN) / float64(c.Steps)
	rep.NISFrac = float64(inI) / float64(c.Steps)
	if rep.NEES, err = metrics.ConsistencyTest(allN, 4, c.Alpha); err != nil {
		return nil, err
	}
	if rep.NIS, err = metrics.ConsistencyTest(allI, 2, c.Alpha); err != nil {
		return nil, err
	}
	return rep, nil
}
