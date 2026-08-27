import json
import os
import re

from warren.engine import Engine
from warren.viz import run_and_export_trace


def _examples(name):
    return os.path.join(os.path.dirname(__file__), "..", "examples", name)


def _extract_trace(html):
    m = re.search(r"const TRACE = (\{.*\});", html)
    assert m, "trace JSON not found in generated HTML"
    return json.loads(m.group(1))


def test_viz_captures_real_trace(tmp_path):
    eng = Engine(backend="wam")
    eng.consult_file(_examples("family.pl"))
    out = tmp_path / "trace.html"
    path = run_and_export_trace(eng, "ancestor(tom, X).", str(out))
    assert os.path.exists(path)
    html = out.read_text()
    # self-contained: no external script/stylesheet references
    assert "http://" not in html and "https://" not in html
    data = _extract_trace(html)
    assert data["solved"] is True
    assert data["solution"] == "X = bob"
    assert len(data["steps"]) > 5
    # every recorded step corresponds to a real executed instruction
    for step in data["steps"]:
        assert "instr" in step and "p" in step


def test_viz_reports_failure_cleanly(tmp_path):
    eng = Engine(backend="wam")
    eng.consult_string("p(1).")
    out = tmp_path / "trace_fail.html"
    run_and_export_trace(eng, "p(2).", str(out))
    data = _extract_trace(out.read_text())
    assert data["solved"] is False
    assert "failed" in data["solution"]
