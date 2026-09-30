"""The enquiry brief: stated facts for an LLM-only read of a render (D-360).

Dave Wright, 30 Sep 2026, on the M&S clothes bin: "350off … Plywood construction with print,
or mild steel powder coated with print … 600 x 600 x 1200mm bump bin with lid with 1800mm back
panel." The render alone had been read as a 1,750 mm carcass of 18 mm MFMDF. Nothing may be
written into the code for one job, so the brief is an input: typed on the portal, filed with the
pack, put to the model as facts that outrank the picture, and stamped on every figure it gives.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402
import source_precedence as sp  # noqa: E402

BRIEF = ("600 x 600 x 1200mm bump bin with lid with 1800mm back panel. Plywood construction "
         "with print, or mild steel powder coated with print. 350 off.")


def test_the_brief_is_put_to_the_model_only_when_there_is_one(monkeypatch):
    seen = {}

    class _Resp:
        choices = [type("C", (), {"message": type("M", (), {"content": "{}"})()})()]

    class _Client:
        def __init__(self, **kw):
            self.chat = type("Ch", (), {"completions": self})()

        def create(self, **kw):
            seen["text"] = kw["messages"][0]["content"][0]["text"]
            return _Resp()

    import types
    monkeypatch.setenv("SDI_OFFLINE", "0")
    monkeypatch.setenv("XAI_API_KEY", "x")
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_Client))
    cs._call_vision_llm([b"png"], "m", BRIEF)
    assert "ENQUIRY BRIEF" in seen["text"] and "600 x 600 x 1200mm" in seen["text"]
    assert "cost ONLY the FIRST one" in seen["text"]
    cs._call_vision_llm([b"png"], "m", "")
    assert "ENQUIRY BRIEF" not in seen["text"]


def test_a_brief_changes_the_cache_key_and_no_brief_keeps_the_old_one():
    k0 = cs._cache_key([b"png"], "m")
    assert cs._cache_key([b"png"], "m", "") == k0
    k1 = cs._cache_key([b"png"], "m", BRIEF)
    assert k1 != k0 and cs._cache_key([b"png"], "m", BRIEF + " steel") != k1


def test_the_brief_outranks_a_sighting_and_yields_to_a_drawing():
    r = sp.SOURCE_RANK if hasattr(sp, "SOURCE_RANK") else None
    rank = (r or {}).get
    get = rank if r else (lambda k: sp.rank_of(k))
    assert get("enquiry_brief") > get("vision_concept")
    assert get("enquiry_brief") < get("bom_tree")
    assert "enquiry brief" in sp.SOURCE_DISPLAY_NAME["enquiry_brief"]


def _answer():
    return {"product": {"name": "bump bin", "assumed_overall_mm":
                        {"height": 1200, "width": 600, "depth": 600}},
            "parts": [
                {"name": "SIDE PANEL", "kind": "fabricated", "material_guess": "PLYWOOD",
                 "assumed_blank_mm": {"length": 1200, "width": 600, "thickness": 18},
                 "quantity": 2, "quantity_basis": "from the brief — two sides",
                 "operations": ["saw"], "why_size": "from the brief: 600 x 600 x 1200mm",
                 "from_brief": ["size", "material", "quantity"]},
                {"name": "CASTOR", "kind": "bought_in", "quantity": 4,
                 "operations": [], "from_brief": []}],
            "options_not_costed": ["mild steel powder coated with print"]}


def test_brief_figures_are_stamped_as_the_brief_and_sighted_ones_are_not():
    parts = cs.parts_from_concept(_answer(), "M&S bin")
    side, castor = parts[0], parts[1]
    src = lambda p, f: sp.source_of(p, f) if hasattr(sp, "source_of") else None  # noqa: E731
    assert src(side, "blank_length_mm") == "enquiry_brief"
    assert src(side, "normalized_material") == "enquiry_brief"
    assert src(side, "quantity") == "enquiry_brief"
    assert src(castor, "quantity") == "vision_concept"
    flags = " ".join(side["review_flags"])
    assert "size from the enquiry brief" in flags and "size assumed from the render" not in flags


def test_the_options_the_brief_did_not_cost_are_named():
    assert cs.concept_note(_answer())["options_not_costed"] == [
        "mild steel powder coated with print"]


def test_the_brief_is_read_from_the_job_folder(tmp_path):
    assert cs.read_brief(tmp_path) == ""
    (tmp_path / cs.BRIEF_FILENAME).write_text("  " + BRIEF + "\n", encoding="utf-8")
    assert cs.read_brief(tmp_path) == BRIEF
    assert cs.read_brief(None) == ""


@pytest.fixture()
def routes():
    sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
    import estimate_routes as m
    return m


def test_the_service_files_this_runs_brief_and_removes_a_stale_one(routes, tmp_path):
    run = routes.Run(run_id="t", client="M&S", drawing_number="bdab4adf", units=350,
                     job_folder=str(tmp_path), output_path="o", queued_at=0.0)
    routes._file_enquiry_brief(run, tmp_path, BRIEF)
    assert (tmp_path / "ENQUIRY_BRIEF.txt").read_text(encoding="utf-8").strip() == BRIEF
    routes._file_enquiry_brief(run, tmp_path, "   ")
    assert not (tmp_path / "ENQUIRY_BRIEF.txt").exists()
    assert "EstimateRequest" in dir(routes)
    assert "enquiry_brief" in routes.EstimateRequest.model_fields \
        if hasattr(routes.EstimateRequest, "model_fields") \
        else "enquiry_brief" in routes.EstimateRequest.__fields__


def test_the_page_sends_the_brief_with_an_llm_read_only():
    page = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
        encoding="utf-8")
    assert 'id="enquiryBrief"' in page
    assert page.count('enquiry_brief: ($("enquiryBrief").value') == 1
    i = page.index('enquiry_brief: ($("enquiryBrief").value')
    assert 'method: "llm"' in page[i - 200:i]


# ── D-361 ──────────────────────────────────────────────────────────────────────────────

def test_a_render_remembers_the_folder_it_was_staged_in(tmp_path, monkeypatch):
    """13:07: the brief sat beside the PNG and the scan read a copy in the output tree."""
    pymupdf = pytest.importorskip("pymupdf")
    import config
    import file_scan as fs
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "out")
    job = tmp_path / "M&S" / "bdab4adf"
    job.mkdir(parents=True)
    png = job / "bin.png"
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4), 0)
    pix.save(str(png))
    (job / cs.BRIEF_FILENAME).write_text(BRIEF, encoding="utf-8")
    pdf = fs.image_as_pdf(png)
    assert pdf.parent != job
    assert fs._render_source_dir(pdf) == str(job.resolve())
    text, where = cs.find_brief([None, fs._render_source_dir(pdf)])
    assert text == BRIEF and where.endswith(cs.BRIEF_FILENAME)


def test_the_finished_book_is_not_resaved_after_excel_calculated_it():
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    i = src.index('summary["invariants"] = _inv')
    assert "_rewrite_estimate_banner(" not in src[i:i + 900]
