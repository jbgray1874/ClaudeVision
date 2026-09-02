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
                {"operation": "P.Coat", "description": "P.Coat, 16 parts",
                 "department": "P/C", "batch_hours": 0.344,
                 "dept_rate_gbp_per_hour": 355.43, "setup_minutes": 15,
                 "total_value_gbp": 122.23},
                {"operation": "Laser (Metal)", "description": "Laser 1.5, 11 parts",
                 "department": "LASM", "batch_hours": 0.472,
                 "dept_rate_gbp_per_hour": 68.19, "setup_minutes": 10,
                 "total_value_gbp": 32.21},
            ],
            "material_rows": [
                {"block": "steel", "description": "01-01M Cross members",
                 "qty_per_unit": 6, "length_mm": 650.7, "width_mm": 178.7, "gauge": 1.5,
                 "qty_per_sheet": 18, "total_value_gbp": 11.48},
                {"block": "steel", "description": "01A Drawer front",
                 "qty_per_unit": 1, "length_mm": 480, "width_mm": 295, "gauge": 1.5,
                 "total_value_gbp": 86.40},
                # The block 12349-02's note left out entirely.
                {"block": "other_sheet", "description": "06A Front cover",
                 "qty_per_unit": 3, "length_mm": 300, "width_mm": 200, "gauge": 5,
                 "total_value_gbp": 30.71},
                {"block": "bom", "part_code": "FIXING908",
                 "description": "CONCRETE SLAB", "qty_per_unit": 2,
                 "unit_price_gbp": 85.62, "supplier": "xAI market indication",
                 "total_value_gbp": 171.24},
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
    "The material we cut, block by block",
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
    order = [text.index("1. The number"), text.index("The material we cut"),
             text.index("3. Bought-in"), text.index("4. Labour"),
             text.index("The drawing pack")]
    assert order == sorted(order)


# ── section 1: the number, and what it is made of ──────────────────────────────

def test_the_number_breaks_into_material_and_labour(note):
    for figure in ("£541.42", "£323.84", "£930.39"):
        assert figure in note["text"], f"{figure} is not in the note"


def test_every_material_block_is_named_with_its_own_subtotal(note):
    """"bought-in and commercial X plus sheet steel Y", with X computed as (material -
    steel), announced a third block's money as bought-in. 12349-02 headed section 3 with
    GBP 69.99 over rows adding to GBP 39.28 that way."""
    text = note["text"]
    assert "sheet steel £97.88" in text
    assert "other sheet material £30.71" in text
    assert "bought-in and commercial £171.24" in text


def test_the_block_nobody_rendered_has_its_own_table(note):
    assert "Other sheet material" in note["text"] and "06A Front cover" in note["text"]


def test_the_material_is_reconciled_against_the_sheets_own_total(note):
    """A residual is stated rather than absorbed — that difference is the whole reason to
    print this line."""
    assert "Material reconciliation" in note["text"] and "£541.42" in note["text"]


# ── section 2: the formula, so nobody divides it back out ──────────────────────

def test_the_nest_formula_is_stated_next_to_the_steel(note):
    assert "ROUNDUP" in note["text"] and "1.04 scrap" in note["text"]


def test_the_note_warns_against_dividing_the_line_total_out(note):
    assert "don't divide these back out" in note["text"]


# ── section 4: the set-up split, which is the quantity story ───────────────────

def test_the_labour_says_how_much_is_set_up(note):
    """The sheet records set-up in MINUTES against a department rate, not in pounds. Asking
    for a `setup_cost_gbp` no row carries returned zero on every row and concluded there was
    no set-up — so the one sentence that answers "what would 50 off cost" never printed.

    15 min at 355.43/hr and 10 min at 68.19/hr, each divided by the order quantity of 7
    because Total Value is per unit: 12.69 + 1.62 = 14.32."""
    assert "£14.32" in note["text"], "the set-up share is the whole of the quantity story"
    assert "£140.12" in note["text"], "and the run time is the half that does not move"


def test_the_set_up_minutes_are_shown_on_each_labour_row(note):
    section = note["text"].split("4. Labour")[1].split("that need you")[0]
    assert "Set-up min" in section


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


# ── the Source column, which was answering "check AI Provenance" on most lines ──
#
# Four lines out of 12349-02's section 3, verbatim. Every one of them said
# "source not named in the workbook — check AI Provenance", which reads as a lookup we forgot
# to do and sends an estimator to a tab that has nothing to tell them.

def _src(row, prov=None):
    return ee._price_source(row, prov or {}, {})


def test_a_part_costed_in_another_block_says_which_block():
    """12349-02-69-01A, 06A and 08J are costed on Other Sheet Material and are correctly
    blank here. The test was for "costed in sheet steel" alone, so all three fell through it
    and landed on the estimator's to-do list for no reason."""
    got = _src({"code": "12349-02-69-01A", "price": 0,
                "text": "GRAVITY FEEDER FABRICATION — costed in Other Sheet Material"})
    assert "Other Sheet Material" in got
    assert "NOT PRICED" not in got and "not named" not in got


def test_sheet_steel_still_names_its_own_block():
    got = _src({"code": "01-01M", "price": None,
                "text": "CROSS MEMBERS — costed in Sheet Steel below"})
    assert "Sheet Steel" in got


@pytest.mark.parametrize("code", ["STD PART", "FIXING", "P/P"])
def test_a_class_in_the_code_column_is_named_as_one(code):
    """You cannot look up a rate for the word FIXING. Saying "source not named" implies we
    could have and did not."""
    got = _src({"code": code, "price": 0, "text": "3.5x19mm WOOD SCREW"})
    assert "CLASS, not a code" in got
    assert "not named in the workbook" not in got


def test_a_class_word_on_a_PRICED_line_keeps_its_price_source():
    """PACKAGING is a category word too. On a line carrying £25.00 the price is what
    matters, not the spelling of its code."""
    got = _src({"code": "PACKAGING", "price": 25.0, "supplier": "market_indication",
                "text": "Packaging"})
    assert "NOT A QUOTE" in got and "CLASS" not in got


def test_a_line_written_as_zero_is_an_unpriced_line():
    """Zero is what a blank reads as once the cell has been written. This asked for None or
    empty only, so every 0.00 line skipped the loud answer."""
    assert "NOT PRICED" in _src({"code": "BI-SCREW", "price": 0.0, "text": "M5x10 CAP"})
    assert "NOT PRICED" in _src({"code": "BI-SCREW", "price": None, "text": "M5x10 CAP"})


def test_a_real_catalogue_line_is_unchanged():
    assert _src({"code": "FIXING908", "price": 1.28, "supplier": "Elite",
                 "text": "ADJUSTABLE FOOT"}) == "catalogue — Elite"


def test_an_indication_is_still_called_out():
    got = _src({"code": "PACKAGING", "price": 25.0, "supplier": "market_indication",
                "text": "Packaging"})
    assert "NOT A QUOTE" in got


def test_the_provenance_row_is_found_when_the_two_sheets_spell_it_differently():
    got = _src({"code": "01 01X", "price": 1.42, "text": "62012RS Ball Bearing"},
               prov={"0101X": {"Price Source": "purchase history 2026-03"}})
    assert "purchase history" in got


# ── nothing is cut off mid-word ────────────────────────────────────────────────

def test_a_long_operation_name_is_not_cut_mid_word(note):
    """"CNC Joinery — 5mm HIGH IMPACT ACRYLIC (12349-02-" is a machine cutting a string at
    character 48, and it reads as software that does not know what it is holding."""
    assert "(12349-02-\n" not in note["text"]
    for line in note["text"].splitlines():
        assert not line.rstrip().endswith("(12349-02-")


def test_the_word_safe_clip_breaks_on_a_space_and_marks_it():
    got = ee._clip("CNC Joinery — 5mm HIGH IMPACT ACRYLIC (12349-02-69-01A)", 30)
    assert got.endswith("…") and not got.rstrip("… ").endswith("-")
    assert len(got) <= 32


def test_the_clip_leaves_something_that_already_fits_alone():
    assert ee._clip("P.Coat, 16 parts", 40) == "P.Coat, 16 parts"
