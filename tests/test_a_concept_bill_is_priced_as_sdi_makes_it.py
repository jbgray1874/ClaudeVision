"""A concept bill is priced the way SDI makes it (D-483 to D-488).

K-Wellness FSDU, the 12:31 book of 12 Oct 2026. The hand-off worked and the bill had the right
parts in the right counts, and the price was £6,943.20 a unit at 200 off:

  - the pages were classed as design-intent sheets, and the sheet read was never given the
    declared standards manual, so no test, documentation or project row was priced (D-483);
  - every made part came back with a count, a material and a route and a size of 0, and the
    bill check let it through (D-484);
  - with nothing to nest, each made part was priced by the market as a FINISHED item — a side
    tray at £420 — with our own laser, fold, weld, dress and powder charged on top (D-485);
  - a unit of about forty pieces was timed as one part handled: 0.8 minutes (D-486);
  - the fixings set sat at £0, the QR labels at 3p for one label, and both — with the
    graphics — had no owner in the hierarchy (D-487);
  - P.Coat was charged on six parts with a coated area of 0 and no powder material (D-488).

Every rule here is generic: nothing names a job, a customer or a part code.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402

SRC = ROOT / "src"


# ── D-483: the standards ride on a design-sheet read ────────────────────────────────────

def test_a_sheet_read_carries_the_standards_section():
    words = "[MANUAL.pdf, page 3]\nAll fixtures must pass a stability test."
    with_std = cs.concept_prompt_text([b"png"], "", sheet=True, sheet_words="SHEET",
                                      standards_words=words)
    without = cs.concept_prompt_text([b"png"], "", sheet=True, sheet_words="SHEET")
    assert "SUPPORTING STANDARDS" in with_std and "stability test" in with_std
    assert "SUPPORTING STANDARDS" not in without


def test_a_sheet_read_without_standards_keeps_its_cache_key():
    base = cs._cache_key([b"png"], "m", sheet=True, sheet_words="SHEET")
    again = cs._cache_key([b"png"], "m", sheet=True, sheet_words="SHEET", standards_words="")
    std = cs._cache_key([b"png"], "m", sheet=True, sheet_words="SHEET", standards_words="X")
    assert base == again
    assert std != base


def test_the_sheet_read_passes_the_reference_pack_to_both_reads(monkeypatch):
    seen = []

    def _fake(paths, **kw):
        seen.append(kw.get("reference_pack"))
        return {"parsed": {"parts": [{"name": "PANEL", "kind": "fabricated", "quantity": 1,
                                      "assumed_blank_mm": {"length": 0, "width": 0}}]},
                "sheet_text": ""}

    monkeypatch.setattr(cs, "read_concept", _fake)
    cs.read_sheet_concept(["a.pdf"], reference_pack=["MANUAL.pdf"])
    assert seen == [["MANUAL.pdf"], ["MANUAL.pdf"]]      # the first read and the re-ask


def test_file_scan_gives_the_sheet_read_its_standards():
    src = (SRC / "file_scan.py").read_text(encoding="utf-8")
    call = src[src.index("_sr = concept_scan.read_sheet_concept("):][:400]
    assert "reference_pack=_ref_pack" in call
    assert "do not ride on a design-sheet read" not in src


# ── D-484: a made part with no size fails the bill check ────────────────────────────────

def _answer(*parts):
    return {"parts": list(parts)}


def test_a_made_part_with_no_size_fails_and_is_named():
    chk = cs.sheet_check(_answer(
        {"name": "SIDE TRAY", "kind": "fabricated", "quantity": 10,
         "assumed_blank_mm": {"length": 0, "width": 0, "thickness": 0}},
        {"name": "POST", "kind": "fabricated", "quantity": 6,
         "assumed_blank_mm": {"length": 1500, "width": 120, "thickness": 2}},
        {"name": "STRIP", "kind": "bought_in", "quantity": 15}))
    assert chk["sizeless"] == ["SIDE TRAY"]
    assert chk["verdict"] == "disagrees" and chk["checked"]
    assert any("SIDE TRAY" in f and "no size" in f for f in chk["failures"])
    assert "SIDE TRAY" in cs.recheck_text(chk)
    assert not any("POST" in f for f in chk["failures"])


def test_a_length_alone_is_a_size():
    chk = cs.sheet_check(_answer({"name": "TUBE", "kind": "fabricated", "quantity": 2,
                                  "assumed_blank_mm": {"length": 900, "width": 0}}))
    assert chk["sizeless"] == []


def test_the_re_ask_that_sizes_the_parts_is_taken(monkeypatch):
    first = _answer({"name": "TRAY", "kind": "fabricated", "quantity": 5,
                     "assumed_blank_mm": {"length": 0, "width": 0}})
    second = _answer({"name": "TRAY", "kind": "fabricated", "quantity": 5,
                      "assumed_blank_mm": {"length": 350, "width": 350, "thickness": 1.5}})
    asked = []

    def _fake(paths, **kw):
        asked.append(kw.get("recheck") or "")
        return {"parsed": second if kw.get("recheck") else first, "sheet_text": ""}

    monkeypatch.setattr(cs, "read_concept", _fake)
    out = cs.read_sheet_concept(["a.pdf"])
    assert "TRAY" in asked[1] and "no size" in asked[1]
    assert out["check"]["second_read_taken"] is True
    assert out["answer"] is second


# ── D-485: a part we make is never priced as a finished item ────────────────────────────

def test_the_market_guard_reads_the_costed_records_route():
    from pricing_service import is_something_you_can_buy
    costed = {"part_number": "J-CPT08", "description": "Side shelf tray",
              "route_context": {"inferred_operations": ["laser_cutting", "folding", "welding"]}}
    assert is_something_you_can_buy(costed, structure_decides=False) is False
    bought = {"part_number": "J-NV01", "description": "Cable ties",
              "route_context": {"inferred_operations": []}}
    assert is_something_you_can_buy(bought, structure_decides=False) is True


def _made_pe(**kw):
    pe = {"part_number": "J-CPT08", "description": "Side shelf tray (mirrored, with welded hooks)",
          "quantity": 10, "normalized_material": "MILD STEEL",
          "material_estimate": {"material": "MILD STEEL", "thickness_mm": 1.5},
          "route_context": {"inferred_operations": ["laser_cutting", "folding", "welding",
                                                    "powder_coating"]}}
    pe.update(kw)
    return pe


def test_an_unsized_made_part_is_asked_for_its_raw_material_only(monkeypatch):
    import estimator as E
    import indicative_price
    briefs = []

    def _fake(line, **kw):
        briefs.append(line)
        return {"price_gbp": 2.40, "status": "indicative", "evidence": {"source": "test"}}

    monkeypatch.setattr(indicative_price, "resolve_indicative", _fake)
    monkeypatch.setattr(E, "_resolve_part_system_cost",
                        lambda pe: pytest.fail("a made part must not reach the finished-item chain"))
    pe = _made_pe()
    assert E.apply_last_resort_prices([pe], E._last_resort_lookup) == 1
    q = briefs[0]["description"]
    assert "RAW MATERIAL ONLY" in q and "nothing else" in q
    assert "Side shelf tray" in q and "mild steel 1.5 mm" in q
    me = pe["material_estimate"]
    assert me["unit_material_cost_gbp"] == 2.40 and me["material_allowance_only"] is True
    assert any(f.startswith("PROVISIONAL MATERIAL ALLOWANCE") for f in pe["review_flags"])
    assert not any(f.startswith("AI/MARKET LAST-RESORT") for f in pe["review_flags"])
    assert "_made_part_material_allowance" not in pe


def test_an_unsized_made_part_with_no_answer_is_an_owned_gap(monkeypatch):
    import estimator as E
    import indicative_price
    monkeypatch.setattr(indicative_price, "resolve_indicative",
                        lambda line, **kw: {"price_gbp": None, "missing": "no listing"})
    pe = _made_pe()
    assert E.apply_last_resort_prices([pe], E._last_resort_lookup) == 0
    assert any("NOT PRICED —" in f and "never priced as a finished" in f
               for f in pe["review_flags"])
    assert "_made_part_material_allowance" not in pe


def test_a_bought_line_still_takes_the_ordinary_chain(monkeypatch):
    import estimator as E
    called = []
    monkeypatch.setattr(E, "_resolve_part_system_cost",
                        lambda pe: called.append(pe) or {"result": {}, "applied_unit_cost": 1.5})
    pe = {"part_number": "J-NV05", "description": "Cable ties", "quantity": 1,
          "page_roles": ["bought_in"], "route_context": {"inferred_operations": []}}
    assert E.apply_last_resort_prices([pe], E._last_resort_lookup) == 1
    assert called and any(f.startswith("AI/MARKET LAST-RESORT") for f in pe["review_flags"])


# ── D-486: a sighted unit is fitted piece by piece ──────────────────────────────────────

def _sighted():
    ans = {"product": {"name": "FSDU"}, "parts": [
        {"name": "POST", "kind": "fabricated", "quantity": 6, "material_guess": "MILD STEEL",
         "assumed_blank_mm": {"length": 1500, "width": 120, "thickness": 2},
         "operations": ["laser_cutting", "folding"]},
        {"name": "SIDE TRAY", "kind": "fabricated", "quantity": 10, "material_guess": "MILD STEEL",
         "assumed_blank_mm": {"length": 350, "width": 350, "thickness": 1.5},
         "operations": ["laser_cutting", "folding"]},
        {"name": "HEADER GRAPHIC", "kind": "graphic", "quantity": 2},
        {"name": "EDGE STRIP", "kind": "bought_in", "quantity": 15},
    ]}
    parts = cs.parts_from_concept(ans, "JOB")
    return ans, parts


def test_the_unit_counts_every_piece_it_fits_and_owns_its_bought_lines():
    ans, parts = _sighted()
    unit = cs.unit_assembly_part(parts, ans, "JOB")
    assert unit["pieces_fitted"] == 6 + 10 + 2 + 15
    made = {p["part_number"] for p in parts if p["concept_kind"] == "fabricated"}
    assert set(unit["assembly_children"]) == made           # the members stay the made parts
    others = {p["part_number"] for p in parts if p["concept_kind"] != "fabricated"}
    assert set(unit["assembly_fitted_items"]) == others


def test_a_steel_unit_is_timed_per_piece_fitted():
    import estimator as E
    unit = {"part_number": "J-CPT00", "description": "unit assembly", "quantity": 1,
            "normalized_material": "MILD STEEL", "is_assembly_parent": True,
            "assembly_children": ["J-CPT01", "J-CPT02"], "inferred_operations": ["assembly"],
            "pieces_fitted": 41, "concept": True, "concept_kind": "assembly"}
    pe = E.estimate_part(dict(unit), job_quantity=200)
    per = float(E.LABOUR_RULES["handling"]["min_per_part"])
    assert pe["process_estimate"]["run_times_min_per_unit"]["handling"] == round(per * 41, 2)
    assert any("unit fitting" in f and "41 piece" in f for f in pe["review_flags"])
    one = dict(unit, pieces_fitted=0)
    pe1 = E.estimate_part(one, job_quantity=200)
    assert pe1["process_estimate"]["run_times_min_per_unit"]["handling"] == round(per, 2)


def test_the_unit_fitting_time_is_a_stated_shop_time_on_the_sheet():
    import wb_populate as W
    hit = [m for m in W._STATED_SHOP_TIME_MARKERS if m[0] == "unit_fitting_applied"]
    assert hit and "handling" in hit[0][1] and "assembly" in hit[0][1]


# ── D-487: consumables scaled to the unit, priced, and owned ───────────────────────────

def test_a_per_component_item_is_counted_per_piece_and_a_set_carries_its_allowance():
    lines = cs.consumable_lines(["QR component labels (20x20mm)",
                                 "fixings and fasteners for carcass assembly"], "JOB",
                                pieces_fitted=41)
    labels, fixings = lines
    assert labels["quantity"] == 41 and "consumable_allowance" not in labels
    assert fixings["quantity"] == 1
    assert "41 fitted pieces" in fixings["research_description"]
    rule = fixings["consumable_allowance"]
    import config
    per = config.CONCEPT_CONSUMABLE_ALLOWANCE["per_piece_fitted"]
    assert rule["count"] == per * 41 and rule["reference_item"]
    # Config holds a COUNT and an item, never a price.
    assert not any("gbp" in k.lower() or "price" in k.lower()
                   for k in config.CONCEPT_CONSUMABLE_ALLOWANCE)


def test_without_a_unit_the_lines_are_as_before():
    (line,) = cs.consumable_lines(["fixings"], "JOB")
    assert line["quantity"] == 1
    assert "consumable_allowance" not in line and "research_description" not in line


def test_an_unanswered_set_is_costed_as_count_times_a_priced_reference_item():
    import estimator as E
    raw = {"part_number": "J-NV01", "consumable_allowance": {
        "count": 164, "per_piece_fitted": 4, "pieces_fitted": 41,
        "reference_item": "M6 x 16 pan head machine screw with nut and washer",
        "basis": "an assumption to confirm"}}
    pe = {"part_number": "J-NV01", "description": "fixings", "quantity": 1,
          "page_roles": ["render"],
          "review_flags": ["J-NV01: NOT PRICED — the research returned no usable figure"]}
    asked = []
    n = E.apply_consumable_allowances([pe], [raw],
                                      reference_lookup=lambda ref: asked.append(ref) or 0.12)
    assert n == 1
    assert asked[0]["description"].startswith("M6 x 16")
    assert pe["material_estimate"]["unit_material_cost_gbp"] == round(0.12 * 164, 2)
    assert pe["material_estimate"]["consumable_allowance"] is True
    assert any(f.startswith("PROVISIONAL CONSUMABLES ALLOWANCE") and "164" in f
               for f in pe["review_flags"])
    assert not any("NOT PRICED —" in f for f in pe["review_flags"])


def test_a_priced_set_is_not_touched():
    import estimator as E
    raw = {"part_number": "J-NV01", "consumable_allowance": {"count": 8, "reference_item": "X"}}
    pe = {"part_number": "J-NV01", "description": "fixings", "quantity": 1,
          "material_estimate": {"extended_material_cost_gbp": 5.0}}
    assert E.apply_consumable_allowances([pe], [raw], reference_lookup=lambda r: 1.0) == 0


def test_the_unit_owns_its_fitted_lines_in_the_hierarchy():
    import route_compiler as rc
    parts = [
        {"part_number": "J-CPT00", "description": "unit", "is_assembly_parent": True,
         "assembly_children": ["J-CPT01"], "assembly_fitted_items": ["J-NV01", "J-CPT03"]},
        {"part_number": "J-CPT01", "description": "post", "normalized_material": "MILD STEEL",
         "quantity": 6},
        {"part_number": "J-CPT03", "description": "graphic", "quantity": 2},
        {"part_number": "J-NV01", "description": "fixings", "quantity": 1},
    ]
    g = rc.build_part_graph(parts, {})
    nodes = {n.part_number: n for n in g["nodes"]}
    for code in ("J-CPT01", "J-CPT03", "J-NV01"):
        assert "J-CPT00" in nodes[code].parents, code


def test_file_scan_hangs_the_consumables_on_the_unit():
    src = (SRC / "file_scan.py").read_text(encoding="utf-8")
    at = src[src.index("_nv_lines = concept_scan.consumable_lines("):][:700]
    assert "pieces_fitted=" in at and "assembly_fitted_items" in at


# ── D-488: P.Coat with nothing to coat is said ─────────────────────────────────────────

def test_a_coat_charged_on_a_zero_area_is_flagged():
    import estimator as E
    pe = E.estimate_part({"part_number": "J-CPT03", "description": "Base / plinth",
                          "quantity": 1, "normalized_material": "MILD STEEL",
                          "inferred_operations": ["laser_cutting", "folding", "powder_coating"],
                          "concept": True, "concept_kind": "fabricated"}, job_quantity=200)
    assert "powder_charged_zero_coated_area" in pe["risk_flags"]
    assert any(f.startswith("P.COAT CHARGED WITH NO COATED AREA") for f in pe["review_flags"])
    import plain_english
    assert "powder_charged_zero_coated_area" in plain_english._CODES


def test_a_coated_part_with_a_blank_is_not_flagged():
    import estimator as E
    pe = E.estimate_part({"part_number": "P-1", "description": "PANEL", "quantity": 1,
                          "normalized_material": "MILD STEEL", "normalized_thickness_mm": 1.5,
                          "blank_length_mm": 400, "blank_width_mm": 300,
                          "normalized_geometry": {"blank_length_mm": 400, "blank_width_mm": 300},
                          "inferred_operations": ["laser_cutting", "powder_coating"]},
                         job_quantity=10)
    assert "powder_charged_zero_coated_area" not in (pe.get("risk_flags") or [])


def test_a_sighted_part_with_a_blank_is_never_flagged_as_having_nothing_to_coat():
    """The workbook's Powder Qty Calculator charges the area of any blank on the Sheet Steel
    block (the 16:53 book: 6.1 m² from the sighted blanks), so only a part with no size at
    all has nothing to coat."""
    import estimator as E
    ans = {"product": {"name": "FSDU"}, "parts": [
        {"name": "SLOTTED POST", "kind": "fabricated", "quantity": 6,
         "material_guess": "MILD STEEL",
         "assumed_blank_mm": {"length": 1500, "width": 80, "thickness": 2},
         "operations": ["laser_cutting", "folding", "powder_coating"]}]}
    (part,) = cs.parts_from_concept(ans, "JOB")
    pe = E.estimate_part(part, job_quantity=200)
    assert "powder_charged_zero_coated_area" not in (pe.get("risk_flags") or [])
