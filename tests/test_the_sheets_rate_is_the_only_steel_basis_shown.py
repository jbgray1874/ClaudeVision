r"""One steel basis on the page, both quantities on the tab, and a bought-in made of what it is.

James Gray, 18 September 2026, on the 401912-02 book:

    2. "Remove the competing GBP 3.88 engine-steel figure from the report. The estimate must
       present the editable workbook rate -- GBP 900/tonne in Estimate!L5 and GBP 3.07 in the
       nest row -- as the single charged steel basis."
    3. "Make Quantity Breaks show both requested quantities, 1 and 3, rather than only the
       last 3-off result."
    4. "Stop the purchased magnetic tape inheriting 'Mild Steel' from the assembly title
       block in BOM/provenance wording."

ON (2), THIS REVERSES PART OF D-118 AND SHOULD. Naming both bases was the right answer while
four steel rates were live and nobody knew which governed: the reader needed to tell a METHOD
disagreement from a RATE one. The ruling settled which rate is controlling, and a second
figure beside the controlling one stopped being evidence and became an invitation to re-open a
closed question. Three readers of that book spent an afternoon on GBP 3.07 vs GBP 3.88 and the
answer was that nothing was wrong. Scoped to the route that HAS a ruling: everywhere else the
engine's figure beside the sheet's has caught real faults and is untouched.

ON (3), the run was `--order-qty 1 --quantity-breaks 3` and the tab came back with one column
headed 3. The tab is the only place the two can be read side by side; without the order
quantity the 1-off cost is on the Estimate sheet and the 3-off cost is here, with nothing
saying they are one estimate at two quantities. On this job that is GBP 150.32 against GBP
56.31 -- the difference between them IS the story of the job.

ON (4), the bill of materials lists "25.4mm ADHESIVE MAGNETIC TAPE, L: 450mm" and the drawing
-quality table reported its material stated as MILD STEEL, read off the GA title block, which
states what the DIVIDER is made of. Nothing was mis-costed -- the tape is priced as a bought-in
and never touched the steel route -- but a purchased line reading as mild steel on a page
headed "Drawing quality, sheet by sheet" is a wrong fact an estimator carries to a supplier.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimate_explained as EE  # noqa: E402


# ── (4) a purchased line is not made of the assembly's material ─────────────────────

def test_a_bought_in_does_not_inherit_the_assembly_material():
    tape = {"page_roles": ["assembly", "bought_in"], "materials": ["MILD STEEL"], "pages": [1]}
    said = EE._material_stated(tape)
    assert "MILD STEEL" not in said
    assert "purchased" in said


def test_it_says_why_rather_than_going_blank():
    """An empty cell reads as a drawing that failed to state a material, which is a different
    complaint and a false one."""
    tape = {"page_roles": ["assembly", "bought_in"], "materials": ["MILD STEEL"], "pages": [1]}
    assert "assembly's material" in EE._material_stated(tape)


def test_a_fabricated_part_still_states_its_material():
    part = {"page_roles": ["detail"], "materials": ["MILD_STEEL"], "pages": [2]}
    assert EE._material_stated(part) == "MILD_STEEL"


def test_a_bought_in_with_a_detail_drawing_keeps_its_own_material():
    """Where a purchased item HAS a sheet of its own, the material on it is genuinely the
    part's. The rule is about inheriting from an assembly, not about being purchased."""
    part = {"page_roles": ["bought_in", "detail"], "materials": ["NYLON"], "pages": [3]}
    assert EE._material_stated(part) == "NYLON"


def test_a_drawing_stating_nothing_still_reads_as_nothing():
    part = {"page_roles": ["detail"], "materials": [], "pages": [4]}
    assert EE._material_stated(part) == "no"


def test_both_copies_of_the_table_use_the_one_rule():
    """This table is rendered twice -- HTML and markdown. Two copies disagreeing about what a
    part is made of is worse than either answer alone."""
    src = EE.__file__.replace(".pyc", ".py")
    text = open(src, encoding="utf-8").read()
    assert text.count("_material_stated(rec)") >= 3, \
        "one of the two tables is still joining rec['materials'] itself"


# ── (3) the quantity the job was costed at is always a break ───────────────────────

def _breaks_for(order_qty, breaks):
    """The selection main.py makes, exercised directly on its own arithmetic."""
    out = [q for q in (breaks or []) if int(q) >= 1]
    if out and order_qty and int(order_qty) >= 1:
        out = sorted({int(q) for q in out} | {int(order_qty)})
    return out


def test_the_order_quantity_joins_the_breaks():
    assert _breaks_for(1, [3]) == [1, 3]


def test_a_break_equal_to_the_order_quantity_is_not_doubled():
    assert _breaks_for(3, [3]) == [3]


def test_the_columns_come_out_in_order():
    assert _breaks_for(50, [1000, 10, 250]) == [10, 50, 250, 1000]


def test_no_breaks_asked_for_means_no_tab():
    """The sweep is opt-in. An order quantity alone must not start one."""
    assert _breaks_for(1, []) == []


def test_main_selects_the_breaks_this_way():
    """The test above is arithmetic; this is the assertion that main.py does it."""
    text = open(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"),
                encoding="utf-8").read()
    assert '_breaks = sorted({int(q) for q in _breaks} | {_order_break})' in text


# ── (2) one basis where the estimator has ruled ─────────────────────────────────────

def test_the_engine_figure_is_withheld_on_the_sheets_own_route():
    """THE TEST THAT DID NOT CATCH IT, REWRITTEN AS THE TEST THAT WOULD HAVE.

    The first version of this asserted the SHAPE OF THE SOURCE of `estimation_report` -- the
    module that builds the Provenance TAB. The page James was reading is built by
    `job_report_html`, which still printed "engine GBP 3.88 - not charged" on the next run.
    The test passed and the report did not change. So it asks the renderer instead.
    """
    import job_report_html as J
    ruled = {"material_estimate": {"cost_method": "workbook_sheet_steel_formula"}}
    assert J._sheet_ruled_basis(ruled) is True


def test_the_report_renderer_is_the_one_that_was_fixed():
    """Two pages, two modules, and only one of them had been found."""
    import job_report_html as J
    text = open(J.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    at = text.index("engine {_money(engine)} — not charged")
    guard = text[max(0, at - 400):at]
    assert "_sheet_ruled_basis(part)" in guard, \
        "the HTML report still publishes the competing figure on the ruled route"


def test_a_part_record_of_either_shape_is_understood():
    """This renderer is handed both a costed part and a bare node."""
    import job_report_html as J
    assert J._sheet_ruled_basis({"cost_method": "workbook_sheet_steel_formula"}) is True
    assert J._sheet_ruled_basis({"material_estimate": {"cost_method": "mass_times_price_per_kg"}}) is False
    assert J._sheet_ruled_basis({}) is False
    assert J._sheet_ruled_basis(None) is False


def test_the_provenance_tab_agrees_with_the_report():
    import estimation_report as R
    text = open(R.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert 'cost_method") or "") == "workbook_sheet_steel_formula"' in text
    assert "and not _sheet_ruled" in text


def test_the_provenance_column_is_withheld_with_it():
    """Removing the figure from one page and leaving it on the other moves the argument, it
    does not end it."""
    import estimation_report as R
    text = open(R.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert '"engine_figure_withheld": bool(_sheet_ruled)' in text
    assert 'not p.get("engine_figure_withheld")' in text


def test_every_other_route_keeps_the_cross_check():
    """The comparison has caught real faults. It is removed only where a ruling replaced it."""
    import estimation_report as R
    text = open(R.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    at = text.index("_sheet_ruled = ")
    assert "workbook_sheet_steel_formula" in text[at:at + 200], \
        "the suppression is not scoped to the ruled route"
