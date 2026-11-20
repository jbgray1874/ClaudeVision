"""A RUNNER'S LOG SAYS WHICH .env ITS SETTINGS CAME FROM (20 Nov 2026).

Slot 2 runs from C:\\ClaudeVision-s2, which has no .env; its runner falls back to the main
checkout's. It said so before its log file was open, and it runs windowless, so the line went
nowhere and nothing on record showed how its engine got SDI_PRINT_CALCULATOR_XLSX.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _runner():
    spec = importlib.util.spec_from_file_location(
        "sdi_estimate_runner_t", ROOT / "tools" / "runner" / "sdi_estimate_runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_log_names_the_env_file_read(tmp_path, monkeypatch):
    mod = _runner()
    monkeypatch.setattr(mod, "_ENV_LOADED_FROM", r"C:\ClaudeVision\.env")
    out, err = sys.stdout, sys.stderr
    try:
        path = mod.start_logging(tmp_path)
    finally:
        sys.stdout, sys.stderr = out, err
    text = Path(path).read_text(encoding="utf-8")
    assert r"[env] settings from C:\ClaudeVision\.env" in text


def test_with_no_file_the_log_says_so(tmp_path, monkeypatch):
    mod = _runner()
    monkeypatch.setattr(mod, "_ENV_LOADED_FROM", "")
    out, err = sys.stdout, sys.stderr
    try:
        path = mod.start_logging(tmp_path)
    finally:
        sys.stdout, sys.stderr = out, err
    assert "no .env file: this process environment only" in Path(path).read_text(encoding="utf-8")
