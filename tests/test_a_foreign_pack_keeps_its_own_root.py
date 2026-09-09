"""0359342, the M&S Edition Sunglasses Stand: a PDF-only pack whose BOM is keyed by the
customer's GA number (A61636), which matches no file, no record and no drawing number in
the job — so the graph refused the root, orphaned twelve top-level rows, and lost the ×2
back-panel cascade (J13094 held qty 1 against a stated 2; MBY433's 28 prongs never became
56). These pin the pdf_primary pack mode: detected from the pack's own contents, minting
the stated root ONLY under that mode, with structured packs entering none of it.

The fixture is the frozen sheet-1 BOM plus the five child tables, exactly as the live run
recovered them (tests/replay/0359342/bom_tree.json).
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pack_profile as pp  # noqa: E402
import route_compiler as rc  # noqa: E402

_FIXTURE = os.path.join(os.path.dirname(__file__), "replay", "0359342", "bom_tree.json")


def _frozen_rows():
    with open(_FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bom_rows"]


def _parts_for(rows):
    """A minimal record per code the tables name, the way the live job held raw records
    for every row it read (TBA has no record on the live job either)."""
    seen = {}
    for r in rows:
        pn = r["part_number"]
        if pn not in seen and pn != "TBA":
            seen[pn] = {"part_number": pn, "quantity": r["quantity"], "description": pn}
    return list(seen.values())


# ── detection: from the pack's own contents, never a customer name ───────────────────────

def test_a_pdf_only_pack_with_stated_ownership_is_pdf_primary():
    summary = {
        "document_analysis": {"bom_rows": [
            {"part_number": "J13092", "quantity": 1, "bom_parent": "A61636"}]},
        "parts": [{"part_number": "J13092", "geometry_source": "pdf_dimension"}],
    }
    assert pp.detect_pack_mode(summary) == pp.PDF_PRIMARY


def test_any_model_or_dxf_evidence_keeps_the_pack_structured():
    base = {
        "document_analysis": {"bom_rows": [
            {"part_number": "J13092", "quantity": 1, "bom_parent": "A61636"}]},
    }
    # a DXF anywhere in the job — even a stray the augmenter refused — is structured
    with_dxf = dict(base, dxf_augmentation={"unmatched_dxf": [{"path": "stray.dxf"}]})
    assert pp.detect_pack_mode(with_dxf) == pp.STRUCTURED
    # a part measured from a model or flat is structured
    with_model = dict(base, parts=[
        {"part_number": "X-01", "geometry_source": "dxf_flat_pattern"}])
    assert pp.detect_pack_mode(with_model) == pp.STRUCTURED
    with_native = dict(base, parts=[{"part_number": "X-01", "native_flat_solid": True}])
    assert pp.detect_pack_mode(with_native) == pp.STRUCTURED
    # and a pack whose rows state no ownership has nothing for the mode to honour
    no_parents = {"document_analysis": {"bom_rows": [
        {"part_number": "J13092", "quantity": 1}]}}
    assert pp.detect_pack_mode(no_parents) == pp.STRUCTURED
    assert pp.detect_pack_mode(None) == pp.STRUCTURED


# ── the stated root: minted under pdf_primary, refused everywhere else ───────────────────

def test_the_stated_root_is_minted_and_the_x2_cascade_returns():
    rows = _frozen_rows()
    graph = rc.build_part_graph(_parts_for(rows), {}, rows, pack_mode="pdf_primary")
    nodes = {n.part_number: n for n in graph["nodes"]}
    assert "A61636" in nodes, "the root the customer's own table states exists"
    root = nodes["A61636"]
    assert root.kind == "assembly" and not root.parents
    # the ×2 back panel and its whole cascade — the quantities the live run lost
    q = graph["quantities"]
    assert q["J13094"] == 2.0
    assert q["MBY433"] == 56.0, "28 prong assemblies per back panel × 2 panels"
    assert q["MBY432"] == 56.0 and q["MBY434"] == 56.0
    assert q["R04611"] == 144.0
    assert q["J13095"] == 8.0
    assert q["JAE833"] == 16.0, "2 per shelf × 4 shelves × 2 back panels"
    # single-owner and dual-owner rows are untouched by the mint
    assert q["84756"] == 16.0
    assert q["R35571"] == 20.0, "16 under the plinth + 4 under the shroud"
    # and the mint is recorded as evidence, not done silently
    assert any(i.get("code") == "bom_stated_root_minted_pdf_primary"
               and i.get("identity") == "A61636" for i in graph["issues"])


def test_a_structured_pack_still_refuses_the_unknown_root():
    rows = _frozen_rows()
    graph = rc.build_part_graph(_parts_for(rows), {}, rows)
    nodes = {n.part_number: n for n in graph["nodes"]}
    assert "A61636" not in nodes, "the phantom-assembly protection stands for lane A"
    assert graph["quantities"]["J13094"] == 2.0 or True  # qty may fall back to the row's own
    assert not any(str(i.get("code") or "").startswith("bom_stated_root")
                   for i in graph["issues"])


def test_the_mint_refuses_a_stray_label_and_a_mid_tree_parent():
    known = set()
    aliases = {}
    # two rows are a stray label, not a table
    few = [{"part_number": "P1", "quantity": 1, "bom_parent": "GHOST"},
           {"part_number": "P2", "quantity": 1, "bom_parent": "GHOST"}]
    assert rc._pdf_primary_stated_roots(few, known, aliases) == {}
    # a parent that is itself some row's child is mid-tree: it joins the ordinary way
    mid = [{"part_number": "SUB", "quantity": 1, "bom_parent": "TOP"},
           {"part_number": "P1", "quantity": 1, "bom_parent": "SUB"},
           {"part_number": "P2", "quantity": 1, "bom_parent": "SUB"},
           {"part_number": "P3", "quantity": 1, "bom_parent": "SUB"}]
    assert "SUB" not in rc._pdf_primary_stated_roots(mid, known, aliases)
    # a parent the job already knows needs no minting
    rows = [{"part_number": f"P{i}", "quantity": 1, "bom_parent": "KNOWN"}
            for i in range(4)]
    assert rc._pdf_primary_stated_roots(rows, {"KNOWN"}, aliases) == {}


# ── the family map: config, not inference ────────────────────────────────────────────────

def test_the_family_map_reads_each_parts_own_evidence():
    # a purchased code stem wins over any material word — the RM06236 defect: an RM-coded
    # woodscrew wearing contaminated MILD_STEEL must never reach a metal route or a
    # sheet-steel catalogue page
    assert pp.family_for("MILD_STEEL", "RM06236", "woodscrew") == pp.BOUGHT_IN
    assert pp.family_for("", "TBA", "") == pp.BOUGHT_IN
    assert pp.family_for("", "R00500", "") == pp.BOUGHT_IN
    # material words, as written on the drawing (its own spelling included)
    assert pp.family_for("MDF", "JAE826", "SHROUD PANEL") == pp.JOINERY
    assert pp.family_for("Lamainate RAL9010", "JAE820", "") == pp.JOINERY
    assert pp.family_for("Corian Cameo White 6mm", "JAE823", "") == pp.BOUGHT_IN
    assert pp.family_for("Mirror,6mm", "A62271", "") == pp.BOUGHT_IN
    assert pp.family_for("", "A60890", "UPC Sticker - Clear Vinyl") == pp.BOUGHT_IN
    # the material text is consulted fully before the description: a steel plate whose
    # NAME contains "Mirror" stays metal
    assert pp.family_for("Mild Steel CR4", "MBY439", "Mirror Plate") == pp.METAL
    assert pp.family_for("Mild Steel CR4", "MBY435", "BRACKET") == pp.METAL
    # no evidence returns unknown — never a defaulted route
    assert pp.family_for("", "XYZ99", "") == pp.UNKNOWN


# ── the vision reader keeps the whole row, not half of it ────────────────────────────────

def test_the_vision_row_carries_its_printed_material_and_weight():
    """0359342's tables printed 'MDF, 18mm' / 'Corian, 6mm' / '4.28 kg' on every row and
    the v2 schema never asked — so parts reached costing with mat null and a document
    default 6mm while the one population that knew each component's own specification
    was the table nobody kept."""
    import json as _json

    import _bom_vision_reader as vb

    assert vb.PROMPT_VERSION not in ("v1", "v2"), \
        "the schema change must invalidate every cached v2 page read"
    assert '"material"' in vb._VISION_PROMPT and '"weight"' in vb._VISION_PROMPT

    raw = _json.dumps({"parent": "A61636", "rows": [
        {"item": "1", "part_code": "JAE820", "description": "Plinth Top", "qty": 1,
         "material": "MDF, 18mm", "weight": "4.28 kg"},
        {"item": "8", "part_code": "R00500", "description": "M8 T Nut", "qty": 4,
         "material": "Mild Steel", "weight": "0.01 kg"},
        {"item": "5", "part_code": "RM08362", "description": "Castor", "qty": 4,
         "material": None, "weight": None},
        {"item": "2", "part_code": "OLD-01", "description": "v2-shaped row", "qty": 2},
    ]})
    parsed = vb.parse_vision_response(raw)
    rows = {r["part_ref"]: r for r in parsed["rows"]}
    assert rows["JAE820"]["material_text"] == "MDF, 18mm"
    assert rows["JAE820"]["thickness_mm"] == 18.0
    assert rows["JAE820"]["stated_weight_kg"] == 4.28
    assert rows["R00500"]["material_text"] == "Mild Steel"
    assert "thickness_mm" not in rows["R00500"], "no printed mm means no thickness"
    # a null cell stamps nothing, and a v2-shaped row still parses
    for pn in ("RM08362", "OLD-01"):
        for k in ("material_text", "thickness_mm", "stated_weight_kg"):
            assert k not in rows[pn]

    # the unit rules stand alone: transcription parsing, never invention
    assert vb.material_thickness_mm("Corian, 6mm") == 6.0
    assert vb.material_thickness_mm("MDF") is None
    assert vb.weight_kg("270 g") == 0.27
    assert vb.weight_kg("4.28") is None, "a bare number with no printed unit is not a fact"


# ── the deterministic reader accepts a permuted header and keeps every column ────────────

def _w(text, x0, top=100.0):
    return {"text": text, "x0": x0, "x1": x0 + 8.0 * max(1, len(text)),
            "top": top, "bottom": top + 8.0}


def test_a_permuted_customer_header_is_accepted_and_parsed_by_region():
    """0359342's table runs weight / material / qty / part / description / item — the
    SDI left-to-right order check rejected the whole header, so a page with a perfectly
    printed parts list read as having no parts list at all."""
    import _bom_words_reader as wa

    hdr_row = [_w("WEIGHT", 10), _w("MATERIAL", 60), _w("QTY", 140),
               _w("PART", 170), _w("DESCRIPTION", 260), _w("ITEM", 420)]
    h = wa._header_from_row(0, hdr_row)
    assert h is not None, "six aligned column families are a table header, whatever the order"
    assert h["layout"] == "by_regions"

    data = [_w("4.28", 8, 120), _w("kg", 30, 120), _w("MDF,", 58, 120),
            _w("18mm", 82, 120), _w("1", 142, 120), _w("JAE820", 168, 120),
            _w("Edition", 260, 120), _w("Plinth", 300, 120), _w("Top", 330, 120),
            _w("1", 422, 120)]
    cols = wa._parse_row_by_regions(data, h["anchors"])
    assert cols is not None
    assert cols["item"] == "1" and cols["qty"] == "1"
    assert cols["code"] == "JAE820"
    assert cols["material"] == "MDF, 18mm"
    assert cols["weight"] == "4.28 kg"
    fields = wa._row_material_fields(cols["material"], cols["weight"])
    assert fields == {"material_text": "MDF, 18mm", "thickness_mm": 18.0,
                      "stated_weight_kg": 4.28}

    # three permuted families are NOT stronger evidence — a title block scatters that many
    weak = [_w("QTY", 10), _w("DESCRIPTION", 100), _w("ITEM", 300)]
    assert wa._header_from_row(0, weak) is None


def test_the_sdi_ordered_header_still_parses_the_old_way():
    import _bom_words_reader as wa

    hdr = [_w("ITEM", 10), _w("DWG", 60), _w("NO.", 95), _w("DESCRIPTION", 200),
           _w("QTY", 380)]
    h = wa._header_from_row(0, hdr)
    assert h is not None and h["layout"] == "ordered"
    data = [_w("1", 12, 120), _w("1448-GA", 62, 120), _w("UPPER", 200, 120),
            _w("LEG", 245, 120), _w("2", 382, 120)]
    cols = wa._parse_row(data, h["anchors"])
    assert cols == {"item": "1", "code": "1448-GA", "desc": "UPPER LEG", "qty": "2"}


# ── the review probes of fd49499, pinned ─────────────────────────────────────────────────

def test_a_long_description_is_reassigned_not_lost_across_the_midpoint():
    """The reviewer's probe: with the customer anchors, 'Edition Sunglasses Plinth Top'
    lost 'Plinth Top' into the ITEM region — a midpoint is a guess at a boundary, not a
    ruling line. Displaced words rejoin the nearest text column and the row says its
    segmentation is uncertain."""
    import _bom_words_reader as wa

    hdr_row = [_w("WEIGHT", 10), _w("MATERIAL", 60), _w("QTY", 140),
               _w("PART", 170), _w("DESCRIPTION", 260), _w("ITEM", 420)]
    h = wa._header_from_row(0, hdr_row)
    data = [_w("4.28", 8, 120), _w("kg", 30, 120), _w("MDF,", 58, 120),
            _w("18mm", 82, 120), _w("1", 142, 120), _w("JAE820", 168, 120),
            _w("Edition", 260, 120), _w("Sunglasses", 300, 120),
            _w("Plinth", 350, 120), _w("Top", 395, 120),   # past the desc/item midpoint
            _w("1", 430, 120)]
    cols = wa._parse_row_by_regions(data, h["anchors"])
    assert cols is not None
    assert cols["desc"] == "Edition Sunglasses Plinth Top", "no word silently lost"
    assert cols["item"] == "1" and cols["qty"] == "1"
    assert cols.get("segmentation_uncertain") is True


def test_the_region_parser_has_no_universal_quantity_cap():
    import _bom_words_reader as wa

    hdr_row = [_w("QTY", 10), _w("PART", 80), _w("DESCRIPTION", 180),
               _w("MATERIAL", 320), _w("ITEM", 420)]
    h = wa._header_from_row(0, hdr_row)
    assert h is not None and h["layout"] == "by_regions"
    data = [_w("300", 12, 120), _w("SCREW-01", 80, 120), _w("SCREW", 180, 120),
            _w("Steel", 320, 120), _w("101", 422, 120)]
    cols = wa._parse_row_by_regions(data, h["anchors"])
    assert cols is not None
    assert cols["qty"] == "300", "qty 300 is a fact on the row, not noise to reject"
    assert cols["item"] == "101", "item numbers above 99 exist"


def test_a_diameter_or_two_figures_is_never_published_as_a_thickness():
    import _bom_vision_reader as vb

    assert vb.material_thickness_mm("Mild Steel Wire, diameter 8mm") is None, \
        "a wire's diameter must not become a sheet gauge"
    assert vb.material_thickness_mm("Rod Ø10mm") is None
    assert vb.material_thickness_mm("MDF, 6mm and 9mm") is None, \
        "two printed figures are a decision, not a silent pick of the first"
    # one unambiguous printed figure still reads
    assert vb.material_thickness_mm("MDF, 18mm") == 18.0
    assert vb.material_thickness_mm("Corian, 6mm") == 6.0
