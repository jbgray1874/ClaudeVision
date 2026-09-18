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
                       "unit_gbp": 149.87, "unit_cell": "Estimate!M105",
                       "unit_cell_value": 149.87},
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
                                       "unit_cell": "Estimate!M105",
                                       "unit_cell_value": 149.87}}
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
        {"run": {"unit_cost_gbp": 149.87, "unit_cell": "Estimate!G6",
                  "unit_cell_value": 149.87}})["amount"] == 149.87


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


# ── D-141: the report and the quote stop bypassing the fact ─────────────────────────
#
# James Gray, 18 Sep 2026: "`job_report_html` still prints raw `hl["unit"]` in its header,
# summary, verdict and footer. `client_quote_html` has its own direct total path."
#
# Four sites in one document, each deciding for itself — the five-surfaces shape inside a
# single file — while the covering email had already been put behind `publishable_total`.

def _hl(unit=149.87, cell="Estimate!M105"):
    import job_report_html as J
    return J._extract_headline({
        "estimate_summary": {"workbook_equivalent_pricing": {
            "m105_total_unit_cost_gbp": unit}},
        "final_estimate": {"totals": {"unit_gbp": unit, "unit_cell": cell,
                                      "unit_cell_value": unit}},
    })


def test_the_report_headline_publishes_a_traceable_total():
    import job_report_html as J
    assert J._unit_text(_hl()) == "£149.87"


def test_the_report_refuses_a_total_it_cannot_trace():
    import job_report_html as J
    said = J._unit_text(_hl(cell=None))
    assert "PENDING" in said
    assert "149.87" not in said


def test_every_site_in_the_report_asks_the_same_helper():
    """Header, summary, verdict and footer. They could disagree before: the email refused a
    total the report printed four ways."""
    import job_report_html as J
    src = open(J.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    # DOCSTRINGS TOO, not just `#` lines. `_unit_text`'s own docstring names the pattern it
    # replaced, and a stripper that misses triple-quoted blocks matched it — the seventh time
    # in this suite a text search has found prose ABOUT a thing rather than the thing.
    body = re.sub(r'"""[\s\S]*?"""', " ", src)
    body = "\n".join(l for l in body.split("\n") if not l.lstrip().startswith("#"))
    assert "_money(hl['unit'])" not in body and '_money(hl["unit"])' not in body, \
        "a headline site is still printing the raw total"
    assert body.count("_unit_text(hl)") >= 6


def test_the_quote_will_not_price_from_an_untraceable_cost():
    """A quote is the one deliverable a customer keeps — the last place an untraceable figure
    should be allowed."""
    import client_quote_html as Q
    src = open(Q.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert "publishable_total" in src
    at = src.index("unit_price = (unit_cost * MARKUP_FACTOR)")
    assert "publishable_total" in src[max(0, at - 1400):at]


def test_the_regen_reader_records_the_cell_it_read_the_price_from():
    """It scans for the price by LABEL, so it knows the cell — and a quote regenerated from an
    amended workbook is still a published figure."""
    import client_quote_regen as R
    src = open(R.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert '"price_cell"' in src
    assert '_fe_tot["unit_cell"] = figures["price_cell"]' in src


# ── and a traceability gap is visible, not a blank ──────────────────────────────────

def test_a_charge_with_no_recorded_cell_says_so_on_the_page():
    """James Gray: it "falls through to a dash. It should say `PENDING — WORKBOOK CELL NOT
    RECORDED`, so the absence is actionable rather than looking like a blank." A dash reads as
    "nothing to see" on a line where the sheet DID calculate a figure."""
    import job_report_html as J
    src = open(J.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert 'pending_traceability' in src
    assert "PENDING — WORKBOOK CELL NOT RECORDED" in src


def test_the_three_pending_states_are_distinguishable():
    """Pending a price, pending traceability, and nothing at all mean different things and
    send a reader to different people."""
    from displayed_charge import displayed_charge
    assert displayed_charge({"engine_ext_gbp": 4.40})["basis"] == "pending"
    assert displayed_charge({"charged_ext_gbp": 9.99})["basis"] == "pending_traceability"
    assert displayed_charge({})["basis"] == "none"


# ── the two rendered cases, not source checks ───────────────────────────────────────
#
# James Gray, 18 Sep 2026: "The tests also need two real rendered cases, rather than source
# checks: quote built with a missing/invalid traceable total → no customer price; report/quote
# where the recorded cell's value disagrees with the proposed total → PENDING, not a figure."
#
# THE SECOND CASE IS THE ONE THAT MATTERS. Pairing an amount from
# `workbook_equivalent_pricing` with a cell from `final_estimate.totals` and checking only
# that the cell EXISTS publishes "£149.87, Estimate!M105" without ever establishing that M105
# holds £149.87. A wrong citation is worse than none: an unsourced number invites checking and
# a cited one stops it.

def _quote_summary(unit=149.87, cell="Estimate!M105", cell_value=149.87):
    totals = {"unit_gbp": unit}
    if cell:
        totals["unit_cell"] = cell
    if cell_value is not None:
        totals["unit_cell_value"] = cell_value
    return {
        "job_output_stem": "401912-02",
        "client": "tesco",
        "estimate_summary": {
            "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": unit},
            "order_quantity": 3,
        },
        "final_estimate": {"totals": totals, "material_rows": [], "labour_rows": []},
    }


def _quote_text(summary):
    import client_quote_html as Q
    return re.sub(r"<[^>]+>", " ", Q.build_quote_html(summary))


def test_a_quote_with_no_traceable_total_carries_no_customer_price():
    """The rendered case. A quote is the one deliverable a customer keeps."""
    said = _quote_text(_quote_summary(cell=None, cell_value=None))
    assert "149.87" not in said
    assert "224.81" not in said, "a marked-up price was computed from an untraceable cost"


def test_a_quote_whose_cell_disagrees_carries_no_customer_price():
    """The citation says Estimate!M105; M105 holds something else. Neither may be published."""
    said = _quote_text(_quote_summary(unit=149.87, cell_value=321.88))
    assert "149.87" not in said
    assert "321.88" not in said


def test_a_quote_with_a_verified_total_does_price():
    """The control. A guard that refuses everything is not a guard."""
    said = _quote_text(_quote_summary())
    assert "149.87" in said or "224" in said, "the verified case must still produce a price"


def test_the_report_refuses_a_total_its_cell_disagrees_with():
    """Same fact, rendered report."""
    import job_report_html as J
    hl = J._extract_headline({
        "estimate_summary": {"workbook_equivalent_pricing": {
            "m105_total_unit_cost_gbp": 149.87}},
        "final_estimate": {"totals": {"unit_gbp": 149.87,
                                      "unit_cell": "Estimate!M105",
                                      "unit_cell_value": 321.88}},
    })
    said = J._unit_text(hl)
    assert "PENDING" in said
    assert "149.87" not in said and "321.88" not in said


def test_the_refusal_names_both_figures():
    """A disagreement between the read and the citation is a real fault in one of them, and
    an estimator can only chase it if the page says which two numbers differ."""
    from displayed_charge import publishable_total
    why = publishable_total({"run": {"unit_cost_gbp": 149.87,
                                     "unit_cell": "Estimate!M105",
                                     "unit_cell_value": 321.88}})["why"]
    assert "149.87" in why and "321.88" in why and "Estimate!M105" in why


def test_the_quote_fails_closed_when_the_check_cannot_run(monkeypatch):
    """It was wrapped in `except Exception: pass`, which leaves the cost SET when the guard
    itself breaks — the one failure mode a guard exists for, on the page a customer keeps.

    AND THIS TEST WAS A SOURCE GREP. It asserted that the string `except Exception` did not
    appear within 400 characters of the call, which is a check on how the fix is spelled and
    not on what it does. It then failed against the CORRECT fix: the quote must catch, because
    a check that raises must not take the whole quotation down — a draft is always generated
    in the portal for an estimator to edit. A grep cannot tell the two handlers apart. Running
    the document can, so it does.
    """
    import client_quote_html as Q
    import displayed_charge

    def _raise(*_a, **_k):
        raise RuntimeError("the check exploded")

    # PATCHED AT THE SOURCE. The quote used to call `publishable_total` itself; it now asks
    # `quote_state`, which is the same question answered in one place instead of two.
    monkeypatch.setattr(displayed_charge, "publishable_total", _raise)
    html = Q.build_quote_html(_quote_summary())
    assert html and "<html" in html.lower(), "the draft quotation must still be generated"
    said = re.sub(r"<[^>]+>", " ", html)
    assert "149.87" not in said, "the traceability check failed open"
    assert "224.81" not in said, "a marked-up price survived a failed check"
