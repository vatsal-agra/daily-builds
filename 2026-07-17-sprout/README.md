# Sprout

*Status: Phase 4 complete — both stretch features built and smoke-tested
(attention visualizer, web playground + auto model card). Real training run
in progress in the background; verification and final numbers next.*

## Stretch features

- `sprout/attention_viz.py` — runs a prompt through a trained checkpoint and
  writes a self-contained interactive HTML page with real per-layer,
  per-head attention heatmaps (a layer/head picker + a query-token slider
  that highlights which earlier tokens that query actually attended to).
  No illustrative/fake data — every value comes straight out of the model's
  own forward-pass cache.
- `sprout/server.py` — a zero-dependency `http.server` playground. Every
  "Generate" click is a real network round trip to a real Python forward
  pass (same pattern this repo's Gambit/Formulate builds used). Verified
  under concurrent requests from multiple simultaneous clients (this is
  also what surfaced and fixed the shared-RNG race noted in `REVIEW.md`).
- `sprout/model_card.py` — auto-generates `MODEL_CARD.md` from a real
  checkpoint's actual training history and live sample generations, with
  an explicit "honest assessment" section instead of marketing copy.

A tiny GPT-style language model, trained from scratch — tokenizer, transformer
forward/backward pass, optimizer, and sampler all hand-written in NumPy, no
autograd or deep learning framework involved.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.

## What's built so far (all 4 required features, working end-to-end)

- `sprout/tokenizer.py` — byte-level BPE tokenizer (train/encode/decode/save/load).
- `sprout/nn.py` — the transformer itself: `Linear`, `LayerNorm`, `Embedding`,
  causal multi-head self-attention, GELU MLP, residual `Block`s, and the full
  `GPT` model, each with a hand-written `backward()`.
- `sprout/gradcheck.py` — verifies every one of those backward passes against
  numerical (finite-difference) gradients. **All checks currently pass.**
  Run it yourself: `python3 sprout/gradcheck.py`
- `sprout/optim.py` — Adam optimizer from scratch.
- `sprout/train.py` — the training loop: batching, loss tracking,
  checkpointing, periodic sampling.
- `sprout/generate.py` — temperature / top-k / top-p sampling + a CLI chat mode.
- `sprout/data/make_corpus.py` — generates the original 170KB training corpus.
- `sprout/tests/test_all.py` — 22 unit tests, all passing.

A full training run is in progress at this checkpoint of the build; results,
the attention visualizer, the web playground, and the model card will be
documented here once training finishes and Phase 3 (adversarial review) and
Phase 4 (stretch + polish) are complete.

## Quickstart (once a checkpoint exists)

```bash
cd sprout
pip install -r requirements.txt
python3 data/make_corpus.py          # generate the training corpus
python3 gradcheck.py                 # verify the math (should all say OK)
python3 train.py --steps 1600        # train (~30-45 min on CPU)
python3 generate.py --prompt "the fox"
python3 server.py                    # web playground at localhost:8420
```
