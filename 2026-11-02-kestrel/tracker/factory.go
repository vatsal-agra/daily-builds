package tracker

import (
	"fmt"

	"kestrel/filter"
	"kestrel/mat"
	"kestrel/model"
	"kestrel/sim"
)

// Options select a filter configuration for the stock tracker.
type Options struct {
	Filter       string  // ekf | ukf | imm-ekf | imm-ukf
	Assoc        string  // gnn | jpda
	QCV          float64 // process noise (acceleration spectral density) for CV
	QTurn        float64 // process noise inside the CT mode
	QW           float64 // turn-rate random walk
	GateProb     float64
	ConfirmM     int
	ConfirmN     int
	MaxMiss      int
	VMax         float64
	ScoreConfirm float64
	DeleteDrop   float64
	Trace        bool // record filter internals for RTS smoothing
}

// DefaultOptions are sensible for the built-in scenarios.
func DefaultOptions() Options {
	return Options{Filter: "ekf", Assoc: "gnn", QCV: 0.5, QTurn: 1.0, QW: 2e-5, GateProb: 0.999,
		ConfirmM: 3, ConfirmN: 5, MaxMiss: 5, VMax: 350, ScoreConfirm: 4, DeleteDrop: 9}
}

// ForScenario builds a tracker config matched to a scenario's radar.
func ForScenario(sc sim.Scenario, o Options) (Config, error) {
	rad := model.NewRadar(0, 2, sc.Radar.X, sc.Radar.Y, sc.Radar.SigR, sc.Radar.SigB)
	cfg := Config{
		Name: o.Filter + "/" + o.Assoc, Radar: rad, Pd: sc.Radar.Pd,
		ClutterDensity: sc.Radar.ClutterDensity(), GateProb: o.GateProb,
		ConfirmM: o.ConfirmM, ConfirmN: o.ConfirmN, MaxMiss: o.MaxMiss, VMax: o.VMax,
		Trace: o.Trace, MergeGate: 9.5, Assoc: o.Assoc, ScoreConfirm: o.ScoreConfirm, DeleteDrop: o.DeleteDrop,
	}
	if sc.Radar.ClutterMean == 0 { // density 0 would make every pairing infinitely likely
		cfg.ClutterDensity = 1e-12
	}
	if cfg.Pd >= 1 {
		cfg.Pd = 0.9999
	}
	switch o.Filter {
	case "ekf", "ukf":
		cfg.Dim = 4
		mot := model.NewCV(o.QCV, 4)
		cfg.Make = func(x, p *mat.M) (filter.Filter, error) {
			if o.Filter == "ekf" {
				return filter.NewEKF(mot, x, p), nil
			}
			return filter.NewUKF(mot, x, p), nil
		}
	case "imm-ekf", "imm-ukf":
		cfg.Dim = 5
		cv, ct := model.NewCV(o.QCV, 5), model.NewCT(o.QTurn, o.QW)
		cfg.Make = func(x, p *mat.M) (filter.Filter, error) {
			mk := func(m model.Motion) filter.Filter {
				if o.Filter == "imm-ekf" {
					return filter.NewEKF(m, x, p)
				}
				return filter.NewUKF(m, x, p)
			}
			return filter.NewIMM([]filter.Filter{mk(cv), mk(ct)}, []float64{0.8, 0.2},
				[][]float64{{0.95, 0.05}, {0.1, 0.9}})
		}
	default:
		return cfg, fmt.Errorf("unknown filter %q (ekf|ukf|imm-ekf|imm-ukf)", o.Filter)
	}
	return cfg, nil
}
