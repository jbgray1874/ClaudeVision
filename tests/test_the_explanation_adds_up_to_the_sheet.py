"""The explanation document has to reconcile to the sheet it explains.

An explanation an estimator cannot check is a second opinion, not a record. These fix the
three claims the document makes about itself:

  * every material and labour line it prints sums to the Estimate sheet's OWN labelled
    totals, and where it does not, it says so in pounds rather than presenting a partial
    itemisation as a complete one;
  * a part SDI cuts gets BOTH its halves — the BOM row that shows a dash and the Sheet Steel
    row that holds the money — each stamped with the drawing page that owns it;
  * labour appears with money on it. It was a third of the unit cost and the document listed
    the operations without a figure against any of them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import handover_note                                                    # noqa: E402


# ── a workbook shaped like the SDI template ──────────────────────────────────
# Rows follow wb_populate.CELL_MAP: BOM 11-50, Sheet Steel 63-81, labour 96-167. The blocks
# are found by their header text, so only the headers and the relative order matter here.

def _workbook(tmp_path: Path, *, steel_cost=1.05, steel_ext=6.30,
              material_total=200.00, labour_total=50.00) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"

    # The header cell wb_populate writes the order quantity into; everything on the sheet
    # that scales with the order reads $D$6.
    ws.cell(6, 4, 1)

    ws.cell(10, 3, "Bill of Materials (per unit)")
    ws.cell(10, 8, "Part code")
    # A part we cut: a dash in the price column, and its money on the Sheet Steel block.
    ws.cell(11, 3, "12552-01-01M CROSS MEMBERS — costed in Sheet Steel below")
    ws.cell(11, 8, "12552-01-01M")
    ws.cell(11, 11, 6)
    # A part we buy, priced from a catalogue.
    ws.cell(12, 3, "FIXING535 M6 X 35MM SOCKET CAP")
    ws.cell(12, 8, "FIXING535")
    ws.cell(12, 9, "Elite Sourcing Solutions Ltd")
    ws.cell(12, 10, 0.05)
    ws.cell(12, 11, 8)

    ws.cell(62, 3, "Part Description")
    ws.cell(62, 6, "Part Length")
    ws.cell(62, 8, "Gauge")
    ws.cell(63, 3, "12552-01-01M CROSS MEMBERS")
    ws.cell(63, 5, 6)
    ws.cell(63, 6, 650.7)
    ws.cell(63, 7, 178.7)
    ws.cell(63, 8, 1.5)
    ws.cell(63, 9, 2500)
    ws.cell(63, 10, 1250)
    ws.cell(63, 12, 0.04)

    ws.cell(170, 3, "Total Material Cost")
    ws.cell(170, 13, material_total)
    ws.cell(171, 3, "Total Labour Cost (Including  Downtime)")
    ws.cell(171, 13, labour_total)
    ws.cell(172, 3, "Total Unit Cost Price")
    ws.cell(172, 13, 268.82)

    detail = wb.create_sheet("AI Material Detail")
    detail.append(["Part", "Desc", "Material", "Blank L", "Blank W", "Gauge",
                   "Cost/Part", "Ext Material", "Cut len (mm)", "Geom source"])
    detail.append(["12552-01-01M", "CROSS MEMBERS", "MILD STEEL", 650.7, 178.7, 1.5,
                   steel_cost, steel_ext, 3200, "measured off the SOLIDWORKS flat pattern"])

    prov = wb.create_sheet("AI Price Provenance")
    prov.append(["Part", "Desc", "Unit £", "Price Source", "Verified", "Supplier",
                 "Review Flags"])

    route = wb.create_sheet("Canonical Route")
    route.append(["Seq", "Operation", "Status", "Target", "Scope", "Qty/unit",
                  "Participants", "Source", "Reason", "Decision ID"])
    route.append([10, "laser_cutting", "required", "12552-01-01M", "part", 6,
                  "", "drawing_notes", "textual_operations on existing part record", "d1"])

    path = tmp_path / "12552-00.xlsx"
    wb.save(path)
    return path


def _run_json(tmp_path: Path, *, labour_value=50.00, material_values=(6.30, 0.40)) -> Path:
    steel_gbp, bom_gbp = material_values
    doc = {
        "parts": [
            {"part_number": "12552-01-01M", "pages": [6], "page_roles": ["detail"],
             "materials": ["MILD STEEL"], "thicknesses_mm": [1.5],
             "surface_finishes": ["POWDER COATED"],
             "geometry_rollup": {"estimated_cut_length_mm": 3200}},
            {"part_number": "FIXING535", "pages": [], "page_roles": []},
        ],
        "final_estimate": {
            "schema": "final_estimate.v2",
            "totals": {"material_gbp": 200.00, "labour_gbp": labour_value,
                       "unit_gbp": 268.82},
            "labour_rows": [
                {"operation": "Laser (Metal)", "department": "LAS", "qty_per_unit": 6,
                 "batch_hours": 0.42, "dept_rate_gbp_per_hour": 62.5,
                 "setup_minutes": 10, "total_value_gbp": labour_value,
                 "workbook_row": 96},
            ],
            "material_rows": [
                {"block": "steel", "description": "12552-01-01M CROSS MEMBERS",
                 "total_value_gbp": steel_gbp},
                {"block": "bom", "description": "FIXING535", "part_code": "FIXING535",
                 "total_value_gbp": bom_gbp},
            ],
            "adapter_problems": [],
        },
        "workbook_labour": {
            "rows": [{"workbook_row": 96, "wb_operation": "Laser (Metal)",
                      "engine_operations": ["laser_cutting"],
                      "part_numbers": ["12552-01-01M"],
                      "rate_basis": "template_calculated"}],
        },
    }
    path = tmp_path / "12552-00.json"
    path.write_text(handover_note.json.dumps(doc), encoding="utf-8")
    return path


def test_a_part_we_cut_gets_both_of_its_halves_and_the_page_on_each(tmp_path):
    """One part, two rows: the BOM's dash and the Sheet Steel row that holds the money."""
    text = handover_note.build(_workbook(tmp_path), _run_json(tmp_path))
    bom_row = next(l for l in text.splitlines()
                   if l.startswith("| 12552-01-01M | CROSS MEMBERS"))
    steel_row = next(l for l in text.splitlines() if "↳ `Estimate!63`" in l)

    assert "p.6 (detail)" in bom_row, "the BOM half must name the drawing that owns it"
    assert "p.6 (detail)" in steel_row, (
        "the Sheet Steel half is the same part on the same drawing — leaving its page blank "
        "is what made the join look like a missing answer")
    assert "650.7 × 178.7" in steel_row and "1.5" in steel_row
    assert "**£6.30**" in steel_row, "column M — the line total — is the money on this row"
    assert "line total, not per part" in steel_row, (
        "M is headed 'Cost Per Part' and holds ROUNDUP(sheet/nest,2) x qty x scrap. A "
        "per-part figure divided back out of it is one the sheet never computed.")
    assert "£1.05" not in steel_row, (
        "the AI Material Detail per-part figure is blank-area only and is not in the unit "
        "cost — it must not appear in the money column")


def test_the_two_views_of_the_steel_are_shown_disagreeing(tmp_path):
    """The engine's per-part figures and the sheet's own steel rows are different numbers.

    It is the sheet's that reaches Total Material Cost. Printing one and reconciling with
    the other leaves both honestly labelled and nothing saying they disagree — which is how
    a covering note came to quote a per-part steel cost the sheet does not charge.
    """
    text = handover_note.build(_workbook(tmp_path), _run_json(tmp_path))
    row = next(l for l in text.splitlines() if l.startswith("| 12552-01-01M | 650.7"))
    assert "**£6.30**" in row, "the sheet's own charge is the bold, quotable figure"
    assert "the one you pay" not in text, (
        "6.30 against 6.30 is agreement — the warning must not fire on a job that ties")

    louder = handover_note.build(_workbook(tmp_path),
                                 _run_json(tmp_path, material_values=(17.60, 0.40)))
    assert "**The two columns disagree, and the sheet's is the one you pay.**" in louder
    assert "the sheet charges £17.60" in louder
    assert "a difference of £11.30" in louder
    assert "Nest per sheet" in louder


def test_the_labour_lines_carry_the_money_the_sheet_charged(tmp_path):
    text = handover_note.build(_workbook(tmp_path), _run_json(tmp_path))
    assert "## Every labour line, and what it charges" in text
    row = next(l for l in text.splitlines() if "`Estimate!96`" in l)
    assert "Laser (Metal)" in row
    assert "12552-01-01M" in row, "a labour line has to name the parts it is charging for"
    assert "£50.00" in row
    assert "template_calculated" in row, "how the rate was arrived at is part of the answer"


def test_it_says_so_when_the_lines_add_up_to_the_sheet(tmp_path):
    """Material 6.30 + 0.40 against a 200.00 total is a £193.30 hole, and it says so."""
    text = handover_note.build(_workbook(tmp_path), _run_json(tmp_path))
    assert "## This document against the sheet" in text
    assert "**£193.30 short**" in text, "an itemisation covering 3% of a total must say so"
    assert "**none — it reconciles**" in text, "labour does reconcile and should read so"
    assert "Not entirely" in text


def test_a_complete_itemisation_reports_no_gap(tmp_path):
    text = handover_note.build(
        _workbook(tmp_path, material_total=6.70),
        _run_json(tmp_path))
    assert "short" not in text.split("## Every line")[0]
    assert text.count("**none — it reconciles**") == 2
    assert ("Yes. Every material and labour line below sums to the Estimate sheet's own"
            in text)


def test_a_bought_in_with_no_sheet_is_not_a_missing_drawing(tmp_path):
    """The question is whether the absence moves the price, not whether a file exists."""
    text = handover_note.build(_workbook(tmp_path), _run_json(tmp_path))
    assert "## Drawings the pack does not contain, and what that costs" in text
    assert "**None of them is a part SDI cuts**" in text
    section = text.split("## Drawings the pack does not contain")[1]
    row = next(l for l in section.splitlines() if l.startswith("| FIXING535 |"))
    assert "No — it is not a drawn part" in row


def test_an_uncached_total_falls_back_to_the_runs_read_back_of_the_same_cell(tmp_path):
    """Total Material Cost is a SUM formula. openpyxl sees no cached result for it.

    The read-back already opened that workbook through Excel and scanned the same labelled
    cells, so the figure exists — and the document says which of the two it used, because
    "read from the file" and "read from the run's record of the file" are different claims.
    """
    workbook = _workbook(tmp_path)
    wb = openpyxl.load_workbook(workbook)
    wb["Estimate"].cell(170, 13).value = None
    wb.save(workbook)

    text = handover_note.build(workbook, _run_json(tmp_path))
    assert "£200.00" in text
    assert "**Total Material Cost** came from the run's read-back of that cell" in text
    assert "**Total Labour Cost** came from the workbook's own cell" in text


def test_a_total_neither_source_holds_is_never_reported_as_zero(tmp_path):
    """With no cached cell AND no read-back, printing GBP 0.00 would fake an exact match."""
    workbook = _workbook(tmp_path)
    wb = openpyxl.load_workbook(workbook)
    wb["Estimate"].cell(170, 13).value = None
    wb.save(workbook)

    scan = _run_json(tmp_path)
    doc = handover_note.json.loads(scan.read_text(encoding="utf-8"))
    doc["final_estimate"]["totals"].pop("material_gbp")
    scan.write_text(handover_note.json.dumps(doc), encoding="utf-8")

    text = handover_note.build(workbook, scan)
    assert "not readable from the sheet" in text
    assert "cannot be checked" in text
    assert "£0.00" not in text


def test_without_the_calculated_rows_it_refuses_to_claim_completeness(tmp_path):
    path = tmp_path / "trimmed.json"
    path.write_text(handover_note.json.dumps(
        [{"part_number": "12552-01-01M", "pages": [6], "page_roles": ["detail"]}]),
        encoding="utf-8")

    text = handover_note.build(_workbook(tmp_path), path)
    assert "## Every labour line" not in text, (
        "no calculated rows means no labour figures — inventing a section for them would be "
        "the confident wrong answer this document exists to avoid")
    assert "Not yet — no calculated rows were supplied" in text


# ── the same rows, for the tab and the report ────────────────────────────────

def test_the_structured_view_is_the_document_and_not_a_second_answer(tmp_path):
    """The tab and the HTML report render THIS, so it has to carry the same figures.

    Not a second pass over the workbook: a second pass is how the tab and the document come
    to disagree, which is the failure this whole document exists to expose.
    """
    text = handover_note.build(_workbook(tmp_path), _run_json(tmp_path))
    parsed = handover_note.sections(text)

    titles = [s["title"] for s in parsed]
    assert "This document against the sheet" in titles
    assert "Every line on the Bill of Materials" in titles
    assert "Every labour line, and what it charges" in titles

    recon = next(s for s in parsed if s["title"] == "This document against the sheet")
    assert recon["tables"], "a section with a table must carry it"
    assert recon["tables"][0]["columns"][0] == "Block"
    material = next(r for r in recon["tables"][0]["rows"] if "All material" in r[0])
    assert material[2] == "£6.70", "the £ column must survive the round trip intact"
    assert any("read back after Excel recalculated" in n for n in recon["notes"])

    labour = next(s for s in parsed if s["title"].startswith("Every labour line"))
    row = labour["tables"][0]["rows"][0]
    assert "Estimate!96" in handover_note.plain(row[0])
    assert row[8] == "£50.00"


def test_plain_strips_the_emphasis_a_cell_cannot_render(tmp_path):
    assert handover_note.plain("**£11.48**") == "£11.48"
    assert handover_note.plain("`Estimate!63`") == "Estimate!63"
    assert handover_note.plain("— line total, not per part") == "— line total, not per part"


def test_the_tab_gets_cells_not_markdown(tmp_path):
    """A cell renders `**£11.48**` as those characters, so the tab takes plain text."""
    rows = handover_note.worksheet_rows(
        handover_note.sections(handover_note.build(_workbook(tmp_path),
                                                   _run_json(tmp_path))))
    flat = ["|".join(r) for r in rows]
    assert any(r == "This document against the sheet" for r in flat), (
        "a section title is a row of its own on a tab — there are no headings in a sheet")
    assert not any("**" in r or "`" in r for r in flat), "no markdown reaches a cell"
    money = next(r for r in rows if r and r[0] == "All material")
    assert money[2] == "£6.70"
    labour = next(r for r in rows if r and r[0] == "Estimate!96")
    assert labour[8] == "£50.00"


# ── the two things the covering email had to work out by hand ────────────────

def test_the_labour_splits_into_set_up_and_run(tmp_path):
    """The whole quantity story, and it was being derived by hand for every email.

    Set-up is one-off per department row and spreads across the order; run time per unit
    never moves. An estimator asked "what would 25 off cost" should not have to open the
    sheet and find eleven set-up cells and eleven rates themselves.
    """
    text = handover_note.build(_workbook(tmp_path), _run_json(tmp_path))
    assert "## What the labour is: set-up, and run time" in text
    # 10 min at GBP 62.50/hr, on a 1-off estimate, is GBP 10.42 of the GBP 50.00 row.
    assert "**£10.42 is set-up**" in text
    assert "**£39.58 is run time**" in text
    row100 = next(l for l in text.splitlines() if l.startswith("| 100 |"))
    assert "£0.10" in row100, "set-up per unit falls as 1/qty"
    assert "£39.58" in row100, "run time per unit is the floor and does not move"
    assert "not a unit price" in text, (
        "material and freight are not in that table — saying so is the difference between a "
        "labour curve and a price somebody quotes")


def test_the_lines_needing_a_person_are_listed_not_counted(tmp_path):
    """"3 lines carry no price" is true and unactionable. They want codes and money."""
    workbook = _workbook(tmp_path)
    wb = openpyxl.load_workbook(workbook)
    ws = wb["Estimate"]
    ws.cell(13, 3, "BI-SCREW M5X10mm CAP SCREW")
    ws.cell(13, 8, "BI-SCREW")
    ws.cell(13, 11, 10)
    ws.cell(14, 3, "12552-01-02X CONCRETE SLAB")
    ws.cell(14, 8, "12552-01-02X")
    ws.cell(14, 9, "xAI Grok LLM - INDICATIVE")
    ws.cell(14, 10, 85.62)
    ws.cell(14, 11, 2)
    wb.save(workbook)

    text = handover_note.build(workbook, _run_json(tmp_path))
    assert "## What a person still has to settle" in text
    section = text.split("## What a person still has to settle")[1].split("## ")[0]
    slab = next(l for l in section.splitlines() if l.startswith("| 12552-01-02X"))
    assert "£171.24" in slab, "the money at stake, not just the fact of it"
    assert "cannot be reproduced" in slab
    screw = next(l for l in section.splitlines() if l.startswith("| BI-SCREW"))
    assert "£0.00 — the line is costing nothing" in screw
    assert slab.index("|") < screw.index("|") or section.index(slab) < section.index(screw), (
        "worst first — an estimator reads the top of the list")


# ── the pack's own verdict, where somebody reads it ──────────────────────────

def _insufficient(tmp_path: Path) -> Path:
    path = _run_json(tmp_path)
    doc = handover_note.json.loads(path.read_text(encoding="utf-8"))
    doc["data_sufficiency"] = {
        "status": "insufficient_data",
        "message": "INSUFFICIENT DATA — part DXFs required for credible auto-estimate",
        "suppress_headline_total": True,
        "document_total_provisional_gbp": 327.39,
        "credible_cost_ratio": 0.26,
        "fabricated_part_count": 12,
        "parts_with_dxf": 9,
        "unreliable_parts": [
            {"part_number": "12349-02-69-05M", "description": "SIDE PANEL",
             "extended_cost_gbp": 41.20,
             "reasons": ["no part DXF", "blank inferred from an overall dimension"]},
            {"part_number": "12349-02-69-07M", "description": "BRACKET",
             "extended_cost_gbp": 8.15, "reasons": ["no part DXF"]},
        ],
    }
    path.write_text(handover_note.json.dumps(doc), encoding="utf-8")
    return path


def test_a_pack_the_engine_cannot_cost_says_so_where_a_person_reads(tmp_path):
    """It suppresses its own headline and prints one line to a console nobody keeps, while
    the workbook computes an ordinary Unit Cost — so the estimate arrives priced and the
    reason to doubt it arrives nowhere."""
    text = handover_note.build(_workbook(tmp_path), _insufficient(tmp_path))
    section = text.split("## Drawings the pack does not contain")[1]
    assert "does not consider this pack sufficient to cost on its own" in section
    assert "26% rests on figures it considers credible" in section
    assert "9 of 12 fabricated part(s) have a DXF" in section
    assert "the workbook still computes a unit cost and it is a real figure" in section.lower(), (
        "the suppressed figure is the engine's own parallel total, not the sheet's — saying "
        "otherwise would have an estimator distrust a number that is fine")


def test_the_doubted_lines_are_named_and_priced_worst_first(tmp_path):
    text = handover_note.build(_workbook(tmp_path), _insufficient(tmp_path))
    section = text.split("## Drawings the pack does not contain")[1]
    panel = next(l for l in section.splitlines() if l.startswith("| 12349-02-69-05M"))
    bracket = next(l for l in section.splitlines() if l.startswith("| 12349-02-69-07M"))
    assert "£41.20" in panel and "no part DXF" in panel
    assert "blank inferred from an overall dimension" in panel
    assert section.index(panel) < section.index(bracket), "worst first"
    assert "single thing that would move this estimate from provisional to defensible" in section


def test_a_sufficient_pack_gets_no_lecture(tmp_path):
    text = handover_note.build(_workbook(tmp_path), _run_json(tmp_path))
    assert "does not consider this pack sufficient" not in text
