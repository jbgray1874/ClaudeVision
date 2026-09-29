"""A sheet's general notes are not a route for a screw, an MDF board or a sheet bracket.

12173 Card Spinner (M&S), run 29 Sep 2026. Every M&S sheet prints the same specification
block — "RESISTANCE WELDING WIRE TO WIRE ... POWDERCOATING 80-120 MICRON" — and the extract
transcribed it onto every part as operations. The pack had SolidWorks data, so the family
gate (drawings-only lane) never ran, and the book charged:

  * the purchased glides, screws and inserts (FIXING125, FIXING49, BI-SCREW ...) deburring,
    powder coating, welding and a Robomac wire-forming row each;
  * the MDF base welding, folding and wire forming;
  * the sheet brackets and tube frames a Robomac row each — some thirty rows in all.

The rules: a part the engine prices as bought in is not also fabricated here, in any lane;
board is not welded, folded or wire formed; wire forming needs wire.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                            # noqa: E402
from stock_form_rules import impossibility_reason                     # noqa: E402


def _d(target, op, scope="part"):
    return NS(target_id=target, operation=op, scope=scope, status=rc.REQUIRED, reason="",
              field_provenance={})


_RECORDS = {
    # The title block's MILD STEEL, inherited by a purchased glide.
    "FIXING125": {"part_number": "FIXING125", "normalized_material": "MILD STEEL",
                  "description": "M8 x Ø38mm DIA GLIDE; THREAD: 25mm"},
    "FIXING49": {"part_number": "FIXING49", "normalized_material": "MILD STEEL",
                 "description": "M6 THINSHEET THREADED INSERT"},
    # Priced as a purchased line: no material of its own, nothing measured.
    "WINDMILL: WSF45": {"part_number": "WINDMILL: WSF45", "normalized_material": "BOUGHT_IN",
                        "description": "TICKET STRIP (LENGTH: 335mm)"},
    "12173-03-01J": {"part_number": "12173-03-01J", "normalized_material": "MDF",
                     "description": "BASE"},
    # A code SHAPED like a catalogue code is not a purchase statement: this is a steel part.
    "MBY439": {"part_number": "MBY439", "normalized_material": "Steel, Mild 2mm",
               "description": "Prong"},
}


def test_a_purchased_part_is_not_fabricated_in_a_model_backed_pack():
    ds = [_d(p, op) for p in ("FIXING125", "FIXING49", "WINDMILL: WSF45")
          for op in ("deburring", "powder_coating", "welding", "wire_forming")]
    rc._family_gate(ds, {}, _RECORDS, positive_only=True)
    left = [(d.target_id, d.operation) for d in ds if d.status == rc.REQUIRED]
    assert left == [], left
    assert all("purchased" in d.reason for d in ds)


def test_the_raw_record_under_another_spelling_does_not_blind_the_gate():
    """The merged record is read first; the raw one had no description for the screw."""
    screw = _d("3.5-X16MM-PAN-HEAD", "powder_coating")
    rc._family_gate([screw], {"3.5-X16MM-PAN-HEAD": {}},
                    {"3.5-X16MM-PAN-HEAD": {"description":
                                            "Ø3.5x16mm PAN HEAD MULTI-PURPOSE SCREW"}},
                    positive_only=True)
    assert screw.status == rc.NOT_APPLICABLE


def test_mdf_is_not_welded_folded_or_wire_formed_but_keeps_its_own_route():
    ops = {op: _d("12173-03-01J", op) for op in
           ("welding", "folding", "wire_forming", "cnc_routing", "edge_banding", "wet_spray")}
    rc._family_gate(list(ops.values()), {}, _RECORDS, positive_only=True)
    for op in ("welding", "folding", "wire_forming"):
        assert ops[op].status == rc.NOT_APPLICABLE, op
    for op in ("cnc_routing", "edge_banding", "wet_spray"):
        assert ops[op].status == rc.REQUIRED, op


def test_a_steel_part_with_a_catalogue_shaped_code_keeps_its_route():
    ds = [_d("MBY439", "laser_cutting"), _d("MBY439", "folding")]
    rc._family_gate(ds, {}, _RECORDS, positive_only=True)
    assert all(d.status == rc.REQUIRED for d in ds)


def test_wire_forming_needs_wire():
    assert impossibility_reason("wire_forming", "sheet", "MILD STEEL")
    assert impossibility_reason("wire_forming", "tube", "MILD STEEL")
    assert impossibility_reason("wire_forming", "wire", "MILD STEEL") is None
    # Unknown stock is not evidence either way: nothing is taken away on a guess.
    assert impossibility_reason("wire_forming", "", "MILD STEEL") is None


def test_the_drawings_only_lane_is_unchanged():
    """positive_only is False there: the sheet-good branch still runs as before."""
    corian = _d("JAE823", "folding")
    rc._family_gate([corian], {"JAE823": {"normalized_material": "Corian,6mm",
                                          "description": "Overlay"}})
    assert corian.status == rc.NOT_APPLICABLE


def test_two_screw_sizes_are_two_items():
    """12173's spinner table: Ø3.5x16mm x8 and Ø3.5x12mm x16. They shared "3.5" and were
    read as one item — the x16 screw took the x12's 16, and the x12 was added again."""
    import estimator as E
    x12 = E._bought_in_token_set({"description": "Ø3.5x12mm PAN HEAD MULTI-PURPOSE SCREW"})
    x16 = E._bought_in_token_set({"description": "Ø3.5x16mm PAN HEAD MULTI-PURPOSE SCREW"})
    same = E._bought_in_token_set({"description": "3.5 x 12mm Pan Head Multi-Purpose Screw"})
    assert not E._bought_in_same_item(x12, x16)
    assert E._bought_in_same_item(x12, same)
