"""An assembly written ASM or ASSY is an assembly, not something to buy (D-663).

12754-01-GA, 3 Nov 2026 19:16. The GA's parts list carries three of SDI's own drawings,
"PODIUM 1 ASM", "DRILL PODIUM 2 ASM" and "PODIUM 3 ASM", with no members listed in the pack.
The market gate refused a line whose description said WELDMENT or ASSEMBLY, and read the short
forms as nothing: all three went to market research and came back as finished, powder-coated
podiums at £175, £220 and £220, about 90% of the job's material. A part SDI makes has no market
price; the line is a named gap until its drawings or members are supplied.

A purchased item whose description says ASSY (a hinge assembly bought by its code) is still
bought: the short forms are read only on a line the bought-in rules do not claim.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from pricing_service import is_something_you_can_buy  # noqa: E402


@pytest.mark.parametrize("pn, desc", [
    ("12754-01-201", "PODIUM 1 ASM"),
    ("12754-01-202", "DRILL PODIUM 2 ASM"),
    ("12754-01-203", "PODIUM 3 ASM"),
    ("X-01-110", "BRACKET SUB-ASSY"),
    ("X-01-111", "FRAME ASSY"),
])
def test_an_assembly_in_short_form_is_not_priced_by_the_market(pn, desc):
    part = {"part_number": pn, "description": desc}
    assert is_something_you_can_buy(part) is False
    assert is_something_you_can_buy(part, structure_decides=False) is False, \
        "the researched-price rung asks with structure_decides=False"


@pytest.mark.parametrize("part", [
    {"part_number": "HG-01", "description": "HINGE ASSY", "page_roles": ["bought_in"]},
    {"part_number": "FIXING1010", "description": "RETRACTABLE TETHER | WITH CABLE LOOP"},
    {"part_number": "12754-01-09G", "description": "BACK WALL GRAPHIC"},
    {"part_number": "ASMX-1", "description": "PLASMA CUTTER CONSUMABLE"},
])
def test_a_purchase_or_a_word_that_only_contains_the_letters_is_still_buyable(part):
    assert is_something_you_can_buy(part) is True
