"""Autoregressive sampling from a trained GPT: temperature, top-k, top-p."""
import numpy as np


def _filter_logits(logits, top_k=None, top_p=None):
    """logits: 1D numpy array over the vocab. Returns a filtered copy with
    disallowed entries set to -inf, ready for softmax."""
    logits = logits.copy()
    if top_k is not None and 0 < top_k < len(logits):
        kth = np.partition(logits, -top_k)[-top_k]
        logits[logits < kth] = -np.inf

    if top_p is not None and 0 < top_p < 1.0:
        order = np.argsort(-logits)
        sorted_logits = logits[order]
        probs = np.exp(sorted_logits - sorted_logits.max())
        probs /= probs.sum()
        cumprobs = np.cumsum(probs)
        cutoff = np.searchsorted(cumprobs, top_p) + 1
        cutoff = max(1, cutoff)
        keep = order[:cutoff]
        mask = np.full_like(logits, -np.inf)
        mask[keep] = logits[keep]
        logits = mask
    return logits


def sample_next(logits, temperature=1.0, top_k=None, top_p=None, rng=None):
    """logits: 1D numpy array (vocab,). Returns a sampled token id."""
    rng = rng or np.random.default_rng()
    if temperature <= 0:
        return int(np.argmax(logits))
    logits = logits / temperature
    logits = _filter_logits(logits, top_k=top_k, top_p=top_p)
    m = np.max(logits)
    probs = np.exp(logits - m)
    probs /= probs.sum()
    return int(rng.choice(len(probs), p=probs))


def generate(model, tokenizer, prompt, max_new_tokens=200, temperature=0.8,
             top_k=None, top_p=None, seed=None, return_attn=False):
    rng = np.random.default_rng(seed)
    # An empty prompt still needs a real seed token: raw id 0 would be a
    # null byte under the BPE tokenizer, so prefer a plain space -- valid
    # and printable under either tokenizer kind -- and only fall back to id
    # 0 if the training corpus genuinely never contained one.
    if prompt:
        ids = list(tokenizer.encode(prompt))
    else:
        try:
            ids = list(tokenizer.encode(" "))
        except ValueError:
            ids = [0]
    attn_frames = []
    block_size = model.max_seq_len

    for _ in range(max_new_tokens):
        context = np.array(ids[-block_size:])[None, :]
        if return_attn:
            logits, attn_maps = model(context, return_attn=True)
            attn_frames.append({
                "tokens": [tokenizer.token_str(i) for i in context[0]],
                "layers": [layer[0].tolist() for layer in attn_maps],  # (H,T,T) per layer
            })
        else:
            logits = model(context)
        last_logits = logits.data[0, -1, :]
        next_id = sample_next(last_logits, temperature=temperature, top_k=top_k, top_p=top_p, rng=rng)
        ids.append(next_id)

    text = tokenizer.decode(ids)
    if return_attn:
        return text, attn_frames
    return text
