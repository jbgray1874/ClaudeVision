"""D-592: a hole or a cut read off a drawing's lines is a candidate, said and asked as one.

The review of D-591: a plausible bound does not validate a cutting profile; the outline is a
provisional allowance, not the contour; unknown holes must stay unknown, not become "no holes";
a page-read count must never become measured cutting or punching; the quote's worked example
needs evidence, not only the absence of a question. And the rules must hold on parts they did
not touch on 0351292: sections, blanks that arrive after the scan, perforated families, and a
measured flat whose holes are real.
"""
from __future__ import annotations

import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "diagnose"))
os.environ.setdefault("SDI_OFFLINE", "1")

import detail_page_geometry as g  # noqa: E402
import estimator as e  # noqa: E402


def _page(n, dn, *, weight=None, thk=None, cut=0.0, holes=0, cues=None):
    return {"page_number": n,
            "geometry_summary": {"estimated_cut_length_mm": cut, "estimated_hole_count": holes,
                                 "estimated_pierce_count": holes},
            "page_analysis": {"title_block": {"drawing_numbers": list(dn),
                                              "weights": [weight] if weight else [],
                                              "thicknesses_mm": list(thk or [])},
                              "feature_cues": dict(cues or {})}}


def _summary(*pages, rows=()):
    return {"pages": list(pages), "document_analysis": {"bom_rows": list(rows)}}


# ── a section is re-read from its own sheet too ────────────────────────────────────────────

def test_a_tube_takes_its_own_sheets_weight_not_its_assemblys():
    summary = _summary(_page(12, ["ASM-12", "TUBE-1"], weight="2.5KG", cut=9090.0),
                       _page(15, ["TUBE-1"], weight="1.4KG", cut=5100.0),
                       rows=[{"part_number": "TUBE-1", "bom_sheet": "p.pdf#11", "bom_parent": "ASM-12"}])
    tube = {"part_number": "TUBE-1", "description": "CROSS RAIL", "normalized_material": "MILD_STEEL",
            "pages": [12, 15], "weights": ["2.5KG", "1.4KG"],
            "section_stock": {"a": 50, "b": 20, "t": 2, "length_mm": 703},
            "geometry_rollup": {"estimated_cut_length_mm": 14190.0, "estimated_hole_count": 0}}
    assert g.revalidate_from_own_sheets([tube], summary) == ["TUBE-1"]
    assert g._stated_weight_kg(tube) == pytest.approx(1.4)
    assert tube["geometry_rollup"]["estimated_cut_length_mm"] == 5100.0


def test_a_bought_section_is_not_re_read():
    bought = {"part_number": "RHS-B", "pages": [15], "is_bought_in": True,
              "page_roles": ["bought_in"], "section_stock": {"a": 50, "b": 20, "t": 2}}
    assert g._made_here(bought) is False


# ── the gauge its own sheet states ─────────────────────────────────────────────────────────

def test_the_own_sheets_one_gauge_replaces_an_assembly_sheets():
    import source_precedence as sp
    summary = _summary(_page(3, ["ASM-3", "T-1"], thk=["5", "2", "3"]), _page(8, ["T-1"], thk=["2"]),
                       rows=[{"part_number": "T-1", "bom_sheet": "p.pdf#2", "bom_parent": "ASM-3"}])
    tab = {"part_number": "T-1", "normalized_material": "MILD_STEEL", "pages": [3, 8]}
    sp.apply_field(tab, "normalized_thickness_mm", 5.0, "drawing_deterministic")
    g.revalidate_from_own_sheets([tab], summary)
    assert tab["normalized_thickness_mm"] == 2.0
    assert sp.source_of(tab, "normalized_thickness_mm") == "own_sheet_title_block"


def test_two_gauges_on_its_own_sheet_decide_nothing():
    import source_precedence as sp
    summary = _summary(_page(2, ["S-1"], thk=["5", "3"]))
    strip = {"part_number": "S-1", "normalized_material": "STAINLESS_STEEL", "pages": [2]}
    sp.apply_field(strip, "normalized_thickness_mm", 5.0, "drawing_deterministic")
    g.revalidate_from_own_sheets([strip], summary)
    assert strip["normalized_thickness_mm"] == 5.0


def test_a_measured_gauge_is_not_displaced_by_a_sheet():
    import source_precedence as sp
    summary = _summary(_page(8, ["T-1"], thk=["2"]))
    tab = {"part_number": "T-1", "normalized_material": "MILD_STEEL", "pages": [8]}
    sp.apply_field(tab, "normalized_thickness_mm", 1.5, "solidworks_api")
    g.revalidate_from_own_sheets([tab], summary)
    assert tab["normalized_thickness_mm"] == 1.5


# ── a blank that arrives late is held to the same bound; unknown stays unknown ─────────────

def _late_tab():
    return {"part_number": "T-1", "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 2.0,
            "geometry_rollup": {"estimated_cut_length_mm": 2823.0, "estimated_hole_count": 10,
                                "estimated_pierce_count": 12},
            "normalized_geometry": {"cut_length_mm": 2823.0, "hole_count": 10},
            "manufacturing_features": {"cut_length_mm": 2823.0, "hole_count": 10}}


def test_a_blank_known_only_at_costing_still_bounds_the_cutting():
    tab = _late_tab()
    assert g.bound_cutting_to_blank(tab) == [], "no blank yet: nothing to hold it to"
    notes = g.bound_cutting_to_blank(tab, 30.0, 7.4)
    assert notes and tab["normalized_geometry"]["cut_length_mm"] == pytest.approx(74.8)


def test_unread_holes_are_unknown_not_zero_and_asked():
    tab = _late_tab()
    g.bound_cutting_to_blank(tab, 30.0, 7.4)
    for holder in ("normalized_geometry", "geometry_rollup", "manufacturing_features"):
        assert tab[holder]["hole_count" if holder != "geometry_rollup" else "estimated_hole_count"] is None
    assert tab["_internal_features_unread"] is True
    assert any("internal features unread" in str(q.get("issue"))
               for q in tab.get("manufacturing_questions") or [])
    assert g.machining_evidence(tab)["basis"] == "outline_only"


def _over(pn, length, width, *, src="drawing_deterministic", thk=None, weight=None, desc="BRACKET",
          cut=6546.0, holes=4):
    p = {"part_number": pn, "description": desc, "normalized_material": "MILD_STEEL",
         "blank_length_mm": length, "blank_width_mm": width, "blank_length_mm_source": src,
         "geometry_rollup": {"estimated_cut_length_mm": cut, "estimated_hole_count": holes},
         "normalized_geometry": {"cut_length_mm": cut, "hole_count": holes}}
    if thk:
        p["normalized_thickness_mm"] = thk
    if weight:
        p["weights"] = [weight]
    return p


def test_an_assemblys_outline_bounds_nothing():
    """401918's base panel: 8 kg costed on its assembly's 324 x 77 mm outline."""
    panel = _over("BP-1", 324.0, 77.0, src=g.ASSEMBLY_ALLOWANCE_SOURCE, cut=4958.0)
    assert g.bound_cutting_to_blank(panel) == []
    assert panel["normalized_geometry"]["cut_length_mm"] == 4958.0, "kept as read"
    assert panel["normalized_geometry"]["hole_count"] == 4
    assert "allowance" in panel["_cut_path_not_bounded"]
    assert any("more than its 324 x 77 blank holds" in str(q.get("issue"))
               for q in panel.get("manufacturing_questions") or [])


def test_a_blank_lighter_than_the_part_bounds_nothing():
    plate = _over("PL-1", 100.0, 50.0, thk=2.0, weight="8KG")
    assert g.bound_cutting_to_blank(plate) == []
    assert "less than the part cut from it" in plate["_cut_path_not_bounded"]
    assert plate["normalized_geometry"]["cut_length_mm"] == 6546.0


def test_a_punched_pattern_named_on_the_drawing_bounds_nothing():
    panel = _over("PP-1", 300.0, 200.0, desc="PERFORATED VENT PANEL", cut=9000.0, holes=600)
    assert g.bound_cutting_to_blank(panel) == []
    assert panel["normalized_geometry"]["hole_count"] == 600, "real machining kept"


def test_a_blank_heavier_than_the_part_is_held_at_the_ceiling_not_the_outline():
    """401918's bracket: 274 x 94.1 at 3 mm weighs 3x its stated 0.2 kg — it has cut-outs."""
    br = _over("BR-1", 274.0, 94.1, thk=3.0, weight="0.2KG")
    notes = g.bound_cutting_to_blank(br)
    assert notes and "material is cut out" in notes[0]
    assert br["normalized_geometry"]["cut_length_mm"] == pytest.approx(3 * 2 * (274.0 + 94.1), abs=0.1)
    assert br["normalized_geometry"]["hole_count"] == 4, "a count the blank can hold stays a candidate"
    ev = g.machining_evidence(br)
    assert ev["basis"] == g.CUT_OUT_ALLOWANCE and not ev["measured"]


def test_a_blank_its_weight_agrees_with_is_cut_as_its_outline_and_its_circles_are_unread():
    tab = _late_tab()
    tab["weights"] = ["0.003KG"]
    notes = g.bound_cutting_to_blank(tab, 30.0, 7.4)
    assert "agrees with the stated 0.003 kg" in notes[0]
    assert tab["normalized_geometry"]["cut_length_mm"] == pytest.approx(74.8)
    small = _over("SM-1", 200.0, 100.0, cut=9000.0, holes=3)
    g.bound_cutting_to_blank(small)
    assert small["normalized_geometry"]["hole_count"] is None, "the page's circles: unread, not 3"


def test_a_weld_is_not_timed_from_holes_that_are_unread():
    """0351292's end plate: 14 page circles booked 21 minutes of welding; unread, one joint."""
    import config
    plate = _over("EP-1", 60.0, 17.0, cut=2823.0, holes=14)
    plate.update(normalized_thickness_mm=3.0, quantity=1, textual_operations=["laser_cutting", "welding"])
    g.bound_cutting_to_blank(plate)
    assert plate["_internal_features_unread"] is True
    process = e.estimate_process_times(plate)
    per_joint = float(config.WELD_TIME_MODEL["weld_min_per_joint"])
    weld = process["run_times_min_per_unit"].get("welding")
    assert weld == pytest.approx(max(1.0, per_joint))
    assert any("WELD TIME FOR ONE JOINT" in f for f in plate["review_flags"])
    assert any(str(q.get("issue")).startswith("Welding of EP-1")
               for q in plate.get("manufacturing_questions") or [])


def test_a_weld_is_not_timed_from_a_pages_circles_but_is_from_measured_holes():
    """0351292's strip: 104 page circles booked 157 minutes of welding."""
    import config
    per_joint = float(config.WELD_TIME_MODEL["weld_min_per_joint"])
    strip = _panel(part_number="ST-1", description="STRIP",
                   textual_operations=["laser_cutting", "welding"])
    strip["geometry_rollup"].update(estimated_hole_count=104, estimated_pierce_count=104)
    weld = e.estimate_process_times(strip)["run_times_min_per_unit"]["welding"]
    assert weld == pytest.approx(max(1.0, per_joint))
    assert any("104 hole(s) that would time it are read off the drawing's lines" in f
               for f in strip["review_flags"])
    measured = _panel(part_number="ST-2", description="STRIP", dxf_augmented=True,
                      geometry_source="dxf_flat_pattern", blank_length_mm_source="dxf_flat_pattern",
                      textual_operations=["laser_cutting", "welding"])
    weld_m = e.estimate_process_times(measured)["run_times_min_per_unit"]["welding"]
    assert weld_m > per_joint, "measured holes keep the per-hole timing"
    assert not any("WELD TIME FOR ONE JOINT" in f for f in measured.get("review_flags") or [])


def test_a_few_page_circles_below_one_joint_keep_the_small_timer():
    import config
    per_joint = float(config.WELD_TIME_MODEL["weld_min_per_joint"])
    tab = _panel(part_number="TB-1", description="TAB", textual_operations=["welding"])
    tab["geometry_rollup"] = {"estimated_cut_length_mm": 200.0, "estimated_hole_count": 2,
                              "estimated_pierce_count": 2}
    tab["manufacturing_features"] = {"hole_count": 2, "cut_length_mm": 200.0}
    weld = e.estimate_process_times(tab)["run_times_min_per_unit"]["welding"]
    assert weld < per_joint
    assert not any("WELD TIME FOR ONE JOINT" in f for f in tab.get("review_flags") or [])


def test_the_estimator_does_not_ask_twice_about_cutting_kept_as_read():
    part = _panel(blank_length_mm_source=g.ASSEMBLY_ALLOWANCE_SOURCE)
    part["normalized_geometry"] = {"cut_length_mm": 40000.0, "hole_count": 40}
    g.bound_cutting_to_blank(part)
    e.estimate_process_times(part)
    cutting = [q for q in part.get("manufacturing_questions") or []
               if str(q.get("issue") or "").startswith("Cutting of P-1")]
    assert len(cutting) == 1


def test_the_estimator_bounds_on_the_blank_it_costed(monkeypatch):
    tab = _late_tab()
    g._write_blank(tab, 30.0, 7.4, g.PROVISIONAL_SOURCE)
    tab["_blank_provisional"] = {"basis": g.PROVISIONAL_SOURCE, "weight_confirmed_small_part": True}
    tab.update(description="TOP BLANK", quantity=1, textual_operations=["laser_cutting"])
    e.estimate_part(tab, job_quantity=1)
    assert tab.get("_cut_path_bounded"), "the costing pass asked the same rule"


# ── a page-read count is a candidate: never measured, never the punch on its own ──────────

def _panel(**kw):
    p = {"part_number": "P-1", "description": "SIDE PANEL", "normalized_material": "MILD_STEEL",
         "normalized_thickness_mm": 1.5, "quantity": 1, "blank_length_mm": 600.0,
         "blank_width_mm": 400.0, "textual_operations": ["laser_cutting"],
         "geometry_rollup": {"estimated_cut_length_mm": 4000.0, "estimated_hole_count": 40,
                             "estimated_pierce_count": 40},
         "manufacturing_features": {"hole_count": 40, "cut_length_mm": 4000.0}}
    p.update(kw)
    return p


def test_page_read_holes_do_not_send_a_part_to_the_punch():
    part = _panel()
    e.estimate_process_times(part)
    assert "punch" not in (part.get("inferred_operations") or [])
    flags = " ".join(part.get("review_flags") or [])
    assert "PUNCH NOT ASSUMED" in flags and "unverified, not measured" in flags
    assert "measured hole(s)" not in flags


def test_page_read_holes_on_the_laser_are_asked_as_candidates():
    part = _panel()
    e.estimate_process_times(part)
    assert any("read off the drawing's lines" in str(q.get("issue"))
               for q in part.get("manufacturing_questions") or [])


def test_a_perforated_family_named_on_the_drawing_still_goes_to_the_punch():
    part = _panel(description="PERFORATED PEG PANEL")
    e.estimate_process_times(part)
    assert "punch" in (part.get("inferred_operations") or [])
    assert "unverified, not measured" in " ".join(part.get("review_flags") or [])


def test_measured_holes_keep_the_punch_and_are_called_measured():
    part = _panel(dxf_augmented=True, geometry_source="dxf_flat_pattern",
                  blank_length_mm_source="dxf_flat_pattern")
    e.estimate_process_times(part)
    assert "punch" in (part.get("inferred_operations") or [])
    assert "measured hole(s)" in " ".join(part.get("review_flags") or [])


def test_an_assembly_is_not_asked_about_cutting():
    part = _panel(part_number="ASM-1", is_assembly_parent=True)
    e.estimate_process_times(part)
    assert not any("read off the drawing's lines" in str(q.get("issue"))
                   for q in part.get("manufacturing_questions") or [])


# ── a fold the counter charges from the drawing carries that evidence ──────────────────────

def test_a_fold_with_a_drawn_angle_carries_it_and_one_without_does_not():
    drawn = {"part_number": "S-1", "textual_operations": ["folding"], "angles_deg": ["90"]}
    bare = {"part_number": "S-2", "textual_operations": ["folding"]}
    assert g.settle_fold_evidence([drawn, bare]) == ["S-1"]
    assert "90" in drawn["operation_evidence"]["folding"]
    assert not (bare.get("operation_evidence") or {}).get("folding")


# ── the quote's worked example needs size, price and route evidence ────────────────────────

def _story(monkeypatch, *, firm=True, source="drawing_notes", blank_evidence=True):
    import costed_facts as cf
    import quote_story as qs
    rec = {"part_number": "A-1", "normalized_thickness_mm": 2.0}
    if blank_evidence:
        rec["_blank_provisional"] = {"weight_agrees": True}
    monkeypatch.setattr(cf, "record_lines", lambda s: {"A-1": {"price_origin": {
        "firmness": cf.FIRM if firm else cf.INDICATIVE_MARKET}}})
    summary = {"estimate_summary": {"canonical_route_shadow": {"decisions": [
        {"status": "required", "target_id": "A-1", "operation": "laser_cutting", "source": source}]}}}
    return qs._line_is_supported(summary, {"made": [rec]}, "A-1")


def test_a_supported_line_can_be_the_example(monkeypatch):
    assert _story(monkeypatch) is True


@pytest.mark.parametrize("kw", [{"firm": False}, {"source": "unrecorded"},
                                {"blank_evidence": False}])
def test_a_line_missing_any_evidence_is_not_the_example(monkeypatch, kw):
    assert _story(monkeypatch, **kw) is False


# ── the replay tool reads, it never writes ─────────────────────────────────────────────────

def test_the_replay_reports_and_leaves_the_record_as_it_was(tmp_path):
    import replay_sheet_geometry as rp
    record = _summary(_page(12, ["ASM-12", "TUBE-1"], weight="2.5KG", cut=9090.0),
                      _page(15, ["TUBE-1"], weight="1.4KG", cut=5100.0),
                      rows=[{"part_number": "TUBE-1", "bom_sheet": "p.pdf#11", "bom_parent": "ASM-12"}])
    record["manufacturing_writeup"] = {"parts": [
        {"part_number": "TUBE-1", "normalized_material": "MILD_STEEL", "pages": [12, 15],
         "weights": ["2.5KG"], "section_stock": {"a": 50, "b": 20, "t": 2},
         "geometry_rollup": {"estimated_cut_length_mm": 14190.0, "estimated_hole_count": 0},
         "normalized_geometry": {"cut_length_mm": 14190.0, "hole_count": 0}}]}
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    rows = rp.replay(str(path))
    assert rows and rows[0]["weight_after_kg"] == "1.4" and rows[0]["other_pages"] == "12"
    assert path.read_text(encoding="utf-8") == before
