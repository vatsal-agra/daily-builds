# Loom

A GPT-style decoder-only Transformer language model built entirely from
scratch: its own reverse-mode autograd tensor engine (NumPy is used only as
a dense-array/BLAS backend -- no PyTorch, TensorFlow, JAX, or scikit-learn
anywhere), its own byte-level BPE tokenizer trained from real corpus
statistics, its own multi-head causal self-attention and training loop, and
an interactive HTML visualizer that shows the real attention weights of the
real trained model as it generates text.

**Status: shipped.** All 4 required features and all 3 planned stretch
features are implemented and verified (70/70 tests, `demo.sh` green). See
[PLAN.md](./PLAN.md) for the full architecture and feature list, and
[REVIEW.md](./REVIEW.md) for the adversarial-review findings.

A real model is checked in at `checkpoints/` (381,792 parameters: 3 layers,
4 heads, 96-dim embeddings, 384-token vocab), trained for 2,500 steps
(~21.5 minutes on CPU) on the bundled corpus. Loss: **5.93 -> 0.31** train /
**5.93 -> 0.26** validation (train and val track closely throughout --
no meaningful overfitting). Sample generation (temperature 0.4, top-k 20,
`--no-kv-cache`, from the real checkpoint):

> Long ago, in the Whispering Forest, there lived a curious Otter. Then,
> without warning, the first snow came earlier than anyone expected. The
> Otter gathered the others beneath the great oak to make a plan. It took
> three days, but the forest was whole again by the new moon. The elders
> still say that the old paths are old for a reason.

That's the real trained model reconstructing the corpus's fable structure
(character, setting, problem, action, outcome, moral) correctly and
grammatically -- not memorized verbatim (the specific character/setting/
problem/moral combination doesn't appear in the corpus), but reliably
composed from the template statistics it learned. At higher temperature it
degrades into recognizable vocabulary in less grammatical order, which is
the honest, expected behavior of a toy-scale (382K-parameter) model on an
85 KB corpus -- see [PLAN.md](./PLAN.md)'s Non-goals.

## Why this, today

Every prior "from scratch" daily build reached for a classical algorithm --
SAT solvers, ray tracers, a VCS, a bytecode VM, ciphers, compressors. None
had built the architecture behind modern LLMs. The interesting part isn't
calling an API -- it's proving every gradient by hand: backprop through
softmax, layer normalization, multi-head attention, and embedding lookups
as primitive tensor operations, each one checked against numerical
finite-difference gradients (the same way a real ML framework's test suite
works), then watching a from-scratch training loop actually reduce loss on
real text.

## Quick start

```bash
pip install numpy          # the only dependency

# run the full test suite (gradient checks + module tests + tokenizer +
# integration tests + CLI tests)
python3 -m unittest discover -s tests -q

# train a model on the bundled original corpus (~20 min on CPU for the
# shipped-size model; pass smaller --n-embd/--n-layer/--steps for a quick run)
python3 cli.py train --out-dir checkpoints

# generate text from a trained checkpoint
python3 cli.py generate --checkpoint-dir checkpoints \
    --prompt "Long ago, in the Whispering Forest," --max-new-tokens 200

# interactive streaming chat REPL
python3 cli.py chat --checkpoint-dir checkpoints

# render the interactive attention-heatmap visualizer (a sample built from
# the real checkpoint is already checked in at attention_viz.html)
python3 cli.py viz --checkpoint-dir checkpoints --out attention_viz.html

# run everything end-to-end (tests + a quick fresh training run + generation
# + the real shipped checkpoint if present + the visualizer + edge cases)
./demo.sh
```

## Architecture

```
loom/tensor.py      autograd engine: Tensor class over NumPy arrays, with
                     hand-derived backward passes for every primitive op
                     (add/sub/mul/div/matmul/transpose/reshape/sum/mean/
                     exp/log/sqrt/pow/tanh/relu/softmax/embedding/
                     cross_entropy), broadcasting-aware, gradient-checked.
loom/nn.py           Embedding, LayerNorm, CausalSelfAttention (multi-head,
                     causal mask, optional KV-cache), GELU MLP, Block
                     (pre-norm residual), GPT (full model + autoregressive
                     generate() with temperature/top-k sampling).
loom/optim.py        Adam (bias-corrected) + LR warmup/cosine-decay +
                     global-norm gradient clipping.
loom/tokenizer.py    byte-level BPE: trains merges from corpus statistics,
                     encode/decode, exact round-trip on arbitrary unicode.
loom/train.py        batching, training loop, periodic eval, checkpointing.
loom/generate.py     load a checkpoint, autoregressive sampling.
loom/chat.py         interactive REPL, streams tokens with correct
                     incremental UTF-8 decoding.
loom/viz.py          renders attention_viz.html from a real captured
                     generation.
cli.py               train / generate / chat / tokenize / gradcheck / viz / demo
data/corpus.txt      ~85 KB original text (fables about a fixed cast of
                     forest animals), generated by tools/generate_corpus.py
                     from hand-written templates -- not scraped or copied.
tests/               70 tests total: 28 tensor gradient-check tests, 13 nn
                     module tests (incl. a hard causality invariant and
                     KV-cache equivalence), 11 tokenizer tests, 6 training/
                     checkpoint integration tests, 7 viz/chat tests, 5 CLI
                     tests.
demo.sh              exercises every feature end-to-end.
```

## Feature list

**Required (all shipped, fully working end-to-end):**
1. From-scratch autograd tensor engine, every op gradient-checked.
2. GPT-style Transformer (multi-head causal self-attention, pre-norm
   residual blocks, GELU MLP, weight-tied output head).
3. From-scratch byte-level BPE tokenizer trained from corpus statistics.
4. Real training loop (Adam + LR schedule + grad clipping) that measurably
   reduces loss on the bundled corpus, with checkpointing and
   temperature/top-k autoregressive generation.

**Stretch (3 shipped):**
5. Interactive HTML attention visualizer replaying a real generation.
6. KV-cache for O(1)-per-token incremental decoding (verified numerically
   identical to the non-cached path).
7. Interactive streaming `chat` REPL.

## Where a human could take this next

- Swap the toy corpus for a larger real one and scale up `n_embd`/`n_layer`
  (the architecture doesn't change -- only config).
- Add dropout and a validation-loss-based early stop / best-checkpoint save.
- Port the hot path (attention, matmuls) to a compiled backend once the
  pure-Python/NumPy version is proven correct, using this repo's gradient
  checks as the correctness oracle for the port.
- Add rotary or ALiBi position embeddings instead of learned absolute ones.
- Multi-GPU / data-parallel training (the Adam optimizer and grad-clipping
  logic are already framework-agnostic enough to extend).
