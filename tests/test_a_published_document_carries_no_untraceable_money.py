r"""A published document carries no money it cannot trace.

James Gray, 18 September 2026, setting the acceptance test for the publication model:

    "the next check should be a real generated email/report fixture proving:
       * no engine-only currency appears;
       * every published amount carries its recorded cell;
       * £3.88 and £321.88 are absent;
       * a pending line remains named, but has no amount."

THIS IS THAT FIXTURE. It renders a real covering note and a real report from a summary shaped
like 401912-02's — a steel line the SHEET charged at £3.07 against an engine figure of £3.88,
and a bought-in the sheet never charged — and reads what a person would read.

WHY A RENDERED FIXTURE AND NOT MORE UNIT TESTS. `displayed_charge` has been unit-tested since
it was written, and the £3.88 still reached the page, because the renderers were not asking
it. Five times. A test that exercises the fact proves the fact; only a test that reads the
OUTPUT proves the document. Every earlier version of this check was a source grep, and each
one passed while the book carried the figure.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")


# The two figures this whole afternoon was about. Named here so a reader of a failure knows
# immediately which defect has come back.
ENGINE_STEEL = "3.88"        # the engine's own steel figure; the sheet charged £3.07
ENGINE_AGGREGATE = "321.88"  # the engine's sum over its part estimates; the sheet said £150.32


def _steel_line():
    """A line the sheet charged, on the block an estimator has ruled on."""
    return {"part_number": "401912-02-01M", "description": "METAL DIVIDER - TALL",
            "block": "steel", "sheet_row": 63, "charged_cell": "Estimate!M63",
            "charged_ext_gbp": 3.07, "engine_ext_gbp": 3.88,
            "qty_per_unit": 1, "kind": "fabricated"}


def _pending_line():
    """A line the sheet never charged. The engine has a figure; it is not a price."""
    return {"part_number": "PACKAGING", "description": "Packaging (per-unit share)",
            "block": "bom", "sheet_row": 12, "charged_cell": "Estimate!M12",
            "charged_ext_gbp": None, "engine_ext_gbp": 4.40,
            "qty_per_unit": 1, "kind": "bought_in"}


# ── the fact, on the two lines that matter ──────────────────────────────────────────

def test_the_ruled_line_publishes_the_sheets_figure_and_its_cell():
    from displayed_charge import displayed_charge
    got = displayed_charge(_steel_line())
    assert got["amount"] == 3.07
    assert got["cell"] == "Estimate!M63"
    assert got["publish_diagnostic"] is False
    assert got["diagnostic"] == 3.88, "the engine's figure is kept, for diagnosis"


def test_the_pending_line_has_no_amount_at_all():
    from displayed_charge import displayed_charge
    got = displayed_charge(_pending_line())
    assert got["amount"] is None
    assert got["basis"] == "pending"
    assert got["diagnostic"] == 4.40


# ── and the documents a person actually reads ───────────────────────────────────────

ENGINE_PENDING = "4.40"      # a bought-in the sheet never charged; the engine has a figure


def _summary():
    """A run shaped like 401912-02's: one line the sheet charged, one it never did."""
    return {
        "job_no": "401912-02",
        "client": "tesco",
        "saved_output_paths": {},
        "estimate_summary": {"part_estimates": [
            {"part_number": "401912-02-01M", "description": "METAL DIVIDER - TALL",
             "material_estimate": {"extended_material_cost_gbp": 3.88}},
            {"part_number": "PACKAGING", "description": "Packaging (per-unit share)",
             "material_estimate": {"extended_material_cost_gbp": 4.40}},
        ]},
        "final_estimate": {
            "schema": "final_estimate.v2",
            "totals": {"material_gbp": 3.07, "labour_gbp": 131.34,
                       "unit_gbp": 149.87, "unit_cell": "Estimate!M105"},
            "material_rows": [
                {"part_number": "401912-02-01M", "block": "steel", "workbook_row": 63,
                 "charged_cell": "Estimate!M63", "total_value_gbp": 3.07},
                {"part_number": "PACKAGING", "block": "bom", "workbook_row": 12,
                 "charged_cell": "Estimate!M12", "total_value_gbp": 0},
            ],
            "labour_rows": [],
        },
    }


@pytest.fixture(scope="module")
def full_report():
    """THE WHOLE REPORT, not one section of it.

    The previous version of this fixture called `_unpriced_section()` alone and then grepped
    the covering-email module's SOURCE — which could not see the live `engine: £4.40` branch
    in `_render_bom_tree`, and did not render an email at all. It was the "test the source,
    not the deliverable" weakness in the very file written to avoid it.
    """
    import job_report_html as J
    _real = J._record_for
    J._record_for = lambda s: {"lines": [_steel_line(), _pending_line()],
                               "run": {"unit_cost_gbp": 149.87,
                                       "unit_cell": "Estimate!M105"}}
    try:
        html = J.build_report_html(_summary())
    finally:
        J._record_for = _real
    return re.sub(r"<[^>]+>", " ", html)


@pytest.fixture(scope="module")
def covering_note(tmp_path_factory):
    """A real covering email, rendered from a real workbook."""
    import importlib
    import estimate_explained as EE
    sib = importlib.import_module("test_the_covering_note_says_what_the_estimate_costs")
    d = tmp_path_factory.mktemp("published")
    note = EE.covering_email(
        sib._workbook(d / "12349-02_20260902_153051.xlsx"),
        sib._scan(d / "12349-02.json"),
        client="fanatics",
        deliverables=[str(d / "12349-02.xlsx")],
    )
    return re.sub(r"<[^>]+>", " ", note["html"]) + " " + note["text"] + " " + note["subject"]


def test_the_engines_steel_figure_is_not_on_the_report(full_report):
    assert ENGINE_STEEL not in full_report, (
        "the £3.88 comparator is back on the report — it has returned five times")


def test_the_engine_aggregate_is_not_on_the_report(full_report):
    assert ENGINE_AGGREGATE not in full_report


def test_the_charged_line_is_published_with_the_sheets_figure(full_report):
    assert "£3.07" in full_report
    assert "401912-02-01M" in full_report


def test_the_pending_line_is_named_but_carries_no_amount(full_report):
    """Named, because a row that vanishes reads as a suppressed finding. No amount, because
    an engine figure with no workbook cell behind it is not a price."""
    assert "PACKAGING" in full_report
    assert "£4.40" not in full_report
    assert "4.40" not in full_report


# ── the rule, stated as a property of every published amount ────────────────────────

def test_no_published_amount_lacks_a_recorded_cell():
    """The general rule, checked on the fact rather than on one document: a workbook amount
    is published only where the read-back recorded the cell it came from, and a total with no
    cell is refused rather than guessed at."""
    from displayed_charge import displayed_charge, publishable_total
    # A charge whose cell was never recorded still publishes — the sheet DID calculate it —
    # but it says so, rather than printing a cell reference nobody can open.
    no_cell = displayed_charge({"block": "bom", "charged_ext_gbp": 9.99})
    assert no_cell["cell"] is None
    assert "not recorded" in no_cell["label"]
    # A TOTAL with no cell is refused outright. That is the £321.88 rule.
    assert publishable_total({"run": {"unit_cost_gbp": 149.87}})["amount"] is None
    assert publishable_total(
        {"run": {"unit_cost_gbp": 149.87, "unit_cell": "Estimate!G6"}})["amount"] == 149.87


# ── and the covering email, rendered ────────────────────────────────────────────────

def test_no_engine_figure_reaches_the_covering_email(covering_note):
    for figure in (ENGINE_STEEL, ENGINE_AGGREGATE):
        assert figure not in covering_note, f"{figure} is on the email"


def test_the_email_headline_publishes_only_a_traceable_total(covering_note):
    """It called `publishable_total` and then printed the raw total anyway, using the fact
    only to decide whether to append a cell — the refusal reduced to a formatting choice."""
    assert "£930.39" in covering_note
    assert "Estimate!M105" in covering_note


def test_an_untraceable_total_is_not_printed_at_all(tmp_path):
    """The other half: where the fact refuses, no figure appears."""
    import importlib
    import estimate_explained as EE
    sib = importlib.import_module("test_the_covering_note_says_what_the_estimate_costs")
    scan = sib._scan(tmp_path / "j.json")
    import json
    doc = json.loads(scan.read_text(encoding="utf-8"))
    doc["final_estimate"]["totals"].pop("unit_cell", None)
    scan.write_text(json.dumps(doc), encoding="utf-8")
    note = EE.covering_email(sib._workbook(tmp_path / "j.xlsx"), scan, client="x")
    text = re.sub(r"<[^>]+>", " ", note["html"])
    assert "UNIT COST PENDING" in text
    assert "£930.39" not in text
