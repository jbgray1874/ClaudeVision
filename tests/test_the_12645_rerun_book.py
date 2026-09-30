"""The 12645 re-run of 29 Sep 2026, 21:27 (engine 60a7421), scored against the drawings.

D-342  Rows added to the Estimate template's Sheet Steel block carried J=1250 and an empty I.
       The writer read a blank I as 2500 for its fit test and wrote nothing, so 20 parts had
       no parts-per-sheet, no cost and a default laser rate: "21 prices missing".
D-343  The estimator asked the stocked-sheet table for "MILD_STEEL"; it is keyed "MILD
       STEEL", so it saw 2500 x 1250 only and called six 2,600-2,975 mm parts "longer than
       every stocked sheet" while their workbook rows nested them on 3000 x 1500.
D-344  The table's item number rode on each flattened BOM row as "item_number" — the name
       identity readers fall back to — so a row whose code column held words became part
       "4" (a second hinge line at £0.26).
D-346  The report counted a bought-in line with labour as "costed on the block rows".
D-347  12645-01GA prints "Half Inch Whitworth Nut" as the code of "M8 FULL NUT BZP GRADE 8".
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf  # noqa: E402
import part_identity as pi  # noqa: E402
import wb_populate as wp  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

_STEEL = {"first_row": 93, "last_row": 136, "col_sheet_l": 9, "col_sheet_w": 10}


def _template_sheet_block(added_rows_have_length: bool):
    """The 12645 template: rows 93-103 and 129-136 pre-fill 2500 x 1250; rows 104-128 were
    added in Excel and carry the width only."""
    ws = openpyxl.Workbook().active
    for r in range(93, 137):
        added = 104 <= r <= 128
        ws.cell(row=r, column=10, value=1250)
        if not added or added_rows_have_length:
            ws.cell(row=r, column=9, value=2500)
    return ws


# ── D-342 ──────────────────────────────────────────────────────────────────────────────

def test_the_block_sheet_is_read_from_the_template_not_assumed():
    ws = _template_sheet_block(added_rows_have_length=False)
    assert wp.template_block_sheet(ws, _STEEL) == (2500.0, 1250.0)


def test_a_template_with_no_prefilled_sheet_says_so():
    ws = openpyxl.Workbook().active
    assert wp.template_block_sheet(ws, _STEEL) == (0.0, 0.0)


def test_with_no_template_sheet_the_smallest_stocked_sheet_is_chosen():
    """(0, 0) fits nothing, so the row is given a stocked sheet instead of a blank."""
    sheet, why = wp.steel_sheet_for_row(200, 95.22, "MILD_STEEL", (0.0, 0.0))
    assert sheet == (2500, 1250) and why


def test_the_writer_fills_a_blank_sheet_cell_rather_than_assuming_it():
    src = open(os.path.join(ROOT, "src", "wb_populate.py"), encoding="utf-8").read()
    assert "or 2500," not in src, "a blank template cell must not be read as 2500"
    i = src.index("_tpl = (_l0 or _block_sheet[0], _w0 or _block_sheet[1])")
    block = src[i:i + 900]
    assert "if _sheet is None and not _why and not (_l0 and _w0):" in block
    assert 'column=s["col_sheet_l"], value=_tpl[0]' in block


# ── D-343 ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spelling", ["MILD_STEEL", "MILD STEEL", "Mild Steel"])
def test_one_stocked_sheet_list_whatever_the_spelling(spelling):
    assert [tuple(map(float, s)) for s in cf.stocked_sheet_sizes(spelling)] == \
        [(2500.0, 1250.0), (3000.0, 1500.0)]


@pytest.mark.parametrize("length,width,per_sheet", [
    (2912.54, 381.31, 3),      # 12645-01-02M CORNER
    (2600.0, 88.44, 14),       # 12645-01-10M U-CHANNEL
    (2975.08, 685.41, 2),      # 12645-01-05M Left top cover
])
def test_a_long_part_is_on_the_stocked_sheet_the_workbook_row_uses(length, width, per_sheet):
    from estimator import select_sheet_size
    part: dict = {"description": "PANEL"}
    se = select_sheet_size("MILD_STEEL", length, width, part=part)
    assert list(se["candidate_sheet_size_mm"]) == [3000, 1500]
    assert se["parts_per_sheet"] == per_sheet
    assert not se.get("oversize_sheet")
    assert not any("OVERSIZE" in f for f in part.get("review_flags") or [])
    # and the workbook row asks the same question the same way
    assert wp.steel_sheet_for_row(length, width, "MILD_STEEL", (2500, 1250))[0] == (3000, 1500)


def test_the_3020_covers_are_still_oversize():
    from estimator import select_sheet_size
    se = select_sheet_size("MILD_STEEL", 3020.02, 727.39)
    assert se.get("oversize_sheet") and list(se["candidate_sheet_size_mm"]) == [4000.0, 1830.0]


def test_steel_stays_on_the_template_sheet_while_it_fits():
    from estimator import select_sheet_size
    assert list(select_sheet_size("MILD_STEEL", 1434.0, 748.0)["candidate_sheet_size_mm"]) \
        == [2500, 1250]


# ── D-344 ──────────────────────────────────────────────────────────────────────────────

def test_a_table_position_is_never_offered_as_an_identity(monkeypatch):
    import bom_pipeline
    import merge_boms
    monkeypatch.setattr(merge_boms, "reconcile_job", lambda paths, **k: {"parents": [
        {"label": "12645-03GA", "rows": [
            {"item_number": "4", "part_number": "piano hinge", "description": "HINGE",
             "quantity": 1}]}]})
    out = bom_pipeline.reconciled_bom_rows_for_job(pdfs=["12645-03GA_REVA.pdf"])
    row = out["rows"][0]
    assert "item_number" not in row, "identity readers fall back to item_number"
    assert row["bom_item_no"] == "4"


def test_the_pair_rule_still_reads_the_table_position():
    import route_compiler as rc
    rows = [{"part_number": "12173-07-2-02M", "quantity": 1, "bom_item_no": "1",
             "bom_parent": "12173-07-2-GA"},
            {"part_number": "12173-07-2-02M", "quantity": 1, "bom_item_no": "3",
             "bom_parent": "12173-07-2-GA"}]
    edges = {(c, p): q for c, p, q in rc._bom_stated_edges(
        rows, {}, {"12173-07-2-GA", "12173-07-2-02M"})}
    assert edges[("12173-07-2-02M", "12173-07-2-GA")] == 2


# ── D-347 ──────────────────────────────────────────────────────────────────────────────

def test_an_imperial_code_on_a_metric_description_is_asked():
    why = pi.thread_names_disagree("HALF INCH WHITWORTH NUT", "M8 FULL NUT BZP GRADE 8")
    assert "imperial" in why and "metric" in why


def test_agreeing_or_silent_threads_are_not_asked():
    assert pi.thread_names_disagree("M8 HEX HEAD BOLT", "M8x20mm HEX HEAD BOLT, BZP") == ""
    assert pi.thread_names_disagree("FIXING632", "PEM STUD M6 x 12") == ""
    assert pi.thread_names_disagree("BI-NUT", "M8 FULL NUT") == ""


def test_two_metric_sizes_are_asked():
    assert "M4" in pi.thread_names_disagree("M4 PEM", "PEM STUD M6 x 12")


# ── D-346 ──────────────────────────────────────────────────────────────────────────────

def _report_summary(total, labour):
    return {
        "final_estimate": {"material_rows": [{
            "part_number": "Roller Shutter", "price_gbp": 0,
            "unpriced_reason": {"category": "no_price_source", "owner": "estimator",
                                "why": "x", "detail": "no catalogue row"}}]},
        "estimate_summary": {"part_estimates": [{
            "part_number": "Roller Shutter", "description": "Roller Shutter Door",
            "is_bought_in": True, "material_estimate": {},
            "extended_total_cost_gbp": total,
            "labour_estimate": {"extended_labour_cost_gbp": labour}}]},
    }


def test_a_bought_in_whose_total_is_only_labour_is_not_costed_elsewhere():
    """The shutters: £9.04 of handling, no purchase price — unpriced, not "costed below"."""
    import job_report_html as jrh
    html = jrh._unpriced_section(_report_summary(9.04, 9.04))
    assert "ARE costed" not in html
    assert "Roller Shutter" in html[html.index("<tbody>"):]


def test_a_bought_in_whose_total_includes_its_price_still_counts_as_costed():
    import job_report_html as jrh
    html = jrh._unpriced_section(_report_summary(21.04, 9.04))
    assert "<tbody>" not in html or "Roller Shutter" not in html[html.index("<tbody>"):]


# ── D-345 ──────────────────────────────────────────────────────────────────────────────

def test_the_page_says_when_the_job_changes_under_an_untouched_client():
    """12645 (Tesco) was headed "M&S": the Client box still held 12173's client."""
    page = open(os.path.join(ROOT, "sdi-intelligence-backend",
                             "sdi-estimating-intelligence.html"), encoding="utf-8").read()
    assert 'id="clientHint"' in page
    assert "function checkClient()" in page and "function jobOf(" in page
    assert 'client.addEventListener("input", () => { clientFor = jobOf(drawing.value)' in page
    assert 'drawing.addEventListener("input", checkClient);' in page
    # a run pairs the client with the job it was run for
    i = page.index('setStatus("run","Running");')
    assert "clientFor = jobOf(drawing.value)" in page[max(0, i - 300):i]
