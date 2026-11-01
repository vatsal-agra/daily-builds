package viz

import (
	"encoding/json"
	"regexp"
	"strings"
	"testing"

	"wayfinder/grid"
	"wayfinder/plan"
)

func TestPageEmbedsValidJSONAndEscapes(t *testing.T) {
	g, _ := grid.Generate("rooms", 30, 20, 2, 0, 0.2)
	a, _ := plan.AStar(g, g.Start, g.Goal)
	ex, err := plan.Explore(g, 2)
	if err != nil {
		t.Fatal(err)
	}
	page, err := Page(`</script><b>"x"&`, g, []*plan.Result{a}, ex)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(page, "</script><b>") {
		t.Fatal("title not escaped")
	}
	if strings.Count(page, "</script>") != 1 {
		t.Fatal("data could terminate the script tag")
	}
	m := regexp.MustCompile(`(?s)const D=(.*?);\nconst \$=`).FindStringSubmatch(page)
	if m == nil {
		t.Fatal("data block not found")
	}
	var p pageJSON
	if err := json.Unmarshal([]byte(strings.ReplaceAll(m[1], `<\/`, `</`)), &p); err != nil {
		t.Fatal(err)
	}
	if p.W != 30 || p.H != 20 || len(p.Cost) != 600 || len(p.Algos) != 1 || p.Explore == nil {
		t.Fatalf("bad data: %+v", p)
	}
	if p.Algos[0].Cost != a.Cost || len(p.Algos[0].Order) != a.Expanded {
		t.Fatal("algo trace not preserved")
	}
	if len(p.Explore.Trail) != len(ex.Trail) || len(p.Explore.Events) != len(ex.Events) {
		t.Fatal("exploration not preserved")
	}
}

func TestPageWithoutTraces(t *testing.T) {
	g := grid.New(5, 5)
	page, err := Page("empty", g, nil, nil)
	if err != nil || !strings.Contains(page, `"algos":null`) && !strings.Contains(page, `"algos":[]`) {
		t.Fatalf("%v", err)
	}
}
