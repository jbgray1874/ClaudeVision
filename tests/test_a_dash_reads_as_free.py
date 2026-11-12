"""If the engine has a number, the number goes on the sheet.

BI-SCREW CAME BACK FROM THE MARKET AT GBP 3.12 AND THE PRICE COLUMN SHOWED A DASH. The row
explained itself at length — "an AI market estimate suggested £3.12, which changes every run
and is NOT a quote" — and then priced the line at nothing.

THAT WAS MY POLICY AND IT WAS WRONG TWICE. A blank cell reads as FREE, which is the one error
on an estimate nobody catches: it sums as zero, it looks deliberate, and it survives every
review because there is nothing there to argue with. And it overrode a judgement that belongs
to the estimator — whether an indicative number beats no number. It does. Tim can strike
GBP 3.12; he cannot strike a blank he never notices.

NOTHING ABOUT THE PROVENANCE CHANGED, WHICH IS THE WHOLE POINT. The row still reads
[AI ESTIMATE - INDICATIVE, NOT A QUOTE], the supplier cell still names the model, and
price_not_reproducible is still BLOCKING — so the job cannot leave as a firm quote or an ERP
export. Reproducibility is a property to DECLARE and a gate on FIRMNESS. It is never a reason
to withhold a figure somebody asked for.

THE OTHER WAY INTO THAT BRANCH IS A QUANTITY NOBODY COULD READ. There is no figure there to
write, so that line stays blank and stays owned — the two cases are not the same and must not
be collapsed.
"""
from __future__ import annotations

import os

SRC = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
           encoding="utf-8").read()


def _branch() -> str:
    """The BOM branch that decides whether a figure reaches the money column."""
    at = SRC.index("price = _line[\"withheld_gbp\"]")
    return SRC[at - 2000:at + 3000]


def test_an_ai_indication_reaches_the_money_column():
    """THE DEFECT, STATED AS THE TEST. The figure exists; it must be written."""
    assert 'price = _line["withheld_gbp"] if _line.get("withheld_gbp") else None' in SRC


def test_a_line_with_no_figure_at_all_is_still_left_blank_and_owned():
    """A quantity nobody could read has no number to write. Filling it would be inventing
    one, which is the opposite failure and a worse one."""
    assert "else None" in _branch(), "every unpriced line now gets a number from somewhere"


def test_a_line_we_have_just_priced_is_not_also_marked_as_carrying_no_money():
    """ONE FACT, ONE WRITER — in the ledger this time. `mark_withheld` states that no money
    reached the sheet. Saying that about a line the sheet shows a figure for would tell every
    downstream check the cell is empty while an estimator reads a price in it."""
    b = _branch()
    assert 'if not _line.get("withheld_gbp"):' in b
    assert b.index('if not _line.get("withheld_gbp"):') < b.index("_pp.mark_withheld(pe)")


def test_the_withheld_lines_list_does_not_claim_a_priced_line():
    """Same fact, second home. `withheld_price_lines` is read by checks that report what the
    sheet is missing; a line carrying a figure is not missing."""
    assert '_code and not _line.get("withheld_gbp")' in SRC


def test_the_flag_says_it_was_priced_rather_than_refused():
    """An estimator reading "KEPT OFF the price column" against a column with a number in it
    is being told two different things about one cell."""
    assert "KEPT OFF the price" not in SRC
    assert "ESTIMATOR TO CONFIRM" in SRC
    assert "NOT A FIRM PRICE until a catalogue or" in SRC


def test_the_firmness_gate_is_untouched():
    """The number appears AND the job still cannot go out as a quote. Those are two separate
    statements and this change only ever moved the first."""
    inv = open(os.path.join(os.path.dirname(__file__), "..", "src", "invariants.py"),
               encoding="utf-8").read()
    assert "price_not_reproducible" in inv
    at = inv.index("price_not_reproducible")
    assert "BLOCKING" in inv[at:at + 400], (
        "an AI figure now reaches the total, so the check that stops it being called firm is "
        "the only thing keeping it out of a quote")
