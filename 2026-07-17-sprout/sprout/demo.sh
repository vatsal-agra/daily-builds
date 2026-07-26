#!/usr/bin/env bash
# Exercises every Sprout feature end to end. Run from the sprout/ directory.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1/7  regenerating the training corpus ==="
python3 data/make_corpus.py

echo
echo "=== 2/7  gradient-checking every backward pass ==="
python3 gradcheck.py

echo
echo "=== 3/7  running the unit test suite ==="
python3 -m unittest discover -s tests -v

echo
echo "=== 4/7  training checkpoint ==="
if [ -f checkpoints/sprout.pkl ]; then
  echo "using the committed checkpoint at checkpoints/sprout.pkl"
else
  echo "no checkpoint found -- training a small one now (this will take a few minutes)"
  python3 train.py --steps 300 --vocab-size 384 --block-size 48 \
    --n-layer 3 --n-head 3 --n-embd 96 --batch-size 24 --eval-every 100
fi

echo
echo "=== 5/7  generating text from four prompts ==="
for p in "the fox" "a heron" "Day at" '"I saw a'; do
  echo "--- prompt: $p ---"
  python3 generate.py --prompt "$p" --max-new-tokens 60 --seed 0
  echo
done

echo "=== 6/7  building the attention visualizer + model card ==="
python3 attention_viz.py --prompt "the fox and the otter argued about" --out /tmp/sprout_attention_demo.html
python3 model_card.py --out /tmp/sprout_model_card_demo.md
echo "wrote /tmp/sprout_attention_demo.html and /tmp/sprout_model_card_demo.md"

echo
echo "=== 7/7  edge cases: empty prompt, temperature=0, tiny checkpoint round trip ==="
python3 - <<'PYEOF'
import numpy as np
from generate import sample
from train import load_checkpoint

model, tok, data = load_checkpoint("checkpoints/sprout.pkl")
rng = np.random.default_rng(0)
assert isinstance(sample(model, tok, prompt="", max_new_tokens=5, rng=rng), str)
assert isinstance(sample(model, tok, prompt="the", max_new_tokens=5, temperature=0.0, rng=rng), str)
assert isinstance(sample(model, tok, prompt="the", max_new_tokens=5, top_k=999999, rng=rng), str)
print("edge cases OK")
PYEOF

echo
echo "ALL DEMOS PASSED."
