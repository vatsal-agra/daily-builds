package web

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"cubist/cube"
)

func post(t *testing.T, h http.Handler, body string) (*httptest.ResponseRecorder, map[string]any) {
	t.Helper()
	req := httptest.NewRequest("POST", "/api/solve", bytes.NewBufferString(body))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	var out map[string]any
	json.Unmarshal(rec.Body.Bytes(), &out)
	return rec, out
}

func TestAPI(t *testing.T) {
	h := Handler(cube.Options{Target: 24, TimeLimit: 200e6})
	rec, out := post(t, h, `{"scramble":"R U F' D2 L B"}`)
	if rec.Code != 200 || out["final"] != cube.SolvedFacelets {
		t.Fatalf("scramble: %d %v", rec.Code, out)
	}
	rec, out = post(t, h, `{"random":true}`)
	if rec.Code != 200 || out["final"] != cube.SolvedFacelets {
		t.Fatalf("random: %d %v", rec.Code, out)
	}
	rec, out = post(t, h, `{"facelets":"`+cube.FromMoves(mustParse([]string{"R", "U"})).Facelets()+`"}`)
	if rec.Code != 200 {
		t.Fatalf("facelets: %d %v", rec.Code, out)
	}
	for body, code := range map[string]int{
		`{"scramble":"R U x"}`: 422, `{"facelets":"UUU"}`: 422, `{}`: 422, `nope`: 400,
		`{"scramble":"` + strings.Repeat("R U ", 300) + `"}`: 422,
	} {
		if rec, _ := post(t, h, body); rec.Code != code {
			t.Errorf("%.30s: got %d want %d", body, rec.Code, code)
		}
	}
	req := httptest.NewRequest("GET", "/api/solve", nil)
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != 405 {
		t.Errorf("GET should be 405, got %d", rec.Code)
	}
}

func TestRenderHTMLEscapesAndEmbeds(t *testing.T) {
	page, err := RenderHTML(Solution{Start: cube.SolvedFacelets, Scramble: "</script><b>x", Moves: []string{"R"}}, false)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(page, "</script><b>") {
		t.Fatal("scramble text was not escaped inside the script block")
	}
	if strings.Contains(page, "/*__DATA__*/") {
		t.Fatal("placeholder left in page")
	}
	page, _ = RenderHTML(Solution{Start: cube.SolvedFacelets}, true)
	if !strings.Contains(page, "const SERVE = true") {
		t.Fatal("serve flag not set")
	}
}

func TestInverseShortcut(t *testing.T) {
	ms, _ := cube.ParseMoves("R U R' U'")
	sol, err := BuildSolution(cube.FromMoves(ms), "R U R' U'", cube.Options{})
	if err != nil {
		t.Fatal(err)
	}
	if sol.Method != "inverse-of-scramble" || len(sol.Moves) != 4 || sol.Final != cube.SolvedFacelets {
		t.Fatalf("%+v", sol)
	}
}
