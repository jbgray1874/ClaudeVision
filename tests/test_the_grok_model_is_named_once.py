"""The Grok models are named once, in config, and .env can override them (D-612).

JG, 1 Nov 2026: "we need to upgrade the model so we get the best possible llm as we know we use
this a lot... is it in the .env file? must be in config.py? as I only have the XAI_API_KEY."

grok-4.3 was written into a dozen modules, each with its own default; two still fell back to
grok-2, which xAI no longer serves; and the price store was keyed on a different setting from
the one the call used, so a change of model kept serving the old model's prices.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("SDI_OFFLINE", "1")

import config  # noqa: E402
import xai_models  # noqa: E402

CALLERS = ["concept_scan.py", "llm_full_extract.py", "merge_boms.py", "llm_scan_price.py",
           "_bom_vision_reader.py", "web_ai_price_lookup.py", "quote_render.py", "run_readers.py",
           "probe_pipeline.py", "patch_merge_boms_reconcile_job.py",
           "source_connectors/web_prices.py"]
MODEL_LITERAL = re.compile(r"""["']grok-[0-9][^"'\s]*["']""")


def _modules():
    return [p for p in sorted(SRC.rglob("*.py")) if p.is_file() and "__pycache__" not in p.parts]


# ── named once ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", CALLERS)
def test_no_caller_writes_its_own_model_name(name):
    text = (SRC / name).read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    assert not MODEL_LITERAL.findall(code), f"{name} names a Grok model itself"


def test_no_module_reads_the_old_model_variables_itself():
    for path in _modules():
        if path.name in ("config.py", "xai_models.py"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"""getenv\(\s*["']XAI_(VISION_)?MODEL["']|environ\.get\(\s*["']"""
                             r"""XAI_(VISION_)?MODEL["']""", text), path.name


def test_only_config_and_xai_models_name_a_default():
    hits = []
    for path in _modules():
        if path.name.startswith("_keyprobe"):
            continue
        code = "\n".join(line.split("#", 1)[0]
                         for line in path.read_text(encoding="utf-8", errors="replace")
                         .splitlines())
        if re.search(r"""["']grok-(?:[0-9]|imagine)[^"'\s]*["']""", code):
            hits.append(path.name)
    assert sorted(hits) == ["config.py", "xai_models.py"]


def test_config_upgrades_to_grok_4_7_and_every_setting_uses_it():
    clean = {k: v for k, v in os.environ.items()
             if not re.match(r"(SDI_)?XAI_(VISION_|IMAGE_)?MODEL$", k)}
    out = subprocess.run(
        [sys.executable, "-c",
         "import config as c; print(c.XAI_MODEL, c.XAI_VISION_MODEL, c.XAI_IMAGE_MODEL, "
         "c.PRICE_SOURCE_CONFIG['web']['xai_model'], c.QUOTE_RENDER['model'], "
         "c.QUOTE_RENDER['text_model'])"],
        cwd=str(SRC), env=dict(clean, SDI_OFFLINE="1"),
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.split()[-6:] == ["grok-4.7", "grok-4.7", "grok-imagine-image-2.0",
                                       "grok-4.7", "grok-imagine-image-2.0",
                                       "grok-imagine-image-2.0"]


def test_dot_env_can_set_the_model_back_for_one_machine():
    out = subprocess.run(
        [sys.executable, "-c",
         "import config as c, xai_models as x; print(c.PRICE_SOURCE_CONFIG['web']['xai_model'], "
         "x.text_model(), x.vision_model(), x.image_model())"],
        cwd=str(SRC), env=dict(os.environ, SDI_OFFLINE="1", SDI_XAI_MODEL="grok-4.3",
                               SDI_XAI_IMAGE_MODEL="grok-imagine-image"),
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.split()[-4:] == ["grok-4.3", "grok-4.3", "grok-4.3", "grok-imagine-image"]


def test_the_vision_reads_can_be_set_apart():
    out = subprocess.run(
        [sys.executable, "-c", "import xai_models as x; print(x.text_model(), x.vision_model())"],
        cwd=str(SRC), env=dict(os.environ, SDI_OFFLINE="1", SDI_XAI_MODEL="grok-4.7",
                               SDI_XAI_VISION_MODEL="grok-4.3"),
        capture_output=True, text=True, timeout=120)
    assert out.stdout.split()[-2:] == ["grok-4.7", "grok-4.3"]


def test_the_readers_panel_names_the_model_that_read_the_pages(monkeypatch):
    import run_readers
    monkeypatch.setattr(config, "XAI_VISION_MODEL", "grok-test-9")
    vision = next(r for r in run_readers.readers_that_ran(llm_only=False) if r["key"] == "vision")
    assert vision["library"].startswith("grok-test-9,")
    assert run_readers.reader_by_key("vision")["library"].startswith("grok-test-9,")


def test_the_llm_scan_stamps_the_configured_model(monkeypatch, tmp_path):
    import llm_scan_price
    monkeypatch.setattr(config, "XAI_VISION_MODEL", "grok-test-9")
    out = llm_scan_price.scan_price(tmp_path / "missing.pdf", 5)
    assert out["model"] == "grok-test-9"


# ── the price store follows the model the call uses ─────────────────────────────────────

def test_the_price_store_is_keyed_on_the_model_the_call_asks(monkeypatch):
    import generated_price_cache
    import web_ai_price_lookup as w
    seen = {}

    def fake_cached(spec, provider, model, compute, **kw):
        seen["model"] = model
        return {"found": False}

    monkeypatch.setattr(generated_price_cache, "cached_estimate", fake_cached)
    monkeypatch.setitem(config.PRICE_SOURCE_CONFIG["web"], "xai_model", "grok-test-9")
    monkeypatch.delenv("XAI_MODEL", raising=False)
    w._llm_market_estimate({"material": "Mild steel"}, "xai")
    assert seen["model"] == "grok-test-9"


# ── the call itself ─────────────────────────────────────────────────────────────────────

class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, body):
    return urllib.error.HTTPError("https://api.x.ai/v1/chat/completions", code, "err", {},
                                  io.BytesIO(body.encode("utf-8")))


def _live(monkeypatch, model="grok-test-9"):
    import web_ai_price_lookup as w
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setitem(config.PRICE_SOURCE_CONFIG["web"], "xai_model", model)
    monkeypatch.setattr(w, "_XAI_CAPACITY_TRIPPED", False)
    monkeypatch.setattr(w, "_XAI_NO_EFFORT", set())
    monkeypatch.setattr(xai_models, "_REFUSED", set())
    return w


def test_the_call_sends_the_configured_model(monkeypatch):
    w = _live(monkeypatch)
    sent = []

    def fake_open(req, timeout=0):
        sent.append(json.loads(req.data.decode("utf-8")))
        return _Reply(json.dumps({"choices": [{"message": {"content": '{"ok": 1}'}}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    assert w._call_xai_llm("price this") == {"ok": 1}
    assert sent[0]["model"] == "grok-test-9" and sent[0]["reasoning_effort"] == "low"


def test_a_model_that_refuses_the_reasoning_setting_is_asked_again_without_it(monkeypatch, capsys):
    w = _live(monkeypatch)
    sent = []

    def fake_open(req, timeout=0):
        body = json.loads(req.data.decode("utf-8"))
        sent.append(body)
        if "reasoning_effort" in body:
            raise _http_error(400, '{"error": "Argument not supported on this model: '
                                   'reasoning_effort"}')
        return _Reply(json.dumps({"choices": [{"message": {"content": '{"ok": 2}'}}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    assert w._call_xai_llm("price this") == {"ok": 2}
    assert w._call_xai_llm("and this") == {"ok": 2}
    assert [("reasoning_effort" in b) for b in sent] == [True, False, False]
    assert "does not take a reasoning setting" in capsys.readouterr().out


def test_a_refused_model_is_said_once_with_the_fix(monkeypatch, capsys):
    w = _live(monkeypatch, model="grok-nope")

    def fake_open(req, timeout=0):
        raise _http_error(404, '{"error": "The model grok-nope does not exist or your team '
                               'does not have access to it."}')

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    assert w._call_xai_llm("one") is None
    assert w._call_xai_llm("two") is None
    out = capsys.readouterr().out
    assert out.count("xAI REFUSED THE MODEL 'grok-nope'") == 1
    assert "python src\\xai_models.py" in out and "SDI_XAI_MODEL" in out


def test_other_refusals_are_not_called_a_model_refusal():
    assert not xai_models.looks_like_model_refusal(429, "resource-exhausted: model at capacity")
    assert not xai_models.looks_like_model_refusal(401, "invalid api key")
    assert not xai_models.looks_like_model_refusal(400, "prompt too long")
    assert xai_models.looks_like_model_refusal(404, "Model not found: grok-9")


def test_the_openai_client_refusal_is_said_too(monkeypatch, capsys):
    monkeypatch.setattr(xai_models, "_REFUSED", set())

    class NotFound(Exception):
        status_code = 404

    assert xai_models.note_exception(NotFound("Error code: 404 - model 'grok-x' not found"),
                                     "grok-x")
    assert "xAI REFUSED THE MODEL 'grok-x' (HTTP 404)" in capsys.readouterr().out


# ── the check ───────────────────────────────────────────────────────────────────────────

def _account(language, image=()):
    def fetch(path, key):
        if path == "/language-models":
            return {"models": language}
        if path == "/image-generation-models":
            return {"models": list(image)}
        return {"data": []}
    return fetch


def _set(monkeypatch, text="grok-4.7", vision="grok-4.7", image="grok-imagine-image-2.0"):
    monkeypatch.setattr(config, "XAI_MODEL", text)
    monkeypatch.setattr(config, "XAI_VISION_MODEL", vision)
    monkeypatch.setattr(config, "XAI_IMAGE_MODEL", image)


def test_the_check_passes_when_the_account_serves_every_setting(monkeypatch):
    _set(monkeypatch)
    code, lines = xai_models.check("k", _account(
        [{"id": "grok-4.7", "input_modalities": ["text", "image"]},
         {"id": "grok-4.3", "input_modalities": ["text", "image"]}],
        [{"id": "grok-imagine-image-2.0"}]))
    assert code == 0
    assert sum(line.startswith("OK") for line in lines) == 3


def test_the_check_names_a_model_the_account_does_not_serve(monkeypatch):
    _set(monkeypatch, text="grok-9", vision="grok-9")
    code, lines = xai_models.check("k", _account(
        [{"id": "grok-4.3", "input_modalities": ["text", "image"]}],
        [{"id": "grok-imagine-image-2.0"}]))
    assert code == 1
    assert any(line.startswith("NOT SERVED  grok-9") for line in lines)
    assert any("This account serves: grok-4.3, grok-imagine-image-2.0" in line for line in lines)


def test_the_check_refuses_a_reading_model_that_takes_no_pictures(monkeypatch):
    _set(monkeypatch, vision="grok-text-only")
    code, lines = xai_models.check("k", _account(
        [{"id": "grok-4.7", "input_modalities": ["text", "image"]},
         {"id": "grok-text-only", "input_modalities": ["text"]}],
        [{"id": "grok-imagine-image-2.0"}]))
    assert code == 1 and any(line.startswith("NO IMAGE INPUT") for line in lines)


def test_an_alias_counts(monkeypatch):
    _set(monkeypatch, text="grok-latest", vision="grok-latest")
    code, lines = xai_models.check("k", _account(
        [{"id": "grok-4.7", "aliases": ["grok-latest"], "input_modalities": ["text", "image"]}],
        [{"id": "grok-imagine-image-2.0"}]))
    assert code == 0 and any("alias of grok-4.7" in line for line in lines)


def test_no_key_or_no_answer_is_unchecked_not_passed(monkeypatch):
    _set(monkeypatch)
    assert xai_models.check("")[0] == 2

    def down(path, key):
        raise OSError("no route")
    assert xai_models.check("k", down)[0] == 2


def test_the_check_says_where_each_setting_comes_from(monkeypatch):
    _set(monkeypatch)
    monkeypatch.delenv("SDI_XAI_MODEL", raising=False)
    monkeypatch.delenv("XAI_MODEL", raising=False)
    monkeypatch.setenv("SDI_XAI_IMAGE_MODEL", "grok-imagine-image-2.0")
    lines = xai_models.check("")[1]
    assert "config.py default" in lines[0]
    assert ".env or shell (SDI_XAI_IMAGE_MODEL)" in lines[2]
