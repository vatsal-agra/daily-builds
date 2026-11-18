package main

import "testing"

func TestLooksLikeFacelets(t *testing.T) {
	yes := []string{"UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB", "uuuuuuuuurrrrrrrrrfffffffffdddddddddlllllllllbbbbbbbbb"}
	no := []string{"R U R' U'", "", "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBB", "RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR"}
	for _, s := range yes {
		if !looksLikeFacelets(s) {
			t.Errorf("%q should look like facelets", s)
		}
	}
	for _, s := range no {
		if looksLikeFacelets(s) {
			t.Errorf("%q should not look like facelets", s)
		}
	}
}
