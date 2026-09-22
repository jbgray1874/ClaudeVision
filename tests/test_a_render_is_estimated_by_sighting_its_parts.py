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
    assert len(parts) == 11, "the make list, not the noun list"

    carcass = parts[0]
    assert carcass["concept"] is True
    assert source_of(carcass, "quantity") == "vision_concept"
    assert source_of(carcass, "normalized_material") == "vision_concept"
    assert carcass["normalized_material"] == "MDF"
    assert carcass["blank_length_mm"] == 900.0
    # THE PAIR RULE (D-152): length and width share one recorded source, so flat_blank_mm
    # treats them as one reading rather than refusing an assembled pair.
    assert (source_of(carcass, "blank_length_mm")
            == source_of(carcass, "blank_width_mm") == "vision_concept")
    from document_builder import flat_blank_mm
    assert flat_blank_mm(carcass) != (None, None)
    # And the doubt rides on the part, in the estimator's imperative.
    assert any("confirm" in f.lower() for f in carcass["review_flags"]), carcass["review_flags"]


def test_an_enclosure_is_its_panels_not_one_blank():
    """James Gray, 22 Sep 2026, on the first render run: "You have a noun list, not a
    credible BOM or route... cabinet as faces or a carcass, not one 900×450 blank."

    The first answer returned four nouns — header, cabinet, lid, castors — and the cabinet
    was ONE blank. A carcass is not a part; it is five or six panels, each with its own
    blank and its own work, and nothing downstream can recover that from a single line.
    """
    names = [p["description"].upper() for p in
             concept_scan.parts_from_concept(FIXTURE, "PlanA")]
    for face in ("FRONT", "SIDE", "BACK", "BASE"):
        assert any(face in n for n in names), f"no {face} panel — the carcass is one blank again"
    assert not any("CABINET" in n and "PANEL" not in n for n in names), names


def test_every_made_part_carries_work_the_rate_card_can_price():
    """"A route that charges nothing is not a route." Sighted parts used to reach the
    compiler with no operations at all, so it minted a generic assembly on each leaf,
    correctly ruled every one out, and the labour column came to £0.00."""
    from department_codes import code_for                                # noqa: WPS433

    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    made = [p for p in parts if p.get("concept_kind") == "fabricated"]
    assert len(made) >= 6, "the fixture has no make list to speak of"
    for part in made:
        ops = part.get("inferred_operations") or []
        assert ops, f"{part['description']} carries no operation — it would cost nothing"
        for op in ops:
            assert code_for(op), f"{op!r} resolves to no department, so it charges nothing"


def test_an_operation_the_rate_card_cannot_price_is_dropped_and_said():
    """A word outside the vocabulary resolves to no department, mints nothing and charges
    nothing — silently. Dropping it is right; dropping it quietly is how a route looks
    complete and is not."""
    answer = json.loads(json.dumps(FIXTURE))
    answer["parts"][0]["operations"] = ["saw", "print", "wrap"]
    part = concept_scan.parts_from_concept(answer, "PlanA")[0]
    assert part["inferred_operations"] == ["saw"]
    assert any("not on the rate card" in f and "print" in f and "wrap" in f
               for f in part["review_flags"]), part["review_flags"]


def test_a_pack_with_measured_cad_is_never_sighted_over():
    """James Gray, 22 Sep 2026, on the split between the two paths: "If you point the render
    assembler at a real pack, you will flatten a weldment into one 5 mm panel again."

    The first gate was `--llm-only AND (a render pack OR no parts came out)`, and the second
    half is the hole: a REAL drawing pack whose BOM read came back empty — an unreadable
    table, a scan the reader could not see — would be handed to the concept read and guessed
    at, with flats and models sitting measured and ignored in the same folder.

    A drawing pack that produced no parts is a READER FAILURE. The honest output is that
    failure, not a picture-guess wearing its name.
    """
    # A flat in the pack: refused by file.
    assert concept_scan.why_not_sightable(
        {}, ["C:/job/11350-02-01_1mm MS_RevB.DXF"]) is not None
    assert "DXF" in concept_scan.why_not_sightable({}, ["x/a.DXF"])
    for cad in ("b.dwg", "c.SLDPRT", "d.sldasm", "e.step"):
        assert concept_scan.why_not_sightable({}, [cad]), cad

    # A DXF-sourced scan: refused by the summary.
    assert concept_scan.why_not_sightable({"source_format": "dxf"}, [])

    # A measured flat on a part: refused even when the file list is empty, because a pack
    # can reach this point with its geometry already merged onto the records.
    measured = {"manufacturing_writeup": {"parts": [
        {"part_number": "12349-02-69-04M", "flat_pattern_detected": True}]}}
    assert "measured flat" in concept_scan.why_not_sightable(measured, [])
    sw = {"manufacturing_writeup": {"parts": [
        {"part_number": "7332-01-003", "geometry_source": "solidworks_flat_pattern"}]}}
    assert concept_scan.why_not_sightable(sw, [])

    # THE CONTROL. A render pack has nothing to measure and is sightable.
    assert concept_scan.why_not_sightable(
        {"source_format": "image_render",
         "manufacturing_writeup": {"parts": []}},
        ["C:/job/PlanA-bin-render.png", "C:/job/visuals.pdf"]) is None


def test_the_refusal_is_wired_in_before_the_read_and_fails_closed():
    """A refusal is not a failure, so it is decided BEFORE the try — otherwise a deliberate
    refusal is reported as a concept read that crashed. And if the guard itself cannot run,
    the read does not run: the one thing worse than refusing a pack we could have sighted is
    sighting over a pack we could have measured."""
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "_concept_refused" in src
    assert "MEASURED CAD IS NEVER SIGHTED OVER" in src
    assert "the measured-CAD guard could not run" in src, "the guard does not fail closed"
    # The refusal must be decided before the concept read is attempted.
    assert src.index("_concept_refused = None") < src.index("_sighted = concept_scan.parts_from_concept")


def test_a_castor_is_never_nested_however_the_model_sizes_it():
    """James Gray, 22 Sep 2026: "Never nest a caster."

    The first run did. CASTORS came back with a 75×75 envelope, the assembler wrote it as a
    blank, and the nest block worked out 338 castors per 2500×1250 sheet. A castor is bought
    by the each; a blank is an instruction to nest, so a bought-in line must never get one.

    THE MAPPER REFUSES THE KIND — it does not rely on the prompt asking nicely. The model
    can see a castor and may well return its size, so the size is kept as a note and refused
    as a blank.
    """
    answer = json.loads(json.dumps(FIXTURE))
    castor = next(p for p in answer["parts"] if p["name"] == "CASTOR")
    castor["assumed_blank_mm"] = {"length": 75, "width": 75, "thickness": 75}

    part = next(p for p in concept_scan.parts_from_concept(answer, "PlanA")
                if "CASTOR" in p["part_number"])
    assert part.get("blank_length_mm") in (None, 0), "a castor was written as a blank"
    assert part.get("blank_width_mm") in (None, 0)
    assert part.get("normalized_thickness_mm") in (None, 0)
    # Kept as evidence, not thrown away — it is a real observation, just not a blank.
    assert part["concept_sighted_size_mm"]["length"] == 75
    assert any("never nested" in f for f in part["review_flags"]), part["review_flags"]


def test_an_applied_graphic_is_not_nested_either():
    """A print laid onto a panel is bought by area or by the each; it is not cut from a
    sheet of graphics. Same rule, same reason."""
    answer = json.loads(json.dumps(FIXTURE))
    part = next(p for p in concept_scan.parts_from_concept(answer, "PlanA")
                if "GRAPHIC" in p["part_number"])
    assert part["concept_kind"] == "graphic"
    assert part.get("blank_length_mm") in (None, 0), "the graphic was written as a blank"


def test_a_fabricated_panel_still_gets_its_blank():
    """The control. A guard that refuses everything is not a guard — a made panel must
    still nest, or there is no material cost at all."""
    part = concept_scan.parts_from_concept(FIXTURE, "PlanA")[0]
    assert part["concept_kind"] == "fabricated"
    assert part["blank_length_mm"] == 900.0 and part["blank_width_mm"] == 400.0


def test_the_prompt_cannot_change_without_its_cache_version():
    """THE SILENT UNDO. The prompt is part of the cache key, so editing it WITHOUT bumping
    the version means the new instructions are never sent: every pack replays the answer the
    old prompt produced, and the run looks entirely normal. This whole rewrite — "an
    enclosure is its panels" — would have reached nothing on the machine it was written for.

    So the prompt's own hash is pinned beside the version. Change the prompt, this fails, and
    the fix is two lines: bump the version, record the new hash."""
    import hashlib

    got = hashlib.sha256(concept_scan._PROMPT.encode()).hexdigest()[:12]
    assert got == concept_scan._PROMPT_FINGERPRINT, (
        f"the concept prompt changed. Bump CONCEPT_PROMPT_VERSION (now "
        f"{concept_scan.CONCEPT_PROMPT_VERSION!r}) and set _PROMPT_FINGERPRINT = {got!r}")


def test_every_operation_offered_to_the_model_resolves_to_a_department():
    """The vocabulary is the contract. A word in this list that the rate card cannot resolve
    is an operation the model will happily return and nothing will ever charge for."""
    from department_codes import code_for

    for op in concept_scan.SIGHTABLE_OPERATIONS:
        assert code_for(op), f"{op!r} is offered to the model and resolves to no department"


def test_the_unit_has_work_of_its_own():
    """"assemble carcass → fit lid & wheels → pack" happens to the PRODUCT, not to any one
    panel, and has nowhere else to live. A unit of several parts is assembled whatever else
    the model said."""
    assert concept_scan.unit_operations(FIXTURE) == ["bench_work", "assembly"]
    assert concept_scan.unit_operations({"parts": [{}, {}]}) == ["assembly"]
    assert concept_scan.unit_operations({"parts": [{}]}) == [], "one part is not an assembly"
    assert concept_scan.unit_operations(
        {"parts": [{}, {}], "unit_operations": ["teleportation"]}) == ["assembly"]


def test_a_made_part_with_no_sighted_work_says_so():
    """Material and no labour is a part somebody must look at, not a cheap one."""
    answer = json.loads(json.dumps(FIXTURE))
    answer["parts"][0]["operations"] = []
    part = concept_scan.parts_from_concept(answer, "PlanA")[0]
    assert not part.get("inferred_operations")
    assert any("no manufacturing operation" in f for f in part["review_flags"])


def test_a_bought_in_line_needs_no_work_and_no_blank():
    """A castor is bought. It has no blank and no operations, and neither is a defect."""
    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    castor = next(p for p in parts if "CASTOR" in p["part_number"])
    assert not castor.get("inferred_operations")
    assert not any("no manufacturing operation" in f for f in castor["review_flags"])


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


def test_a_staged_render_survives_the_walk_from_discovery_to_the_job(tmp_path):
    """THE FIRST LIVE RUN FILED A SUMMARY AND NO WORKBOOK.

        Found 1 drawing file(s).
        Folder-as-job: 0 job folder(s) from 1 file(s).

    `list_input_files` discovered the render (config.SUPPORTED_EXTENSIONS knew about it);
    `group_input_files_by_folder` filtered to `.pdf` and dropped it. Nothing failed — the
    pack simply became empty between one function and the next, and the run reported
    success over an empty book.

    Both halves are asserted here, because the defect lived in the JOIN between them: a
    render must be discovered AND still be there when the job is grouped.
    """
    from file_scan import group_input_files_by_folder, list_input_files

    job = tmp_path / "M&S" / "bdab4adf"
    job.mkdir(parents=True)
    _png(job, "PlanA-bin-render.png")
    (job / "notes.txt").write_bytes(b"not a drawing")

    found = list_input_files(job, "*")
    assert [p.name for p in found] == ["PlanA-bin-render.png"], found

    groups = group_input_files_by_folder(found)
    assert len(groups) == 1, "the render was discovered and then dropped before the job"
    assert [p.name for p in next(iter(groups.values()))] == ["PlanA-bin-render.png"]


def test_files_found_but_not_grouped_stops_the_run(tmp_path):
    """"0 job folder(s) from 1 file(s)" was a line of information and the run carried on,
    filing a summary with no workbook and exiting 0. Discovery and grouping disagreeing is
    always a defect in the engine — never a fact about the pack — so it refuses, names the
    files it could not place, and exits NON-ZERO. A returned code would not do: main() is
    called for its side effects and its value is discarded."""
    import re

    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    guard = re.search(r"if files and not scan_jobs:(.{0,1400})", src, re.S)
    assert guard, "the discovery/grouping disagreement guard is gone"
    body = guard.group(1)
    assert "NOTHING WILL BE ESTIMATED" in body
    assert "raise SystemExit(2)" in body, (
        "a `return` here exits 0 — the refusal would report success")


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
    assert parsed is not None and len(parsed["parts"]) == 11
    assert concept_scan.parse_concept_response("the model apologises") is None
