r"""
test_the_covering_note_says_what_the_estimate_costs.py

WHAT WENT OUT WITH 12349-02:

    Subject: SDI Intelligence estimate, PROVISIONAL. not reported/unit at 7 off. 12349-02
    Body:    not reported per unit, ex VAT
             12349-02_20260902_153051.xlsx
             12349-02_llm_extract.json
             12349-02_quote.html
             ...

A headline of "not reported" over a list of filenames, on a job whose workbook had a unit
cost in it the whole time. James: "the write up is very poor. it needs to be in this format"
— and then the note he had written by hand for 12552, which is what this reproduces.

TWO DEFECTS, and the second is the one that made the first invisible.

  1. The runner reports the unit cost by reading the summary JSON, and its list of key paths
     did not include `final_estimate.totals.unit_gbp` — the figure the read-back takes off
     the recalculated workbook, and the only one that provably sums to the sheet's own
     totals. Four older paths were tried, none of which exists on a v2 record, so the runner
     honestly reported nothing and the service printed "not reported".

  2. The covering note was written by the mail service, which by design has never read an
     estimate. It therefore could not say anything about the estimate beyond the one number
     it was handed — so when that number was missing there was nothing left but filenames.

The note is now written by the engine, from the workbook, through the same _gather() the full
document uses: the two cannot disagree, because they are one reading rendered twice.

The format is the specification, not decoration. It answers, before any table: what does it
cost, what is the biggest number made of, what is the labour, what needs a person, what is
wrong with the pack, and what is wrong with US. Each of those is actionable. A list of
attachments is not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

openpyxl = pytest.importorskip("openpyxl", reason="the document reads a workbook")
import estimate_explained as ee                                    # noqa: E402


# ── a workbook and a run record shaped like a real job ──────────────────────────

def _workbook(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["D6"] = 7
    ws["C9"] = "BILL OF MATERIALS (PER UNIT)"
    ws["H9"] = "Part code"
    rows = [
        ("CONCRETE SLAB", "FIXING908", "xAI market indication", 85.62, 2),
        ("ADJUSTABLE FOOT", "FIXING909", "Elite", 1.28, 6),
        ("M5 x 10 CAP SCREW", "BI-SCREW", "", None, 10),
        ("CROSS MEMBER — costed in Sheet Steel", "01-01M", "", None, 6),
    ]
    for i, (text, code, supplier, price, qty) in enumerate(rows, start=10):
        ws.cell(i, 3, text)
        ws.cell(i, 8, code)
        ws.cell(i, 9, supplier)
        ws.cell(i, 10, price)
        ws.cell(i, 11, qty)
    wb.create_sheet("AI Material Detail")
    wb.create_sheet("AI Price Provenance")
    rt = wb.create_sheet("Canonical Route")
    for c, h in enumerate(["Target", "Operation", "Seq", "Scope", "Qty/unit", "Source",
                           "Reason"], start=1):
        rt.cell(1, c, h)
    route = [
        ("01-01M", "laser_cutting", 1, "part", 6, "drawing_deterministic",
         "cut from a 1.5mm flat, stated on the detail"),
        ("01-01M", "folding", 2, "part", 6, "solidworks_flat_pattern",
         "4 bends in the model's cut list"),
        ("01A", "punching", 1, "part", 1, "inference",
         "no punch is drawn; inferred from the hole pattern"),
    ]
    for i, row in enumerate(route, start=2):
        for c, v in enumerate(row, start=1):
            rt.cell(i, c, v)
    wb.save(path)
    return path


def _scan(path: Path) -> Path:
    path.write_text(json.dumps({
        "job_source_pdfs": ["K:\\jobs\\12349-02-69-GA_Gravity Feeders_RevA.PDF"],
        "final_estimate": {
            "schema": "final_estimate.v2",
            "totals": {"material_gbp": 541.42, "labour_gbp": 323.84, "unit_gbp": 930.39},
            "labour_rows": [
                {"row": 103, "description": "P.Coat, 16 parts", "department": "P/C",
                 "batch_hours": 0.344, "rate_gbp_per_hour": 355.43,
                 "total_value_gbp": 122.23, "setup_cost_gbp": 90.0},
                {"row": 97, "description": "Laser 1.5, 11 parts", "department": "LASM",
                 "batch_hours": 0.472, "rate_gbp_per_hour": 68.19,
                 "total_value_gbp": 32.21, "setup_cost_gbp": 11.4},
            ],
            "material_rows": [
                {"block": "steel", "description": "01-01M Cross members",
                 "quantity": 6, "total_value_gbp": 11.48},
                {"block": "steel", "description": "01A Drawer front",
                 "quantity": 1, "total_value_gbp": 86.40},
            ],
        },
        "parts": [
            {"part_number": "01-01M", "description": "CROSS MEMBER", "pages": [6],
             "geometry_source": "solidworks_flat_pattern",
             "dxf_source_file": "K:\\jobs\\12349-02-69-01-01M_1.5mm_MS.DXF"},
            {"part_number": "01A", "description": "DRAWER FRONT", "pages": [],
             "geometry_source": "document_text_largest_numbers"},
            {"part_number": "FIXING908", "description": "CONCRETE SLAB", "pages": [11],
             "geometry_source": "bom_tree"},
        ],
    }), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def note(tmp_path_factory):
    d = tmp_path_factory.mktemp("job")
    return ee.covering_email(
        _workbook(d / "12349-02_20260902_153051.xlsx"),
        _scan(d / "12349-02.json"),
        client="fanatics",
        deliverables=["K:\\out\\12349-02.xlsx", "K:\\out\\12349-02_explained.md"],
    )


# ── the headline that was missing ──────────────────────────────────────────────

def test_the_unit_cost_reaches_the_subject_line(note):
    assert "£930.39/unit at 7 off" in note["subject"]
    assert "not reported" not in note["subject"]


def test_the_subject_says_how_many_lines_need_a_person(note):
    assert "need a person" in note["subject"]


def test_the_unit_cost_is_the_first_thing_in_the_body(note):
    head = note["text"][:400]
    assert "£930.39" in head, f"the number is not near the top:\n{head}"


# ── the seven sections, in order ───────────────────────────────────────────────

@pytest.mark.parametrize("heading", [
    "1. The number",
    "2. Sheet steel",
    "3. Bought-in and commercial",
    "4. Labour",
    "that need you",
    "Every operation, and who decided it",
    "The drawing pack",
])
def test_every_section_an_estimator_acts_on_is_present(note, heading):
    assert heading in note["text"], f"missing section: {heading}"


def test_the_sections_are_in_the_order_they_are_read_in(note):
    text = note["text"]
    order = [text.index("1. The number"), text.index("2. Sheet steel"),
             text.index("3. Bought-in"), text.index("4. Labour"),
             text.index("The drawing pack")]
    assert order == sorted(order)


# ── section 1: the number, and what it is made of ──────────────────────────────

def test_the_number_breaks_into_material_and_labour(note):
    for figure in ("£541.42", "£323.84", "£930.39"):
        assert figure in note["text"], f"{figure} is not in the note"


def test_material_is_split_into_bought_in_and_sheet_steel(note):
    """541.42 total less 97.88 of steel = 443.54 bought-in. Stated, not left to the reader."""
    assert "£97.88" in note["text"] and "£443.54" in note["text"]


# ── section 2: the formula, so nobody divides it back out ──────────────────────

def test_the_nest_formula_is_stated_next_to_the_steel(note):
    assert "ROUNDUP" in note["text"] and "1.04 scrap" in note["text"]


def test_the_note_warns_against_dividing_the_line_total_out(note):
    assert "don't divide these back out" in note["text"]


# ── section 4: the set-up split, which is the quantity story ───────────────────

def test_the_labour_says_how_much_is_set_up(note):
    assert "£101.40" in note["text"], "the set-up share is the whole of the quantity story"
    assert "£53.04" in note["text"], "and the run time is the half that does not move"


# ── section 5: what a person has to settle ─────────────────────────────────────

def test_an_ai_market_indication_is_named_as_one(note):
    assert "market indication" in note["text"].lower()


def test_a_line_costing_nothing_is_called_out(note):
    assert "BI-SCREW" in note["text"]


def test_a_line_costed_in_the_steel_block_is_not_listed_as_unpriced(note):
    """It has no price on the BOM because its money is in Sheet Steel. Listing it as needing
    a rate sends an estimator looking for a supplier for a part we cut ourselves."""
    section = note["text"].split("that need you")[1].split("Every operation")[0]
    assert "01-01M" not in section


# ── section 6: where a part number stopped tracing ─────────────────────────────

def test_a_part_that_lost_its_trail_is_named_with_what_it_cost(note):
    text = note["text"]
    assert "01A" in text and "£86.40" in text


def test_the_substitution_the_engine_made_is_stated(note):
    assert "largest numbers in the document text" in note["text"]


def test_a_properly_traced_part_is_not_reported_as_a_break(note):
    section = note["text"].split("The drawing pack")[1]
    assert "01-01M" not in section.split("Ours, not yours")[0]


def test_the_list_is_addressed_to_design_where_the_break_is_theirs(note):
    assert "Design" in note["text"]


# ── the shape of the thing ─────────────────────────────────────────────────────

def test_the_html_and_the_text_carry_the_same_price(note):
    assert "£930.39" in note["html"] and "£930.39" in note["text"]


def test_the_text_alternative_is_not_markup(note):
    assert "<table" not in note["text"] and "<p>" not in note["text"]


def test_the_note_never_calls_itself_ai_in_the_subject(note):
    """It goes to customers' engineers in forwarded threads."""
    assert " AI " not in note["subject"]


def test_the_quote_is_named_as_withheld_while_provisional(note):
    assert "No customer quote" in note["text"]


# ── section 6: the route, which is half the estimate ───────────────────────────
#
# It was absent from the note entirely. Section 4 says what the labour COSTS; this says what
# we think the shop does to each part and on whose authority. An operation nobody drew is the
# cheapest thing on the sheet to strike out and the easiest to miss.

def test_every_route_line_is_in_the_note(note):
    section = note["text"].split("Every operation")[1].split("The drawing pack")[0]
    for op in ("laser_cutting", "folding", "punching"):
        assert op in section, f"{op} is not in the route table"


def test_each_operation_names_who_decided_it(note):
    section = note["text"].split("Every operation")[1].split("The drawing pack")[0]
    for who in ("drawing_deterministic", "solidworks_flat_pattern", "inference"):
        assert who in section


def test_an_inferred_operation_is_called_out_for_confirmation(note):
    """The ones worth an estimator's attention: nothing on the drawing asked for them."""
    section = note["text"].split("Every operation")[1].split("The drawing pack")[0]
    assert "inferred rather than drawn" in section and "punching" in section


# ── section 7: the pack, in full rather than in summary ────────────────────────

def test_the_pack_is_graded_sheet_by_sheet(note):
    section = note["text"].split("The drawing pack")[1]
    assert "Drawing quality, sheet by sheet" in section


def test_a_line_with_no_sheet_is_reported_with_whether_it_bites(note):
    section = note["text"].split("The drawing pack")[1]
    assert "with no sheet of their own" in section


def test_sheets_no_costed_part_claimed_are_named(note):
    section = note["text"].split("The drawing pack")[1]
    assert "no costed part was traced to" in section or "claimed by at least one" in section


def test_the_quality_grade_is_refused_rather_than_guessed_from_a_trimmed_extract(tmp_path):
    """A field missing from the extract is not a field missing from the drawing. Answering
    from a trimmed one produces a confident wrong assessment of Design's work."""
    import json as _json
    (tmp_path / "trim.json").write_text(_json.dumps({
        "final_estimate": {"totals": {"unit_gbp": 1.0}, "labour_rows": [],
                           "material_rows": []},
        "parts": [{"part_number": "01-01M", "pages": [6]}],   # numbers and pages only
    }), encoding="utf-8")
    note = ee.covering_email(_workbook(tmp_path / "wb.xlsx"), tmp_path / "trim.json")
    assert "not produced" in note["text"].lower()
