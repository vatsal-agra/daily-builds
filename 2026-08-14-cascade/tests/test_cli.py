import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_cli(args, timeout=30):
    return subprocess.run(
        [sys.executable, "-m", "cascade.cli", *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout,
    )


def test_demo_command_exits_zero():
    result = run_cli(["demo", "--port", "5470"], timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All checks passed." in result.stdout


def test_resolve_prints_answer():
    result = run_cli(["resolve", "www.example.com.", "A", "--port", "5471"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "93.184.216.34" in result.stdout
    assert "status: NOERROR" in result.stdout


def test_resolve_nxdomain_exits_zero_like_real_dig():
    result = run_cli(["resolve", "nope.example.com.", "A", "--port", "5472"])
    assert result.returncode == 0
    assert "NXDOMAIN" in result.stdout


def test_resolve_with_trace_and_viz(tmp_path):
    out = tmp_path / "trace.html"
    result = run_cli(["resolve", "mail.example.com.", "A", "--trace", "--viz", str(out), "--port", "5473"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "resolution trace" in result.stdout
    assert out.exists()
    html = out.read_text()
    assert "mail.example.com." in html
    assert "<!doctype html>" in html.lower()


def test_dig_bad_name_reports_clean_error_not_traceback():
    result = run_cli(["dig", "bad..name.com", "A", "--server", "127.0.0.1", "--port", "1"])
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "cascade: error:" in result.stderr


def test_dig_unreachable_server_reports_clean_error():
    result = run_cli(["dig", "example.com.", "A", "--server", "127.0.0.1", "--port", "1", "--timeout", "0.3"])
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_serve_and_dig_against_it():
    zonefile = PROJECT_ROOT / "zones" / "example.com.zone"
    proc = subprocess.Popen(
        [sys.executable, "-m", "cascade.cli", "serve", str(zonefile),
         "--origin", "example.com.", "--host", "127.0.0.90", "--port", "5474"],
        cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        time.sleep(0.5)
        result = run_cli(["dig", "example.com.", "A", "--server", "127.0.0.90", "--port", "5474"])
        assert result.returncode == 0, result.stdout + result.stderr
        assert "93.184.216.34" in result.stdout
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_serve_port_in_use_reports_clean_error():
    zonefile = PROJECT_ROOT / "zones" / "example.com.zone"
    proc = subprocess.Popen(
        [sys.executable, "-m", "cascade.cli", "serve", str(zonefile),
         "--origin", "example.com.", "--host", "127.0.0.91", "--port", "5475"],
        cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        time.sleep(0.5)
        result = run_cli(["serve", str(zonefile), "--origin", "example.com.",
                           "--host", "127.0.0.91", "--port", "5475"], timeout=5)
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert "cascade: error:" in result.stderr
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_help_and_no_args_do_not_crash():
    result = run_cli(["--help"])
    assert result.returncode == 0
    assert "cascade" in result.stdout

    result = run_cli([])
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
