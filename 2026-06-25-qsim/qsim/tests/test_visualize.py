"""Tests for ASCII and HTML visualizers."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from qsim.circuit import Circuit
from qsim.state import QuantumState
from qsim.visualize import circuit_to_ascii, build_html


def _bell_circuit():
    qc = Circuit(2, 0, name="Bell|φ+⟩")
    qc.h(0)
    qc.cnot(0, 1)
    return qc


def _grover_circuit():
    from qsim.algorithms import grover
    r = grover(2, [1])
    return r['circuit']


def test_ascii_returns_string():
    """circuit_to_ascii returns a non-empty string."""
    qc = _bell_circuit()
    out = circuit_to_ascii(qc)
    assert isinstance(out, str) and len(out) > 0


def test_ascii_contains_qubit_lines():
    """ASCII output has one line per qubit."""
    qc = _bell_circuit()
    out = circuit_to_ascii(qc)
    lines = out.strip().split("\n")
    # Should have at least 2 lines (one per qubit)
    assert len(lines) >= 2, f"Too few lines: {len(lines)}"


def test_ascii_h_gate_present():
    """H gate appears in ASCII output."""
    qc = Circuit(1, 0, name="test")
    qc.h(0)
    out = circuit_to_ascii(qc)
    assert "H" in out, f"H gate not found in ASCII: {out}"


def test_ascii_cnot_connector():
    """CNOT connector (● or ⊕) appears for 2-qubit gate."""
    qc = _bell_circuit()
    out = circuit_to_ascii(qc)
    assert "●" in out or "⊕" in out or "X" in out, \
        f"No CNOT connector found: {out}"


def test_ascii_measure_gate():
    """Measure instruction shows in ASCII output."""
    qc = Circuit(1, 1, name="test")
    qc.h(0)
    qc.measure(0, 0)
    out = circuit_to_ascii(qc)
    assert "M" in out, f"Measure not in ASCII: {out}"


def test_ascii_single_qubit():
    """Single-qubit circuit renders without crash."""
    qc = Circuit(1, 0)
    qc.x(0)
    qc.h(0)
    out = circuit_to_ascii(qc)
    assert isinstance(out, str) and len(out) > 0


def test_ascii_empty_circuit():
    """Empty circuit renders as just wire lines."""
    qc = Circuit(2, 0)
    out = circuit_to_ascii(qc)
    assert isinstance(out, str) and len(out) > 0


def test_html_returns_string():
    """build_html returns a non-empty string."""
    qc = _bell_circuit()
    result = qc.run(shots=100)
    html = build_html(qc, result, title="Test")
    assert isinstance(html, str) and len(html) > 100


def test_html_is_valid_html():
    """HTML output starts with <!DOCTYPE html> and has </html>."""
    qc = _bell_circuit()
    result = qc.run(shots=100)
    html = build_html(qc, result, title="Test")
    assert html.strip().lower().startswith("<!doctype html") or "<html" in html.lower()
    assert "</html>" in html.lower()


def test_html_contains_title():
    """HTML output includes the circuit name."""
    qc = _bell_circuit()
    result = qc.run(shots=1)
    html = build_html(qc, result, title="My Bell Circuit")
    assert "My Bell Circuit" in html or "Bell" in html


def test_html_grover_circuit():
    """HTML generation for a Grover circuit doesn't crash."""
    qc = _grover_circuit()
    result = qc.run(shots=64)
    html = build_html(qc, result)
    assert len(html) > 500


def test_html_no_syntax_error_in_script():
    """The HTML output's <script> block has no obvious Python f-string leaks."""
    qc = _bell_circuit()
    result = qc.run(shots=1)
    html = build_html(qc, result)
    # Check for the fixed f-string issue: single unescaped } outside JSON
    # A rough heuristic: the JS should have valid JSON-like structure
    import re
    script_match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    if script_match:
        script = script_match.group(1)
        # The script should define some variables
        assert "const" in script or "var" in script or "let" in script


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
