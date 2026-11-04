# Gosper
Hashlife cellular-automaton laboratory (Go, stdlib only). See PLAN.md and REVIEW.md.

**Status (phase 3): core built and adversarially reviewed (10 findings fixed).**

```
go build -o gosper .
./gosper patterns
./gosper run gosper-gun -gens 2^40 -o gun.mc     # a trillion generations in ~10 ms
./gosper analyze rpentomino                       # settles at gen 1103, pop 116
./gosper analyze acorn                            # settles at gen 5206, pop 633
./gosper verify -n 300                            # Hashlife vs naive simulator
```
Done: Hashlife engine for any B/S rule with node budget + compaction, RLE/cells/Macrocell I/O,
naive oracle + differential verifier, period / spaceship / settling / growth analyzer.
Still to come: census, PNG render, HTML report, tests, full docs.
