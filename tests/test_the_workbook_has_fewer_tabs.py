"""Fewer tabs, and the ones that remain answer one question each.

James: "we do have too many tabs in that overall spreadsheet." Six supporting tabs sat behind
the Estimate sheet. Two of them — AI Material Detail and AI Price Provenance — were written
before Excel calculated and carried the engine's per-part money beside an AI Provenance tab
and an Estimate sheet charging different money for the same lines: the last place in the
workbook where one line still had two figures. They are gone; their content is on AI
Provenance, which is written after the read-back from the charged rows and now reads value
used → source → evidence → estimator action. The Explanation tab leads with the decisions.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

openpyxl = pytest.importorskip("openpyxl")

import estimation_report as er  # noqa: E402
import wb_populate as W  # noqa: E402
from test_one_costed_record_for_every_deliverable import seventy_three_thirty_two  # noqa: E402


def _provenance_sheet():
    wb = openpyxl.Workbook()
    wb.active.title = "Estimate"
    er.add_provenance_sheet(wb, seventy_three_thirty_two(), {"job_number": "7332"})
    return wb["AI Provenance"]


def _rows(ws):
    """The part-table rows only — block 1 — which end at the first blank column-A row."""
    out = []
    for row in ws.iter_rows():
        vals = [c.value for c in row]
        if out and len(out) > 5 and vals[0] in (None, ""):
            break
        out.append(vals)
    return out


def test_the_supporting_tabs_are_four_not_six():
    wb = openpyxl.Workbook()
    wb.active.title = "Estimate"
    job = seventy_three_thirty_two()
    W._append_ai_sheets(wb, job, [])
    er.add_provenance_sheet(wb, job, {"job_number": "7332"})
    generated = [n for n in wb.sheetnames if n != "Estimate"]
    # The AI Explanation tab is written by main.py after the read-back; of the tabs these
    # two writers produce, one remains. The Canonical BOM and Route are blocks on it.
    assert set(generated) == {"AI Provenance"}, generated


def _tab_text(ws) -> str:
    return "\n".join(" | ".join(str(c.value) for c in r if c.value is not None)
                     for r in ws.iter_rows())


def test_the_hierarchy_is_a_block_on_the_provenance_tab():
    text = _tab_text(_provenance_sheet())
    assert "2 — THE BILL OF MATERIALS AS THE ENGINE ASSEMBLED IT" in text
    block = text.split("2 — THE BILL OF MATERIALS")[1].split("3 — THE ROUTE")[0]
    assert "▸ 7332-01-GA" in block and "▸ 7332-01-101" in block
    assert "    7332-01-002" in block.replace("\u00a0", " ")     # indented under the frame
    assert "£11.72" in block and "£2.82" in block


def test_the_route_block_keeps_the_ruled_out_decisions_beside_the_charged_ones():
    text = _tab_text(_provenance_sheet())
    block = text.split("3 — THE ROUTE")[1].split("4 — IDENTITY")[0]
    leg = [ln for ln in block.splitlines() if ln.startswith("7332-01-002")]
    kept = [ln for ln in leg if "tubebend" in ln]
    ruled = [ln for ln in leg if "folding" in ln]
    assert kept and "charged" in kept[0] and "Estimate!103" in kept[0]
    assert ruled and "ruled out" in ruled[0] and "not physically possible" in ruled[0]
    assert "decision:9e3d96e71416" in kept[0]
    assert "the drawing" in kept[0], "who decided it, in words"


def test_the_identity_block_says_what_did_not_track_through_the_pack():
    import estimation_report as er
    job = seventy_three_thirty_two()
    leg = next(n for n in job["estimate_summary"]["canonical_route_shadow"]["nodes"]
               if n["part_number"] == "7332-01-002")
    leg["evidence"] = {"raw_aliases": ["7332-01-002", "7332-01-02 LEG"]}
    job["dxf_augmentation"] = {
        "unmatched_dxf": [{"path": "K:\\jobs\\7332\\7332-01-009_1mm MS.DXF",
                           "reason": "no_bom_line_for_this_part_number"}],
        "ambiguous_dxf": [], "parts_without_dxf": ["7332-01-002"],
    }
    wb = openpyxl.Workbook()
    wb.active.title = "Estimate"
    er.add_provenance_sheet(wb, job, {"job_number": "7332"})
    text = _tab_text(wb["AI Provenance"])
    block = text.split("4 — IDENTITY AND TRACKING")[1]
    assert "Merged under one name | 7332-01-002 | also appears as 7332-01-02 LEG" in block
    assert "Drawing file matched to no part | 7332-01-009_1mm MS.DXF" in block
    assert "no bom line for this part number" in block
    assert "No DXF flat for this part | 7332-01-002" in block


def test_a_clean_pack_says_so_in_the_identity_block():
    text = _tab_text(_provenance_sheet())
    block = text.split("4 — IDENTITY AND TRACKING")[1]
    assert "Every part tracked through the pack under one name" in block


def test_the_provenance_tab_reads_value_source_evidence_action():
    ws = _provenance_sheet()
    header = [c.value for c in ws[5]]
    assert header[:7] == ["Part Number", "Description", "Qty", "Material — source",
                          "Thickness — source", "Geometry / size — source",
                          "Operations charged"]
    assert "Charged £ unit" in header and "Charged £ ext" in header
    assert "Engine £ ext — not charged" in header
    assert "Evidence" in header and "Estimator action" in header
    assert "Conf." not in header and "Unit £ material" not in header


def test_the_money_is_the_sheets_and_the_engines_is_beside_it_as_not_charged():
    ws = _provenance_sheet()
    header = [c.value for c in ws[5]]
    rows = {r[0]: r for r in _rows(ws)[5:] if r and r[0]}
    lens = rows["7332-01-007"]
    assert lens[header.index("Charged £ ext")] == "£2.82"
    assert lens[header.index("Engine £ ext — not charged")] == "£2.02"
    leg = rows["7332-01-002"]
    assert leg[header.index("Charged £ ext")] == "£11.72"
    assert leg[header.index("Engine £ ext — not charged")] == "—"
    assert leg[header.index("Operations charged")] == "tubebend"
    assert "1,397 mm" in str(leg[header.index("Geometry / size — source")])
    assert "section-stock trade rate" in str(leg[header.index("Price source")])


def test_the_evidence_is_a_word_and_the_action_is_the_records():
    ws = _provenance_sheet()
    header = [c.value for c in ws[5]]
    rows = {r[0]: r for r in _rows(ws)[5:] if r and r[0]}
    # The fixture records no material_source on its parts, so the weakest field is unread —
    # the word, not a percentage, is the point.
    assert rows["7332-01-001"][header.index("Evidence")] in ("measured", "transcribed",
                                                             "inferred", "unread")
    assert rows["PACKAGING"][header.index("Estimator action")] == "enter the per-unit figure"
    assert "confirm the plated member list" in \
        str(rows["7332-01-101"][header.index("Estimator action")])
    assert "confirm the developed length" in \
        str(rows["7332-01-002"][header.index("Estimator action")])
    assert rows["7332-01-003"][header.index("Estimator action")].startswith("none")
    # a commercial line's blank is explained in the price-source column, owner first
    assert "ESTIMATOR TO PRICE" in str(rows["DELIVERY"][header.index("Price source")])


def test_the_explanation_leads_with_the_decisions(tmp_path):
    import json
    import estimate_explained as ee
    job = seventy_three_thirty_two()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["D6"] = 6
    ws["C9"] = "Bill of Materials (Per Unit)"
    ws["H9"] = "Part code"
    r = 10
    for m in job["final_estimate"]["material_rows"]:
        if m["block"] != "bom":
            continue
        ws.cell(r, 3, m["description"])
        ws.cell(r, 8, m["part_code"])
        ws.cell(r, 10, m["unit_price_gbp"])
        ws.cell(r, 11, m["qty_per_unit"])
        r += 1
    xlsx = tmp_path / "7332-01.xlsx"
    wb.save(xlsx)
    jp = tmp_path / "7332-01.json"
    jp.write_text(json.dumps(job), encoding="utf-8")
    md = ee.build(xlsx, jp)
    assert md.index("## What a person still has to settle") < md.index("## The questions, answered first")
    settle = md.split("## What a person still has to settle")[1].split("## ")[0]
    assert "plated after welding" in settle and "PACKAGING" in settle
    # and the rows the two dropped tabs used to feed are still on the page, from the JSON
    assert "— (subcontract service)" in md and "— (commercial line)" in md
    assert "section-stock trade rate" in md
