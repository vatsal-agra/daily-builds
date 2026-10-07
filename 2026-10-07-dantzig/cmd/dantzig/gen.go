package main

import (
	"fmt"
	"strconv"

	"dantzig/internal/gen"
	"dantzig/internal/model"
)

func cmdGen(args []string) (int, error) {
	if len(args) == 0 || args[0] == "list" {
		fmt.Println("generators:")
		for _, k := range gen.Kinds {
			fmt.Printf("  %-34s %s\n", k.Usage, k.Doc)
		}
		return 0, nil
	}
	var nums []int
	for _, a := range args[1:] {
		if a == "hard" || a == "easy" {
			if a == "hard" {
				nums = append(nums, 1)
			} else {
				nums = append(nums, 0)
			}
			continue
		}
		v, err := strconv.Atoi(a)
		if err != nil {
			return 2, fmt.Errorf("argument %q is not a number", a)
		}
		nums = append(nums, v)
	}
	m, err := gen.Build(args[0], nums)
	if err != nil {
		return 2, err
	}
	fmt.Print(model.Format(m))
	return 0, nil
}
