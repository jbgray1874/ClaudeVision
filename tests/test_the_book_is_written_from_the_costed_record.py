r"""The engine got it right and the workbook wrote something else.

The 11908-21 book of 17 September 2026, 16:39, on build 3629222 — the pulled code, a
restarted runner, every fix in the process. The saved record is correct throughout: the
board is promoted to MFMDF, the laminate is ruled out of the route with the reason recorded
on all three trays, the edging carries Tony's confirmed five metres at a researched rate,
delivery is his deliberate exclusion.

The workbook carried almost none of it:

    Glue  laminating  9 off  40/hr  set-up 30    £18.43     the ruling was recorded and
                                                            the row was written anyway
    Bench Work Joinery      30/hr                            Tony measured 2/hr
    Packing Joinery         75/hr                            Tony measured 20/hr
    every labour row        "9mm MDF"                        it costed MFMDF
    edge banding            no labour row                    the tape was bought and
                                                            nobody was paid to apply it

Four separate hand-offs, and each fails in the same way: a fact is established in one place
and the place that spends the money asks a different question.

    THE RULING            the canonical grader never asked whether an operation was ruled
                          out. The legacy grader beside it has always asked — its own
                          comment calls it "the last gate before a labour row, and the one
                          that spends money" — and the decision graph is compiled before
                          the ruling exists, so compiling is too early and rendering is the
                          only moment that can catch it. D-102, one road over.

    THE SCOPE             `_faced_board_job` searched `bom_parts`, and a board panel is
                          never in `bom_parts` — the router sends it to `board_parts`,
                          which is what the Other Sheet block is for. The one list that
                          could not hold a faced board was the only list consulted, so the
                          scoped pilot has never applied to anything.

    THE NAME              every row read "9mm MDF" while the money was MFMDF's, because
                          `normalized_material` is the drawing's word and nothing showed
                          the family the price was for. Three readers of that book
                          concluded the engine was costing raw MDF when it was not.

    THE WORK              a confirmed banded length buys metres of ABS and also says
                          somebody runs the bander. Only the material half was wired, and
                          the labour rule that existed timed the PERIMETER — the default
                          D-104 outlawed for the material and left standing beside it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator  # noqa: E402
import wb_populate  # noqa: E402


# ── 1 · a ruling is the last gate before a labour row, on the canonical road too ─────

def _decision(operation, decision_id, part="11908-21-01J"):
    return {"decision_id": decision_id, "operation": operation, "status": "required",
            "target_id": part, "participants": [part], "scope": "part"}


def _groups(decisions, part):
    summary = {"canonical_route_shadow": {
        "nodes": [{"part_number": part["part_number"], "qty_per_unit": 1}],
        "decisions": decisions},
        "parts": [dict(part)]}
    return wb_populate.canonical_labour_groups(summary, [dict(part)], 1)


_TRAY = {"part_number": "11908-21-01J", "description": "SUNGLASSES TRAY - LRG - BASE",
         "normalized_material": "MDF", "normalized_thickness_mm": 9.0,
         "blank_length_mm": 390.0, "blank_width_mm": 390.0, "quantity": 1,
         "material_estimate": {"material": "MDF", "thickness_mm": 9.0,
                               "costing_material_family": "MFMDF"},
         "labour_estimate": {"costs_gbp": {"laminating": 18.43, "cnc_routing": 1.0}}}


def test_a_ruled_out_operation_gets_no_labour_row():
    """£18.43 of glue on a board whose facing is in the sheet price."""
    part = dict(_TRAY, operations_ruled_out={
        "laminating": "laminating removed from the route: this board is bought PRE-FACED"})
    groups = _groups([_decision("laminating", "d-glue")], part)
    assert not any(str(g.get("wb_op") or "").lower() in ("glue", "laminating")
                   for g in groups.values()), groups


def test_an_operation_nobody_ruled_out_is_untouched():
    """The control. The gate cancels what a person or a measurement answered, and nothing
    else — a grader that drops rows on its own initiative is worse than one that adds them."""
    groups = _groups([_decision("cnc_routing", "d-cnc")], dict(_TRAY))
    assert any("CNC" in str(g.get("wb_op") or "").upper() for g in groups.values())


def test_a_ruling_on_one_part_does_not_cancel_a_shared_row():
    """Two parts on one setup, one of them ruled out: the work is still being done for the
    other, and the row stays."""
    other = dict(_TRAY, part_number="11908-21-02J")
    dec = {"decision_id": "d-shared", "operation": "cnc_routing", "status": "required",
           "target_id": "11908-21-01J",
           "participants": ["11908-21-01J", "11908-21-02J"], "scope": "part"}
    summary = {"canonical_route_shadow": {
        "nodes": [{"part_number": "11908-21-01J", "qty_per_unit": 1},
                  {"part_number": "11908-21-02J", "qty_per_unit": 1}],
        "decisions": [dec]},
        "parts": [dict(_TRAY, operations_ruled_out={"cnc_routing": "not on this one"}),
                  other]}
    groups = wb_populate.canonical_labour_groups(
        summary, [dict(_TRAY, operations_ruled_out={"cnc_routing": "not on this one"}),
                  other], 1)
    assert any("CNC" in str(g.get("wb_op") or "").upper() for g in groups.values())


# ── 2 · the row says which board the money was for ──────────────────────────────────

def test_the_row_names_the_family_that_was_costed():
    """"9mm MDF" on a row costed as MFMDF is how three readers concluded the engine was
    still pricing raw board when it was not."""
    groups = _groups([_decision("cnc_routing", "d-cnc")], dict(_TRAY))
    said = " ".join(str(g.get("material") or "") for g in groups.values()).upper()
    assert "MFMDF" in said, said


def test_a_plain_board_still_reads_as_itself():
    part = dict(_TRAY, material_estimate={"material": "MDF", "thickness_mm": 9.0})
    groups = _groups([_decision("cnc_routing", "d-cnc")], part)
    said = " ".join(str(g.get("material") or "") for g in groups.values()).upper()
    assert "MDF" in said and "MFMDF" not in said


# ── 3 · the scoped rates are asked of the list the board is actually in ─────────────

def test_the_scope_test_reads_the_board_parts():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "wb_populate.py"
           ).read_text(encoding="utf-8")
    start = src.index("_faced_board_job = any(")
    block = src[start:start + 700]
    assert "list(board_parts or [])" in block, (
        "the faced-board scope is still asked only of bom_parts, which is the one list a "
        "board panel is never in")


# ── 4 · the bander is timed on the edges that are banded ────────────────────────────

def _timed(part):
    return estimator.estimate_process_times(part, quantity=1)


def test_a_confirmed_length_times_the_edge_banding():
    """Tony's five metres, doing the work it describes rather than only buying the tape."""
    part = dict(_TRAY, textual_operations=["edge_banding"],
                _confirmed_banded_mm=5000.0, _confirmed_banded_by="Tony Ford")
    out = _timed(part)
    run = (out.get("run_times_min_per_unit") or {}).get("edge_banding")
    assert run, out.get("run_times_min_per_unit")
    # 5000 mm at the configured rate — and unmistakably more than the 1.56 m perimeter.
    perimeter_part = dict(_TRAY, textual_operations=["edge_banding"])
    assert run > (_timed(perimeter_part).get("run_times_min_per_unit") or {}).get(
        "edge_banding", 0)


def test_the_perimeter_is_used_only_as_a_named_ceiling():
    """Where nothing establishes a length the bander is still running and the work is
    still real — but the sheet must not present a ceiling as a measurement."""
    part = dict(_TRAY, textual_operations=["edge_banding"])
    _timed(part)
    assert any("TIMED ON THE PERIMETER" in str(f) for f in part.get("review_flags", [])), \
        part.get("review_flags")


def test_a_measured_length_says_what_it_was_measured_from():
    part = dict(_TRAY, textual_operations=["edge_banding"],
                description="TRAY, ABS EDGE BANDED ALL ROUND")
    _timed(part)
    assert any("not the perimeter" in str(f) for f in part.get("review_flags", []))


def test_a_part_with_no_edge_banding_gains_no_row():
    """The control on this half: the operation still has to be on the route."""
    out = _timed(dict(_TRAY, textual_operations=["cnc_routing"],
                      _confirmed_banded_mm=5000.0))
    assert "edge_banding" not in (out.get("run_times_min_per_unit") or {})


# ── and the ruling reaches the parts before anything is costed ──────────────────────

def test_a_confirmed_length_routes_the_bander():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "file_scan.py"
           ).read_text(encoding="utf-8")
    assert '_tgt["_confirmed_banded_mm"] = float(_bm_unit) * 1000.0' in src
    assert '_tgt.setdefault("textual_operations", []).append("edge_banding")' in src, (
        "the metres are bought and nobody is routed to apply them")
    assert "the ruling did nothing" in src, (
        "a banded length with nowhere to land must not be a silent no-op")
