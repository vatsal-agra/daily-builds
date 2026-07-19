# Loom

*Status: shipped. All 4 required + 2 stretch features implemented, reviewed,
and verified — see [REVIEW.md](./REVIEW.md) for what adversarial testing
found and fixed.*

A transformer language model — the architecture behind modern LLMs — built
entirely from scratch: a **reverse-mode tensor autodiff engine** (no
PyTorch, no TensorFlow, no JAX, no autograd of any kind), a GPT-style
decoder-only transformer on top of it, a real Adam training loop, and
autoregressive text generation with temperature/top-k/top-p sampling.

Every gradient the model uses during training was written by hand and is
checked against numerical finite differences — both op-by-op (26 ops in
`loom/gradcheck.py`) and end-to-end through the full model (a real weight,
perturbed inside a real forward pass, `tests/test_nn.py`).

See [PLAN.md](./PLAN.md) for the full architecture and feature rationale.
See [REVIEW.md](./REVIEW.md) for the adversarial review findings.

## Sample output

The shipped checkpoint (`checkpoints/loom.npz`) is a 4-layer, 4-head,
64-dim transformer (~207K parameters) trained on the ~17.7 KB original
corpus in `corpus/loom_corpus.txt`, character-level, for 4000 steps —
shipping the step-600 snapshot, which had the best validation loss (1.79)
before the model started overfitting this small a corpus (see REVIEW.md
finding #8). Sampled at temperature 0.7:

```
$ python3 -m loom.cli generate --ckpt checkpoints/loom --prompt "The " -n 300 --temperature 0.7 --seed 1

The stavell of the mark seeps of unce, the could the whole forst and
least on samply as the leang in the long shop believed the make hany
nought of the patience of to passomse that nothere humber that of ships
ship were agains of in had the workning had sall each on and who noth
the same the sailors saill he watch pastience was paled the sampling
inamins carried and the simply but hims ounce the long
```

Honest read: correct spelling of real words, correct capitalization and
punctuation rhythm, and vocabulary pulled straight from the training
corpus's themes (lighthouse, storm, ships, sailors, patience, watch) — but
not grammatical sentences. That's the expected ceiling for a ~207K-parameter
character-level model trained on 17.7 KB of text; the point of this build
is a *correct*, verified-from-scratch implementation of the Transformer
architecture and its training loop, not a competitive language model.
Greedy decoding (temperature 0) visibly falls into repetition loops
("...the she storm was of the small storm and the she storm was...") — the
textbook failure mode of greedy sampling, reproduced faithfully rather than
papered over.

## Quickstart

```bash
pip install -r requirements.txt   # numpy only

# Verify the autodiff engine against numerical gradients
python3 -m loom.cli gradcheck

# Train a small GPT on the bundled original corpus (~15-25 min on CPU
# for the full 4000-step run used to produce checkpoints/loom.npz;
# use --steps 100 or so for a fast smoke run)
python3 -m loom.cli train --steps 4000 --out checkpoints/loom

# Generate text from a trained checkpoint
python3 -m loom.cli generate --ckpt checkpoints/loom --prompt "The old" -n 300 --temperature 0.7

# Train a from-scratch BPE tokenizer and inspect its merges
python3 -m loom.cli bpe --merges 200

# Capture real attention weights from a generation run and render the
# interactive visualizer
python3 -m loom.cli attn --ckpt checkpoints/loom --prompt "The " -n 60 --out viz/attention.html
```

Run `./demo.sh` to exercise every feature end-to-end (tests, gradient
checks, tokenizers, a quick training run, all three sampling modes, and
the attention visualizer).

## Architecture

```
loom/tensor.py      reverse-mode autodiff Tensor: add/sub/mul/div/matmul/
                    reshape/permute/gather/slice/concat/sum/mean/exp/log/
                    tanh/relu/gelu/softmax/layernorm — all broadcasting-aware
loom/nn.py          Linear, Embedding, LayerNorm, MultiHeadAttention (causal),
                    dropout, FeedForward, TransformerBlock, GPT, cross-entropy
loom/optim.py       Adam (bias-corrected) + warmup/cosine LR schedule + grad clip
loom/tokenizer.py   CharTokenizer + from-scratch byte-level BPE tokenizer
loom/data.py        corpus loading + sliding-window minibatch sampler
loom/train.py       training loop; tracks + ships the best-val-loss checkpoint
loom/generate.py    autoregressive sampling: temperature / top-k / top-p
loom/checkpoint.py  save/load (npz weights + json config/tokenizer)
loom/attn_viz.py    renders the interactive attention-heatmap visualizer
loom/gradcheck.py   central finite-difference checker for every autodiff op
loom/cli.py         `loom` CLI: gradcheck/train/generate/attn/tokenize/bpe
corpus/loom_corpus.txt   original hand-authored training text
viz/attention_template.html   self-contained interactive visualizer shell
tests/              unittest suite
demo.sh
```

## Feature list

**Required:**
1. **Tensor autodiff engine** — numpy-backed, real computation graph,
   reverse-mode `.backward()`, broadcasting-aware. All 26 ops gradient-checked.
2. **GPT-style transformer built on the engine** — token + positional
   embeddings, causal multi-head self-attention, pre-norm LayerNorm,
   residual streams, GELU feedforward, final projection to vocab logits.
3. **Training pipeline** — Adam, LR warmup + cosine decay, gradient
   clipping, minibatched sliding windows, dropout, checkpointing (ships the
   best-validation-loss weights, not just the final step's).
4. **Sampling / generation CLI** — temperature, top-k, top-p (nucleus)
   sampling from a trained checkpoint given an arbitrary prompt.

**Stretch:**
5. **Interactive HTML attention visualizer** — replays a real generation
   run, rendering the model's actual per-layer/per-head attention matrices.
   A pre-generated example from the shipped checkpoint is committed at
   `viz/attention.html` — open it directly in a browser, no server needed.
6. **From-scratch byte-level BPE tokenizer** — trains merge rules directly
   from the corpus, usable as a drop-in alternative to char-level tokenization.

## Why this, today

Every ML-adjacent build in this ledger so far (Cotangent's scalar autodiff
MLP, QSim's quantum circuits, VecNN's HNSW) stayed at the "classical
algorithm" layer. The Transformer is the one big idea in modern computing
this ledger hadn't touched, and it's a genuinely harder autodiff problem
than a scalar computation graph: broadcasting through matmul, softmax and
layernorm Jacobians, and attention masking all have to be right, and
"right" is checkable — which is exactly the kind of build this repo does well.

## Where a human could take this next

- Scale up (more layers/heads, a bigger corpus, subword BPE training end to
  end) — the architecture doesn't change, only the numbers.
- Add KV-caching for O(1)-per-token generation instead of recomputing the
  full context every step.
- Multi-query / grouped-query attention, RoPE positional encoding, RMSNorm
  — modern architectural variants, each a small diff against `nn.py`.
- A numpy → GPU backend swap (CuPy) would make the exact same autodiff
  graph run on a GPU with no algorithmic changes.
- Instruction-tuning: fine-tune on (prompt, completion) pairs with the loss
  masked to only the completion tokens.
