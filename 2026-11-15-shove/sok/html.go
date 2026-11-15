package sok

import (
	"encoding/json"
	"fmt"
	"strings"
)

// HTMLLevel is one level as embedded in the exported game.
type HTMLLevel struct {
	Name     string   `json:"name"`
	Rows     []string `json:"rows"`
	Solution string   `json:"solution"`
	Pushes   int      `json:"pushes"`
	Rating   string   `json:"rating"`
}

// BuildHTML solves (or accepts a supplied solution for) every level, verifies each
// solution with the independent replayer, and renders a standalone game page.
func BuildHTML(title string, lvs []*Level, sols []*Solution, opt Options) (string, []HTMLLevel, error) {
	var out []HTMLLevel
	for i, lv := range lvs {
		var sol *Solution
		if sols != nil && i < len(sols) {
			sol = sols[i]
		}
		if sol == nil {
			var err error
			sol, err = Solve(lv, opt)
			if err != nil {
				return "", nil, fmt.Errorf("%s: %v", lv.Name, err)
			}
		}
		if _, err := lv.Verify(sol.Moves); err != nil {
			return "", nil, fmt.Errorf("%s: solution failed verification: %v", lv.Name, err)
		}
		rows := strings.Split(strings.TrimRight(lv.String(), "\n"), "\n")
		out = append(out, HTMLLevel{Name: lv.Name, Rows: rows, Solution: sol.Moves, Pushes: sol.Pushes, Rating: Rate(sol)})
	}
	data, err := json.Marshal(out)
	if err != nil {
		return "", nil, err
	}
	safe := strings.ReplaceAll(string(data), "</", "<\\/")
	page := strings.Replace(htmlTemplate, "/*LEVELS*/[]", safe, 1)
	page = strings.Replace(page, "{{TITLE}}", htmlEscape(title), -1)
	return page, out, nil
}

func htmlEscape(s string) string {
	r := strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", "\"", "&quot;")
	return r.Replace(s)
}
