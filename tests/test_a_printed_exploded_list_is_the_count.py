"""A kit's printed exploded list is the product's count — not a second path to add up.

11650-06, 23 Sep 2026 (16:49 run): the kit GA's sheet 2 prints the whole kit exploded —
slider 12, M4 PEM 18, M4 knob 32, arm 3 + handed 3. The roll-up re-multiplied the tree beside
it: sliders 24, PEM 30, knobs 20, plain arm 0. Review: "Prefer the printed kit sheet over
re-multiplying 03-GA x sliders."
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                           # noqa: E402

KIT, S1, S2 = "11650-06-GA", "KIT.PDF#0", "KIT.PDF#1"


def _kit():
    parts = [{"part_number": KIT, "description": "COFFRET HOSPITAL KIT", "quantity": 1,
              "is_assembly_parent": True}]
    for pn in ("11650-03-GA", "11650-03-SA01", "11650-02-SA02"):
        parts.append({"part_number": pn, "quantity": 1, "is_sub_assembly": True})
    for pn, d in (("11650-03-01M", "SLIDER"), ("11650-03-02M", "ARM"),
                  ("MIRROR11650-03-02M", "HANDED ARM BRACKET"), ("11650-02-03M", "RSB PLATE"),
                  ("FIXING", "M4x12mm THREADED PEM STUD"),
                  ("FIXINGTBC", "M4 KNURLED KNOB"), ("FIXING1659", "M6 KNURLED KNOB")):
        parts.append({"part_number": pn, "description": d, "quantity": 1})
    # The tree as the 16:49 run built it — including the 03-GA -> slider x6 edge and the
    # handed bracket standing where the plain arm should.
    extract = {"assemblies": [
        {"part_number": KIT, "children": [
            {"part_number": "11650-03-GA", "qty": 3}, {"part_number": "11650-02-SA02", "qty": 3},
            {"part_number": "11650-03-01M", "qty": 6}, {"part_number": "FIXINGTBC", "qty": 20},
            {"part_number": "FIXING1659", "qty": 20}]},
        {"part_number": "11650-03-GA", "children": [
            {"part_number": "11650-03-SA01", "qty": 1}, {"part_number": "11650-03-01M", "qty": 6},
            {"part_number": "FIXINGTBC", "qty": 2}]},
        {"part_number": "11650-03-SA01", "children": [
            {"part_number": "MIRROR11650-03-02M", "qty": 1}, {"part_number": "FIXING", "qty": 2}]},
        {"part_number": "11650-02-SA02", "children": [
            {"part_number": "11650-02-03M", "qty": 1}, {"part_number": "FIXING", "qty": 2}]},
    ]}

    def row(pn, q, sheet):
        return {"part_number": pn, "quantity": q, "bom_parent": KIT, "bom_sheet": sheet}
    rows = [row("11650-03-GA", 3, S1), row("11650-02-SA02", 3, S1), row("11650-03-01M", 6, S1),
            row("FIXINGTBC", 20, S1), row("FIXING1659", 20, S1),
            # sheet 2 — the exploded list
            row("11650-03-02M", 3, S2), row("FIXING", 18, S2), row("11650-03-01M", 12, S2),
            row("FIXINGTBC", 32, S2), row("MIRROR11650-03-02M", 3, S2),
            row("11650-02-03M", 3, S2), row("FIXING1659", 20, S2)]
    return parts, extract, rows


def _graph():
    parts, extract, rows = _kit()
    return rc.build_part_graph(parts, extract, rows, [KIT], declared_product=KIT)


def test_the_printed_totals_are_costed():
    q = _graph()["quantities"]
    assert q["11650-03-01M"] == 12, q          # was 24
    assert q["FIXING"] == 18, q                # was 30
    assert q["FIXINGTBC"] == 32, q             # was 20
    assert q["MIRROR11650-03-02M"] == 3 and q["11650-02-03M"] == 3 and q["FIXING1659"] == 20


def test_the_plain_arm_is_on_the_product():
    g = _graph()
    assert g["quantities"].get("11650-03-02M") == 3, g["quantities"]
    assert not any(i.get("code") == "not_linked_to_the_product" and
                   "11650-03-02M" in i.get("identities", []) for i in g["issues"])


def test_the_disagreement_stays_on_the_line():
    g = _graph()
    node = next(n for n in g["nodes"] if n.part_number == "11650-03-01M")
    assert any("printed total on KIT.PDF#1: 12" in t and "roll-up (24)" in t
               for t in node.qty_trail), node.qty_trail
    assert "printed exploded list says 12" in node.qty_note


def test_the_kits_own_bom_sheet_is_not_an_exploded_list():
    """Sheet 1 lists assemblies (03-GA, 02-SA02); it stays the BOM it is."""
    parts, extract, rows = _kit()
    rows = [r for r in rows if r["bom_sheet"] == S1]
    q = rc.build_part_graph(parts, extract, rows, [KIT], declared_product=KIT)["quantities"]
    assert q["11650-03-GA"] == 3 and q["11650-02-SA02"] == 3


def test_an_ordinary_ga_table_with_one_shared_fastener_is_untouched():
    """A GA listing a sub-assembly and a loose screw also used inside it is not exploded."""
    parts = [{"part_number": "GA", "quantity": 1, "is_assembly_parent": True},
             {"part_number": "SA", "quantity": 1, "is_sub_assembly": True},
             {"part_number": "SCREW", "quantity": 1}, {"part_number": "PANEL", "quantity": 1},
             {"part_number": "FOOT", "quantity": 1}]
    extract = {"assemblies": [{"part_number": "SA", "children": [
        {"part_number": "SCREW", "qty": 4}]}]}
    rows = [{"part_number": p, "quantity": q, "bom_parent": "GA", "bom_sheet": "GA#0"}
            for p, q in (("SA", 2), ("SCREW", 4), ("PANEL", 1), ("FOOT", 4))]
    q = rc.build_part_graph(parts, extract, rows, ["GA"], declared_product="GA")["quantities"]
    # Exactly as before this rule (the loose row is refused beside the extract's placement —
    # an existing, separate rule): the table is not an exploded list, so nothing changes.
    assert q["SCREW"] == 8 and q["SA"] == 2 and q["FOOT"] == 4, q


def test_a_printed_part_claimed_by_an_owner_the_kit_never_reaches_is_still_linked():
    """The 16:49 run's plain arm: its only owner was one the kit never reached, so it was
    'not linked'. The kit's own printed list says it is in there."""
    parts, extract, rows = _kit()
    parts.append({"part_number": "MIRROR11650-03-GA", "quantity": 1, "is_sub_assembly": True})
    extract["assemblies"].append({"part_number": "MIRROR11650-03-GA", "children": [
        {"part_number": "11650-03-02M", "qty": 1}]})
    g = rc.build_part_graph(parts, extract, rows, [KIT], declared_product=KIT)
    assert g["quantities"].get("11650-03-02M") == 3, g["quantities"]
