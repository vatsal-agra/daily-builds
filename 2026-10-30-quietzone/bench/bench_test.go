package bench

import "testing"

// Every scenario must meet its floor on a deterministic 12-trial sample.
func TestScenarioFloors(t *testing.T) {
	for _, r := range Run(12, 7, "") {
		if r.Rate() < r.Floor {
			t.Errorf("%s: %d/%d (%.0f%%) below floor %.0f%%; %v", r.Name, r.Pass, r.Trials, 100*r.Rate(), 100*r.Floor, r.Failures)
		}
	}
}
