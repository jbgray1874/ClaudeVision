"""A model assembly named "<drawing number> SA" is that drawing's record, and a disc base plate
is its circle (D-734).

12002-02-GA, 6 Nov 2026, 12:13 book, and the review of it:

  "Row 93 prices 15.2 x 15.2 x 3 mm at £0.03. That is the central square hole. The actual
   plate is Ø300 x 3 mm."
  "101 and 102 remain alongside 101 SA and 102 SA. The former appear as purchased items, while
   their fabricated children are also charged. This also produces an additional weld/dress
   group."
  "Row 158 charges £91.77 on the base and arm assemblies; row 164 charges another £91.20 on
   the GA. Nothing establishes a second coating pass."

Synthetic records, a stand-in model tree and a drawn DXF; no job's files.
"""
from __future__ import annotations

import importlib.util
import math
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import route_compiler as rc                                              # noqa: E402
from source_connectors import solidworks as sw                           # noqa: E402

_spec = importlib.util.spec_from_file_location("dxf_reader_d734", ROOT / "src" / "dxf_reader.py.py")
dxfr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dxfr)


# ── the base plate: a 300 mm circle round a 15.2 mm square cut-out ───────────────────

def _plate(tmp_path, square=15.2, hole=5.0, radius=150.0, extra_line_outside=False):
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_circle((150, 150), radius)
    h = square / 2.0
    pts = [(150 - h, 150 - h), (150 + h, 150 - h), (150 + h, 150 + h), (150 - h, 150 + h),
           (150 - h, 150 - h)]
    for a, b in zip(pts, pts[1:]):
        msp.add_line(a, b)
    msp.add_circle((150, 100), hole / 2.0)
    if extra_line_outside:
        msp.add_line((0, 400), (300, 400))
    path = tmp_path / "T-M01_3mm_MS.DXF"
    doc.saveas(path)
    return dxfr.extract_flat_pattern_data(path)


def test_the_circle_round_the_lines_is_the_plates_outline(tmp_path):
    d = _plate(tmp_path)
    assert (d["blank_length_mm"], d["blank_width_mm"]) == (300.0, 300.0)
    assert d["outline_shape"] == "circle" and d["outline_diameter_mm"] == 300.0
    net = math.pi * 150 ** 2 - 15.2 ** 2 - math.pi * 2.5 ** 2
    assert d["blank_area_mm2"] == pytest.approx(net, rel=1e-3)
    assert d["perimeter_mm"] == pytest.approx(2 * math.pi * 150 + 4 * 15.2, abs=0.5)


def test_a_line_outside_the_circle_leaves_the_lines_as_the_outline(tmp_path):
    d = _plate(tmp_path, extra_line_outside=True)
    assert d["blank_length_mm"] > 300.0 or d.get("outline_shape") != "circle"


def test_a_hole_inside_a_plate_is_still_a_hole(tmp_path):
    """The ordinary case: a 200 mm square plate with a 20 mm hole keeps its square outline."""
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    pts = [(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)]
    for a, b in zip(pts, pts[1:]):
        msp.add_line(a, b)
    msp.add_circle((100, 100), 10)
    path = tmp_path / "T-SQ_3mm_MS.DXF"
    doc.saveas(path)
    d = dxfr.extract_flat_pattern_data(path)
    assert (d["blank_length_mm"], d["blank_width_mm"]) == (200.0, 200.0)
    assert d.get("outline_shape") != "circle"


# ── the identities: the model's "101 SA" is the drawing's 101 ────────────────────────

@pytest.mark.parametrize("name, stem", [("12002-02-101 SA", "12002-02-101"),
                                        ("12002-02-101-SA", "12002-02-101"),
                                        ("12002-02-101_SUBASSY", "12002-02-101"),
                                        ("12002-02-102 ASSY", "12002-02-102"),
                                        ("ABC-SALT", ""), ("12002-02-GA", ""),
                                        ("12002-02-M01", "")])
def test_the_drawing_number_inside_a_model_assembly_name(name, stem):
    assert sw.model_assembly_stem(name) == stem


def _model_job():
    return types.SimpleNamespace(hierarchy={
        "12002-02-GA": [("12002-02-101 SA", 1), ("12002-02-102 SA", 1), ("BI-THUMBSCREW", 1)],
        "12002-02-101 SA": [("12002-02-M01", 1), ("12002-02-M02", 1)],
        "12002-02-102 SA": [("12002-02-M03", 1), ("12002-02-M04", 1), ("12002-02-M05", 2)]})


def _steel(pn):
    return {"part_number": pn, "quantity": 1, "normalized_material": "MILD STEEL",
            "normalized_thickness_mm": 3.0, "dxf_augmented": True, "normalized_finish": "RAW",
            "normalized_geometry": {"blank_length_mm": 300, "blank_width_mm": 120,
                                    "geometry_source": "dxf_flat_pattern"},
            "textual_operations": ["laser_cutting"]}


def _job_parts():
    coat = {"textual_operations": ["powder_coating"],
            "operation_sources": {"powder_coating": "drawing_deterministic"},
            "normalized_finish": "POWDER COATED"}
    return [
        {"part_number": "12002-02-GA", "quantity": 1, "is_assembly_parent": True, **coat},
        {"part_number": "12002-02-101", "quantity": 1, "description": "SA STAND BASE",
         "normalized_material": "MILD STEEL", **coat},
        {"part_number": "12002-02-102", "quantity": 1, "description": "SA STAND ARM",
         "normalized_material": "MILD STEEL", **coat},
        *[_steel(f"12002-02-M0{i}") for i in range(1, 6)],
        {"part_number": "BI-THUMBSCREW", "quantity": 1, "is_bought_in": True,
         "description": "M6 x 12mm Knurled Thumbscrew"},
    ]


def test_the_model_tree_lands_on_the_drawings_records():
    parts = _job_parts()
    sw.apply_native_hierarchy_to_parts(parts, _model_job())
    by = {p["part_number"]: p for p in parts}
    assert not any(" SA" in p["part_number"] for p in parts), "no second assembly minted"
    assert by["12002-02-101"]["assembly_children"] == ["12002-02-M01", "12002-02-M02"]
    assert by["12002-02-102"]["assembly_children"] == ["12002-02-M03", "12002-02-M04",
                                                       "12002-02-M05"]
    assert by["12002-02-GA"]["assembly_children"] == ["12002-02-101", "12002-02-102",
                                                      "BI-THUMBSCREW"]
    assert by["12002-02-101"]["model_assembly_name"] == "12002-02-101 SA"
    assert any("not a second assembly" in f for f in by["12002-02-101"]["review_flags"])


def test_the_ga_is_not_coated_again_over_its_coated_sub_assemblies():
    parts = _job_parts()
    sw.apply_native_hierarchy_to_parts(parts, _model_job())
    out = rc.compile_job_route(parts, known_assemblies=["12002-02-GA", "12002-02-101",
                                                        "12002-02-102"])
    ds = [d if isinstance(d, dict) else d.__dict__ for d in out["decisions"]]

    def coat(pn):
        hits = [d for d in ds if d["target_id"] == pn and d["operation"] == "powder_coating"]
        assert len(hits) == 1, (pn, hits)
        return hits[0]
    assert coat("12002-02-GA")["status"] == rc.NOT_APPLICABLE
    assert "12002-02-101 (a sub-assembly coated on its own sheet)" in coat("12002-02-GA")["reason"]
    assert coat("12002-02-101")["status"] == rc.REQUIRED
    assert coat("12002-02-102")["status"] == rc.REQUIRED


def test_a_drawing_route_naming_the_model_file_lands_on_the_record():
    """The read keyed the weld callout to "12002-02-101 SA"; the work is the record's."""
    parts = [{"part_number": "A-101", "quantity": 1, "assembly_children": ["A-M01"],
              "is_sub_assembly": True},
             {"part_number": "A-M01", "quantity": 1, "normalized_material": "MILD STEEL"}]
    out = rc.compile_job_route(
        parts, {"routes": [{"operation": "welding", "part_numbers": ["A-101 SA"],
                            "scope": "assembly"}]}, known_assemblies=["A-101"])
    ds = [d if isinstance(d, dict) else d.__dict__ for d in out["decisions"]]
    welds = [d for d in ds if d["operation"] == "welding"]
    assert [(d["target_id"], d["status"]) for d in welds] == [("A-101", rc.REQUIRED)]


# ── D-736: 12002-02-GA 12:47 — the read's "NNN SA" is the record too, and one weld ────────

def _read_and_tables():
    """The 12:47 inputs: the vision read names the sub-assemblies "12002-02-101 SA" and
    "-102 SA" with their members; the deterministic GA table reads the same lines as
    12002-02-101 / "SA STAND BASE"; each sub-assembly sheet's parts list groups its rows under
    the "SA" name; the model's tree lands on 101 and 102 (D-734)."""
    J = "12002-02"
    parts = _job_parts()
    parts.append({"part_number": "BI-HANKBUSH", "quantity": 1, "is_bought_in": True,
                  "description": "M6 HANKBUSH"})
    by = {p["part_number"]: p for p in parts}
    by[f"{J}-M05"]["quantity"] = 2
    sw.apply_native_hierarchy_to_parts(parts, _model_job())
    llm = {"assemblies": [
        {"part_number": f"{J}-GA", "children": [{"part_number": f"{J}-101 SA", "qty": 1},
                                                {"part_number": f"{J}-102 SA", "qty": 1},
                                                {"part_number": "BI-THUMBSCREW", "qty": 1}]},
        {"part_number": f"{J}-101 SA", "children": [{"part_number": f"{J}-M01", "qty": 1},
                                                    {"part_number": f"{J}-M02", "qty": 1},
                                                    {"part_number": "BI-HANKBUSH", "qty": 1}]},
        {"part_number": f"{J}-102 SA", "children": [{"part_number": f"{J}-M03", "qty": 1},
                                                    {"part_number": f"{J}-M04", "qty": 1},
                                                    {"part_number": f"{J}-M05", "qty": 2}]}]}
    rows = [{"part_number": f"{J}-101", "description": "SA STAND BASE", "quantity": 1,
             "bom_parent": f"{J}-GA"},
            {"part_number": f"{J}-102", "description": "SA STAND ARM", "quantity": 1,
             "bom_parent": f"{J}-GA"},
            *[{"part_number": f"{J}-M0{i}", "quantity": 1, "bom_parent": f"{J}-101 SA"}
              for i in (1, 2)],
            {"part_number": "BI-HANKBUSH", "quantity": 1, "bom_parent": f"{J}-101 SA"},
            *[{"part_number": f"{J}-M0{i}", "quantity": 1, "bom_parent": f"{J}-102 SA"}
              for i in (3, 4)],
            {"part_number": f"{J}-M05", "quantity": 2, "bom_parent": f"{J}-102 SA"}]
    return parts, llm, rows


def test_the_reads_sa_name_is_the_drawings_record_and_nothing_is_counted_twice():
    parts, llm, rows = _read_and_tables()
    g = rc.build_part_graph(parts, llm, rows, ["12002-02-GA", "12002-02-101", "12002-02-102"],
                            declared_product="12002-02-GA")
    q = g["quantities"]
    assert [q[f"12002-02-M0{i}"] for i in range(1, 6)] == [1.0, 1.0, 1.0, 1.0, 2.0]
    assert q["BI-HANKBUSH"] == 1.0
    assert not any(k.endswith(" SA") for k in q), sorted(q)
    assert g["children"]["12002-02-GA"] >= {"12002-02-101", "12002-02-102"}
    assert set(g["children"]["12002-02-101"]) == {"12002-02-M01", "12002-02-M02",
                                                  "BI-HANKBUSH"}


def test_no_second_assembly_event_is_booked_on_the_sa_name():
    parts, llm, rows = _read_and_tables()
    out = rc.compile_job_route(parts, llm, rows, known_assemblies=[
        "12002-02-GA", "12002-02-101", "12002-02-102"], declared_product="12002-02-GA")
    ds = [d if isinstance(d, dict) else d.__dict__ for d in out["decisions"]]
    assert not [d for d in ds if str(d["target_id"]).endswith(" SA")
                and d["status"] == rc.REQUIRED]


def test_an_sa_name_with_no_record_of_its_drawing_number_stays_itself():
    """Joined only where the record exists: the rule never invents an identity."""
    parts = [{"part_number": "B-GA", "quantity": 1, "is_assembly_parent": True},
             {"part_number": "B-M01", "quantity": 1, "normalized_material": "MILD STEEL"}]
    llm = {"assemblies": [
        {"part_number": "B-GA", "children": [{"part_number": "B-201 SA", "qty": 1}]},
        {"part_number": "B-201 SA", "children": [{"part_number": "B-M01", "qty": 1}]}]}
    g = rc.build_part_graph(parts, llm, None, ["B-GA"], declared_product="B-GA")
    assert "B-201 SA" in g["children"]
    assert g["quantities"]["B-M01"] == 1.0


def test_an_assembly_that_owns_its_weld_is_not_welded_again_as_a_part():
    """12:47 row 159: the read's weld on "101 SA" lands on 101 as its assembly weld, and the
    weldment-inside-a-welded-assembly rule (D-566) charged 101's own sheet's weld again as a
    part weld, with a second dress event. 101 is that weld's target, not a member of it."""
    parts = [{"part_number": "A-101", "quantity": 1, "assembly_children": ["A-M01", "A-M02"],
              "is_sub_assembly": True, "description": "SA STAND BASE",
              "weld_stated_by_note": True, "textual_operations": ["welding", "dress_welds"],
              "operation_sources": {"welding": "drawing_deterministic",
                                    "dress_welds": "drawing_deterministic"}},
             {"part_number": "A-M01", "quantity": 1, "normalized_material": "MILD STEEL"},
             {"part_number": "A-M02", "quantity": 1, "normalized_material": "MILD STEEL"}]
    out = rc.compile_job_route(
        parts, {"routes": [{"operation": "welding", "part_numbers": ["A-101 SA"],
                            "scope": "assembly"}]}, known_assemblies=["A-101"])
    ds = [d if isinstance(d, dict) else d.__dict__ for d in out["decisions"]]
    for op in ("welding", "dress_welds"):
        hits = [d for d in ds if d["operation"] == op and d["status"] == rc.REQUIRED]
        assert [(d["target_id"], d["scope"]) for d in hits] == [("A-101", "assembly")], (op, hits)
