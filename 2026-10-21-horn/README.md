# Horn

A from-scratch **Prolog system in Go** (standard library only).

**Status:** Phase 2 (core build) — reader, engine, builtins and toplevel work end to end; see
[PLAN.md](PLAN.md) for the full feature list. Build and run:

```
go build -o horn .
./horn tests/core.pl -g halt          # 250+ assertions
./horn examples/queens.pl -g halt
echo 'member(X,[a,b]).' | ./horn --all
```
