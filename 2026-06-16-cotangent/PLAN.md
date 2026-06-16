# Cotangent — Plan

## Concept
**Cotangent** is a from-scratch **reverse-mode automatic differentiation (autodiff)
engine** written in pure Python (stdlib only), plus a small neural-network library
built on top of it, optimizers, synthetic datasets, a training harness, and an
**interactive single-file HTML visualizer** that shows (a) a live computation graph
with forward values + backward gradients, and (b) a training playground where a
neural net's decision boundary is animated as it learns.

The name: reverse-mode AD works by seeding the output with a cotangent (`d_out = 1`)
and pushing cotangents backward through the graph via the chain rule. That backward
pass *is* the whole trick, and Cotangent implements it from first principles.

## Why it's interesting
- Autodiff is the engine under every modern ML framework (PyTorch/JAX/TF), yet it's
  conceptually tiny: a DAG of operations + the chain rule applied in reverse
  topological order. Building it from scratch is illuminating.
- It is **numerically verifiable**: every analytic gradient can be checked against a
  central finite-difference estimate. That gives us an unusually strong, honest test
  gate — we don't just assert "it runs", we assert "the math is correct to 1e-6".
- The payoff is real: with ~a few hundred lines you can train a multi-layer
  perceptron to classify a non-linearly-separable spiral, and *watch* it happen.
- Distinct from prior daily builds (world generator, regex engine).

## Architecture
```
engine.py      Value: scalar node in the autodiff DAG (+ - * / ** , relu/tanh/
               sigmoid/exp/log, etc.), topological backprop, graph introspection.
nn.py          Module/Neuron/Layer/MLP, parameter init, activations, zero_grad.
losses.py      MSE, binary cross-entropy, softmax cross-entropy (numerically stable).
optim.py       SGD (+ momentum + weight decay), Adam.
data.py        Synthetic datasets: xor, moons, circles, spiral (deterministic seed).
train.py       Training loop: minibatching, metrics (loss/accuracy), history.
gradcheck.py   Central finite-difference gradient checker over arbitrary Value graphs.
viz.py         Emits a standalone interactive HTML: computation-graph view +
               training playground (decision boundary animation from real run data).
cotangent.py   CLI: gradcheck | train | viz | demo.
tests/         Full test suite (gradcheck on every op, training convergence,
               optimizer behavior, graph topology, loss correctness, CLI smoke).
demo.sh        One-shot runnable demo exercising every feature.
```

No third-party dependencies. Visualization is generated HTML/SVG/JS (no build step,
opens in any browser). Randomness uses a seeded PRNG for determinism.

## Features

### Required (4)
1. **Reverse-mode autodiff engine** — a `Value` scalar type forming a DAG over a
   complete op set (`+ - * / ** -x`, `exp log relu tanh sigmoid`, reductions via
   composition). Correct topological backward pass that accumulates gradients and
   handles shared sub-expressions and self-references (e.g. `x*x`, `x+x`).
2. **Finite-difference gradient checker** — central-difference numerical gradients
   compared against the engine's analytic gradients for arbitrary scalar functions,
   reporting max relative error. This is both a feature and our correctness gate.
3. **Neural-net library + optimizers** — `Neuron/Layer/MLP` with selectable
   activations, plus `SGD` (momentum, weight decay) and `Adam`. `zero_grad`,
   parameter iteration, deterministic init.
4. **Training harness on real datasets** — minibatched training loop with loss +
   accuracy metrics and recorded history, converging on synthetic but genuinely
   non-linear datasets (spiral / moons / circles / xor).

### Stretch (2+)
5. **Interactive computation-graph visualizer** — given any Value expression, emit a
   standalone HTML rendering the DAG with each node's forward value and backward
   gradient, op labels, and topological layout (no Graphviz dependency — custom
   layered layout in pure Python → SVG/JS).
6. **Training playground HTML** — run a real training session, capture decision-
   boundary snapshots over epochs, and emit an interactive page with a play/scrub
   timeline showing the boundary morphing and the loss/accuracy curve.
7. *(bonus)* **Adam vs SGD comparison + loss-curve export** in the CLI/demo.

## Verification strategy
- Gradient-check **every** primitive op and several composite expressions vs central
  differences (tolerance ~1e-6 on relative error).
- Assert training reaches high accuracy (e.g. ≥95%) on at least two datasets.
- Test optimizer state updates (momentum/Adam moments), zero_grad, determinism.
- Test the visualizer emits valid self-contained HTML containing the embedded data.
- CLI smoke tests for every subcommand. `demo.sh` runs the lot.

## Done = all six phases' gates pass; tests green; demo runs end-to-end.
