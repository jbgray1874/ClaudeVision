"""A PART ITS OWN MODEL MEASURED IS NOT GIVEN A GUESSED BLANK (both 12674 jobs, 12 Nov 2026).

Reviewer: "Use evidenced construction, dimensions, thickness, finish and price units. Do not
turn a model envelope into a sheet blank or use an arbitrary fallback price."

The base's model measures 2369.6 x 90 x 610 mm. The 17:21 run costed it as a 350 x 250
"typical tier"; the 17:17 run costed it as 2369.6 x 295.2 borrowed from another panel. The
parts below carry the fields those two records carry for that base and its neighbour.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geometry_inference as G  # noqa: E402


def _base(**over):
    p = {"part_number": "X-01-01J", "description": "BASE", "quantity": 1,
         "material_family": "timber", "surface_finishes": ["WALNUT LAMINATE"],
         "bbox_mm": [2369.6, 90.0, 610.0], "bbox_mm_source": "solidworks_api",
         "native_material_without_geometry": True, "solidworks_native": True}
    p.update(over)
    return p


def _measured_panel():
    return {"part_number": "X-01-07J", "description": "BASE PANEL", "quantity": 1,
            "normalized_material": "TIMBER", "dxf_augmented": True,
            "normalized_geometry": {"blank_length_mm": 2369.6, "blank_width_mm": 295.2}}


def _run(*parts):
    summary = {"manufacturing_writeup": {"parts": list(parts)}}
    return G.infer_missing_geometry(summary), summary["manufacturing_writeup"]["parts"]


def test_it_is_not_given_the_typical_size_for_its_name():
    report, (base,) = _run(_base())
    assert not base.get("geometry_inferred") and "normalized_geometry" not in base
    assert report["inferred"] == [] and "X-01-01J" in report["still_missing"]


def test_it_is_not_lent_another_panels_blank():
    report, (base, panel) = _run(_base(normalized_material="TIMBER"), _measured_panel())
    assert not base.get("geometry_inferred"), base.get("geometry_inference")
    assert (base.get("normalized_geometry") or {}).get("blank_width_mm") is None
    assert panel["normalized_geometry"]["blank_width_mm"] == 295.2


def test_its_envelope_is_recorded_and_it_says_why_it_is_not_priced():
    report, (base,) = _run(_base())
    held = base["model_envelope_unresolved"]
    assert held["envelope_mm"] == [2369.6, 610.0, 90.0] and held["source"] == "solidworks_api"
    assert "not a sheet blank" in held["note"] and "2369.6 x 610 x 90" in held["note"]
    assert "model_envelope_construction_unstated" in base["review_flags"]
    assert report["held_on_envelope"] == [{"part": "X-01-01J", "description": "BASE",
                                           "envelope_mm": [2369.6, 610.0, 90.0]}]


def test_a_part_no_model_measured_is_still_given_a_provisional_size():
    report, (base,) = _run(_base(bbox_mm=None))
    assert base.get("geometry_inferred") and base["geometry_inference"]["basis"] == "category_default"
    assert "model_envelope_unresolved" not in base


def test_an_envelope_that_was_itself_inferred_is_not_a_measurement():
    assert G.measured_model_envelope(_base(bbox_mm_source="geometry_inference")) is None
    assert G.measured_model_envelope(_base(bbox_mm=[100.0, 0.0, 50.0])) is None
    assert G.measured_model_envelope(_base()) == [2369.6, 610.0, 90.0]


def test_its_material_line_is_never_passed_as_a_credible_figure():
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    at = src.index('if mfg.get("model_envelope_unresolved"):')
    assert 'reasons.append("model_envelope_construction_unstated")' in src[at:at + 200]
