"""A read made once is kept, keyed on everything that would change its answer (D-554).

James Gray, 20 Oct 2026: "can we not re use / cache file or otherwise store enough data to
prevent from re running all the same processes in full for every drawing set ... unless there
had been a coding change or something else requiring it." 0359342 spent 3,002 s of a 3,775 s
run reading its PDFs — OCR and a local vision model over every page — and every re-run spent
it again on bytes nothing had changed. The store keeps the RAW reading; the interpretation is
made again on every run by the current code.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import read_store as rs  # noqa: E402
import run_timing as rt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_READ_STORE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("SDI_READ_REFRESH", raising=False)
    rt.reset()
    yield tmp_path / "cache"
    rt.reset()


# ── the key is the question ───────────────────────────────────────────────────────────

def test_the_key_moves_with_the_content_the_code_and_the_settings():
    def k(**kw):
        args = {"content": b"abc", "fingerprint": "f1", "context": {"a": 1}}
        args.update(kw)
        return rs.key("t", **args)
    assert k() == k()
    assert k(content=b"abd") != k()
    assert k(fingerprint="f2") != k()
    assert k(context={"a": 2}) != k()
    assert rs.key("other", content=b"abc", fingerprint="f1", context={"a": 1}) != k()
    assert k(content=[b"ab", b"c"]) != k(content=[b"a", b"bc"])     # pages are not one blob


# ── given back, not made again ────────────────────────────────────────────────────────

def test_the_second_read_of_the_same_bytes_is_given_back_not_made(store):
    calls = []

    def compute():
        calls.append(1)
        return {"words": ["a", "b"], "n": 2}

    first = rs.reuse("t", content=b"pdf-bytes", fingerprint="f", context={"dpi": 300},
                     compute=compute, source="x.pdf")
    second = rs.reuse("t", content=b"pdf-bytes", fingerprint="f", context={"dpi": 300},
                      compute=compute, source="x.pdf")
    assert first["hit"] is False and second["hit"] is True and calls == [1]
    assert second["raw"] == first["raw"]
    assert rt.reuse_counts()["t"] == {"reused": 1, "computed": 1}
    entry = json.loads(Path(first["path"]).read_text(encoding="utf-8"))
    assert entry["schema"] == rs.SCHEMA and entry["source"] == "x.pdf"
    assert entry["components"]["fingerprint"] == "f"
    assert entry["components"]["context"] == {"dpi": 300}
    assert len(entry["components"]["content_sha256"]) == 64
    assert Path(first["path"]).parent == store / "t"


def test_a_changed_reader_or_setting_is_a_new_read(store):
    calls = []

    def compute():
        calls.append(1)
        return len(calls)

    rs.reuse("t", content=b"x", fingerprint="code-1", context={}, compute=compute)
    rs.reuse("t", content=b"x", fingerprint="code-2", context={}, compute=compute)
    rs.reuse("t", content=b"x", fingerprint="code-2", context={"dpi": 600}, compute=compute)
    rs.reuse("t", content=b"x", fingerprint="code-2", context={"dpi": 600}, compute=compute)
    assert calls == [1, 1, 1]


def test_a_reading_the_caller_will_not_keep_is_used_and_not_stored(store):
    calls = []

    def compute():
        calls.append(1)
        return {"answered": False}

    a = rs.reuse("t", content=b"x", fingerprint="f", compute=compute, keep=lambda r: r["answered"])
    b = rs.reuse("t", content=b"x", fingerprint="f", compute=compute, keep=lambda r: r["answered"])
    assert a["raw"] == b["raw"] == {"answered": False} and calls == [1, 1]
    assert a["path"] is None and not list((store / "t").glob("*.json")) if (store / "t").exists() else True


def test_what_is_kept_can_be_thinner_than_what_is_used(store):
    first = rs.reuse("t", content=b"x", fingerprint="f", compute=lambda: {"a": 1, "big": [object()]},
                     thin=lambda r: {"a": r["a"]})
    assert first["raw"]["big"]                                   # this run has the whole thing
    second = rs.reuse("t", content=b"x", fingerprint="f", compute=lambda: pytest.fail("made again"),
                      thin=lambda r: {"a": r["a"]})
    assert second["hit"] is True and second["raw"] == {"a": 1}


def test_a_fresh_read_consults_nothing_kept_and_keeps_the_new_read(store, monkeypatch):
    calls = []

    def compute():
        calls.append(1)
        return {"n": len(calls)}

    rs.reuse("t", content=b"x", fingerprint="f", compute=compute)
    monkeypatch.setenv("SDI_READ_REFRESH", "1")
    fresh = rs.reuse("t", content=b"x", fingerprint="f", compute=compute)
    assert fresh["hit"] is False and fresh["raw"] == {"n": 2}
    monkeypatch.delenv("SDI_READ_REFRESH")
    after = rs.reuse("t", content=b"x", fingerprint="f", compute=compute)
    assert after["hit"] is True and after["raw"] == {"n": 2}      # the fresh read replaced the old


def test_the_readers_own_failure_is_the_runs_and_is_raised_once(store):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("pdfplumber is not installed")

    with pytest.raises(RuntimeError, match="pdfplumber"):
        rs.reuse("t", content=b"x", fingerprint="f", compute=boom)
    assert calls == [1]
    assert rt.reuse_counts() == {}


def test_a_store_that_cannot_be_written_still_answers(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("SDI_READ_STORE_DIR", str(blocker))
    monkeypatch.delenv("SDI_READ_REFRESH", raising=False)
    got = rs.reuse("t", content=b"x", fingerprint="f", compute=lambda: {"ok": True}, source="y.pdf")
    assert got["raw"] == {"ok": True} and got["hit"] is False and got["path"] is None
    assert "could not keep the read for y.pdf" in capsys.readouterr().out


def test_a_corrupt_entry_is_a_miss_and_is_rewritten(store):
    first = rs.reuse("t", content=b"x", fingerprint="f", compute=lambda: {"n": 1})
    Path(first["path"]).write_text("{not json", encoding="utf-8")
    again = rs.reuse("t", content=b"x", fingerprint="f", compute=lambda: {"n": 2})
    assert again["hit"] is False and again["raw"] == {"n": 2}
    assert json.loads(Path(first["path"]).read_text(encoding="utf-8"))["raw"] == {"n": 2}


# ── the reader's code, fingerprinted by what it reaches ──────────────────────────────

def _load(tmp_path, name, body):
    """Import a module from source — compiled here, not through the loader, which would reuse
    a .pyc written in the same second for a file of the same size."""
    import linecache
    path = tmp_path / f"{name}.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    sys.modules.pop(name, None)
    linecache.cache.pop(str(path), None)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)
    return mod


@pytest.fixture
def codebase(tmp_path, monkeypatch):
    """A two-module codebase standing in for src/: a reader, the helper it calls, a constant it
    reads through the module, and a function it never touches."""
    monkeypatch.setattr(rs, "_SRC_ROOT", tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    def build(helper_body="return x * 2", limit="3", unrelated="return 'a'"):
        rs._FINGERPRINTS.clear()
        _load(tmp_path, "rs_helperlib", f"""
            import re
            LIMIT = {limit}
            PATTERN = re.compile(r"\\d+")
            def helper(x):
                {helper_body}
            def unrelated():
                {unrelated}
        """)
        reader = _load(tmp_path, "rs_reader", """
            import rs_helperlib
            from rs_helperlib import helper
            def read(x):
                return helper(x) + rs_helperlib.LIMIT + len(rs_helperlib.PATTERN.findall("12"))
        """)
        return rs.fingerprint_code(reader.read)

    yield build
    for n in ("rs_helperlib", "rs_reader"):
        sys.modules.pop(n, None)
    rs._FINGERPRINTS.clear()


def test_the_fingerprint_follows_the_helpers_and_constants_a_reader_reaches(codebase):
    base = codebase()
    assert codebase() == base                                       # the same code, the same print
    assert codebase(helper_body="return x * 3") != base             # a helper three calls down
    assert codebase(limit="4") != base                              # a constant read via the module
    assert codebase(unrelated="return 'b'") == base                 # a function it never touches


def test_a_module_root_covers_the_sibling_functions_it_imports():
    import vision_extraction
    seen, out = set(), []
    rs._closure_sources(vision_extraction, seen, out)
    heads = [s.split("\n", 1)[0] for s in out]
    assert "module vision_extraction" in heads
    assert any(h.startswith("layout_zones.zone_boxes") for h in heads), heads
    assert any(h.startswith("extractor_patterns.normalize_text") for h in heads), heads


def test_the_fingerprint_is_short_stable_and_cached():
    import file_scan
    rs._FINGERPRINTS.clear()
    a = rs.fingerprint_code(file_scan.extract_with_pdfplumber)
    b = rs.fingerprint_code(file_scan.extract_with_pdfplumber)
    assert a == b and re.fullmatch(r"[0-9a-f]{16}", a)


def test_library_versions_name_what_is_installed_and_what_is_not():
    v = rs.library_versions("pytest", "no-such-distribution-xyz")
    assert v["pytest"] and v["no-such-distribution-xyz"] is None


# ── the PDF readings go through it ───────────────────────────────────────────────────

def test_the_pdf_readings_are_kept_and_the_interpretation_is_the_same(store, tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    pytest.importorskip("pdfplumber")
    import file_scan
    monkeypatch.setenv("SKIP_VISION_EXTRACTION", "1")

    def pdf(name, text):
        p = tmp_path / name
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
        doc.save(str(p))
        doc.close()
        return p

    a = pdf("a.pdf", "DRAWING NO 401918-01-05M   MATERIAL 2mm MILD STEEL   QTY 2")
    r1 = file_scan.pdf_readings(a)
    r2 = file_scan.pdf_readings(a)
    assert rt.reuse_counts()["pdf_readings"] == {"reused": 1, "computed": 1}
    assert r2["plumber"][0]["text"] == r1["plumber"][0]["text"]
    assert "401918-01-05M" in r1["plumber"][0]["text"]

    def interpret(r):
        s = file_scan.summarise_document(a, r["plumber"], r["pypdf"], vision_pages=r["vision"])
        return re.sub(r'"scanned_at": "[^"]*"', "", json.dumps(s, default=file_scan._json_default, sort_keys=True))
    assert interpret(r1) == interpret(r2)

    b = pdf("b.pdf", "DRAWING NO 401918-01-06M   MATERIAL 3mm MILD STEEL   QTY 4")
    file_scan.pdf_readings(b)
    assert rt.reuse_counts()["pdf_readings"] == {"reused": 1, "computed": 2}   # new bytes, new read
    entries = list((store / "pdf_readings").glob("*.json"))
    assert len(entries) == 2
    comp = json.loads(entries[0].read_text(encoding="utf-8"))["components"]
    assert comp["context"]["skip_vision"] is True and "libraries" in comp["context"]
    assert set(comp["context"]["env"]) == set(file_scan._VISION_ENV_KNOBS)


def test_a_vision_pass_the_local_model_never_answered_is_kept_and_said(monkeypatch, capsys):
    """D-564: the first policy kept no such reading, so a machine whose local model is never
    running re-read every page on every run (the 13:10 401918 book). Kept now, counted, and
    said in the log; whether the model was there to ask is part of the key instead."""
    import file_scan
    assert file_scan._pages_the_local_model_left_unanswered(
        [{"ollama_attempted": True, "used_llava": False}, {"ollama_attempted": True, "used_llava": True},
         {"ollama_attempted": False, "used_llava": False}]) == 1
    assert file_scan._pages_the_local_model_left_unanswered([]) == 0
    src = (ROOT / "src" / "vision_extraction.py").read_text(encoding="utf-8")
    assert '"ollama_attempted": bool(is_critical and _use_ollama() and ollama is not None)' in src
    fs = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "keep=lambda r: _vision_reading_is_whole" not in fs
    assert '"local_vision_model_reachable": _local_vision_model_reachable(skip_vision)' in fs


def test_whether_the_local_model_is_there_to_ask_is_part_of_the_settings(monkeypatch):
    import file_scan
    import vision_extraction as ve
    assert file_scan._local_vision_model_reachable(True) is None          # no vision pass at all
    monkeypatch.setenv("VISION_USE_OLLAMA", "0")
    assert file_scan._local_vision_model_reachable(False) is None         # not asked, so not a setting
    monkeypatch.setenv("VISION_USE_OLLAMA", "1")
    monkeypatch.setattr(ve, "ollama", None)
    assert file_scan._local_vision_model_reachable(False) is None         # no client installed

    class _Down:
        def Client(self, timeout=None):
            raise ConnectionError("refused")
    monkeypatch.setattr(ve, "ollama", _Down())
    assert file_scan._local_vision_model_reachable(False) is False

    class _Up:
        class Client:
            def __init__(self, timeout=None):
                pass

            def list(self):
                return {"models": []}
    monkeypatch.setattr(ve, "ollama", _Up())
    assert file_scan._local_vision_model_reachable(False) is True


def test_the_store_keeps_the_readings_without_the_fitz_drawings():
    import file_scan
    thin = file_scan._thin_readings({"plumber": [1], "pypdf": ["t"],
                                     "vision": [{"drawings": [object()], "ocr_text": "x"}]})
    assert thin["vision"] == [{"ocr_text": "x"}] and thin["plumber"] == [1] and thin["pypdf"] == ["t"]


def test_the_extract_reads_through_the_store_and_fresh_read_reaches_it():
    fs = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    body = fs.split("def extract_pdf_summary(")[1].split("\ndef ")[0]
    assert "readings = pdf_readings(pdf_path)" in body
    assert 'read_store.reuse("pdf_readings"' in fs
    main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ["SDI_READ_REFRESH"] = "1"' in main


# ── the whole-pack LLM store re-reads the words it kept ─────────────────────────────

@pytest.fixture
def llm(tmp_path, monkeypatch):
    import llm_full_extract as lfe
    monkeypatch.setenv("SDI_LLM_EXTRACT_CACHE_DIR", str(tmp_path / "llm"))
    monkeypatch.delenv("SDI_LLM_EXTRACT_REFRESH", raising=False)
    return lfe


def test_a_kept_transcription_is_read_again_by_the_current_code(llm, monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "build_document_context", lambda p: "PACK TEXT")
    answer = json.dumps({"bom": [{"part_number": "P1", "description": "BRACKET",
                                  "material_family": "metal", "material": "MILD STEEL",
                                  "thickness_or_section": "3mm", "quantity": 2}]})
    calls = []

    def fake_call(content, model, system=llm.SYSTEM_TRANSCRIBE):
        calls.append(1)
        return answer

    monkeypatch.setattr(llm, "_call_llm", fake_call)
    first = llm.extract_full_job("x.pdf", model="m")
    assert first.get("found") is True and calls == [1]
    entry = json.loads(next((tmp_path / "llm").glob("v1_*.json")).read_text(encoding="utf-8"))
    assert entry["_raw_full"] == answer                              # the words, whole

    # The model is now unreachable and the normaliser has moved on.
    def no_model(*a, **k):
        raise RuntimeError("no model")
    monkeypatch.setattr(llm, "_call_llm", no_model)
    real = llm.normalize_job

    def newer(job):
        real(job)
        job["reread_by"] = "newer code"
        return job
    monkeypatch.setattr(llm, "normalize_job", newer)
    second = llm.extract_full_job("x.pdf", model="m")
    assert second.get("found") is True and second.get("_from_cache") is True
    assert second.get("reread_by") == "newer code" and calls == [1]
    assert second.get("parts") == first.get("parts")


def test_a_kept_inference_is_read_again_too(llm, monkeypatch):
    answer = json.dumps({"parts": [{"part_number": "P1", "material_family": "metal",
                                    "material": "MILD STEEL", "thickness_or_section": "3mm"}],
                         "routes": [{"part_number": "P1", "operation": "welding"}]})
    calls = []

    def fake_call(content, model, system=llm.SYSTEM_INFER):
        calls.append(1)
        return answer

    monkeypatch.setattr(llm, "_call_llm", fake_call)
    first = llm.infer_missing_details("ctx", [], [{"part_number": "P1"}], model="m")
    assert first["found"] is True and first["routes"][0]["inferred"] is True and calls == [1]

    def no_model(*a, **k):
        raise RuntimeError("no model")
    monkeypatch.setattr(llm, "_call_llm", no_model)
    second = llm.infer_missing_details("ctx", [], [{"part_number": "P1"}], model="m")
    assert second["found"] is True and second.get("_from_cache") is True
    assert second["routes"][0]["operation"] == "welding" and calls == [1]


def test_an_entry_kept_before_the_words_were_is_used_as_it_is(llm, monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "build_document_context", lambda p: "OLD PACK")
    key = llm._cache_key("full", "OLD PACK", "m", llm._PROMPT, llm.SYSTEM_TRANSCRIBE)
    llm._cache_write(key, {"source": llm.SOURCE_NAME, "found": True, "parts": [{"part_number": "OLD"}]})
    monkeypatch.setattr(llm, "_call_llm", lambda *a, **k: pytest.fail("the model was asked"))
    got = llm.extract_full_job("x.pdf", model="m")
    assert got["parts"] == [{"part_number": "OLD"}] and got.get("_from_cache") is True
