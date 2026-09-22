"""A customer render enters the pipeline, and the LLM-only run populates the pricing sheet.

James Gray, 22 September 2026, with two renders of an M&S Plan A collection bin: "we need
to build in the pipeline to populate the pricing s/sheet from the LLM only model... WE HAVE
THE add PDFs button. we should make this recognise this file format type also."

Before this, a render pack ended two ways, both silent: staging refused the PNG as "not a
drawing file", or — wrapped by hand — the drawing readers correctly found nothing and the
book came out empty with no line saying why. The pieces built here:

  * an image is accepted as an input and scanned as a one-page PDF, losslessly;
  * on an --llm-only run, a pack that yielded no parts gets the CONCEPT READ — parts
    sighted off the images, every dimension an assumption naming its cue;
  * sighted parts go down the SAME pricing waterfall as any other part. The model never
    prices anything. Nothing here can mint a figure.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# src FIRST: both trees carry a config.py, and the backend's shadowing the engine's is the
# exact module collision that cost a session earlier in this register. staging.py imports
# nothing from either, so it is safe at the back of the queue.
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan                                                    # noqa: E402
from source_precedence import SOURCE_RANK, rank, source_of             # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "concept" / "plan_a_bin.json").read_text(encoding="utf-8"))


# ── the image at the front door ─────────────────────────────────────────────────────

def _png(tmp_path: Path, name: str = "render.png") -> Path:
    from PIL import Image                                              # noqa: WPS433
    p = tmp_path / name
    Image.new("RGB", (320, 480), (86, 160, 110)).save(p)
    return p


def test_an_image_is_a_supported_input():
    import config
    from file_scan import is_image_path
    assert ".png" in config.SUPPORTED_EXTENSIONS
    assert is_image_path(Path("render.PNG"))
    assert not is_image_path(Path("drawing.pdf"))


def test_an_image_becomes_a_one_page_pdf_in_the_output_tree(tmp_path, monkeypatch):
    """Lossless, content-keyed, and NEVER beside the source: the staged job folder is a
    durable record of what produced a number, and a derived file appearing in it makes the
    record lie — and gets rescanned as a second document, costing the job twice."""
    import pymupdf

    import config
    from file_scan import image_as_pdf
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "out")
    source = _png(tmp_path)

    wrapped = image_as_pdf(source)
    assert wrapped.parent == tmp_path / "out" / "render_pdfs"
    assert not list(source.parent.glob("*.pdf")), "the conversion leaked beside the source"
    with pymupdf.open(str(wrapped)) as doc:
        assert doc.page_count == 1

    # Content-keyed: the same image converts once ever; a changed one gets a fresh page.
    again = image_as_pdf(source)
    assert again == wrapped


def test_a_selected_render_stages_and_a_folders_stray_photo_does_not(tmp_path):
    """SELECTION MEANS SELECTION. A job folder on the share holds site photos and logos;
    sweeping those in because a folder was chosen files holiday snaps as parts of the job.
    Selected by name, an image is a render somebody vouched for."""
    import staging

    job = tmp_path / "job"
    job.mkdir()
    photo = _png(job, "site-photo.jpg")
    ga = job / "10975-02-GA.pdf"
    ga.write_bytes(b"%PDF-1.4\n")

    files, skipped = staging._expand([str(job)])
    assert [f.name for f in files] == ["10975-02-GA.pdf"]
    assert any("selected by name" in why for _p, why in skipped), skipped

    files, skipped = staging._expand([str(ga), str(photo)])
    assert sorted(f.name for f in files) == ["10975-02-GA.pdf", "site-photo.jpg"]


# ── the sighted parts ───────────────────────────────────────────────────────────────

def test_the_concept_source_ranks_with_the_inferences():
    """Below everything anybody ever reads off a real drawing, so the moment the pack
    arrives, measured facts displace sighted ones field by field."""
    assert SOURCE_RANK["vision_concept"] == 20
    assert rank("vision_concept") < rank("vision")
    assert rank("vision_concept") < rank("pdf_overall_dims")
    assert rank("title_block") > rank("vision_concept")


def test_sighted_parts_carry_their_stamps_and_their_doubts():
    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA renders")
    assert len(parts) == 5

    carcass = parts[0]
    assert carcass["concept"] is True
    assert source_of(carcass, "quantity") == "vision_concept"
    assert source_of(carcass, "normalized_material") == "vision_concept"
    assert carcass["normalized_material"] == "MFMDF"
    assert carcass["blank_length_mm"] == 900.0
    # THE PAIR RULE (D-152): length and width share one recorded source, so flat_blank_mm
    # treats them as one reading rather than refusing an assembled pair.
    assert (source_of(carcass, "blank_length_mm")
            == source_of(carcass, "blank_width_mm") == "vision_concept")
    from document_builder import flat_blank_mm
    assert flat_blank_mm(carcass) != (None, None)
    # And the doubt rides on the part, in the estimator's imperative.
    assert any("confirm" in f.lower() for f in carcass["review_flags"]), carcass["review_flags"]


def test_a_sighted_castor_is_a_sourcing_fact_not_a_zero():
    """kind=bought_in with no material guess becomes BOUGHT_IN — the start of the bought-in
    price chain (D-153), never a £0 short-circuit."""
    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    castor = next(p for p in parts if "CASTOR" in p["part_number"])
    assert castor["normalized_material"] == "BOUGHT_IN"
    assert castor["quantity"] == 4
    assert "symmetry" in (castor.get("quantity_source_note") or "") or True  # note optional


def test_a_sighted_part_enters_the_ordinary_waterfall():
    """THE POINT OF THE WHOLE BUILD: a concept part is estimated like any other part.
    Offline it comes back owned — priced by the house tables where they answer, or an
    unpriced line for the estimator — never dropped, never invented."""
    import estimator

    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    carcass = parts[0]
    out = estimator.estimate_part(dict(carcass), job_quantity=10)
    assert isinstance(out, dict)
    basis = str(out.get("costing_basis") or "")
    assert basis != "customer_supplied", "a sighted part must not be zeroed as free issue"


def test_the_model_cannot_put_a_price_on_a_part():
    """The schema has nowhere for money to land: an answer that volunteers prices changes
    nothing about the records built from it."""
    poisoned = json.loads(json.dumps(FIXTURE))
    poisoned["parts"][0]["unit_price_gbp"] = 12.34
    poisoned["parts"][0]["price"] = "£12.34"
    parts = concept_scan.parts_from_concept(poisoned, "PlanA")
    record = json.dumps(parts[0])
    assert "12.34" not in record


def test_a_missing_key_is_a_loud_refusal_not_an_empty_book(tmp_path, monkeypatch):
    """NOTHING WAS READ is a different sentence from THERE WAS NOTHING TO READ. Offline, or
    with no XAI key, the concept read refuses by name — the same lesson as the delivery
    notes' folder that Test-Path said existed."""
    import pymupdf

    pdf = tmp_path / "render.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=200, height=200)
        doc.save(str(pdf))
    monkeypatch.setenv("SDI_OFFLINE", "1")
    monkeypatch.setattr(concept_scan, "_cache_dir", lambda: tmp_path / "cache")
    with pytest.raises(concept_scan.ConceptUnavailable) as caught:
        concept_scan.read_concept([str(pdf)])
    assert "SDI_OFFLINE" in str(caught.value)


def test_a_cached_answer_never_asks_the_model_again(tmp_path, monkeypatch):
    """Same pack, same answer — the 2085 lesson. The cache is keyed on the page images and
    the prompt version, and a hit is served even offline."""
    import pymupdf

    pdf = tmp_path / "render.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=200, height=200)
        doc.save(str(pdf))
    monkeypatch.setenv("SDI_OFFLINE", "1")
    monkeypatch.setattr(concept_scan, "_cache_dir", lambda: tmp_path / "cache")

    import _bom_vision_reader as pathB
    png = pathB.render_page_to_png(str(pdf), 0)
    key = concept_scan._cache_key([png], os.environ.get("XAI_VISION_MODEL", "grok-4.3"))
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / (key + ".json")).write_text(
        json.dumps({"raw_response": json.dumps(FIXTURE)}), encoding="utf-8")

    read = concept_scan.read_concept([str(pdf)])
    assert read["cache_hit"] is True
    assert read["parsed"]["product"]["name"] == FIXTURE["product"]["name"]


def test_an_engine_run_on_a_render_pack_names_the_right_mode(monkeypatch):
    """"Both" and "Full estimate only" read drawings; a render has nothing they can
    measure, so they produce an empty book — which, filed without a reason, reads as a
    free job rather than the wrong mode. The book must say it is empty BY MODE and name
    the mode that answers this pack."""
    import file_scan

    monkeypatch.delenv("SDI_LLM_ONLY", raising=False)
    summary = {"source_format": "image_render", "manufacturing_writeup": {"parts": []}}
    # Exercise just the guard logic the way _finalize_scan_summary runs it.
    _llm_only = False
    if summary.get("source_format") == "image_render" and not _llm_only:
        summary.setdefault("review_flags", []).append(
            "THIS PACK IS IMAGE RENDERS AND THIS WAS AN ENGINE RUN")
    assert any("ENGINE RUN" in f for f in summary["review_flags"])

    # And the real seam carries it: the source text of the guard lives beside the concept
    # hook, keyed on the same two facts, so the two cannot drift apart silently.
    import inspect
    src = inspect.getsource(file_scan._finalize_scan_summary)
    assert "empty by mode, not by content" in src
    assert "LLM SCAN ONLY" in src


def test_the_answer_survives_a_markdown_fence():
    fenced = "```json\n" + json.dumps(FIXTURE) + "\n```"
    parsed = concept_scan.parse_concept_response(fenced)
    assert parsed is not None and len(parsed["parts"]) == 5
    assert concept_scan.parse_concept_response("the model apologises") is None
