package tabula

import (
	"encoding/json"
	"fmt"
	"os"
)

func SaveJSON(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0o644)
}

func LoadSolution(path string) (*Solution, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var s Solution
	if err := json.Unmarshal(b, &s); err != nil {
		return nil, fmt.Errorf("%s: %v", path, err)
	}
	return &s, nil
}
