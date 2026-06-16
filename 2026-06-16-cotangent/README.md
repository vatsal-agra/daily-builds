# Cotangent

A from-scratch **reverse-mode automatic differentiation engine** + a small
neural-network library, written in **pure Python (standard library only)** — with
**finite-difference gradient checking** and two **interactive single-file HTML
visualizers**: a computation-graph viewer and a training playground that animates a
neural net's decision boundary as it learns.

> Reverse-mode AD works by seeding the output with a *cotangent* (`d_out/d_out = 1`)
> and pushing cotangents backward through the graph via the chain rule. That backward
> pass is the entire trick — and Cotangent implements it from first principles.

```
$ python3 cotangent.py gradcheck
OK   add            max_rel_error=6.55e-12
OK   mul            max_rel_error=2.14e-11
...
OK   loss:softmax_ce max_rel_error=3.20e-11
worst max_rel_error = 5.10e-11  (tolerance 1e-05)
All gradient checks passed.
```

## Why this, today
Autodiff is the engine under every modern ML framework, yet it's conceptually tiny:
a DAG of operations plus the chain rule applied in reverse topological order. It's
also **honestly verifiable** — every analytic gradient can be checked against a
central finite-difference estimate, which makes the test gate real math, not just
"it runs". And the payoff is tangible: with a few hundred lines you can train an MLP
to separate a two-arm spiral and *watch* the boundary form. (Prior daily builds were
a procedural world generator and a regex engine — this is deliberately different.)

## Run it
No dependencies, no build step. Python 3.9+.

```bash
# verify the math (analytic gradients vs finite differences)
python3 cotangent.py gradcheck

# train an MLP on a synthetic dataset
python3 cotangent.py train --dataset moons --hidden 16,16 --epochs 80

# Adam vs SGD, side by side
python3 cotangent.py compare --dataset xor --hidden 8,8 --epochs 30

# emit an interactive training playground (open the HTML in a browser)
python3 cotangent.py viz --dataset spiral --hidden 24,24 --epochs 120 --lr 0.05

# emit a computation-graph view of out = tanh(a*b + c)
python3 cotangent.py graph --a 1.5 --b -2.0 --c 3.0

# end-to-end showcase of everything
./demo.sh

# full test suite
python3 tests/test_cotangent.py
```

Datasets: `xor`, `moons`, `circles`, `spiral`. The first three reach 100% accuracy
quickly; the **spiral** is the genuinely hard one and reaches ~95% with a wider net
and a longer schedule (`--hidden 24,24 --epochs 120 --lr 0.05`, ~4 min in pure
Python).

## Features
**Required**
1. **Reverse-mode autodiff engine** — `Value` scalar DAG over `+ - * / ** -x`,
   `exp/log/relu/tanh/sigmoid`, with a correct topological backward pass that
   accumulates gradients and handles shared subexpressions (`x*x`, `x+x`).
2. **Finite-difference gradient checker** — central differences vs analytic
   gradients for arbitrary scalar functions; max relative error reported.
3. **Neural-net library + optimizers** — `Neuron/Layer/MLP`, selectable activations,
   `SGD` (momentum + weight decay) and `Adam` (bias-corrected), deterministic init.
4. **Training harness** — minibatched loop with loss/accuracy history, converging on
   non-linear datasets.

**Stretch / bonus**
5. **Computation-graph visualizer** — custom layered layout (no Graphviz) → SVG/JS,
   showing each node's forward value and backward gradient.
6. **Training playground** — scrub/play a real training run; watch the decision
   boundary morph with a live loss/accuracy curve.
7. **Adam-vs-SGD comparison** in the CLI/demo.

## Layout
`engine.py` (autodiff) · `gradcheck.py` · `nn.py` · `losses.py` · `optim.py` ·
`data.py` · `train.py` · `viz.py` · `cotangent.py` (CLI) · `tests/` · `demo.sh`

> **Status:** Phase 4 (stretch + polish) complete. Verification & ship next.
