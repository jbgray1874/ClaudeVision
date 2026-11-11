"""Four surfaces agree on what the read's findings are (SCRUM-136, step 3).

test_four_surfaces_say_the_same_thing proves the money, the gaps, the decisions, the finish and
the release agree across the workbook, the e-mail, the report and the quote. It runs on a
drawing read, which has no read ledger, so it cannot see the defect the HPP 15:47 book had: a
Roll row charging £23.74 while the report said "R1.op.rolling ... no calculated row charges it".
A charged row called uncharged is a finding that is false on its face, and every internal
surface that repeats it repeats a mistake.

So this runs one saved run with a read ledger through the same pipeline a run does (the ledger
audit, the invariants, then the four writers) and reads all four outputs:

  * a rolled part with a Roll row is called uncharged on no surface;
  * the same part with no Roll row is flagged on every internal surface, and the customer
    quote names none of it;
  * the read items each internal surface says are unresolved are the same set;
  * a held engine allowance is named alike on every internal surface.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

openpyxl = pytest.importorskip("openpyxl", reason="the e-mail and the explanation read a workbook")

import client_quote_html as q  # noqa: E402
import estimate_explained as ee  # noqa: E402
import invariants  # noqa: E402
import job_report_html as jr  # noqa: E402
import read_charge_contract as rcc  # noqa: E402
from test_a_rolled_part_is_charged_by_the_roll_row import B, _book, _rolled_bracket, _with_row  # noqa: E402

INTERNAL = ("report", "email", "explanation")
ROLLING_UNCHARGED = re.compile(r"R2\.op\.rolling[^;]{0,80}no calculated row charges it")
ITEM_ID = re.compile(r"\b(R\d+(?:\.(?:op\.[a-z_]+|joint|quantity|material|size|cutout\d+))?"
                     r"|U\.op\.[a-z_]+|S\.[a-z_]+|NV\d+)\b")


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _surfaces(summary, tmp: Path):
    """One saved run, as the engine finishes it, read by all four writers."""
    summary["read_charge_result"] = rcc.audit(summary)
    summary.setdefault("job_number", "1234567")
    summary.setdefault("job_output_stem", "1234567")
    invariants.check_job(summary, write_back=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["D6"] = 1
    ws["C9"] = "Bill of Materials (Per Unit)"
    ws["H9"] = "Part code"
    xlsx = tmp / "1234567_20261031_010000.xlsx"
    wb.save(xlsx)
    jp = tmp / "1234567.json"
    jp.write_text(json.dumps(summary, default=str), encoding="utf-8")
    note = ee.covering_email(xlsx, jp, deliverables=["1234567.xlsx"])
    return {"report": _text(jr.build_report_html(summary)), "email": note["text"],
            "explanation": ee.build(xlsx, jp),
            "quote": _text(q.build_quote_html(summary, job_stem="1234567"))}


@pytest.fixture(scope="module")
def with_roll(tmp_path_factory):
    os.environ["SDI_QUANTITY_BREAKS"] = "1000"
    s = _with_row(_book(answer=_rolled_bracket()), 161, ["roll"], B, .77, 23.74, "Roll", 2)
    return _surfaces(s, tmp_path_factory.mktemp("roll"))


@pytest.fixture(scope="module")
def without_roll(tmp_path_factory):
    os.environ["SDI_QUANTITY_BREAKS"] = "1000"
    return _surfaces(_book(answer=_rolled_bracket()), tmp_path_factory.mktemp("noroll"))


def _unresolved_ids(text: str) -> set:
    """The read items a surface names in the unresolved-items finding."""
    out = set()
    # The finding ends at "Charge each", at a table cell's edge, or at the end of its line.
    for m in re.finditer(r"reach no charge and no ruling: (.*?)(?:Charge each|\||$)", text, re.M):
        out |= set(ITEM_ID.findall(m.group(1)))
    return out


def test_a_charged_roll_is_called_uncharged_on_no_surface(with_roll):
    for name, text in with_roll.items():
        assert not ROLLING_UNCHARGED.search(text), name


def test_a_missing_roll_is_flagged_on_every_internal_surface_and_not_the_quote(without_roll):
    for name in INTERNAL:
        assert ROLLING_UNCHARGED.search(without_roll[name]), name
    assert not ROLLING_UNCHARGED.search(without_roll["quote"]), "the customer copy names no gap"
    assert "no calculated row" not in without_roll["quote"]


@pytest.mark.parametrize("case", ["with_roll", "without_roll"])
def test_the_unresolved_read_items_are_one_set_on_every_internal_surface(case, request):
    surfaces = request.getfixturevalue(case)
    sets = {name: _unresolved_ids(surfaces[name]) for name in INTERNAL}
    assert all(sets.values()), f"every internal surface names the unresolved items: {sets}"
    first = sets["report"]
    assert all(s == first for s in sets.values()), sets
    assert ("R2.op.rolling" in first) == (case == "without_roll")


def test_a_held_allowance_is_named_alike_on_every_internal_surface(with_roll):
    said = "Engine allowance not confirmed for this job: brush before plate"
    for name in INTERNAL:
        assert said in with_roll[name], name
    assert said not in with_roll["quote"]
