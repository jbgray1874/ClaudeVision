"""12173-02 Card Spinner, 1 Oct 21:19 book (D-384): two faults no earlier fix covered, and the
estimator's two rulings from his brief.

1. The base's two 25 mm MDF layers were minted as numbered pieces (D-378) and then listed "not
   linked to 12173-02-GA, so not priced" — the base had bench, edging and spray labour and no
   board material at all.
2. The MFC back read "welding removed: part is MFC" on the report while the sheet charged
   £23.77 of Weld (CO2): the board gate cleaned the op lists and never wrote the ruling the
   route reads.
3. config.JOB_DECISIONS grows a make_or_buy ruling; the 12173-02 entry answers the mesh
   question (buy) and the 201 parent-weld question (operations_off).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bought_in_policy as bip                                        # noqa: E402
import drawing_job_merge as d                                         # noqa: E402
import estimator_confirmed as ec                                      # noqa: E402
import route_compiler as rc                                           # noqa: E402


# ── a numbered piece hangs on its part ──────────────────────────────────────────────────

def _two_layers(tmp_path):
    import ezdxf
    for n in ("9999-01-01J-1_25mm MDF.DXF", "9999-01-01J-2_25mm MDF.DXF"):
        doc = ezdxf.new()
        doc.modelspace().add_lwpolyline([(0, 0), (500, 0), (500, 500), (0, 500)], close=True)
        doc.saveas(tmp_path / n)
    parts = [{"part_number": "9999-01-GA", "description": "STAND", "is_assembly_parent": True,
              "assembly_children": ["9999-01-01J"]},
             {"part_number": "9999-01-01J", "description": "BASE", "quantity": 1,
              "normalized_material": "MDF"}]
    out = d.augment_summary_with_dxf({"manufacturing_writeup": {"parts": parts}, "pages": []},
                                     sorted(tmp_path.glob("*.DXF")), reestimate=False)
    return out["manufacturing_writeup"]["parts"]


def test_the_pieces_are_the_parts_children(tmp_path):
    parts = _two_layers(tmp_path)
    base = next(p for p in parts if p["part_number"] == "9999-01-01J")
    assert set(base["assembly_children"]) >= {"9999-01-01J-01", "9999-01-01J-02"}
    assert base["is_assembly_parent"] is True


def test_the_product_reaches_the_pieces(tmp_path):
    parts = _two_layers(tmp_path)
    g = rc.build_part_graph(parts, {}, [], known_assemblies=["9999-01-GA"])
    nodes = {n.part_number: n for n in g["nodes"]}
    for k in ("9999-01-01J-01", "9999-01-01J-02"):
        assert "9999-01-01J" in nodes[k].parents, f"{k} hangs on nothing"
        assert g["quantities"].get(k) == 1


def test_an_extract_that_states_the_parent_does_not_orphan_its_pieces(tmp_path):
    parts = _two_layers(tmp_path)
    llm = {"assemblies": [{"part_number": "9999-01-01J",
                           "children": [{"part_number": "BI-DOWEL", "qty": 6}]}]}
    g = rc.build_part_graph(parts, llm, [], known_assemblies=["9999-01-GA"])
    nodes = {n.part_number: n for n in g["nodes"]}
    assert "9999-01-01J" in nodes["9999-01-01J-01"].parents


# ── a board's weld is ruled out where the route reads it ─────────────────────────────────

def test_the_board_gate_writes_the_ruling_the_route_reads():
    import estimator as e
    part = {"part_number": "X-03J", "description": "BACK PANEL", "normalized_material": "MFC",
            "normalized_thickness_mm": 18, "quantity": 2,
            "textual_operations": ["cnc_routing", "welding", "dress_welds"]}
    e.estimate_part(part, job_quantity=1)
    ro = part.get("operations_ruled_out") or {}
    assert "welding" in ro and "dress_welds" in ro, ro
    assert "not welded" in ro["welding"]


# ── the make-or-buy ruling ───────────────────────────────────────────────────────────────

def test_the_ruling_key_is_read_and_normalised():
    out, problems = ec._read_decisions(
        {"estimator_decisions": {"make_or_buy": {"x-04m": "BUY", "X-05M": "made", "X-06M": "?"}}},
        "test")
    assert out["make_or_buy"] == {"X-04M": "buy", "X-05M": "make"}
    assert any("X-06M" in p for p in problems)


def _mesh(**kw):
    p = {"part_number": "X-04M", "description": "LOWER TIER MESH",
         "normalized_material": "MILD_STEEL", "surface_finishes": ["RAW"],
         "textual_operations": ["laser_cutting", "wire_forming", "welding", "handling"]}
    p.update(kw)
    return p


def test_buy_rules_the_part_bought_and_answers_the_question():
    p = _mesh(_estimator_make_or_buy="buy", _estimator_make_or_buy_by="James Gray")
    assert "ruled bought in by James Gray" in bip.bought_in_reason(p)
    assert bip.make_buy_question(p) == {}
    removed = set(bip.strip_fabrication_ops(p))
    assert {"laser_cutting", "wire_forming", "welding"} <= removed
    assert p["textual_operations"] == ["handling"]


def test_a_bought_ruling_keeps_a_coat_its_own_sheet_states():
    p = _mesh(_estimator_make_or_buy="buy", surface_finishes=["POWDER COATED"],
              textual_operations=["welding", "powder_coating"])
    bip.strip_fabrication_ops(p)
    assert p["textual_operations"] == ["powder_coating"]


def test_make_withdraws_the_question_and_leaves_the_route():
    p = _mesh(_estimator_make_or_buy="make")
    assert bip.make_buy_question(p) == {}
    assert bip.bought_in_reason(p) == ""


def test_the_route_gate_honours_buy_on_a_cut_part_suffix():
    from types import SimpleNamespace as NS

    def _d(op):
        return NS(target_id="X-04M", operation=op, scope="part", status=rc.REQUIRED,
                  reason="", field_provenance={})
    ds = {op: _d(op) for op in ("laser_cutting", "wire_forming")}
    rec = {"X-04M": dict(_mesh(_estimator_make_or_buy="buy"))}
    rc._family_gate(list(ds.values()), {}, rec)
    assert all(x.status == rc.NOT_APPLICABLE for x in ds.values())


def test_the_card_spinner_rulings_are_on_record():
    import config
    j = config.JOB_DECISIONS["12173-02"]
    assert j["confirmed_by"] == "James Gray"
    ed = j["estimator_decisions"]
    assert ed["make_or_buy"] == {"12173-04-04M": "buy", "12173-04-05M": "buy"}
    assert ed["operations_off"] == {"12173-03-201": ["welding", "dress_welds"]}
    out, problems = ec._read_decisions(j, "config")
    assert not problems and out["make_or_buy"] and out["operations_off"]
