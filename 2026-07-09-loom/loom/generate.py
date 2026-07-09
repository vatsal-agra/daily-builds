"""Autoregressive sampling from a trained GPT: greedy, temperature,
top-k, and nucleus (top-p) filtering, plus a small interactive chat loop."""
import numpy as np


def _softmax_np(x):
    x = x - np.max(x)
    e = np.exp(x)
    return e / e.sum()


def _sample_next(logits, temperature, top_k, top_p, rng):
    logits = logits.astype(np.float64)
    if temperature <= 0:
        return int(np.argmax(logits))
    logits = logits / temperature

    if top_k is not None and 0 < top_k < len(logits):
        kth_value = np.partition(logits, -top_k)[-top_k]
        logits = np.where(logits < kth_value, -np.inf, logits)

    probs = _softmax_np(logits)

    if top_p is not None and 0 < top_p < 1.0:
        order = np.argsort(-probs)
        sorted_probs = probs[order]
        cumsum = np.cumsum(sorted_probs)
        cutoff = int(np.searchsorted(cumsum, top_p) + 1)
        keep = order[:cutoff]
        mask = np.zeros_like(probs, dtype=bool)
        mask[keep] = True
        probs = np.where(mask, probs, 0.0)
        probs = probs / probs.sum()

    return int(rng.choice(len(probs), p=probs))


def generate(model, tokenizer, prompt="", max_new_tokens=200, temperature=0.8,
             top_k=None, top_p=None, seed=None):
    rng = np.random.RandomState(seed)
    if prompt:
        ids = list(tokenizer.encode(prompt))
    else:
        ids = [int(rng.randint(0, tokenizer.vocab_size))]

    for _ in range(max_new_tokens):
        context = ids[-model.max_len:]
        x = np.array([context])
        logits = model.forward(x)
        last_logits = logits.data[0, -1]
        next_id = _sample_next(last_logits, temperature, top_k, top_p, rng)
        ids.append(next_id)

    return tokenizer.decode(ids)


def chat(model, tokenizer, max_new_tokens=200, temperature=0.8, top_k=40, top_p=0.95, seed=None):
    print("Loom chat -- type a prompt (any prefix of characters the model was trained on).")
    print("Empty line or Ctrl-D to quit.\n")
    while True:
        try:
            prompt = input("> ")
        except EOFError:
            print()
            break
        if not prompt.strip():
            break
        try:
            text = generate(model, tokenizer, prompt, max_new_tokens=max_new_tokens,
                             temperature=temperature, top_k=top_k, top_p=top_p, seed=seed)
        except ValueError as e:
            print(f"[error] {e}\n")
            continue
        print(text)
        print()
