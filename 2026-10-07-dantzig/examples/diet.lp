\ Diet LP: minimum-cost foods meeting nutrition limits (optimum is a clean fraction)
Minimize
 cost: 18 oats + 24 milk + 12 bread + 47 chicken + 8 beans + 35 cheese + 9 rice + 15 apple
Subject To
 calories: 2000 <= 110 oats + 120 milk + 90 bread + 180 chicken + 130 beans + 110 cheese + 205 rice + 80 apple <= 2600
 protein: 4 oats + 8 milk + 3 bread + 30 chicken + 9 beans + 7 cheese + 4 rice + apple >= 55
 calcium: 20 oats + 290 milk + 60 bread + 15 chicken + 60 beans + 200 cheese + 20 rice + 10 apple >= 800
 fat: 3 oats + 5 milk + 1 bread + 7 chicken + 1 beans + 9 cheese + rice <= 70
 fiber: 4 oats + 3 bread + 8 beans + 1 rice + 4 apple >= 25
Bounds
 oats <= 4
 milk <= 4
 bread <= 8
 chicken <= 3
 beans <= 6
 cheese <= 3
 rice <= 4
 apple <= 5
End
