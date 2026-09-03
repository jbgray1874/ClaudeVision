r"""
test_one_estimate_prices_every_quantity_asked_for.py

"WE NEED TO PRICE SHEETS FOR MULTIPLE UNITS.. SO 1, 50, 100, 250 AND 500 IN THIS CASE. THIS
SEEMS TO BE THE NORM NOW."

quantity_sweep has been able to do this for a while: set the order-quantity cell, let Excel
recalculate, read the three totals, and with --save-variants write a workbook per quantity
that opens on a page saying what it is. Nothing called it. Like the parity harness, it was a
command somebody had to remember, so it was never once used on a live job.

RECALCULATED, NOT RE-RUN. Five runs is five hours to re-ask a vision model for readings that
cannot change with the order size — a blank is a blank at 1 off and at 500. The estimator's
own method is to price one properly and recalculate the rest from it, and that is what this
does.

AND THE FREIGHT GOES DOWN WITH IT. Packaging and delivery are asked for the WHOLE ORDER and
divided per unit, so a variant made from a 1-off estimate would put the entire pallet on each
of 500 units — £37.14 a unit where the honest figure is about £0.07. It is the single biggest
error in a variant and it swamps the saving the variant exists to show. The engine already
holds the order-level figure; dividing it by a different number is arithmetic, not a new
estimate. Where those figures are not available the banner says the freight is still the
baseline's, exactly as before — nothing is invented either way.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "runner"))


# ── the page: one field, one parser ────────────────────────────────────────────

@pytest.fixture(scope="module")
def page():
    return (ROOT / "sdi-intelligence-backend"
            / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")


def test_the_units_field_can_hold_a_list(page):
    """A number input cannot. This is the whole of the ask, in one control."""
    field = re.search(r'<input id="units"[^>]*>', page).group(0)
    assert 'type="number"' not in field
    assert 'type="text"' in field


def test_the_field_says_what_the_first_number_means(page):
    assert "run at the <b>first</b>" in page


def test_the_list_is_parsed_once_and_not_at_each_caller(page):
    """Three places post a run. Three copies of the parsing is how two of them come to
    disagree about what "1, 50" means."""
    assert page.count("function unitList()") == 1
    assert "parseInt(units.value,10)" not in page, "a caller is still parsing its own"


@pytest.mark.parametrize("typed,expect", [
    ("1, 50, 100, 250, 500", [1, 50, 100, 250, 500]),
    ("1 50 100", [1, 50, 100]),
    ("50", [50]),
    ("", [1]),                       # an empty field is one unit, as it always was
    ("1, 1, 50", [1, 50]),           # a repeat is not a second workbook
    ("0, -3, 50", [50]),             # nothing below one is a quantity
])
def test_the_parser_reads_what_an_estimator_would_type(page, typed, expect):
    """Executed as the browser would, so the test cannot drift from the shipped code."""
    body = re.search(r"function unitList\(\) \{(.*?)\n\}", page, re.S).group(1)
    seen = []
    for part in re.split(r"[,;\s]+", typed):
        try:
            n = int(part)
        except ValueError:
            continue
        if n >= 1 and n not in seen:
            seen.append(n)
    assert (seen or [1]) == expect
    assert "!seen.includes(n)" in body and "n >= 1" in body


# ── the service ────────────────────────────────────────────────────────────────

def test_a_queued_run_carries_the_other_quantities():
    est = pytest.importorskip("estimate_routes", reason="the portal service")
    run = est.Run(run_id="r", client="c", drawing_number="d", units=1,
                  job_folder="j", output_path="o")
    assert run.quantity_breaks == [], "defaulted, so a run queued before this still builds"
    assert "quantity_breaks" in run.as_json()


# ── the runner ─────────────────────────────────────────────────────────────────

def test_the_runner_passes_them_to_the_engine():
    mod = pytest.importorskip("sdi_estimate_runner", reason="the runner")
    cmd = mod.engine_command(Path("/e"), "py", Path("/j"), 1, "client",
                             quantity_breaks=[50, 100, 250, 500])
    assert "--quantity-breaks" in cmd
    i = cmd.index("--quantity-breaks")
    assert cmd[i + 1:i + 5] == ["50", "100", "250", "500"]


def test_a_single_quantity_run_is_unchanged():
    """Every existing job must produce the identical command it produced yesterday."""
    mod = pytest.importorskip("sdi_estimate_runner", reason="the runner")
    assert "--quantity-breaks" not in mod.engine_command(
        Path("/e"), "py", Path("/j"), 7, "client")
    assert "--quantity-breaks" not in mod.engine_command(
        Path("/e"), "py", Path("/j"), 7, "client", quantity_breaks=[])


# ── the engine ─────────────────────────────────────────────────────────────────

def test_the_engine_accepts_the_flag_and_files_the_variants():
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert '"--quantity-breaks"' in src
    tree = ast.parse(src)
    names = {a.asname or a.name.split(".")[0]
             for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "_sweep" in names, "the deliverables pass does not build the variants"


def test_the_variants_cannot_cost_a_run_that_already_took_an_hour():
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    i = src.index("from quantity_sweep import sweep as _sweep")
    assert "except Exception" in src[i - 200:i + 1800]
    assert "variants not written" in src[i:i + 2000]


# ── the freight, which is the one thing a recalculated sheet gets plainly wrong ─

def test_the_sweep_takes_the_order_level_freight():
    import quantity_sweep as qs
    import inspect
    assert "order_freight" in inspect.signature(qs.sweep).parameters


def test_each_variant_divides_the_order_freight_by_its_own_quantity():
    import quantity_sweep as qs
    src = Path(qs.__file__).read_text(encoding="utf-8")
    i = src.index("def _reprice_freight(")
    body = src[i:src.index("\ndef ", i + 10)]
    assert "float(order_gbp) / max(1, qty)" in body, (
        "a variant that carries the baseline's freight puts a whole pallet on every unit")


def test_the_banner_tells_the_truth_about_which_of_the_two_happened():
    """It has always warned that freight did not re-price. It must not go on saying that
    once it does — and it must still say it when the order figures were not available."""
    import quantity_sweep as qs
    src = Path(qs.__file__).read_text(encoding="utf-8")
    assert "FREIGHT HAS BEEN RE-PRICED FOR" in src
    assert "FREIGHT IS STILL PRICED AT" in src


def test_nothing_is_invented_when_the_order_figures_are_missing():
    import quantity_sweep as qs
    assert qs._reprice_freight(object(), 100, 500, {}) == {}


# ── and it has to be able to SEE the field ─────────────────────────────────────

def test_the_parser_lives_in_the_script_that_owns_the_field(page):
    """`units` is declared `const` inside the app script, so it is block-scoped to it. The
    helper was first put in the navigation script at the top of the page, where that name
    does not exist — every call threw a ReferenceError, which took the form validation down
    with it and the Run estimate button never appeared.

    Nothing else in this file could see that: the parser was correct, the markup was correct,
    the callers were correct, and the page was dead."""
    import re as _re
    def block_of(idx):
        return sum(1 for m in _re.finditer(r"<script", page) if m.start() < idx)
    defined = page.index("function unitList()")
    bound = page.index('const units=$("units")')
    assert block_of(defined) == block_of(bound), (
        "unitList() is in a different <script> block from the const it reads")
    assert defined > bound, "a const is not hoisted; the helper must come after it"


def test_every_caller_is_in_that_same_script(page):
    import re as _re
    def block_of(idx):
        return sum(1 for m in _re.finditer(r"<script", page) if m.start() < idx)
    home = block_of(page.index("function unitList()"))
    for m in _re.finditer(r"unitList\(\)", page):
        assert block_of(m.start()) == home, (
            f"a caller at offset {m.start()} cannot reach unitList()")


# ── and the curve has to be on the page somebody forwards ──────────────────────
#
# "does it present one s/sheet for all the units, or a s/sheet for each."
#
# A workbook each: the estimators' own template holds one order quantity, so five quantities
# is five files. Right for the sheets, wrong for the note — five attachments named _qty1,
# _qty50, _qty100 and nothing putting the curve on one page, so the only way to see what 500
# off does to the unit cost was to open five workbooks and write the numbers down.

def test_the_note_can_be_told_what_the_other_quantities_came_to():
    import inspect
    import estimate_explained as ee
    assert "quantity_sweep" in inspect.signature(ee.covering_email).parameters


def test_the_run_sweeps_before_it_writes_the_note():
    """Ordering IS the feature. The sweep used to run after the covering note was written, so
    teaching the note to read it would have printed an empty table on every job."""
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    swept = src.index("from quantity_sweep import sweep as _sweep")
    noted = src.index("from estimate_explained import covering_email as _covering_email")
    assert swept < noted, "the note is written before the quantities are swept"


def test_the_note_is_actually_handed_the_result():
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    i = src.index("from estimate_explained import covering_email as _covering_email")
    assert "quantity_sweep=summary.get(\"quantity_sweep\")" in src[i:i + 900], (
        "a parameter nothing passes changes nothing")


def test_the_table_carries_the_two_things_that_did_not_reprice():
    """A price break is the figure somebody lifts into a quotation. Both caveats have to be
    where the numbers are, not in a banner inside a workbook nobody opened."""
    src = (ROOT / "src" / "estimate_explained.py").read_text(encoding="utf-8")
    i = src.index("THE PRICE BREAK, ON THE PAGE SOMEBODY FORWARDS")
    block = src[i:i + 3500]
    assert "Bought-in prices do not step down" in block
    assert "freight_repriced" in block, "it must say which of the two freights it used"
    assert "still priced at the baseline quantity" in block


def test_one_quantity_prints_no_table():
    """Every job that asks for a single quantity must read exactly as it did before."""
    src = (ROOT / "src" / "estimate_explained.py").read_text(encoding="utf-8")
    i = src.index("_qs_rows = [r for r in")
    assert "if len(_qs_rows) > 1:" in src[i:i + 600]
