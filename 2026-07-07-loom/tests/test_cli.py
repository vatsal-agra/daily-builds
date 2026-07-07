import json
import os
import tempfile

from loom.cli import main

CORPUS_TEXT = (
    "ROMEO: But soft, what light through yonder window breaks?\n"
    "JULIET: O Romeo, Romeo, wherefore art thou Romeo?\n"
) * 30


def _write_corpus(d):
    path = os.path.join(d, "corpus.txt")
    with open(path, "w") as f:
        f.write(CORPUS_TEXT)
    return path


def test_tokenizer_train_encode_decode_cli(capsys, tmp_path=None):
    with tempfile.TemporaryDirectory() as d:
        corpus = _write_corpus(d)
        tok_path = os.path.join(d, "tok.json")
        main(["tokenizer", "train", "--corpus", corpus, "--vocab-size", "270", "--out", tok_path])
        assert os.path.exists(tok_path)

        capsys.readouterr()
        main(["tokenizer", "encode", "--tokenizer", tok_path, "ROMEO"])
        encoded = capsys.readouterr().out.strip()
        ids = encoded.split()
        assert len(ids) > 0

        main(["tokenizer", "decode", "--tokenizer", tok_path, encoded])
        decoded = capsys.readouterr().out.strip()
        assert decoded == "ROMEO"


def test_train_and_generate_cli(capsys):
    with tempfile.TemporaryDirectory() as d:
        corpus = _write_corpus(d)
        ckpt = os.path.join(d, "ckpt")
        main([
            "train", "--corpus", corpus, "--out", ckpt,
            "--vocab-size", "270", "--n-embd", "16", "--n-head", "2", "--n-layer", "1",
            "--block-size", "16", "--batch-size", "8", "--steps", "5",
        ])
        assert os.path.exists(os.path.join(ckpt, "weights.npz"))
        assert os.path.exists(os.path.join(ckpt, "config.json"))
        assert os.path.exists(os.path.join(ckpt, "tokenizer.json"))
        assert os.path.exists(os.path.join(ckpt, "history.json"))

        capsys.readouterr()
        main(["generate", "--checkpoint", ckpt, "--prompt", "ROMEO", "--max-new-tokens", "10",
              "--greedy"])
        out = capsys.readouterr().out
        assert "ROMEO" in out


def test_viz_cli(capsys):
    with tempfile.TemporaryDirectory() as d:
        corpus = _write_corpus(d)
        ckpt = os.path.join(d, "ckpt")
        main([
            "train", "--corpus", corpus, "--out", ckpt,
            "--vocab-size", "270", "--n-embd", "16", "--n-head", "2", "--n-layer", "1",
            "--block-size", "16", "--batch-size", "8", "--steps", "3",
        ])
        viz_out = os.path.join(d, "viz.html")
        main(["viz", "--checkpoint", ckpt, "--out", viz_out, "--prompt", "ROMEO:"])
        assert os.path.exists(viz_out)
        assert "<!doctype html>" in open(viz_out).read().lower()


def test_cli_missing_args_exits_cleanly():
    import pytest
    with pytest.raises(SystemExit):
        main(["train"])  # missing required --corpus/--out


def test_cli_missing_checkpoint_gives_clean_error_not_traceback(capsys):
    import pytest
    with pytest.raises(SystemExit) as excinfo:
        main(["generate", "--checkpoint", "/tmp/loom-does-not-exist-xyz", "--prompt", "hi"])
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "loom: error:" in err
    assert "checkpoint directory not found" in err


def test_cli_missing_corpus_gives_clean_error(capsys):
    import pytest
    with pytest.raises(SystemExit) as excinfo:
        main(["train", "--corpus", "/tmp/loom-no-such-corpus.txt", "--out", "/tmp/loom-out"])
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "corpus file not found" in err


def test_cli_decode_bad_id_gives_clean_error_not_keyerror(capsys):
    import pytest
    with tempfile.TemporaryDirectory() as d:
        corpus = _write_corpus(d)
        tok_path = os.path.join(d, "tok.json")
        main(["tokenizer", "train", "--corpus", corpus, "--vocab-size", "270", "--out", tok_path])
        capsys.readouterr()
        with pytest.raises(SystemExit) as excinfo:
            main(["tokenizer", "decode", "--tokenizer", tok_path, "999999"])
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "loom: error:" in err
        assert "outside this tokenizer's vocab" in err


def test_cli_decode_non_integer_ids_gives_clean_error(capsys):
    import pytest
    with tempfile.TemporaryDirectory() as d:
        corpus = _write_corpus(d)
        tok_path = os.path.join(d, "tok.json")
        main(["tokenizer", "train", "--corpus", corpus, "--vocab-size", "270", "--out", tok_path])
        capsys.readouterr()
        with pytest.raises(SystemExit) as excinfo:
            main(["tokenizer", "decode", "--tokenizer", tok_path, "not-a-number"])
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "loom: error:" in err
