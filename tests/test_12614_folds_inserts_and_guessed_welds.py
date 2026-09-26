"""12614-01-GA at 132 off (26 Sep): three route faults on the Tesco deep header.

D-255  the fascia's DXF bend layer carried 6 bends where its sheet prints 10 callouts and the
       model has 10; the lock plate's DXF carried none against 2 and 2. Two statements that
       agree outrank one export that falls short. The model alone still never does.
D-256  two M5 thin-sheet nutserts had no insertion while the PEM studs beside them did.
D-258  the header case was charged 8 joints of weld and dress (£48.98 a unit) on the
       extract's inference alone. It stays charged — inference is priced — and the review
       list asks whether it is welded, with the money it carries.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import fold_count as fc  # noqa: E402
import route_compiler as rc  # noqa: E402


# ── D-255 ─────────────────────────────────────────────────────────────────────────────────

def test_callouts_agreeing_with_the_model_outrank_a_short_bend_layer():
    r = fc.press_brake_folds({"bend_count_dxf": 6, "drawing_bend_callouts": 10,
                              "solidworks_bend_features": 10})
    assert r["count"] == 10 and r["source"] == fc.CALLOUTS_AND_MODEL and r["measured"]


def test_a_flat_bend_layer_does_not_hide_two_stated_bends():
    r = fc.press_brake_folds({"bend_count_dxf": 0, "drawing_bend_callouts": 2,
                              "solidworks_bend_features": 2})
    assert r["count"] == 2


def test_the_model_alone_still_never_overrides_the_flat_pattern():
    """401912-02: three CAD features, one fold."""
    assert fc.press_brake_folds({"bend_count_dxf": 1, "solidworks_bend_features": 3})["count"] == 1
    assert fc.press_brake_folds({"bend_count_dxf": 1, "drawing_bend_callouts": 3,
                                 "solidworks_bend_features": 2})["count"] == 1


# ── D-256 / D-257 through the compiler ───────────────────────────────────────────────────

def _compile(routes, extra_parts=()):
    parts = [
        {"part_number": "CASE", "description": "HEADER CASE FABRICATION"},
        {"part_number": "P1", "description": "TOP PANEL", "normalized_material": "MILD_STEEL"},
        {"part_number": "P2", "description": "BOTTOM PANEL", "normalized_material": "MILD_STEEL"},
        {"part_number": "FIXING320", "description": "M6x15mm THREADED PEM STUD",
         "page_roles": ["bought_in"], "quantity": 4},
        {"part_number": "FIXING48", "description": "M5 THINSHEET THREADED INSERT",
         "page_roles": ["bought_in"], "quantity": 2},
    ] + list(extra_parts)
    extract = {
        "top_assembly": {"part_number": "CASE"},
        "assemblies": [{"part_number": "CASE", "children": [
            {"part_number": "P1", "qty": 1}, {"part_number": "P2", "qty": 1},
            {"part_number": "FIXING320", "qty": 4}, {"part_number": "FIXING48", "qty": 2}]}],
        "routes": routes,
    }
    graph = rc.compile_job_route(parts, extract)
    return [d if isinstance(d, dict) else d.__dict__ for d in (graph.get("decisions") or [])]


def _by_op(decisions, op):
    return [d for d in decisions if d.get("operation") == op]


def test_the_nutserts_are_fitted_alongside_the_pem_studs():
    ds = _compile([{"operation": "hardware_insertion", "scope": "assembly",
                    "part_numbers": ["FIXING320"]}])
    ins = [d for d in _by_op(ds, "hardware_insertion") if d.get("status") == "required"]
    assert ins and any("FIXING48" in (d.get("participants") or []) for d in ins)


def test_an_inferred_weld_is_charged():
    ds = _compile([{"operation": "welding", "scope": "assembly", "inferred": True,
                    "part_numbers": ["P1", "P2"],
                    "notes": "case shown as single fabricated unit on page 4"}])
    assert any(d.get("status") == "required" for d in _by_op(ds, "welding"))


def test_an_inferred_weld_is_put_to_the_estimator_with_its_money():
    import costed_facts as cf
    source = {
        "estimate_summary": {
            "canonical_route_shadow": {"decisions": [
                {"operation": "welding", "status": "required", "source": "inference",
                 "target_id": "12614-01-101", "evidence": "",
                 "reason": "case shown as single fabricated unit on page 4"}]},
            "final_estimate": {"labour_rows": [
                {"operation": "Weld (CO2)", "total_value_gbp": 33.58, "workbook_row": 112},
                {"operation": "Dress Welds", "total_value_gbp": 15.41, "workbook_row": 113}]},
            "workbook_labour": {"rows": [
                {"workbook_row": 112, "engine_operations": ["welding"],
                 "part_numbers": ["12614-01-101"]},
                {"workbook_row": 113, "engine_operations": ["dress_welds"],
                 "part_numbers": ["12614-01-101"]}]},
        },
        "manufacturing_writeup": {"parts": []},
    }
    job = cf.costed_job(source)
    hits = [d for d in job["decisions_required"] if "inferred, not drawn" in str(d.get("issue"))]
    assert len(hits) == 1
    assert hits[0]["gbp_at_stake"] == 48.99 or abs(hits[0]["gbp_at_stake"] - 48.99) < 0.01


def test_a_weld_the_drawing_states_is_not_asked():
    import costed_facts as cf
    source = {"estimate_summary": {"canonical_route_shadow": {"decisions": [
        {"operation": "welding", "status": "required", "source": "inference",
         "target_id": "A", "evidence": "WELD AND DRESS"}]}},
        "manufacturing_writeup": {"parts": []}}
    assert not [d for d in cf.costed_job(source)["decisions_required"]
                if "inferred, not drawn" in str(d.get("issue"))]


# ── D-259: the drawing must be read in full, and a short DXF zero is not a measurement ──

def test_the_best_text_layer_counts_the_callouts():
    """pdfplumber drops rotated callouts (12614-01 fascia: 6 of 10); another layer keeps them."""
    import drawing_job_merge as djm
    short = "DOWN 90° R 1 " * 6
    full = "DOWN 90° R 1 " * 10
    parts = [{"part_number": "01M", "pages": [5]}]
    djm.stamp_drawing_bend_callouts(parts, {"pages": [
        {"page_number": 5, "pdfplumber_text": short, "pypdf_text": full}]})
    assert parts[0]["drawing_bend_callouts"] == 10


def test_a_page_read_twice_is_not_counted_twice():
    import drawing_job_merge as djm
    t = "UP 90° R 1 DOWN 90° R 1"
    parts = [{"part_number": "X", "pages": [1]}]
    djm.stamp_drawing_bend_callouts(parts, {"pages": [
        {"page_number": 1, "pdfplumber_text": t, "normalized_text": t}]})
    assert parts[0]["drawing_bend_callouts"] == 2


def test_the_model_confirms_the_callouts_it_does_not_supply_them():
    r = fc.press_brake_folds({"bend_count_dxf": 6, "drawing_bend_callouts": 11,
                              "solidworks_bend_features": 12})
    assert r["count"] == 11


def test_a_dxf_zero_does_not_rule_out_folds_the_drawing_and_model_agree_on():
    import estimator
    part = {"manufacturing_features": {"bend_count": 0, "bend_count_source": "dxf"},
            "drawing_bend_callouts": 2, "solidworks_bend_features": 2}
    assert estimator._model_measured_zero_bends(part) is False
    part2 = {"manufacturing_features": {"bend_count": 0, "bend_count_source": "dxf"}}
    assert estimator._model_measured_zero_bends(part2) is True


def test_a_dxf_zero_ruling_is_lifted_when_the_drawing_and_model_say_it_folds():
    import drawing_job_merge as djm
    part = {"part_number": "14M", "pages": [16], "solidworks_bend_features": 2,
            "operations_ruled_out": {"folding": "DXF flat pattern measured 0 bend lines — "
                                                "the part does not fold"}}
    djm.stamp_drawing_bend_callouts([part], {"pages": [
        {"page_number": 16, "pdfplumber_text": "DOWN 49.4° R 1.76 DOWN 40.6° R 1.76"}]})
    assert "folding" not in part["operations_ruled_out"]
    assert any("folding reinstated" in f for f in part["review_flags"])


def test_a_dxf_zero_ruling_stands_without_the_model():
    import drawing_job_merge as djm
    part = {"part_number": "Z", "pages": [1],
            "operations_ruled_out": {"folding": "DXF flat pattern measured 0 bend lines"}}
    djm.stamp_drawing_bend_callouts([part], {"pages": [
        {"page_number": 1, "pdfplumber_text": "DOWN 90° R 1"}]})
    assert "folding" in part["operations_ruled_out"]


# ── D-260: a mirrored hand bends like the hand it mirrors ──────────────────────────────

def test_a_handed_part_with_no_sheet_takes_the_bases_callouts_and_features():
    import drawing_job_merge as djm
    base = {"part_number": "12614-01-06M", "pages": [10], "solidworks_bend_features": 12}
    hand = {"part_number": "12614-01-06M-H", "pages": []}
    djm.stamp_drawing_bend_callouts([base, hand], {"pages": [
        {"page_number": 10, "pdfplumber_text": "DOWN 90° R 1 " * 11}]})
    assert base["drawing_bend_callouts"] == 11
    assert hand["drawing_bend_callouts"] == 11 and hand["solidworks_bend_features"] == 12
    r = fc.press_brake_folds(dict(hand, bend_count_dxf=6))
    assert r["count"] == 11


def test_a_hand_with_its_own_sheet_keeps_its_own_count():
    import drawing_job_merge as djm
    base = {"part_number": "X-01M", "pages": [1]}
    hand = {"part_number": "X-01M-H", "pages": [2]}
    djm.stamp_drawing_bend_callouts([base, hand], {"pages": [
        {"page_number": 1, "pdfplumber_text": "DOWN 90° R 1 " * 4},
        {"page_number": 2, "pdfplumber_text": "DOWN 90° R 1 " * 3}]})
    assert hand["drawing_bend_callouts"] == 3
