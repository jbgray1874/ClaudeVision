"""A row owns its stock, and a designation is not priced by a word (D-587).

The 0351292 midfloor rail's 09:48 book, the first after D-586. The fasteners, the cross rail,
the saw and the supports' coat came right; five things did not, and each was a hand-off:

  - the words reader read the top blank's DIMENSION cell ("2 mm"), and the step that
    flattens reconciled rows into part records dropped it, so the stock-form guard never
    saw the row that said sheet and the rail's 30X20X2MM priced four blanks as tube;
  - the same callout reached a hex nut listed on the rail sheet;
  - the GA's title-block "finish" read was the parts list itself, and the supports took
    STAINLESS STEEL and 3 mm from the strip's row through that same read;
  - "ISO 7380-1 - M8 x 16" took £10.00 each from a supplier-catalogue row matched by one
    word of its description — £124.80 on screws researched at £0.15;
  - the strip's weld and fold were honestly labelled "an unrecorded source" and then asked
    of nobody, and the quote said "Mild Steel" twice and "0 bought in" beside five bought
    lines.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import finish_rules as fr  # noqa: E402
import part_code_conventions as pcc  # noqa: E402

_BLOB = ("ROL2021-2468 ROL2021-2468 SEEDWGS-EPCGRAPHITERAL7024SATINFINISH ROL2021-2467 "
         "ROL2021-2467 SEEDWGS-EPCGRAPHITERAL7024SATINFINISH ROL2021-2466 ROL2021-2466 "
         "STAINLESSSTEEL-BRUSHED 3MM ROL2021-2406 ROL2021-2406 STEEL 651.02.909")


# ── the row's printed dimension survives the flatten ─────────────────────────────────────

def test_the_flatten_keeps_the_rows_dimension(monkeypatch):
    import bom_pipeline as bp
    import merge_boms as mb
    result = {"parents": [{"label": "ROL2021-2466", "rows": [
        {"item_number": 6, "part_ref": "ROL2021-2416", "description": "TOP BLANK",
         "quantity": 4, "material_text": "MILD STEEL - RAW", "dimension": "2 mm",
         "source": "A_ONLY"},
        {"item_number": 5, "part_ref": "ROL2021-2405", "description": "BASE RAIL",
         "quantity": 1, "material_text": "MILD STEEL RECT TUBE - RAW",
         "dimension": "30X20X2MM", "source": "A_ONLY"},
        {"item_number": 1, "part_ref": "DIN 934 - M10", "description": "Hex Nut",
         "quantity": 2, "material_text": "MILD STEEL", "source": "A_ONLY"}]}]}
    monkeypatch.setattr(mb, "reconcile_job", lambda *a, **k: result)
    rows = {r["part_number"]: r for r in
            bp.reconciled_bom_rows_for_job(pdfs=["pack.pdf"])["rows"]}
    assert rows["ROL2021-2416"]["dimension"] == "2 mm"
    assert rows["ROL2021-2405"]["dimension"] == "30X20X2MM"
    assert "dimension" not in rows["DIN 934 - M10"], "no cell, no key"


# ── a profile belongs to the row that prints it ─────────────────────────────────────────

def _post_build(part, page_text, bom_rows=(), role="assembly"):
    from document_builder import _apply_post_build_fixes, _empty_part_record
    rec = _empty_part_record(part_number=part["part_number"])
    rec.update({"pages": [3], "page_roles": [role], "materials": ["MILD STEEL"],
                "material_family": "metal"})
    rec.update(part)
    summary = {"pages": [{"page_number": 3, "page": 3, "text": page_text,
                          "page_role": {"primary_role": role}}],
               "document_analysis": {"bom_rows": list(bom_rows)}}
    _apply_post_build_fixes([rec], summary)
    return rec


_RAIL_SHEET = "MILD STEEL RECT TUBE 30 x 20 x 2mm TUBE 1214"
_RAIL_SHEET_NAMED = "30X20X2MM ROL2021-2405 ROL2021-2405 MILD STEEL RECT TUBE 1214"


def test_the_rows_own_gauge_refuses_a_shared_sheets_tube():
    row = {"part_number": "ROL2021-2416", "description": "TOP BLANK", "quantity": 4,
           "material_text": "MILD STEEL - RAW", "dimension": "2 mm"}
    got = _post_build({"part_number": "ROL2021-2416", "description": "TOP BLANK"},
                      _RAIL_SHEET, [row])
    assert got.get("bom_dimension") == "2 mm"
    assert not got.get("section_stock")
    assert any("states a sheet gauge" in str(f) for f in got.get("review_flags") or [])


def test_without_the_row_the_same_part_takes_the_tube():
    """The row is what does the work: with no printed gauge and no other part named, the
    shared callout still applies, exactly as before."""
    got = _post_build({"part_number": "ROL2021-2416", "description": "TOP BLANK"},
                      _RAIL_SHEET)
    assert got.get("section_stock")


def test_a_callout_naming_another_part_is_that_parts():
    got = _post_build({"part_number": "ROL2021-2416", "description": "TOP BLANK"},
                      _RAIL_SHEET_NAMED)
    assert not got.get("section_stock")
    assert any("names ROL2021-2405" in str(f) for f in got.get("review_flags") or [])


def test_the_named_part_keeps_its_own_callout():
    got = _post_build({"part_number": "ROL2021-2405", "description": "BASE RAIL"},
                      _RAIL_SHEET_NAMED)
    assert got.get("section_stock")


def test_a_bought_article_takes_no_stock_form():
    got = _post_build({"part_number": "DIN 934 - M10", "description": "Hex Nut",
                       "page_roles": ["assembly", "bought_in"]}, _RAIL_SHEET)
    assert not got.get("section_stock")
    assert any("bought-in article" in str(f) for f in got.get("review_flags") or [])


def test_two_rows_printing_different_stock_decide_nothing():
    rows = [{"part_number": "X-01", "description": "BRACKET", "quantity": 1,
             "dimension": "2 mm"},
            {"part_number": "X-01", "description": "BRACKET", "quantity": 1,
             "dimension": "30X20X2MM"}]
    got = _post_build({"part_number": "X-01", "description": "BRACKET"}, "NOTHING", rows)
    assert "bom_dimension" not in got
    assert got.get("bom_dimension_candidates") == ["2 mm", "30X20X2MM"]


# ── a title-block read that captured a parts list speaks for no part ─────────────────────

def test_parts_list_rows_are_told_from_a_note():
    assert fr.holds_parts_list_rows(_BLOB)
    assert not fr.holds_parts_list_rows("TO MATCH THE MAIN PANEL A A B B 4 X 6.2 THRU 30")
    assert not fr.holds_parts_list_rows("POWDER COATED RAL 9010")


def _index(finish):
    from document_builder import build_part_index
    page = {"page_number": 1, "page_role": {"primary_role": "detail"},
            "pattern_summary": {"part_numbers": []}, "geometry_summary": {},
            "page_analysis": {"title_block": {
                "drawing_numbers": ["ROL2021-2468"], "materials": ["STAINLESS STEEL"],
                "thicknesses_mm": ["3"], "surface_finishes": [finish],
                "normalized": {"primary_material": "STAINLESS_STEEL",
                               "primary_finish": finish, "primary_thickness_mm": 3.0}}}}
    parts = build_part_index({"pages": [page], "document_analysis": {"bom_rows": []}})
    return next(p for p in parts if p["part_number"] == "ROL2021-2468")


def test_a_parts_list_read_gives_no_material_gauge_or_finish():
    got = _index(_BLOB)
    assert not got.get("materials") and not got.get("normalized_material")
    assert not got.get("thicknesses_mm") and got.get("normalized_thickness_mm") is None
    assert not got.get("surface_finishes") and not got.get("normalized_finish")
    assert any("holds parts-list rows" in str(f) for f in got.get("review_flags") or [])


def test_an_ordinary_title_block_still_reads():
    got = _index("POWDER COATED RAL 9010")
    assert got.get("materials") and "STAINLESS" in str(got.get("materials")[0]).upper()
    assert got.get("normalized_thickness_mm") == 3.0


# ── a standard's designation is not priced by one word of its description ────────────────

def test_a_standards_designation_is_recognised():
    for code in ("ISO 7380-1 - M8 x 16", "ISO 7380-1-M8 X 16", "DIN 7980 - 8", "DIN934-M10"):
        assert pcc.is_standard_designation(code), code
    for code in ("DIN", "RAL7024", "651.02.909", "ROL2021-2405", "M8 X 16"):
        assert not pcc.is_standard_designation(code), code


def _catalogue_service():
    import pricing_service as ps
    svc = ps.PricingService(conn=object())
    asked = []

    def _fetch(sql, params):
        asked.append(list(params))
        return ("https://example.invalid/hex-kit", "HEXAGON KIT", 10.00, 1)
    svc._fetch_one_with_retry = _fetch
    return svc, asked


def test_a_designated_screw_skips_the_word_matched_catalogue():
    svc, asked = _catalogue_service()
    screw = {"part_number": "ISO 7380-1-M8 X 16", "is_bought_in": True,
             "page_roles": ["bought_in"],
             "description": "Hexagon Socket Button Head Screw - Product grade A"}
    assert svc._get_supplier_catalog(screw) is None
    assert asked == [], "the table is not even asked"


def test_a_component_with_no_designation_still_finds_its_category():
    svc, _ = _catalogue_service()
    kit = {"part_number": "BI-HEXKIT", "is_bought_in": True, "page_roles": ["bought_in"],
           "description": "HEXAGON KIT"}
    assert (svc._get_supplier_catalog(kit) or {}).get("unit_price_gbp") == 10.00


# ── a weld or fold on nobody's evidence is asked, with its money ─────────────────────────

def _decisions(shadow_decisions, labour_rows):
    import costed_facts
    # The sheet's calculated rows carry the money; the accepted rows say which operations
    # and parts each one is — joined on the workbook row, as a real record is.
    source = {"estimate_summary": {"part_estimates": [
                  {"part_number": "S-06M", "quantity": 1, "_canonical_kind": "leaf"}],
              "canonical_route_shadow": {"decisions": shadow_decisions},
              "workbook_labour": {"rows": [
                  {"workbook_row": r["workbook_row"], "engine_operations": r["engine_operations"],
                   "part_numbers": r["part_numbers"]} for r in labour_rows]}},
              "final_estimate": {"labour_rows": [
                  {"operation": r["operation"], "total_value_gbp": r["total_value_gbp"],
                   "workbook_row": r["workbook_row"]} for r in labour_rows]}}
    return costed_facts.costed_job(source)["decisions_required"]


def _dec(op, source, evidence=""):
    return {"operation": op, "status": "required", "target_id": "S-06M", "source": source,
            "evidence": evidence, "scope": "part", "participants": ["S-06M"]}


def _row(op, value, row):
    return {"operation": op, "engine_operations": [op], "part_numbers": ["S-06M"],
            "total_value_gbp": value, "workbook_row": row}


def test_an_unrecorded_weld_and_fold_are_decisions():
    got = _decisions([_dec("welding", "unrecorded"), _dec("folding", "unrecorded")],
                     [_row("welding", 22.33, 171), _row("dress_welds", 14.82, 177),
                      _row("folding", 20.44, 165)])
    by = {d["issue"]: d for d in got}
    weld = by.get("Welding on S-06M has no recorded source")
    fold = by.get("Folding on S-06M has no recorded source")
    assert weld and weld["gbp_at_stake"] == 37.15
    assert fold and fold["gbp_at_stake"] == 20.44


def test_a_quoted_or_sourced_weld_is_not_asked_this_way():
    got = _decisions([_dec("welding", "unrecorded", evidence="TIG WELD UNDERSIDE"),
                      _dec("folding", "drawing_notes")], [])
    assert not [d for d in got if str(d.get("issue")).endswith("has no recorded source")]


# ── the customer is told one name per material, and the bought lines are counted ─────────

def test_one_material_one_name():
    from client_quote_html import _materials_line
    parts = [{"part_number": "A", "normalized_material": "MILD STEEL"},
             {"part_number": "B", "normalized_material": "STAINLESS STEEL"},
             {"part_number": "C", "normalized_material": "MILD_STEEL"}]
    assert _materials_line(parts) == "Mild Steel, Stainless Steel"


def test_a_bought_article_on_an_assembly_sheet_is_a_bought_line():
    import quote_story as qs
    screw = {"part_number": "ISO 7380-1-M8 X 16", "page_roles": ["assembly", "bought_in"],
             "is_bought_in": True}
    rail = {"part_number": "R-66", "page_roles": ["assembly", "bought_in"],
            "_canonical_kind": "assembly"}
    assert not qs._is_assembly(screw)
    assert qs._is_assembly(rail)
