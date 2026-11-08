"""The drawing reader can be run on its own, with no language model and no cached answer (D-753).

8 Nov 2026 review of 0358141, SCRUM-194/180: "Reusing cached LLM facts can prove transfer
fixes; it cannot prove the deterministic reader supplied those facts. Likewise, 'no new LLM
call' is not the same as 'no LLM dependence.'" The acceptance needs a run in which every reader
that asks a model about the drawing is off AND no earlier answer from one is applied: the
whole-pack read and its inference pass, the vision BOM reader, the page vision pass, the DXF
interpretation, the note scan and the concept read. --deterministic-only is that run, from the
page's checkbox through the service and the runner to the engine, and it says so on the run.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BACKEND = ROOT / "sdi-intelligence-backend"
RUNNER_DIR = ROOT / "tools" / "runner"
sys.path.insert(0, str(SRC))


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# ── the engine ──────────────────────────────────────────────────────────────────────────

def test_the_engine_takes_the_flag_and_turns_every_model_reader_off():
    src = _read("src/main.py")
    assert '"--deterministic-only"' in src
    at = src.index("if getattr(args, \"deterministic_only\", False):")
    block = src[at:at + 1500]
    for env in ('os.environ["SDI_DETERMINISTIC_ONLY"] = "1"',
                'os.environ["SDI_LLM_FULL_EXTRACT"] = "0"',
                'os.environ["SKIP_VISION_EXTRACTION"] = "1"',
                'os.environ["SDI_DXF_LLM_INTERPRET"] = "0"'):
        assert env in block, env
    assert "--llm-only ask opposite questions" in block
    assert 'summary["deterministic_only"] = bool(getattr(args, "deterministic_only", False))' in src


def test_each_model_reader_checks_the_switch_before_its_cache():
    fs = _read("src/file_scan.py")
    gate = fs[fs.index('_llm_off = _llm_flag in {"0", "false", "no", "off"}'):]
    assert "_det_only_llm()" in gate[:600], "the whole-pack read, and so its cache, is not called"
    assert "skip_vision = skip_vision or _det_only_vis()" in fs
    mb = _read("src/merge_boms.py")
    at = mb.index("b_boms = run_path_b(pdf_paths, _args, unread, worth, spend)")
    assert "if _det:" in mb[at - 900:at] and "b_boms = []" in mb[at - 900:at], \
        "Path B is not run at all, so no cached page answer is used"
    dj = _read("src/drawing_job_merge.py")
    assert 'getenv("SDI_DETERMINISTIC_ONLY"' in dj[dj.index("SDI_DXF_LLM_INTERPRET"):][:400]


def test_the_concept_read_refuses_before_its_cache(monkeypatch):
    import concept_scan
    monkeypatch.setenv("SDI_DETERMINISTIC_ONLY", "1")
    with pytest.raises(concept_scan.ConceptUnavailable) as got:
        concept_scan.read_concept(["nothing.pdf"])
    assert "new or cached" in str(got.value)


def test_the_note_scan_adds_nothing(monkeypatch):
    import config
    import note_scan
    monkeypatch.setattr(config, "NOTE_SCAN_POLICY", {"enable": True}, raising=False)
    monkeypatch.setenv("SDI_DETERMINISTIC_ONLY", "1")
    assert note_scan.scan_notes_for_bought_in("5m MAINS CABLE", existing_pns=set(),
                                              seen_codes=set(), stub_builder=dict) == []


def test_the_run_says_which_readers_were_off(monkeypatch):
    import run_readers as rr
    monkeypatch.delenv("SDI_DETERMINISTIC_ONLY", raising=False)
    assert rr.run_was_deterministic_only({"deterministic_only": True})
    assert not rr.run_was_deterministic_only({})
    readers = {r["key"]: r for r in rr.readers_that_ran(llm_only=False, deterministic_only=True)}
    assert readers["vision"]["ran"] is False
    assert "--deterministic-only" in readers["vision"]["why_off"]
    assert readers["bom_reader"]["ran"] is True and readers["pdf_text"]["ran"] is True
    line = rr.pdf_reader_summary({"deterministic_only": True})
    assert "Grok" not in line and "no language model" in line
    assert any("cached" in w for w in rr.DETERMINISTIC_ONLY_OFF)


# ── the runner ──────────────────────────────────────────────────────────────────────────

def test_the_runner_passes_the_flag_only_when_asked(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(RUNNER_DIR))
    import sdi_estimate_runner as runner
    on = runner.engine_command(tmp_path, tmp_path / "py.exe", tmp_path / "job", 1, "Acme",
                               deterministic_only=True)
    off = runner.engine_command(tmp_path, tmp_path / "py.exe", tmp_path / "job", 1, "Acme")
    assert "--deterministic-only" in on and "--deterministic-only" not in off
    src = _read("tools/runner/sdi_estimate_runner.py")
    assert 'deterministic_only=bool(job.get("deterministic_only"))' in src


# ── the service and the page ────────────────────────────────────────────────────────────

@pytest.fixture()
def er(tmp_path, monkeypatch):
    stub = types.ModuleType("config")
    stub.API_KEY = ""
    stub.FILE_ROOTS = [str(tmp_path)]
    monkeypatch.setitem(sys.modules, "config", stub)
    monkeypatch.syspath_prepend(str(BACKEND))
    sys.modules.pop("estimate_routes", None)
    mod = pytest.importorskip("estimate_routes",
                              reason="fastapi/pydantic not installed in this environment")
    yield mod
    sys.modules.pop("estimate_routes", None)


def test_a_runner_that_drops_the_flag_is_stopped(er):
    run = er.Run(run_id="d1", drawing_number="0358141", client="Acme", units=1,
                 job_folder="", output_path="", deterministic_only=True)
    er._check_the_engine_was_told(run, '$ python -u main.py --job "x" --order-qty 1')
    assert run.instruction_refused and "--deterministic-only" in run.refusal_reason
    told = er.Run(run_id="d2", drawing_number="0358141", client="Acme", units=1,
                  job_folder="", output_path="", deterministic_only=True)
    er._check_the_engine_was_told(told, "$ python -u main.py --job x --deterministic-only")
    assert not told.instruction_refused


def test_the_service_accepts_the_method_and_hands_it_to_the_runner():
    src = _read("sdi-intelligence-backend/estimate_routes.py")
    assert 'if method not in {"both", "llm", "engine", "deterministic"}:' in src
    assert 'deterministic_only=(method == "deterministic"),' in src
    assert '"deterministic_only": bool(getattr(run, "deterministic_only", False)),' in src
    assert "DETERMINISTIC-ONLY: no language model reads the drawings" in src


def test_the_page_offers_it_as_a_test_not_an_estimate():
    page = _read("sdi-intelligence-backend/sdi-estimating-intelligence.html")
    assert 'id="detOnly"' in page and "Not an" in page[page.index('id="detOnly"'):][:600]
    assert ('method: (document.getElementById("detOnly") || {}).checked ? "deterministic" '
            ': undefined,') in page
