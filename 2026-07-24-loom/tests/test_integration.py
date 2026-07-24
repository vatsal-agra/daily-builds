"""End-to-end tests: train a small (but real) model from a text corpus,
save/load its checkpoint, generate from it, and hit the real HTTP server.
These are intentionally small/fast (seconds, not minutes) so they can run
as part of `demo.sh`/CI, but they exercise the *entire* stack -- tokenizer
training, model training, checkpointing, generation, and the web API --
against real code paths, not mocks.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(HERE, "data", "shakespeare.txt")


def test_tiny_end_to_end_training_run():
    from loom.tokenizer import BPETokenizer
    from loom.model import GPT, GPTConfig
    from loom.optim import Adam
    from loom.train import get_batch
    from loom.generate import generate_text
    from loom.checkpoint import save, load

    with open(CORPUS, encoding="utf-8") as f:
        text = f.read()[:150_000]  # a slice is enough to prove the pipeline works

    tok = BPETokenizer()
    tok.train(text, vocab_size=300)
    ids = np.array(tok.encode(text), dtype=np.int64)
    split = int(len(ids) * 0.9)
    train_data, val_data = ids[:split], ids[split:]

    cfg = GPTConfig(vocab_size=tok.vocab_size, block_size=32, n_layer=2, n_head=2, n_embd=32, dropout=0.1)
    model = GPT(cfg)
    opt = Adam(model.parameters(), lr=3e-3)
    rng = np.random.default_rng(0)

    baseline = np.log(cfg.vocab_size)
    losses = []
    for step in range(150):
        x, y = get_batch(train_data, 16, 32, rng)
        _, loss = model(x, y, training=True)
        opt.zero_grad()
        loss.backward()
        opt.step()
        losses.append(loss.data.item())

    avg_first_10 = np.mean(losses[:10])
    avg_last_10 = np.mean(losses[-10:])
    assert avg_first_10 < baseline + 0.5, f"first-step loss {avg_first_10} should start near baseline {baseline}"
    assert avg_last_10 < avg_first_10 - 0.5, (
        f"loss should drop meaningfully with real training: {avg_first_10:.3f} -> {avg_last_10:.3f}"
    )
    print(f"  ok: loss dropped {avg_first_10:.3f} -> {avg_last_10:.3f} over 150 steps (baseline {baseline:.3f})")

    tmpdir = tempfile.mkdtemp()
    try:
        meta = {"step": 150, "max_steps": 150, "history": [], "num_params": model.num_params()}
        save(tmpdir, model, tok, meta)
        model2, tok2, meta2 = load(tmpdir)
        assert meta2["step"] == 150
        assert tok2.vocab_size == tok.vocab_size

        x, y = get_batch(val_data, 8, 32, rng)
        _, loss_before = model(x, y, training=False)
        _, loss_after = model2(x, y, training=False)
        # weights round-trip through float32 in the checkpoint (see checkpoint.py), so
        # allow for that quantization instead of demanding bit-exact float64 equality.
        assert abs(loss_before.data.item() - loss_after.data.item()) < 1e-3, "loaded weights must match (up to float32 round-trip)"
        print("  ok: checkpoint save/load reproduces (near-)identical loss")

        text_out = generate_text(model2, tok2, "ROMEO:", max_new_tokens=60, temperature=0.9, top_k=30, seed=0)
        assert text_out.startswith("ROMEO:")
        assert len(text_out) > len("ROMEO:")
        print(f"  ok: generation from loaded checkpoint: {text_out!r}")
    finally:
        shutil.rmtree(tmpdir)

    return tmpdir  # unused; kept for readability of intent


def _wait_for_server(base_url, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(base_url + "/api/status", timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    return False


def test_server_end_to_end():
    """Trains a tiny checkpoint, launches the real `python -m loom.server`
    process against it, and drives every HTTP endpoint the frontend uses --
    proving the UI's server calls actually work, not just the library code.
    """
    from loom.tokenizer import BPETokenizer
    from loom.model import GPT, GPTConfig
    from loom.checkpoint import save

    with open(CORPUS, encoding="utf-8") as f:
        text = f.read()[:80_000]
    tok = BPETokenizer()
    tok.train(text, vocab_size=280)
    cfg = GPTConfig(vocab_size=tok.vocab_size, block_size=24, n_layer=1, n_head=2, n_embd=16, dropout=0.0)
    model = GPT(cfg)

    tmpdir = tempfile.mkdtemp()
    proc = None
    try:
        save(tmpdir, model, tok, {"step": 1, "max_steps": 1, "history": [
            {"step": 1, "train_loss": 5.0, "val_loss": 5.1, "elapsed_s": 1.0}
        ], "num_params": model.num_params()})

        port = 8511
        env = dict(os.environ)
        proc = subprocess.Popen(
            [sys.executable, "-m", "loom.server", "--checkpoint", tmpdir, "--port", str(port)],
            cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        base = f"http://127.0.0.1:{port}"
        assert _wait_for_server(base), "server did not come up in time:\n" + (proc.stdout.read() if proc.stdout else "")

        with urllib.request.urlopen(base + "/") as r:
            assert r.status == 200
            assert b"Loom" in r.read()
        print("  ok: GET / serves the frontend")

        with urllib.request.urlopen(base + "/style.css") as r:
            assert r.status == 200
        with urllib.request.urlopen(base + "/app.js") as r:
            assert r.status == 200
        print("  ok: static assets served")

        with urllib.request.urlopen(base + "/api/status") as r:
            status = json.loads(r.read())
        assert status["ok"] is True
        assert status["vocab_size"] == cfg.vocab_size
        assert len(status["history"]) == 1
        print("  ok: /api/status reports real model config + history")

        req = urllib.request.Request(
            base + "/api/generate",
            data=json.dumps({"prompt": "ROMEO", "max_new_tokens": 20, "temperature": 0.8, "top_k": 20}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            gen = json.loads(r.read())
        assert gen["ok"] is True
        assert gen["text"].startswith("ROMEO")
        print(f"  ok: /api/generate -> {gen['text']!r}")

        req = urllib.request.Request(
            base + "/api/attention",
            data=json.dumps({"prompt": "ROMEO"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            att = json.loads(r.read())
        assert att["ok"] is True
        assert len(att["layers"]) == cfg.n_layer
        assert len(att["layers"][0]) == cfg.n_head
        n_tok = len(att["tokens"])
        assert len(att["layers"][0][0]) == n_tok
        print(f"  ok: /api/attention -> {cfg.n_layer} layers x {cfg.n_head} heads x {n_tok} tokens")

        # malformed request must come back as a clean 4xx JSON error, not a crash/500
        req = urllib.request.Request(
            base + "/api/generate", data=b"not json", headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            assert False, "expected an HTTP error for malformed JSON"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        print("  ok: malformed request body returns HTTP 400, not a crash")

        # Python's json module accepts non-standard NaN/Infinity literals, and a
        # wrong-typed field (e.g. top_k as a string) must not reach numpy and
        # crash into a 500 -- both must come back as clean 400s.
        for bad_body in [b'{"prompt":"a","temperature":NaN}',
                          b'{"prompt":"a","max_new_tokens":Infinity}',
                          b'{"prompt":"a","top_k":"lots"}',
                          b'{"prompt":"a","seed":"xyz"}']:
            req = urllib.request.Request(
                base + "/api/generate", data=bad_body, headers={"Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(req)
                assert False, f"expected HTTP 400 for {bad_body!r}"
            except urllib.error.HTTPError as e:
                assert e.code == 400, f"{bad_body!r} -> {e.code}"
        print("  ok: NaN/Infinity/wrong-typed generation params return HTTP 400, not a crash")

        req = urllib.request.Request(
            base + "/api/attention", data=json.dumps({"prompt": ""}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            assert False, "expected an HTTP error for empty prompt"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        print("  ok: empty attention prompt returns HTTP 400, not a crash")

    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        print(f"{fn.__name__}:")
        fn()
    print(f"\nAll {len(fns)} integration test groups passed.")
