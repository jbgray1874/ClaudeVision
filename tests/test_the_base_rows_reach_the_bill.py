"""12173-02 Card Spinner, 17:34 book (D-381): the base's own parts list —

    1  626 x 626 x 25 mm      1
    2  626 x 626 x 25 mm      1
    3  EDGING, L: 1979mm      1
    4  DOWEL, ø6mm x 20mm     6

and the spinner plate's "2  EDGING. L:1759mm  1" — has no code column. The dowels never became
a line, and the edging was timed on the blanks' square perimeters (2,520 and 2,224 mm).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bom_pipeline as bp                                             # noqa: E402
import document_builder as db                                         # noqa: E402
import edge_banding as eb                                             # noqa: E402
import route_compiler as rc                                           # noqa: E402
from part_identity import mint_uncoded_row_identities                 # noqa: E402


def _rows():
    def row(item, desc, qty, parent="12173-03-01J"):
        return {"part_number": "", "description": desc, "quantity": qty, "bom_item_no": item,
                "bom_parent": parent, "bom_parent_known": True, "source_pdf": parent}
    return [row("1", "626 x 626 x 25 mm", 1), row("2", "626 x 626 x 25 mm", 1),
            row("3", "EDGING, L: 1979mm", 1), row("4", "DOWEL, ø6mm x 20mm", 6),
            row("1", "556 x 556 x 18 mm", 1, "12173-03-02J"),
            row("2", "EDGING. L:1759mm", 1, "12173-03-02J")]


def test_the_edging_rows_state_a_length_and_a_size_does_not():
    assert eb.stated_edging_length_mm("EDGING, L: 1979mm") == 1979
    assert eb.stated_edging_length_mm("EDGING. L:1759mm") == 1759
    assert eb.stated_edging_length_mm("626 x 626 x 25 mm") is None
    assert eb.stated_edging_length_mm("EDGE OF PLINTH 40mm") is None


def test_only_the_dowel_row_is_named():
    rows = _rows()
    assert mint_uncoded_row_identities(rows) == 1
    assert [r["part_number"] for r in rows] == ["", "", "", "BI-DOWEL", "", ""]
    assert rows[3]["identity_source"] == "uncoded_row"


def test_a_row_whose_drawing_is_unknown_is_not_named():
    rows = _rows()
    for r in rows:
        r["bom_parent_known"] = False
    assert mint_uncoded_row_identities(rows) == 0


def test_two_different_rows_do_not_share_a_name():
    rows = _rows() + [{"part_number": "", "description": "DOWEL, ø8mm x 30mm", "quantity": 4,
                       "bom_parent": "12173-03-02J", "bom_parent_known": True}]
    mint_uncoded_row_identities(rows)
    assert rows[3]["part_number"] == "BI-DOWEL"
    assert rows[6]["part_number"] != "BI-DOWEL" and rows[6]["part_number"].startswith("BI-")


def test_the_dowels_are_a_bought_in_line_under_the_base():
    rows = _rows()
    mint_uncoded_row_identities(rows)
    base = {"part_number": "12173-03-01J", "description": "BASE", "quantity": 1,
            "normalized_material": "MDF", "page_roles": ["detail"]}
    recs = db.bought_in_rows_without_records(rows, [base])
    dowel = next(r for r in recs if r["part_number"] == "BI-DOWEL")
    assert dowel["quantity"] == 6 and dowel["bom_parent"] == "12173-03-01J"
    ga = {"part_number": "12173-03-GA", "description": "SPINNER", "is_assembly_parent": True,
          "assembly_children": ["12173-03-01J"]}
    g = rc.build_part_graph([ga, base] + recs, {}, rows, known_assemblies=["12173-03-GA"])
    nodes = {n.part_number: n for n in g["nodes"]}
    assert nodes["BI-DOWEL"].kind == "bought_in"
    assert "12173-03-01J" in nodes["BI-DOWEL"].parents
    assert g["quantities"].get("BI-DOWEL") == 6


def test_the_stated_edging_is_the_banded_length():
    base = {"part_number": "12173-03-01J",
            "normalized_geometry": {"blank_length_mm": 630.04, "blank_width_mm": 630.04}}
    plate = {"part_number": "12173-03-02J",
             "normalized_geometry": {"blank_length_mm": 556, "blank_width_mm": 556}}
    other = {"part_number": "12173-03-03J"}
    assert bp.apply_stated_edging_to_parts([base, plate, other], _rows()) == 2
    got = eb.banded_length_mm(base)
    assert (got["mm"], got["basis"]) == (1979, "drawing_stated_row")
    assert eb.banded_length_mm(plate)["mm"] == 1759
    assert "stated_banded_length_mm" not in other


def test_the_portal_path_runs_both():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "mint_uncoded_row_identities(_dp[\"rows\"])" in src
    assert "apply_stated_edging_to_parts(" in src


# ── a bought mesh panel is bought (D-381) ───────────────────────────────────────────────

import bought_in_policy as bip                                        # noqa: E402


def _mesh(**kw):
    p = {"part_number": "12173-04-04M", "description": "LOWER TIER MESH",
         "normalized_material": "MILD_STEEL",
         "textual_operations": ["wire_forming", "welding", "deburring", "powder_coating",
                                "handling"],
         "inferred_operations": ["laser_cutting"], "surface_finishes": ["POWDER COATED"]}
    p.update(kw)
    return p


# D-383 RESTATED THESE: bare "MESH" no longer rules a part bought (it only asks — see
# test_a_row_is_read_for_what_it_is_before_it_is_named.py); a compound stock-product word still rules.
_WELDMESH = "LOWER TIER WELDMESH PANEL"


def test_a_mesh_panel_with_no_flat_is_bought_not_lasered():
    p = _mesh(description=_WELDMESH)
    assert "purchased stock product (WELDMESH)" in bip.bought_in_reason(p)
    removed = set(bip.strip_fabrication_ops(p))
    assert {"laser_cutting", "wire_forming", "welding", "deburring"} <= removed
    assert {"powder_coating", "handling"} <= set(p["textual_operations"])


def test_a_raw_mesh_loses_the_coat_too():
    p = _mesh(description=_WELDMESH, surface_finishes=["RAW"])
    bip.strip_fabrication_ops(p)
    assert "powder_coating" not in p["textual_operations"]


def test_a_mesh_we_measured_or_form_is_ours():
    assert bip.bought_in_reason(_mesh(dxf_augmented=True, dxf_measured_outline=True,
                                      normalized_geometry={"blank_length_mm": 333,
                                                           "blank_width_mm": 123,
                                                           "geometry_source": "dxf_flat_pattern"})
                                ) == ""
    assert bip.bought_in_reason(_mesh(wire_schedule=[{"gauge_mm": 3}])) == ""


def test_the_words_are_config(monkeypatch):
    import config
    monkeypatch.setattr(config, "PURCHASED_STOCK_PRODUCT_WORDS", ("PERFORATED",), raising=False)
    assert bip.purchased_stock_product(_mesh()) == ""
    assert bip.purchased_stock_product(_mesh(description="PERFORATED INFILL")) == "PERFORATED"


def test_the_route_gate_rules_the_laser_out_and_keeps_the_coat():
    from types import SimpleNamespace as NS

    def _d(op):
        return NS(target_id="12173-04-04M", operation=op, scope="part", status=rc.REQUIRED,
                  reason="", field_provenance={})
    ds = {op: _d(op) for op in ("laser_cutting", "wire_forming", "powder_coating")}
    rec = {"12173-04-04M": {"part_number": "12173-04-04M", "description": _WELDMESH,
                            "normalized_material": "MILD_STEEL",
                            "surface_finishes": ["POWDER COATED"]}}
    rc._family_gate(list(ds.values()), {}, rec)
    assert ds["laser_cutting"].status == rc.NOT_APPLICABLE
    assert ds["wire_forming"].status == rc.NOT_APPLICABLE
    assert ds["powder_coating"].status == rc.REQUIRED
