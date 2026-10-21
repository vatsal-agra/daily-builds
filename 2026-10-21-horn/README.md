# Horn

A from-scratch **Prolog system in Go** (standard library only).

**Status:** Phase 3 (adversarial review) complete — see [REVIEW.md](REVIEW.md); plan in [PLAN.md](PLAN.md).

```
go build -o horn .
./horn tests/core.pl -g halt           # 257 assertions
./horn tests/adversarial.pl -g halt    # 167 assertions
go test ./...                          # fuzz / property tests
echo 'member(X,[a,b]).' | ./horn --all
```
