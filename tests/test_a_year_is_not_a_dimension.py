r"""
test_a_year_is_not_a_dimension.py

"largest panel 2026 x 1144mm" on a gravity feeder whose biggest part is 1145mm. "2026 x 400mm"
on a 390mm sunglasses tray. The SAME number on two unrelated jobs is not a drawing — it is the
YEAR, printed on every title block, every revision line and every date stamp in the pack, and
2026 sits neatly inside the 50–3000mm band the last-resort dimension scan accepts.

The comment beside that scan already recorded it giving RISER "a garbage 2026x2026 square". It
was read as a one-off rather than as the rule it is.

IT IS NOT A SMALL ERROR. The phantom became the largest blank on the job, so it set the
SHIPPING ENVELOPE: packaging and delivery were asked of the market against a 2026mm panel and
came back at £25 and £12 a unit on a tray that fits in a carton — the two largest bought-in
lines on both jobs, and 64% of one unit price.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SRC = (ROOT / "src" / "document_builder.py").read_text(encoding="utf-8")


def _scan(text: str):
    """The shipped filter, executed — lifted from the module so the test cannot drift from it."""
    i = SRC.index("# A DATE IS NOT A DIMENSION.")
    block = SRC[i:SRC.index("reverse=True,", i)]
    strips = re.findall(r'_page_text = re\.sub\(\s*\n?\s*r?"([^"]+)"', block)
    assert len(strips) >= 2, "the date strippers are no longer where this test reads them"
    t = text
    for pat in strips:
        t = re.sub(pat, " ", t, flags=re.IGNORECASE)
    return sorted({float(v) for v in re.findall(r"\b(\d{3,4}(?:\.\d{1,2})?)\b", t)
                   if 50 <= float(v) <= 3000 and not (1990 <= float(v) <= 2099)}, reverse=True)


@pytest.mark.parametrize("name,text,expect", [
    ("iso date in a title block",
     "DRG 12349-02-69-03M REV A DATE 02/09/2026 SCALE 1:5  1144.5  357.9", [1144.5, 357.9]),
    ("a bare year beside a revision",
     "SUNGLASSES TRAY REV A 2026  390  390  135", [390.0, 135.0]),
    ("us date and a copyright line",
     "(C) 2026 SDI  09-03-2026  818  171", [818.0, 171.0]),
    ("a month name",
     "ISSUED SEP 2026   775  125", [775.0, 125.0]),
    ("dotted date",
     "03.09.2026  1250  525", [1250.0, 525.0]),
])
def test_the_scan_returns_the_part_and_not_the_date(name, text, expect):
    assert _scan(text)[:2] == expect


def test_the_number_that_started_this_cannot_come_back():
    assert 2026.0 not in _scan("REV A 2026 02/09/2026 (C) 2026  400  300")


def test_an_ordinary_drawing_is_unaffected():
    """The band removed is 1990–2099. Everything a display part actually measures is outside
    it, and this must not quietly start refusing real dimensions."""
    assert _scan("1250 525 400 390 171 818 145 23 1144.5")[:2] == [1250.0, 1144.5]


def test_the_cost_of_the_band_is_stated_where_it_is_paid():
    """A genuine 1990–2099mm part IS refused here. That is correct for a guess of last resort
    and must be written down, not discovered by somebody wondering where their panel went."""
    i = SRC.index("# A DATE IS NOT A DIMENSION.")
    block = SRC[i:i + 2200]
    assert "1990" in block and "last resort" in block.lower()


def test_dates_are_stripped_before_the_band_is_applied():
    """Stripping by shape removes the actual cause; the band is the backstop for a bare year
    in a form no pattern catches. Both, in that order."""
    i = SRC.index("# A DATE IS NOT A DIMENSION.")
    block = SRC[i:SRC.index("reverse=True,", i)]
    assert block.index("_page_text = re.sub(") < block.index("1990 <= float(v)")
