r"""
test_the_powder_line_says_where_its_kilos_came_from.py

11650 has NO WIRE. The Wire block is empty, wb_populate reported "0 wire/bar", and the
powder flag said:

    POWDER computed from WIRE geometry: 0.00000 m2 of coated surface (pi x dia x length)
    x 0.2 kg/m2 = 0.08314 kg @ GBP 9.73/kg

Nought times a fifth is not 0.08314. The KILOS were right -- 0.08314 is _powder_kg_total,
the seven coated SHEET parts at 0.4157 m2 -- but the sentence reported _wire_powder_area_m2
and _wire_powder_kg, which are a CONTRIBUTOR to that total and were both zero here. So the
one line explaining a cost on the bill of materials could not be checked against the number
it explained, on any job whose powder does not come from wire.

That is the general fault and it is what this guards: THE LINE THAT EXPLAINS A BOOKED NUMBER
MUST REPORT THAT NUMBER. Not a related one, not an input to it. An estimator asked where
0.08314 kg came from would have been sent to a geometry the job does not contain, and the
answer -- the coated sheet area -- was never printed anywhere.

Structural rather than behavioural: the branch sits deep inside populate_workbook, which
needs a template, a summary and an Excel round trip. What can be checked without any of that
is the thing that was actually wrong -- that the quantity assigned and the quantity reported
are the same variable.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WB_POPULATE = ROOT / "src" / "wb_populate.py"


def _consumable_branch() -> ast.If:
    """The branch that costs a withheld consumable line once its quantity becomes knowable."""
    tree = ast.parse(WB_POPULATE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        src = ast.unparse(node.test)
        if "_is_consumable_line" in src and "_cat_rate" in src:
            return node
    pytest.fail("the consumable-pricing branch is no longer recognisable in wb_populate")


def _assigned_qty(branch: ast.If) -> str:
    for stmt in branch.body:
        if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "qty" for t in stmt.targets):
            return ast.unparse(stmt.value)
    pytest.fail("the branch no longer assigns a quantity, so there is nothing to explain")


def _flag_text(branch: ast.If) -> str:
    """Every string the branch passes to _flag, joined. ast.unparse keeps f-string bodies."""
    out = []
    for node in ast.walk(branch):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "_flag":
            out.append(ast.unparse(node))
    assert out, "the branch prices a line and explains nothing"
    return "\n".join(out)


def test_the_message_reports_the_quantity_it_booked():
    branch = _consumable_branch()
    qty, said = _assigned_qty(branch), _flag_text(branch)
    assert qty in said, (
        f"the branch books qty={qty} and its explanation never mentions it. That is how "
        f"11650 came to print '0.00000 m2 ... = 0.08314 kg': the sentence reported the WIRE "
        f"contribution while the sheet booked the TOTAL, so the number on the bill of "
        f"materials could not be traced to the line explaining it.")


def test_wire_is_named_as_a_contributor_not_as_the_source():
    """Wire adds coated area the sheet-only calculator cannot see. It is one input to the
    total, and on most jobs it is zero -- so a message that presents it as the origin of the
    kilos is wrong on every job that has no wire, which is most of them."""
    said = _flag_text(_consumable_branch())
    assert "computed from WIRE geometry" not in said, (
        "the flag still presents wire as where the powder came from")


def test_the_wire_share_is_only_mentioned_when_there_is_wire():
    """Printing '0.00000 m2 is wire' on a job with no wire is noise at best, and on 11650 it
    was read as the derivation of a number it had nothing to do with."""
    body = ast.unparse(ast.parse(WB_POPULATE.read_text(encoding="utf-8")))
    assert "_wire_powder_area_m2 > 0" in body, (
        "nothing guards the wire clause, so it prints on jobs with no wire")


def test_the_rate_caveat_survives():
    """The coverage rate is the template's 0.2 kg/m2 = 100% transfer efficiency, which
    nothing achieves; Tim's own sheets imply 2.7x-4.9x even on flat parts. This line
    UNDER-READS, and tidying the message must not quietly drop the warning that says so."""
    said = _flag_text(_consumable_branch())
    assert "UNDER-READS" in said and "POWDER_KG_PER_M2" in said, (
        "the under-reading caveat was lost while rewording the flag")
