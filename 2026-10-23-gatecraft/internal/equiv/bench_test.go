package equiv_test

import (
	"fmt"
	"testing"

	"gatecraft/internal/equiv"
	"gatecraft/internal/testutil"
)

func mulPair(t testing.TB, w int) (a, b string) {
	a = fmt.Sprintf("module m(input [%d:0] a, input [%d:0] b, output [%d:0] y); assign y = a * b; endmodule", w-1, w-1, w-1)
	b = fmt.Sprintf("module m(input [%d:0] a, input [%d:0] b, output [%d:0] y); assign y = b * a; endmodule", w-1, w-1, w-1)
	return
}

func BenchmarkMultCommute9(b *testing.B) {
	sa, sb := mulPair(b, 9)
	ga, gb := testutil.Build(b, sa, ""), testutil.Build(b, sb, "")
	for i := 0; i < b.N; i++ {
		r, err := equiv.CheckComb(ga, gb)
		if err != nil || r.Verdict != equiv.Equivalent {
			b.Fatal(err, r)
		}
	}
}
