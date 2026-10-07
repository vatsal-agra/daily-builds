\ Small production-planning MIP: batches must be whole, setup binaries gate each product
Maximize
 profit: 40 a + 55 b + 30 c - 120 sa - 150 sb - 90 sc
Subject To
 labor:    3 a + 5 b + 2 c <= 60
 machine:  2 a + 3 b + 4 c <= 48
 material: 4 a + 2 b + 3 c <= 70
 ga: a - 20 sa <= 0
 gb: b - 12 sb <= 0
 gc: c - 15 sc <= 0
Bounds
 a <= 20
 b <= 12
 c <= 15
Integer
 a b c
Binary
 sa sb sc
End
