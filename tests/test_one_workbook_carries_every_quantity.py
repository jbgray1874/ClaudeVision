"""One estimate, and a _qty10 filed beside it that nobody asked for any more.

    "Let's look at collapsing all the s/sheets into one when we have multiple unit
     quantities."                                           — James Gray, SDI, 15 Sep 2026
    "Still generating multiple s/sheets"                     — James Gray, same day, on the
                                                               run that produced both files

BOTH MECHANISMS WERE RUNNING AT ONCE. The quantity sweep predates the Material Price Break
tab: it recalculates the estimate at each quantity and saves each as its own workbook, which
was the only way to see 10 off before the tab existed. The tab now answers the same question
inside one workbook, on the estimators' own template, with the sheet's own LOOKUP against
$D$6 — and the sweep carried on filing copies underneath it.

WHY THE COPIES ARE THE WORSE ANSWER, not merely the redundant one. A variant looks exactly
like a finished estimate: right drawings, right blanks, plausible unit cost, SDI template
around it. That is why every one of them has to open on a READ THIS FIRST page disclaiming
itself — freight priced at a quantity nobody is quoting, bought-ins that never took their
price break. The tab needs no disclaimer, because nothing was recalculated behind anyone's
back.

THE SWEEP STILL RUNS. Its figures are what the Quantity Breaks tab and the report read. What
stops is the filing of copies — and only where the one sheet can actually carry the breaks,
because a machine whose template has not been widened yet must still get its other
quantities rather than silently getting none.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                       # noqa: E402
import quantity_sweep as QS                                         # noqa: E402


# ── the decision ─────────────────────────────────────────────────────────────────────────

def test_the_one_sheet_being_able_to_carry_them_is_what_settles_it(monkeypatch):
    monkeypatch.setattr(config, "QUANTITY_VARIANT_WORKBOOKS", None, raising=False)
    monkeypatch.setattr(config, "MATERIAL_PRICE_BREAK", {"enabled": True}, raising=False)
    assert QS.file_a_workbook_per_quantity() is False


def test_a_template_that_cannot_carry_them_still_gets_its_quantities(monkeypatch):
    """THE CASE THAT MAKES A FLAT False WRONG. Turn the break tab off — an un-widened
    template on some machine — and the copies are the only way to see 10 off at all."""
    monkeypatch.setattr(config, "QUANTITY_VARIANT_WORKBOOKS", None, raising=False)
    monkeypatch.setattr(config, "MATERIAL_PRICE_BREAK", {"enabled": False}, raising=False)
    assert QS.file_a_workbook_per_quantity() is True


def test_it_can_be_forced_either_way(monkeypatch):
    """A setting somebody can find and change, which is the point of it being in config."""
    monkeypatch.setattr(config, "MATERIAL_PRICE_BREAK", {"enabled": True}, raising=False)
    monkeypatch.setattr(config, "QUANTITY_VARIANT_WORKBOOKS", True, raising=False)
    assert QS.file_a_workbook_per_quantity() is True
    monkeypatch.setattr(config, "MATERIAL_PRICE_BREAK", {"enabled": False}, raising=False)
    monkeypatch.setattr(config, "QUANTITY_VARIANT_WORKBOOKS", False, raising=False)
    assert QS.file_a_workbook_per_quantity() is False


def test_the_shipped_default_is_one_workbook():
    """What an estimator actually gets on the current build, asserted on the real config
    rather than on a patched one."""
    assert config.QUANTITY_VARIANT_WORKBOOKS is None
    assert config.MATERIAL_PRICE_BREAK["enabled"] is True
    assert QS.file_a_workbook_per_quantity() is False


# ── the run obeys it ─────────────────────────────────────────────────────────────────────

def test_the_run_passes_the_decision_to_the_sweep():
    """`save_variants=True` was hard-wired at the call site, so the setting could exist and
    change nothing."""
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "save_variants=_save" in src
    assert "save_variants=True" not in src, "nothing may file copies unconditionally"
    assert "file_a_workbook_per_quantity" in src


def test_the_sweep_itself_is_not_switched_off():
    """The figures are still needed — the Quantity Breaks tab and the report read them. Only
    the filing of copies stops."""
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "_swept = _sweep(" in src
    assert "write_quantity_breaks_tab" in src


# ── and the report does not go quiet about it ────────────────────────────────────────────

def test_no_copies_filed_is_said_out_loud_not_left_blank():
    """The sentence naming the filed workbooks used to vanish when there were none, and an
    absent sentence about other quantities reads as "there are none" — the opposite of what
    one workbook carrying all of them means."""
    src = (ROOT / "src" / "estimate_explained.py").read_text(encoding="utf-8")
    assert "Every quantity is in THIS workbook" in src
    assert "No separate copies are filed." in src
