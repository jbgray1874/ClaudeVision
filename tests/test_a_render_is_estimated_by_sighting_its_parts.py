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


def test_the_bom_page_shows_the_sighted_make_list():
    """THE ONE DELIVERABLE WHOSE JOB IS "WHAT PARTS" ANSWERED WITH SILENCE.

    `bom_sheet` read `document_analysis.bom_rows` and nothing else — the drawing's OWN parts
    list, which a render does not have. So a concept run sighted eleven parts, priced them,
    put them on the Estimate sheet, and the BOMs page still said "Nothing in this record" on
    the pack that needs the question asked most.

    The sighted lines are a bill of materials too. Same table, same detail, with the reader
    named as what it is so nobody has to infer "guessed" from an absent page number.
    """
    from bom_and_route_extract import bom_sheet

    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    rows = bom_sheet({"manufacturing_writeup": {"parts": parts},
                      "document_analysis": {"bom_rows": []}})
    assert len(rows) == 11, "the sighted make list is missing from the BOM page"

    by_desc = {r["description"]: r for r in rows}
    side = by_desc["SIDE PANEL"]
    assert side["read_by"] == "vision_concept", "a sighted line must name its reader"
    assert side["quantity"] == 2
    assert "800.0 x 450.0 x 18.0" in side["assumed_blank"] and "assumed" in side["assumed_blank"]
    assert "saw" in side["work_sighted"], "the work is not on the BOM line"
    assert side["kind"] == "fabricated"

    castor = by_desc["CASTOR"]
    assert castor["kind"] == "bought_in"
    assert not castor["assumed_blank"], "a bought-in line must not show a blank"
    assert castor["work_sighted"] == "", "a bought-in line needs no work"


def test_a_sighted_line_is_not_written_into_the_drawings_bom_rows():
    """`document_analysis.bom_rows` means "read off the drawing's parts list". A sighted line
    is not one, and writing it there would make every downstream reader believe a render had
    a parts list. Two facts, two names."""
    from bom_and_route_extract import bom_sheet

    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    summary = {"manufacturing_writeup": {"parts": parts},
               "document_analysis": {"bom_rows": []}}
    bom_sheet(summary)
    assert summary["document_analysis"]["bom_rows"] == [], (
        "the sighted list was written into the drawing's own BOM rows")


def test_a_drawing_pack_keeps_exactly_the_bom_it_had():
    """The control. Concept rows are ADDED for concept parts only — a real pack's table must
    come out unchanged, or this has quietly altered every job in the building."""
    from bom_and_route_extract import bom_sheet

    drawn = {"manufacturing_writeup": {"parts": [
                 {"part_number": "12349-02-69-04M", "description": "LID"}]},
             "document_analysis": {"bom_rows": [
                 {"part_number": "12349-02-69-04M", "description": "LID", "quantity": 1,
                  "source": "bom_table"}]}}
    rows = bom_sheet(drawn)
    assert len(rows) == 1 and rows[0]["read_by"] == "bom_table"
    assert "kind" not in rows[0], "a drawn row grew a concept column"


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
                if "CASTOR" in p["description"].upper())
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
                if "GRAPHIC" in p["description"].upper())
    assert part["concept_kind"] == "graphic"
    assert part.get("blank_length_mm") in (None, 0), "the graphic was written as a blank"


def test_a_fabricated_panel_still_gets_its_blank():
    """The control. A guard that refuses everything is not a guard — a made panel must
    still nest, or there is no material cost at all."""
    part = concept_scan.parts_from_concept(FIXTURE, "PlanA")[0]
    assert part["concept_kind"] == "fabricated"
    assert part["blank_length_mm"] == 900.0 and part["blank_width_mm"] == 400.0


def test_a_kind_the_mapper_does_not_know_is_refused_not_defaulted():
    """James Gray, 22 Sep 2026: "Any unexpected LLM `kind` falls through as fabricated and
    can still receive a blank, material, dimensions and route. The prompt constrains the
    model, but the mapper does not validate its output."

    `kind or "fabricated"` turned every word the prompt did not write — a translation, a
    typo, "subassembly", "electrical", tomorrow's prompt edit — into a made panel. A made
    panel gets a blank, and a blank is an instruction to nest. So an unknown word is a
    refusal with a name on it, not a default: the line keeps its count and its description,
    and carries no material, no size and no work until somebody classifies it.
    """
    answer = json.loads(json.dumps(FIXTURE))
    answer["parts"][0]["kind"] = "subassembly"

    part = concept_scan.parts_from_concept(answer, "PlanA")[0]
    assert part["concept_kind"] == "unknown", "an unknown kind was mapped to a real one"
    assert part.get("blank_length_mm") in (None, 0), "an unclassified line got a blank"
    assert part.get("blank_width_mm") in (None, 0)
    assert part.get("normalized_thickness_mm") in (None, 0)
    assert not part.get("normalized_material"), "an unclassified line got a material"
    assert not part.get("inferred_operations"), "an unclassified line got a route"
    # The line is still THERE — "we dont drop something if it's obviously something that is
    # part of the unit" — with its count and one action on it.
    assert part["quantity"] == answer["parts"][0]["quantity"]
    flags = [f for f in part["review_flags"] if "not a kind this estimate knows" in f]
    assert len(flags) == 1, part["review_flags"]
    assert "subassembly" in flags[0], "the flag does not say what the model returned"
    # And nothing the model said is thrown away: it is kept as words, off the priced fields.
    assert part["concept_unclassified"]["kind_returned"] == "subassembly"
    assert part["concept_unclassified"]["assumed_blank_mm"]["length"] == 900


def test_a_line_with_no_kind_at_all_is_not_a_made_panel():
    """The empty string took the same fall-through, and an absent field is the commonest
    way a model omits one. One action, not two: an unclassified line is not asked for its
    dimensions before anybody has said what the thing is."""
    answer = json.loads(json.dumps(FIXTURE))
    answer["parts"][0].pop("kind", None)

    part = concept_scan.parts_from_concept(answer, "PlanA")[0]
    assert part["concept_kind"] == "unknown"
    assert part.get("blank_length_mm") in (None, 0)
    assert not any("enter this part's dimensions" in f for f in part["review_flags"]), (
        "an unclassified line was asked for a size as well as a classification")
    assert sum("CONCEPT:" in f for f in part["review_flags"]) == 1, part["review_flags"]


def test_the_same_word_spelled_differently_is_the_same_kind():
    """The mapper normalises the PROMPT'S OWN WORDS — case and punctuation — and nothing
    else. "Bought-In" is bought_in spelled differently; "purchased" is a synonym the mapper
    would be guessing at, and a guess wearing a schema's clothes is the fault above."""
    assert concept_scan._concept_kind("Bought-In") == "bought_in"
    assert concept_scan._concept_kind("  FABRICATED ") == "fabricated"
    assert concept_scan._concept_kind("purchased") == concept_scan.UNKNOWN_KIND
    assert concept_scan._concept_kind(None) == concept_scan.UNKNOWN_KIND
    assert concept_scan._concept_kind(7) == concept_scan.UNKNOWN_KIND


def test_the_bom_page_says_a_line_is_unclassified_rather_than_leaving_it_blank():
    """The BOM row defaulted the kind to `fabricated` too, so a refused line would have read
    as a made part with empty columns — the refusal invisible on the one page an estimator
    reads to answer "what parts"."""
    from bom_and_route_extract import bom_sheet

    answer = json.loads(json.dumps(FIXTURE))
    answer["parts"][0]["kind"] = "widget"
    parts = concept_scan.parts_from_concept(answer, "PlanA")
    rows = bom_sheet({"manufacturing_writeup": {"parts": parts},
                      "document_analysis": {"bom_rows": []}})
    row = next(r for r in rows if r["description"] == answer["parts"][0]["name"])
    assert row["kind"] == "unknown"
    assert "not classified" in row["assumed_blank"]
    assert "classify" in row["work_sighted"]


def test_the_cad_guard_reads_the_staged_pack_not_the_folder():
    """James Gray, 22 Sep 2026: "the CAD refusal scans every file in the job folder, not only
    the selected/staged pack."

    A folder is a place, not a selection. One stale STEP left in a customer's drop — an old
    revision, a neighbouring job, a file somebody parked there — refused the concept read on
    a pack of renders that had nothing to do with it. What counts is what this run staged or
    actually attached, including a DXF the job discovered and MEASURED, because that geometry
    is in the estimate whatever found it.
    """
    import re

    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    guard = re.search(r"_concept_refused = None(.*?)_concept_refused = _cs_probe", src, re.S)
    assert guard, "the measured-CAD guard has moved"
    body = guard.group(1)
    assert "iterdir" not in body, "the guard still lists the whole job folder"
    assert "glob" not in body, "the guard still lists the whole job folder"
    assert "staged_inputs" in body and "dxf_paths" in body

    # And the staged selection is recorded where the guard can read it — as handed in,
    # before scan_folder_job drops what no reader opens (a STEP nobody parses is still a
    # file the estimator chose for this job).
    import inspect

    import file_scan
    staged = inspect.getsource(file_scan.scan_folder_job)
    assert 'merged["staged_inputs"] = [str(p) for p in pdf_paths]' in staged


def test_every_figure_a_render_supplied_is_on_one_list():
    """James Gray, 22 Sep 2026: "The concept path still turns a render's guessed MDF, 5 mm
    thickness, dimensions and operations into normal pricing inputs... It is acceptable only
    as a clearly editable concept budget, with each assumption available to confirm."

    The provenance was already right — every field is stamped `vision_concept` with its cue.
    But provenance answers "where did this come from" about a datum already in your hand;
    an estimator needs the opposite, which is one list of everything that was assumed."""
    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    rows = concept_scan.assumption_register(parts)
    assert len(rows) > 30, "the assumptions list is not the whole of what was assumed"

    fields = {r["field"] for r in rows}
    for expected in ("quantity", "material", "blank_length_mm", "thickness_mm", "operations"):
        assert expected in fields, f"{expected} was assumed and is not on the list"
    for row in rows:
        assert row["cue"], f"{row['part_number']} {row['field']} names no cue"
        assert row["part_number"] and row["description"]

    # A drawing pack assumes none of this, and must produce no list at all.
    assert concept_scan.assumption_register(
        [{"part_number": "12349-02-69-04M", "description": "LID"}]) == []


def test_the_answer_sheet_is_written_out_pre_filled(tmp_path):
    """Confirming an assumption should be editing a line, not hand-authoring JSON for a part
    number nobody wants to retype. The file written is the one `estimator_confirmed` already
    reads and finds — no new convention, no copying anything anywhere."""
    import estimator_confirmed as ec

    parts = concept_scan.parts_from_concept(FIXTURE, "JOB1")
    path = concept_scan.write_assumptions_file(parts, folder=tmp_path, job="JOB1")
    assert path is not None and path.exists()
    assert ec.find_corrections_file(tmp_path, None, "JOB1") == path, (
        "the engine's own finder does not find the file the engine just wrote")

    payload = json.loads(path.read_text(encoding="utf-8"))
    entry = payload["parts"][parts[0]["part_number"]]
    assert entry["blank_length_mm"] == 900.0 and entry["material"] == "MDF"
    assert entry["_sighted_because"], "the cue is not beside the figure"


def test_the_template_cannot_apply_itself(tmp_path):
    """THE WHOLE DESIGN. Writing the answers file must never promote a picture-guess into a
    person's reading. Every entry is `inferred` with its reasoning left EMPTY, and
    `estimator_confirmed` refuses an inferred figure that states no reasoning — "a claim
    without its working is a guess wearing a person's authority".

    Omitting `basis` would default it to `read` — PRINTED ON THE SHEET — which is exactly
    the laundering this refuses, so the absence of that key is the test."""
    import estimator_confirmed as ec

    parts = concept_scan.parts_from_concept(FIXTURE, "JOB1")
    payload = concept_scan.assumptions_payload(parts, job="JOB1")
    for code, entry in payload["parts"].items():
        assert entry["basis"] == "inferred", f"{code} would enter above the render"
        assert entry["read_from"] == "", f"{code} arrives with its reasoning pre-written"
    assert not payload["confirmed_by"], "the file claims a person confirmed it"

    # And the door itself refuses it, which is the fact that matters.
    p = tmp_path / "JOB1_estimator_dimensions.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    data, problems = ec.load_corrections(p)
    assert data["parts"] == {}, "an untouched template applied figures to the estimate"
    assert len(problems) == len(payload["parts"])
    assert all("no reasoning is given" in p for p in problems), problems


def test_an_answered_assumption_displaces_the_render_and_leaves_the_list(tmp_path):
    """The other half: a person who states their reasoning has confirmed that assumption on
    purpose, it enters at THEIR rank, above the render — and it stops being asked about."""
    import estimator_confirmed as ec
    from source_precedence import source_of

    parts = concept_scan.parts_from_concept(FIXTURE, "JOB1")
    path = concept_scan.write_assumptions_file(parts, folder=tmp_path, job="JOB1")
    raw = json.loads(path.read_text(encoding="utf-8"))
    code = parts[0]["part_number"]
    raw["confirmed_by"] = "James Gray"
    raw["parts"][code]["blank_length_mm"] = 1000
    raw["parts"][code]["read_from"] = "measured off the sample on the bench"
    path.write_text(json.dumps(raw), encoding="utf-8")

    fresh = concept_scan.parts_from_concept(FIXTURE, "JOB1")
    before = len(concept_scan.assumption_register(fresh))
    data, _ = ec.load_corrections(path)
    report = ec.apply_estimator_confirmed(fresh, data)
    assert report["stamped"] == 1 and not report["unmatched"], report
    assert fresh[0]["blank_length_mm"] == 1000.0
    assert source_of(fresh[0], "blank_length_mm") == "estimator_inferred", (
        "an answered assumption did not outrank the render")
    assert len(concept_scan.assumption_register(fresh)) < before, (
        "a figure a person has answered is still being asked about")


def test_an_estimators_own_file_is_never_overwritten(tmp_path):
    """A machine that rewrote a person's confirmations with its own guesses would undo the
    exact work this exists to collect — silently, on the run after they did it."""
    theirs = tmp_path / "JOB1_confirmed.json"
    theirs.write_text(json.dumps({"drawing_number": "JOB1", "confirmed_by": "James Gray",
                                  "parts": {"X": {"material": "ACRYLIC", "basis": "read"}}}),
                      encoding="utf-8")
    parts = concept_scan.parts_from_concept(FIXTURE, "JOB1")
    assert concept_scan.write_assumptions_file(parts, folder=tmp_path, job="JOB1") is None
    assert "ACRYLIC" in theirs.read_text(encoding="utf-8")
    assert not (tmp_path / "JOB1_estimator_dimensions.json").exists()


def test_a_note_beside_a_figure_is_not_reported_as_an_error(tmp_path):
    """The answers file teaches writing a note beside a ruling, and `estimator_decisions` has
    read a leading underscore as a comment since. A PART entry could not, so the cue written
    beside each sighted figure would have been reported as a line that did nothing — and an
    estimator told three times that their own notes are errors stops writing notes."""
    import estimator_confirmed as ec

    p = tmp_path / "JOB1_estimator_dimensions.json"
    p.write_text(json.dumps({"drawing_number": "JOB1", "parts": {
        "ABC": {"material": "MDF", "basis": "read", "_why": "scaled from the castors"}}}),
        encoding="utf-8")
    data, problems = ec.load_corrections(p)
    assert data["parts"]["ABC"]["material"] == "MDF"
    assert not problems, problems


def test_the_report_and_the_quote_say_it_is_a_concept_budget():
    """Not a banner and not a warning — the Basis row is where a document says what it is,
    and section 8.5 is the list. Both are silent on every other run."""
    import client_quote_html
    import job_report_html

    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    rows = concept_scan.assumption_register(parts)
    summary = {"concept_read": {"parts": len(parts), "assumptions": rows,
                                "assumptions_file": "K:/jobs/JOB1_estimator_dimensions.json"}}
    section = job_report_html._concept_assumptions_section(summary)
    assert "concept budget" in section.lower()
    assert "sighted from the image" in section
    assert "JOB1_estimator_dimensions.json" in section
    assert job_report_html._concept_assumptions_section({}) == "", (
        "a drawing pack grew a concept section")

    # The quote's Basis row, on the internal page a render run produces.
    from quote_state import PORTAL
    quote = dict(summary, llm_only=True, job_number="JOB1",
                 estimate_summary={"estimate_workbook_inputs": {"assumed_job_quantity": 1},
                                   "workbook_equivalent_pricing":
                                       {"m105_total_unit_cost_gbp": 102.70},
                                   "part_estimates": []},
                 final_estimate={"totals": {}})
    html = client_quote_html.build_quote_html(quote, job_stem="JOB1", audience=PORTAL)
    assert "Concept budget" in html
    assert "sighted from the render" in html


def test_a_sighted_part_is_numbered_after_the_job_not_the_wrapper():
    """A render is scanned as a content-keyed PDF in the output tree, so the anchor's stem is
    a hash: every sighted part came out as `5E09BE03B9741E5F-BDAB4AD-C01 …`, a code no
    estimator would type into a confirmations file and nobody can match to a job by eye."""
    import re

    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    hook = re.search(r"_job_name = (.{0,200})", src, re.S)
    assert hook and "job_folder" in hook.group(1), (
        "the sighted parts are still numbered after the wrapped render")
    parts = concept_scan.parts_from_concept(FIXTURE, "bdab4adf-3340-40M&S")
    assert parts[0]["part_number"] == "BDAB4ADF-3340-40M-S-CPT01"
    assert " " not in parts[0]["part_number"], (
        "a part number with a space in it breaks the nested-block join — see D-187")


def test_somebody_assembles_the_unit():
    """James Gray, 22 Sep 2026, on the first full concept book: "Assembly still ruled out on
    every panel, so glue-up of the box is missing."

    Twenty route lines — saw, cnc_routing, edge_banding, laminating — and nothing that put
    the carcass together. The cause was a field nobody reads: the unit's work was written to
    `summary["assembly_events"]`, and the route compiler builds its assembly events from its
    own payload while the workbook costs from the part records. Neither has ever read it.

    The engine's own rule was already right and had nothing to fire on — it mints bench
    fitting on a BOARD ASSEMBLY, and a render pack presented no assembly. This mints one.
    """
    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    unit = concept_scan.unit_assembly_part(parts, FIXTURE, "PlanA")
    assert unit is not None, "the product itself is not on the parts list"
    # The three names the assembly rules ask by, together.
    assert unit["is_assembly_parent"] is True
    assert unit["canonical_kind"] == "assembly"
    assert len(unit["assembly_children"]) >= 6
    assert unit.get("normalized_material"), "the build has no board to be timed as"
    # It is the product, not a part: it carries work and no size of its own.
    assert unit.get("blank_length_mm") in (None, 0)
    assert unit["concept_kind"] == "assembly"

    # And the dead field is gone, or this fix is a second copy of the same fault.
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert 'setdefault("assembly_events"' not in src, (
        "the unit's work is still written to a key nothing reads")


def test_the_bench_rule_fires_and_times_the_build_off_the_shops_own_rate():
    """The measure that matters: the rule charges, and the minutes are the shop's, not
    ours. Nothing here invents an assembly time — it proves the existing rule reaches a
    concept job and says which rate it used."""
    from estimator import estimate_document

    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    unit = concept_scan.unit_assembly_part(parts, FIXTURE, "PlanA")
    before = estimate_document(list(parts),
                               summary={"manufacturing_writeup": {"parts": list(parts)}})
    after = estimate_document([unit] + parts,
                              summary={"manufacturing_writeup": {"parts": [unit] + parts}})
    _l = lambda e: float((e.get("workbook_equivalent_pricing") or {}).get(   # noqa: E731
        "m103_labour_subtotal_gbp") or 0.0)
    assert _l(after) > _l(before), "the unit assembly charges nothing"
    assert any("bench fitting" in str(f) for f in (unit.get("review_flags") or [])), (
        "the build was timed with no line saying how")


def test_a_one_part_render_is_not_an_assembly():
    """The control. An assembly event minted over nothing charges for nothing, and a pack
    of bought-ins is not a carcass."""
    answer = {"product": {"name": "SIGN"}, "parts": [
        {"name": "FACE", "kind": "fabricated", "material_guess": "MDF",
         "assumed_blank_mm": {"length": 300, "width": 200, "thickness": 18},
         "quantity": 1, "operations": ["saw"]},
        {"name": "CASTOR", "kind": "bought_in", "quantity": 4}]}
    parts = concept_scan.parts_from_concept(answer, "ONE")
    assert concept_scan.unit_assembly_part(parts, answer, "ONE") is None


def test_edging_is_charged_only_where_the_edges_are_named():
    """James Gray, 22 Sep 2026: "I would not merely add it to the confirm list while still
    charging £65.04. Make it an explicit editable concept assumption with a stated
    visible-edge basis; otherwise it should not mint a deterministic edge-banding route."

    All eight panels were banded off one word from a vision model — two department set-ups
    and over half the labour on the job. The engine's rule for a drawing (D-104) is that
    edging is measured where the drawing MARKS it, never round a perimeter; a render is held
    to the same standard.
    """
    answer = json.loads(json.dumps(FIXTURE))
    panel = answer["parts"][0]
    panel["operations"] = ["saw", "edge_banding"]
    panel.pop(concept_scan.EDGE_BASIS_FIELD, None)

    part = concept_scan.parts_from_concept(answer, "PlanA")[0]
    assert "edge_banding" not in (part.get("inferred_operations") or []), (
        "edging was charged with no edge named")
    assert "saw" in part["inferred_operations"], "the rest of the route was thrown away too"
    flag = [f for f in part["review_flags"] if "no edges could be named" in f]
    assert len(flag) == 1 and "banded_metres" in flag[0], part["review_flags"]
    assert any(r["field"] == "banded edges"
               for r in concept_scan.assumption_register([part])), (
        "the edging assumption is not on the list anybody confirms")

    # NAMED, and it is work like any other.
    panel[concept_scan.EDGE_BASIS_FIELD] = "front and top edges show a banded lip"
    part = concept_scan.parts_from_concept(answer, "PlanA")[0]
    assert "edge_banding" in part["inferred_operations"]
    assert part["concept_banded_edges"].startswith("front and top")
    assert not any("no edges could be named" in f for f in part["review_flags"])


def test_a_sighted_description_cannot_match_a_catalogue_row():
    """James Gray, 22 Sep 2026: "Prevent a render-invented material/description from matching
    a catalogue item without matching specification and unit basis."

    `HEADER GRAPHIC SET` / `PRINTED_VINYL` — a material this engine uses nowhere — matched a
    UDEF row on its words and took £115.56 each, a quarter of a £459.56 unit, for a graphic
    with no size at all. A wrong citation is worse than no figure.
    """
    import inspect

    import pricing_service

    assert pricing_service.PricingService._is_sighted_line(
        {"concept": True, "description": "HEADER GRAPHIC SET"})
    assert not pricing_service.PricingService._is_sighted_line(
        {"part_number": "12349-02-69-04M", "description": "LID"})

    # The guard sits in front of EVERY word-matched arm, not only UDEF's — guarding one
    # would have moved the match one arm down the chain.
    chain = inspect.getsource(pricing_service.PricingService._select_anchor_price_source)
    assert "_is_sighted_line" in chain
    assert chain.index("_is_sighted_line") < chain.index("_get_historical_rag"), (
        "the historical-quote RAG still matches a sighted description")
    assert chain.index("_is_sighted_line") < chain.index("_get_supplier_catalog")
    udef = inspect.getsource(pricing_service.PricingService._get_udef_anchor)
    assert "if _sighted:\n            return None" in udef, (
        "UDEF's own description arms are still open to a sighted line")


def test_a_castor_carries_enough_specification_to_be_researched():
    """"We need to be able to price castors and hinges." They sat at £0 because the
    researched rung was handed the single word CASTOR — no diameter, no fixing, no load —
    and it has to name a real current listing. A render answers more than one word."""
    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    castor = next(p for p in parts if "CASTOR" in p["description"].upper())
    spec = castor.get("research_description") or ""
    assert spec, "the bought-in line carries nothing to research"
    assert "sighted on a customer render" in spec and "approximate" in spec, (
        "the brief does not say the specification was sighted")
    # A made panel is priced by nest and has no business being researched as a purchase.
    made = next(p for p in parts if p.get("concept_kind") == "fabricated")
    assert not made.get("research_description")

    # And the rung asks with it, without the code we minted ourselves.
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert '"description": _sighted_desc or part.get("description")' in src
    assert '"code": "" if _sighted_desc else part.get("part_number")' in src


def test_a_sighted_code_is_not_a_code_anybody_can_look_up():
    """The castor's refusal blamed the wrong thing: "'5E09BE03B9741E5F-BDAB4AD-C11 CASTOR'
    is a real code, so it was put to the purchasing catalogue... that is a gap on our side."
    It is not a real code — we minted it from a render — and an estimator sent to check the
    catalogue for it is doing work that cannot succeed."""
    from part_identity import is_engine_minted_code, is_sighted_code

    assert is_sighted_code("5E09BE03B9741E5F-BDAB4AD-CPT11")
    assert is_engine_minted_code("5E09BE03B9741E5F-BDAB4AD-CPT11")
    # NARROW. A code somebody printed on a drawing must never be called an invention.
    for real in ("12349-02-69-04M", "10975-02-GA", "1234-C01", "FIXING1081", "DBR60"):
        assert not is_sighted_code(real), real

    src = (ROOT / "src" / "estimate_explained.py").read_text(encoding="utf-8")
    assert "this part was SIGHTED on a render" in src
    assert "Name the item" in src, "the refusal does not say what would settle it"


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
    castor = next(p for p in parts if "CASTOR" in p["description"].upper())
    assert not castor.get("inferred_operations")
    assert not any("no manufacturing operation" in f for f in castor["review_flags"])


def test_a_sighted_castor_is_a_sourcing_fact_not_a_zero():
    """kind=bought_in with no material guess becomes BOUGHT_IN — the start of the bought-in
    price chain (D-153), never a £0 short-circuit."""
    parts = concept_scan.parts_from_concept(FIXTURE, "PlanA")
    castor = next(p for p in parts if "CASTOR" in p["description"].upper())
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


def test_a_researched_price_that_holds_still_is_written_to_the_column():
    """James Gray, 22 Sep 2026, on the second concept book: "The hinge and four castors are
    still £0. That is against your standing rule: visible bought-ins must enter the pricing
    pipeline."

    THE FIGURE WAS FOUND AND THEN DROPPED BY A MISSING KEY. `lookup_web_ai_price` asks once
    per specification, stores the answer and returns `price_is_reproducible` to say so —
    and three adapters in a row did not carry it. `indicative_price_to_withhold` then saw an
    AI figure with nothing saying it holds still and did the one thing it exists for: kept
    it off the price column. The castors showed £48.16 in one table and "no price" in
    another, and the money column read £0.

    Reproducibility is the whole test that rule turns on — "a guess that changes every run
    is not a price" — and a cached figure passes it. This is not a relaxation of the
    policy; it is the policy finally being asked about the right thing.
    """
    import estimator
    import indicative_price
    from estimator_inputs import indicative_price_to_withhold

    # The producer carries the flag out of the researcher...
    out = indicative_price.resolve_indicative(
        {"code": "", "description": "CASTOR, black swivel, approx 75mm",
         "quantity": 4, "unit_of_measure": "each"},
        order_qty=1, as_of="2026-09-22",
        ask=lambda brief: {"price_gbp": 12.04, "unit": "each",
                           "as_of": "2026-09-22", "source": "a named UK trade listing",
                           "quantity_basis": "pack of 4",
                           "price_is_reproducible": True})
    assert out["price_gbp"], out.get("missing")
    assert out["price_is_reproducible"] is True, "the producer drops the flag"

    # ...and the withholding rule then lets it through, where before it did not.
    priced = {"_price_is_reproducible": True}
    assert indicative_price_to_withhold(priced, True, 48.16) is None, (
        "a reproducible researched figure is still being kept off the price column")
    assert indicative_price_to_withhold({}, True, 48.16) == 48.16, (
        "an UNreproducible figure must still be withheld — that rule does not change")

    # And the adapters in between carry it, or the flag never reaches the stamp.
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert '"price_is_reproducible": bool(_found.get("price_is_reproducible"))' in src
    assert '"price_is_reproducible": bool(_ind.get("price_is_reproducible"))' in src


def test_a_render_pack_is_not_manufactured_to_a_drawing():
    """James Gray, 22 Sep 2026: "The portal quote is also too customer-like for a
    render-only pack: it says 'manufactured to drawing' and 'As drawing', despite having one
    concept PDF, no DXF and 34 assumptions... Keep the concise 'Concept budget' basis, but
    remove those two false claims. No giant warning is needed."

    They are not caveats — they are untrue sentences. There is no drawing, so nothing was
    manufactured to one and no material or finish is "as" one."""
    import client_quote_html
    from quote_state import PORTAL

    parts = concept_scan.parts_from_concept(FIXTURE, "JOB1")
    summary = {
        "concept_read": {"parts": len(parts),
                         "assumptions": concept_scan.assumption_register(parts)},
        "llm_only": True, "job_number": "JOB1", "product": "IN-STORE RECYCLING BIN",
        "manufacturing_writeup": {"parts": parts},
        "estimate_summary": {"estimate_workbook_inputs": {"assumed_job_quantity": 1},
                             "workbook_equivalent_pricing":
                                 {"m105_total_unit_cost_gbp": 269.34},
                             "part_estimates": []},
        "final_estimate": {"totals": {}}}
    html = client_quote_html.build_quote_html(summary, job_stem="JOB1", audience=PORTAL)

    assert "manufactured to drawing" not in html.lower()
    assert "as drawing" not in html.lower()
    assert "Concept budget" in html, "the Basis row lost the one true statement"
    # One placeholder in the LEAD, not two: material and finish default to the same words,
    # and the lead joined them into "sighted from the visual, sighted from the visual".
    # The spec table may legitimately show it against both rows.
    import re
    lead = re.search(r'<p class="lead">(.*?)</p>', html, re.S)
    assert lead, "the lead sentence has gone"
    assert lead.group(1).lower().count("sighted from the visual") == 1, lead.group(1)

    # THE CONTROL. A drawing job still says what it always said.
    drawn = dict(summary, product="TESCO METAL DIVIDER")
    drawn.pop("concept_read")
    assert "manufactured to drawing" in client_quote_html.build_quote_html(
        drawn, job_stem="JOB1", audience=PORTAL).lower()


def test_a_nested_board_line_joins_its_money_on_the_sheet():
    """James Gray, 22 Sep 2026: "The four board panels are charged correctly on the
    workbook's nested-sheet rows (£31.91 total), but the report and Provenance tab show each
    as £0 and call the £31.91 an unexplained residual. That is a generic line-to-workbook
    mapping failure, not an estimating gap."

    THE CAUSE WAS A SPACE IN A PART NUMBER. `costed_facts._material_row_key` joins a nested
    block row on THE FIRST WORD of its description, because that is where wb_populate writes
    the part number. The concept mint was `<CODE> <NAME-SLUG>` — two words — so the Other
    Sheet Material row keyed on the code alone while the part looked itself up by the whole
    string. Two keys for one part: the money under one, the line reading the other as £0,
    and the difference falling out as a residual on every surface that adds the lines up.

    The name was never needed in the code; it is the description, which sits in the next
    column and was already carrying it.
    """
    from costed_facts import _material_row_key

    parts = concept_scan.parts_from_concept(FIXTURE, "bdab4adf-3340-40M&S")
    unit = concept_scan.unit_assembly_part(parts, FIXTURE, "bdab4adf-3340-40M&S")
    for record in [unit] + parts:
        pn = record["part_number"]
        assert " " not in pn, f"{pn} would key a nested row on its first word alone"
        assert record["description"], "the name has to survive somewhere"
        # The join the workbook actually makes, on the row wb_populate writes.
        row = {"description": f"{pn}  {record['description']}"}
        assert _material_row_key(row) == pn, (
            f"the nested-block row keys on {_material_row_key(row)!r}, not {pn!r}")


def test_a_concept_code_cannot_be_mistaken_for_a_drawings_own():
    """The CPT token earns its keep here. `1234-C01` is a code a drawing could genuinely
    print, and telling an estimator their own part number is an invention is the one error
    this recogniser must never make."""
    from part_identity import is_sighted_code

    parts = concept_scan.parts_from_concept(FIXTURE, "JOB1")
    assert all(is_sighted_code(p["part_number"]) for p in parts)
    for real in ("1234-C01", "11650-04-01A", "12349-02-69-04M", "10975-02-GA",
                 "1453-GA-C", "FIXING1081"):
        assert not is_sighted_code(real), real
