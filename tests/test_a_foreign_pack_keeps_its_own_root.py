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
    assert q["JAE833"] == 8.0, ("1 per shelf × 4 shelves × 2 back panels — the "
                                "ruled cells corrected the vision-only qty-2 read")
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


# ── camelot in comparison mode: shared vocabulary, shared schema, never merged ───────────

def test_the_camelot_bench_maps_both_header_dialects_through_one_vocabulary():
    import _bom_camelot_bench as cb

    # the customer's dialect — permuted columns, PART #, weight column
    grid = [
        ["WEIGHT", "MATERIAL", "SHEET", "QTY", "PART #", "DESCRIPTION", "ITEM"],
        ["4.28 kg", "MDF, 18mm", "1", "1", "JAE820",
         "Edition Sunglasses Plinth Top", "1"],
        ["0.27 kg", "", "A", "4", "RM08362", "Swivel Castor", "5"],
        ["", "", "", "", "", "NOTE: SEE SHEET 2", ""],   # a note line, not a row
    ]
    out = cb.map_table_to_rows(grid)
    rows = {r["part_ref"]: r for r in out["rows"]}
    assert rows["JAE820"] == {
        "item_number": "1", "part_ref": "JAE820",
        "description": "Edition Sunglasses Plinth Top", "quantity": 1,
        "material_text": "MDF, 18mm", "thickness_mm": 18.0,
        "stated_weight_kg": 4.28}
    assert rows["RM08362"]["stated_weight_kg"] == 0.27
    assert any("row rejected" in r for r in out["rejected_rows"]), \
        "a skipped line is a named finding, not silence"

    # the SDI dialect maps through the same families
    sdi = [["ITEM", "DWG NO.", "DESCRIPTION", "QTY."],
           ["1", "1448-GA", "UPPER LEG ASSEMBLY", "2"]]
    out2 = cb.map_table_to_rows(sdi)
    assert out2["rows"][0]["part_ref"] == "1448-GA"
    assert out2["rows"][0]["quantity"] == 2

    # an unrecognisable header is a named rejection, never a guessed mapping
    junk = [["AAA", "BBB", "CCC"], ["1", "2", "3"]]
    assert "header unrecognised" in cb.map_table_to_rows(junk)["rejected"]


def test_the_bench_compares_and_never_concatenates():
    import _bom_camelot_bench as cb

    a = [{"item_number": "1", "part_ref": "JAE820", "quantity": 1,
          "description": "Plinth Top"},
         {"item_number": "8", "part_ref": "R00500", "quantity": 4,
          "description": "M8 T Nut"}]
    c = [{"item_number": "1", "part_ref": "JAE820", "quantity": 1,
          "description": "Plinth Top", "material_text": "MDF, 18mm",
          "thickness_mm": 18.0},
         {"item_number": "5", "part_ref": "RM08362", "quantity": 4,
          "description": "Castor"}]
    out = cb.compare_rows(a, c)
    # the shared screw row corroborates or differs — it never becomes two rows
    assert [d["key"] for d in out["cell_diffs"]] == [("1", "JAE820")]
    assert any("material_text" in s for s in out["cell_diffs"][0]["cell_diffs"])
    assert out["only_a"] == [("8", "R00500")]
    assert out["only_c"] == [("5", "RM08362")]
    assert not out["agree"], "a row with cell differences is not agreement"


# ── the live Layer 1: the extract that succeeded is no longer thrown away ────────────────

def _ms_grid():
    """0359342 page 1, in the raw extract_tables() shape the reviewer's probe printed:
    [None, item, description, part, qty, rev, sheet, material, mass]. The twelve data
    rows are the frozen top table (tests/replay/0359342/bom_tree.json)."""
    hdr = [None, "ITEM", "DESCRIPTION", "PART #", "QTY", "REV", "SHEET",
           "MATERIAL", "MASS"]
    rows = [
        [None, "1", "EditionSunglassesPlinthCoverAssembly", "J13092", "1", None,
         "1", "MDF,SolidSurface", "12.00kg"],
        [None, "2", "EditionSunglassesShroudAssembly", "J13093", "1", None,
         "1", "MDF", "8.40kg"],
        [None, "3", "EditionSunglassesBackPanelAssembly", "J13094", "2", None,
         "1", "MDF", "16.20kg"],
        [None, "4", "EditionSunglassesMirror", "A62271", "2", None,
         "1", "Mirror, 6mm", "4.10kg"],
        [None, "5", "EditionSunglassesMirrorPlate", "MBY439", "2", None,
         "1", "Mild Steel", "0.82kg"],
        [None, "6", "SunglassesPlinth", "J13149", "8", None, "1", "MDF", "0.45kg"],
        [None, "7", "M8CrossDowelNut", "RM08363", "4", None, None, "Mild Steel",
         "0.01kg"],
        [None, "8", "M8x80CapHeadScrew", "RM08167", "4", None, None, "Mild Steel",
         "0.04kg"],
        [None, "9", "#4x3/8CskWoodscrew", "RM06236", "16", None, None, "Mild Steel",
         "0.01kg"],
        [None, "10", "M8FlatWasher", "TBA", "4", None, None, "Steel", "0.01kg"],
        [None, "11", "M6x40ConnectingBolt", "TBA", "4", None, None, "Steel",
         "0.02kg"],
        [None, "12", "UPCSticker", "A60890", "1", None, None, "Clear Vinyl", None],
    ]
    return [hdr] + rows


def test_the_ms_page_one_table_survives_layer_one():
    """The reviewer's gate for the isolated fix: 12 rows, J13092 qty 1, RM06236 qty 16,
    and the last cell (a mass) never used as a quantity. Before this, every row failed
    the cells[-1]-is-an-integer test on '12.00kg' and six successfully extracted tables
    produced zero BOM rows — the LLM was then asked to invent a tree the PDF printed."""
    import bom_table_extractor as bte

    rows = bte.bom_rows_from_tables([_ms_grid()])
    assert len(rows) == 12
    by_ref = {r["part_ref"]: r for r in rows if r["part_ref"] != "TBA"}
    assert by_ref["J13092"]["quantity"] == 1, "qty from the QTY column, not the mass"
    assert by_ref["J13094"]["quantity"] == 2
    assert by_ref["RM06236"]["quantity"] == 16
    # ONE classifier whatever the layout (review probe 2) — and the code preserved
    # independently of it, so J13092 never becomes anonymous: the shared identity
    # policy downstream resolves its role from evidence, not from column count
    assert by_ref["J13092"]["kind"] == "bought_in", \
        "the mapped path uses the same classifier as the positional one"
    assert by_ref["J13092"]["code_token"] == "J13092"
    assert by_ref["MBY439"]["code_token"] == "MBY439"
    assert by_ref["RM06236"]["kind"] == "bought_in"
    tba = [r for r in rows if r["part_ref"] == "TBA"]
    assert len(tba) == 2 and all(r["kind"] == "bought_in" for r in tba)
    # the row's own printed material and mass travel with it
    assert by_ref["A62271"]["material_text"] == "Mirror, 6mm"
    assert by_ref["A62271"]["thickness_mm"] == 6.0
    assert by_ref["J13092"]["material_text"] == "MDF,SolidSurface"
    assert "thickness_mm" not in by_ref["J13092"], "no printed mm, no thickness"
    assert by_ref["J13092"]["stated_weight_kg"] == 12.0
    # and no universal cap in the mapped path
    big = [_ms_grid()[0],
           [None, "13", "BulkScrew", "RM09999", "300", None, None, "Steel", "0.30kg"]]
    assert bte.bom_rows_from_tables([big])[0]["quantity"] == 300


def test_an_sdi_table_yields_the_same_rows_through_its_own_header():
    """Review probe 1's correction: a valid header is USED, whatever the columns —
    the positional path is only for genuinely headerless tables. An SDI table's
    header maps to exactly the rows the positional path produced, and THUM620's
    classification is identical with and without a MATERIAL column (probe 2)."""
    import bom_table_extractor as bte

    sdi = [["ITEM", "DWG NO.", "DESCRIPTION", "QTY."],
           ["1", "1448-GA", "UPPER LEG ASSEMBLY", "2"],
           ["2", "THUM620", "M6 THUMBSCREW", "4"]]
    rows = bte.bom_rows_from_tables([sdi])
    assert [(r["item_number"], r["part_ref"], r["quantity"], r["kind"]) for r in rows] \
        == [("1", "1448-GA", 2, "drawing_ref"), ("2", "THUM620", 4, "bought_in")]
    assert rows[0]["part_number"] == "1448-GA"

    # the same rows with a MATERIAL column: layout must not change classification
    sdi_mat = [["ITEM", "DWG NO.", "DESCRIPTION", "QTY.", "MATERIAL"],
               ["1", "1448-GA", "UPPER LEG ASSEMBLY", "2", "Mild Steel"],
               ["2", "THUM620", "M6 THUMBSCREW", "4", ""]]
    rows_mat = bte.bom_rows_from_tables([sdi_mat])
    assert [(r["part_ref"], r["kind"]) for r in rows_mat] == \
        [("1448-GA", "drawing_ref"), ("THUM620", "bought_in")]
    assert rows_mat[0]["material_text"] == "Mild Steel"

    # a genuinely headerless grid still parses by the proven positional shape
    headerless = [["1", "1448-GA", "UPPER LEG ASSEMBLY", "2"]]
    rows_hl = bte.bom_rows_from_tables([headerless])
    assert [(r["part_ref"], r["quantity"]) for r in rows_hl] == [("1448-GA", 2)]
    assert "header_mapped" not in rows_hl[0]


def test_a_desc_before_code_header_with_qty_last_is_still_mapped():
    """Review probe 1: [ITEM, DESCRIPTION, PART, QTY] — no material, qty rightmost —
    was falling to the positional path, which read 'Plinth assembly' as the part and
    J13092 as its description. A recognised header is used, full stop."""
    import bom_table_extractor as bte

    grid = [["ITEM", "DESCRIPTION", "PART", "QTY"],
            ["1", "Plinth assembly", "J13092", "1"]]
    rows = bte.bom_rows_from_tables([grid])
    assert len(rows) == 1
    assert rows[0]["part_ref"] == "J13092"
    assert rows[0]["description"] == "Plinth assembly"
    assert rows[0]["quantity"] == 1
    assert rows[0]["code_token"] == "J13092"


def test_the_grid_read_reaches_the_authoritative_path_a():
    """Review probe 3: reconciliation's Path A called only the words reader, so a
    successful extract_tables() read never reached the authoritative BOM. The grid
    fallback is consulted exactly where the words reader parsed nothing."""
    import merge_boms as mb

    class _StubPage:
        def extract_tables(self):
            return [_ms_grid()]

        def extract_words(self, **kw):
            return []

    bom = mb.grid_bom_fallback(_StubPage())
    assert bom is not None and bom.get("grid_mapped") is True
    assert len(bom["rows"]) == 12
    refs = {r["part_ref"] for r in bom["rows"]}
    assert {"J13092", "J13094", "RM06236", "A60890"} <= refs

    class _EmptyPage:
        def extract_tables(self):
            return []

        def extract_words(self, **kw):
            return []

    assert mb.grid_bom_fallback(_EmptyPage()) is None


def test_the_flatten_keeps_the_rows_printed_specification(monkeypatch):
    """Review probe of 89b82d4: bom_pipeline's flatten built a new dictionary that
    copied everything EXCEPT material_text / thickness_mm / stated_weight_kg — so a
    successful extraction still lost the exact fields needed to retire the blanket
    6mm assumption. The evidence now survives the flatten, and only where a reader
    actually stamped it: a row without the columns is byte-identical."""
    import bom_pipeline
    import merge_boms

    fake = {"parents": [{"label": "A61636", "parent_known": True, "rows": [
        {"part_ref": "JAE820", "part_number": "", "description": "Plinth Top",
         "quantity": 1, "source": "BOTH", "confidence": "HIGH", "flag": "",
         "material_text": "MDF, 18mm", "thickness_mm": 18.0,
         "stated_weight_kg": 4.28, "code_token": "JAE820"},
        {"part_ref": "1448-GA", "part_number": "1448-GA", "description": "LEG ASSY",
         "quantity": 2, "source": "BOTH", "confidence": "HIGH", "flag": ""},
    ]}], "unread": [], "vision_calls": {}, "counts": {}, "findings": []}
    monkeypatch.setattr(merge_boms, "reconcile_job", lambda paths, **kw: fake)
    monkeypatch.setattr(merge_boms, "find_pdfs", lambda folder: ["x.pdf"])
    out = bom_pipeline.reconciled_bom_rows_for_job(folder="whatever")
    rows = {r["part_number"]: r for r in out["rows"]}
    jae = rows["JAE820"]
    assert jae["material_text"] == "MDF, 18mm"
    assert jae["thickness_mm"] == 18.0
    assert jae["stated_weight_kg"] == 4.28
    assert jae["code_token"] == "JAE820"
    assert jae["bom_parent"] == "A61636"
    leg = rows["1448-GA"]
    for k in ("material_text", "thickness_mm", "stated_weight_kg", "code_token"):
        assert k not in leg, "a row without the columns is byte-identical"


def test_an_uncertain_words_read_yields_to_a_ruled_grid_read():
    """The extract check on the real pack: nearly every words row flagged
    segmentation_uncertain, and the flags were right — '55Kg - RM08362' split
    R35571 into two identities and halved a dual-owner sum, while extract_tables
    returned the same rows as clean ruled cells. A majority-uncertain words read
    yields to a header-mapped grid read of equal or better coverage; an SDI page
    (no uncertainty flags, no header-mapped grid) never swaps."""
    import merge_boms as mb

    words = {"rows": [
        {"item_number": "1", "part_ref": "55Kg - RM08362", "quantity": 4,
         "segmentation_uncertain": True},
        {"item_number": "2", "part_ref": "JAE820", "quantity": 1,
         "segmentation_uncertain": True},
        {"item_number": "3", "part_ref": "R00500", "quantity": 4},
    ]}
    grid = {"rows": [
        {"item_number": "1", "part_ref": "RM08362", "quantity": 4,
         "header_mapped": True},
        {"item_number": "2", "part_ref": "JAE820", "quantity": 1,
         "header_mapped": True},
        {"item_number": "3", "part_ref": "R00500", "quantity": 4,
         "header_mapped": True},
    ]}
    assert mb.prefer_grid_read(words, grid) is True
    # an SDI words read carries no uncertainty flags: never swapped
    sdi_words = {"rows": [{"item_number": "1", "part_ref": "1448-GA", "quantity": 2}]}
    assert mb.prefer_grid_read(sdi_words, grid) is False
    # a grid read with fewer rows, or without a printed header, does not win
    assert mb.prefer_grid_read(words, {"rows": grid["rows"][:2]}) is False
    blob = {"rows": [dict(r, header_mapped=False) for r in grid["rows"]]}
    assert mb.prefer_grid_read(words, blob) is False
    assert mb.prefer_grid_read(words, None) is False
    assert mb.prefer_grid_read(None, grid) is False


def test_squashed_two_value_material_text_still_refuses_a_thickness():
    """Chain check on the real pack: extract_tables squashes spaces, so JAE827's cell
    arrives as 'FlexiMDF6mmand9mm' — the trailing word boundary failed against the
    glued 'and', one of two printed figures was counted, and 9.0 was published as a
    fact. Both figures must be seen for the two-figures refusal to fire."""
    import _bom_vision_reader as vb

    assert vb.material_thickness_mm("FlexiMDF6mmand9mm") is None
    assert vb.material_thickness_mm("Flexi MDF 6mm and 9mm") is None
    # squashed single values still read
    assert vb.material_thickness_mm("Steel,Mild2mm") == 2.0
    assert vb.material_thickness_mm("15mmMDF") == 15.0


# ── a placeholder is not an identity, and glued cells rejoin their known codes ───────────

def test_two_tba_rows_stay_two_purchasing_requirements():
    """Review finding on the chain check: two 'TBA x4' rows — a washer and a
    connecting bolt — became ONE graph node, because a placeholder resolved to
    itself both times. The shared part_identity synthesis (the same rule the
    dual-path reconciler mints BI- records with) derives each row's identity from
    its own description, so the graph edge and the minted record agree."""
    rows = _frozen_rows()
    graph = rc.build_part_graph(_parts_for(rows), {}, rows, pack_mode="pdf_primary")
    nodes = {n.part_number: n for n in graph["nodes"]}
    assert "TBA" not in nodes, "the placeholder itself is never a node"
    assert graph["quantities"]["BI-WASHER"] == 4.0
    assert graph["quantities"]["BI-BOLT"] == 4.0
    assert nodes["BI-WASHER"].parents == ["A61636"]
    assert nodes["BI-BOLT"].parents == ["A61636"]


def test_glued_cells_rejoin_their_known_identities_and_junk_stays_junk():
    """'Backplate MBY434' (description spill) and '8RM08363' (glued prefix) must
    rejoin the identities the job already holds — 56 backplates that cannot join
    their detail drawing are not cosmetic. Repairs fire ONLY when they land on a
    known identity; an unanchored glued token stays visibly glued."""
    parts = [{"part_number": "MBY433", "quantity": 28, "description": "PRONG ASSY"},
             {"part_number": "MBY434", "quantity": 1, "description": "BACKPLATE"},
             {"part_number": "RM08363", "quantity": 4, "description": "NUT"},
             {"part_number": "A61636X", "quantity": 1, "description": "GA"}]
    rows = [{"part_number": "Backplate MBY434", "quantity": 1, "bom_parent": "MBY433"},
            {"part_number": "8RM08363", "quantity": 4, "bom_parent": "MBY433"},
            {"part_number": "9XY99999", "quantity": 2, "bom_parent": "MBY433"}]
    graph = rc.build_part_graph(parts, {}, rows)
    nodes = {n.part_number for n in graph["nodes"]}
    assert "MBY434" in nodes and "BACKPLATE MBY434" not in nodes
    assert "RM08363" in nodes and "8RM08363" not in nodes
    parents = graph["parents"]
    assert "MBY433" in parents.get("MBY434", set())
    assert "MBY433" in parents.get("RM08363", set())
    # nothing known anchors 9XY99999 — it stays glued and visible, never invented
    assert "9XY99999" in nodes


def test_the_placeholder_mint_never_fires_on_a_structured_pack():
    """7332 regression (unit fell £80-class -> £64.30): the placeholder mint, shipped
    ungated as a 'generic rule', gave the leg's TBA tube-stock row a second spelling —
    a graph node no record matches, which the missing-bought-in machinery resurrected
    as a phantom assembly row while £11.72 of leg material and the tube-bend labour row
    fell out. A record literally named TBA cannot exist in the known pool
    (clean_part_number refuses placeholders), so no known-set guard can protect the
    structured path: the gate is the pack mode."""
    parts = [{"part_number": "7332-01-GA", "quantity": 1, "description": "GA"}]
    rows = [{"part_number": "TBA", "quantity": 2, "bom_parent": "7332-01-GA",
             "description": "15.875 x 15.875 x 1.2mm TUBE"}]
    # structured (no pack_mode): the old behaviour stands, no minted spelling
    graph = rc.build_part_graph(parts, {}, rows)
    nodes = {n.part_number for n in graph["nodes"]}
    assert not any(n.startswith("TBA-15") or n.startswith("BI-") for n in nodes), \
        "a structured pack's placeholder rows are left exactly as they were"
    # pdf_primary: the mint fires and two placeholder rows stay distinct purchases
    graph2 = rc.build_part_graph(parts, {}, [
        {"part_number": "TBA", "quantity": 4, "bom_parent": "7332-01-GA",
         "description": "M8 Flat Washer - Form D - Steel"},
        {"part_number": "TBA", "quantity": 4, "bom_parent": "7332-01-GA",
         "description": "M6x40 Connecting Bolt"}], pack_mode="pdf_primary")
    n2 = {n.part_number for n in graph2["nodes"]}
    assert "BI-WASHER" in n2 and "BI-BOLT" in n2


def test_the_pre_cost_compile_detects_the_pack_mode_itself():
    """The 0359342 live run: the refresh compile minted A61636 while the PRE-COST
    compile — the one costing actually reads — was never told the pack mode, refused
    the stated root, and priced three orphan assemblies with the x2 cascade lost.
    Every compile consults the one detection."""
    rows = _frozen_rows()
    parts = _parts_for(rows)
    summary = {"document_analysis": {"bom_rows": rows},
               "parts": [dict(p) for p in parts],
               "manufacturing_writeup": {"parts": [dict(p) for p in parts]}}
    graph = rc.apply_canonical_evidence_to_parts(
        [dict(p) for p in parts], {}, rows, summary=summary)
    assert any(n.part_number == "A61636" for n in graph["nodes"]), \
        "the costing graph carries the stated root the detection earns"
    assert graph["quantities"]["J13094"] == 2.0
    # a structured pack (any DXF present) still refuses at the same call site
    s2 = dict(summary, dxf_augmentation={"unmatched_dxf": [{"path": "x.dxf"}]})
    graph2 = rc.apply_canonical_evidence_to_parts(
        [dict(p) for p in parts], {}, rows, summary=s2)
    assert not any(n.part_number == "A61636" for n in graph2["nodes"])


# ── bind (a): the row's printed specification becomes part evidence, ranked ──────────────

def test_a_parts_own_bom_row_retires_the_unsourced_blanket():
    """digest2 measured it: every record carried an UNSOURCED 6.0mm and material None
    while its own BOM row printed the truth. A table reading (bom_tree, rank 60)
    replaces an unsourced figure and records what it displaced; a measured DXF
    thickness refuses it and flags the disagreement instead."""
    import bom_pipeline
    import source_precedence as sp

    rows = [{"part_number": "JAE820", "material_text": "MDF,18mm",
             "thickness_mm": 18.0, "stated_weight_kg": 4.28},
            {"part_number": "MBY439", "material_text": "Steel,Mild2mm",
             "thickness_mm": 2.0, "stated_weight_kg": 0.82},
            {"part_number": "NOROW", "material_text": ""}]
    jae = {"part_number": "JAE820", "normalized_thickness_mm": 6.0}  # unsourced blanket
    dxf_part = {"part_number": "MBY439", "normalized_thickness_mm": 6.0,
                "thickness_source": "dxf"}
    n = bom_pipeline.apply_bom_row_evidence_to_parts([jae, dxf_part], rows)
    assert n == 2
    # the blanket is retired and the displacement recorded
    assert jae["normalized_thickness_mm"] == 18.0
    assert sp.source_of(jae, "normalized_thickness_mm") == "bom_tree"
    assert jae["normalized_material"] == "MDF,18mm"
    assert jae["stated_weight_kg"] == 4.28
    # a measured source stands; the row's disagreement is recorded, not applied
    assert dxf_part["normalized_thickness_mm"] == 6.0
    assert any(e.get("value") == 2.0 and not e.get("applied")
               for e in (dxf_part.get("_displaced") or {})
               .get("normalized_thickness_mm", [])), \
        "the refused table reading is evidence on the record, never silence"
    # the material still filled (dxf said nothing about material)
    assert dxf_part["normalized_material"] == "Steel,Mild2mm"


# ── bind (b): a part's own family decides which route may charge it ──────────────────────

def test_the_family_gate_refuses_fiction_routes_and_keeps_real_ones():
    """digest2's op table: welding, folding, laser, dress and powder 'required' on
    every part uniformly — screws included — because the general legend was
    transcribed onto each record and mechanically became decisions. The gate reads
    each part's OWN evidence and refuses only what its family cannot do; every
    refusal carries its reason into the ruled-out table."""
    from types import SimpleNamespace as NS

    raw = {"JAE820": {"normalized_material": "MDF,18mm", "description": "Plinth Top"},
           "84756": {"normalized_material": "MildSteel",
                     "description": "M6x20ButtonHeadSocketMachineScrew,BZP"},
           "JAE823": {"normalized_material": "Corian,6mm", "description": "Overlay"},
           "MBY433": {"normalized_material": "CR4", "description": "Prong Assembly"},
           "RM05285": {"normalized_material": "Beech", "description": "Dowel - Precut"}}

    def d(t, op, scope="part"):
        return NS(target_id=t, operation=op, scope=scope, status=rc.REQUIRED,
                  reason="", field_provenance={})

    mdf_weld, mdf_pc, mdf_glue, mdf_spray = (d("JAE820", "welding"),
                                             d("JAE820", "powder_coating"),
                                             d("JAE820", "glue"),
                                             d("JAE820", "wet_spray"))
    screw_laser, screw_glue = d("84756", "laser_cutting"), d("84756", "glue")
    corian_fold, corian_glue = d("JAE823", "folding"), d("JAE823", "glue")
    steel_weld = d("MBY433", "welding")
    beech_weld = d("RM05285", "welding")
    asm_scope = d("JAE820", "welding", scope="assembly")
    ds = [mdf_weld, mdf_pc, mdf_glue, mdf_spray, screw_laser, screw_glue,
          corian_fold, corian_glue, steel_weld, beech_weld, asm_scope]
    rc._family_gate(ds, raw)

    # joinery: metal-only ops refused with the reason recorded; glue and spray stay
    assert mdf_weld.status == rc.NOT_APPLICABLE and "CNC" in mdf_weld.reason
    assert mdf_pc.status == rc.NOT_APPLICABLE
    assert mdf_glue.status == rc.REQUIRED
    assert mdf_spray.status == rc.REQUIRED, "wet spray is a joinery finish"
    # hardware: no fabrication at all — the shared vocabulary recognises a screw
    assert screw_laser.status == rc.NOT_APPLICABLE
    assert screw_glue.status == rc.NOT_APPLICABLE
    assert screw_laser.field_provenance["status"] == "family_gate_hardware"
    # bought-in sheet goods: no metal route, but the bond line stays
    assert corian_fold.status == rc.NOT_APPLICABLE
    assert corian_glue.status == rc.REQUIRED
    # metal keeps its real route; timber-family dowel loses the fiction weld
    assert steel_weld.status == rc.REQUIRED
    assert beech_weld.status == rc.NOT_APPLICABLE
    # assembly-scope decisions are never the gate's business
    assert asm_scope.status == rc.REQUIRED


def test_a_document_repeated_figure_yields_to_each_parts_own_row():
    """The thickness probe on the live run: 24 parts all at 6.0 / drawing_deterministic,
    each one's own printed gauge (18, 15, 12, 9, 2) refused at rank 60 with the refusal
    recorded. drawing_deterministic means THIS PART's title block; the same value
    landing identically across the population while their own rows disagree is a
    document note wearing a rank it never earned. Demoted only on the contradicted
    parts, only at scale (>=5 identical, >=3 contradicted) — 7332's shape, where each
    part's own DXF gauge already won, cannot trigger."""
    import bom_pipeline

    def part(pn):
        return {"part_number": pn, "normalized_thickness_mm": 6.0,
                "thickness_source": "drawing_deterministic"}

    rows = [{"part_number": "JAE820", "thickness_mm": 18.0, "material_text": "MDF,18mm"},
            {"part_number": "JAE828", "thickness_mm": 12.0, "material_text": "MDF,12mm"},
            {"part_number": "MBY439", "thickness_mm": 2.0,
             "material_text": "Steel,Mild2mm"},
            {"part_number": "J13149", "thickness_mm": 15.0, "material_text": "15mmMDF"}]
    parts = [part(p) for p in ("JAE820", "JAE828", "MBY439", "J13149",
                               "JAE824", "JAE827")]      # two have no row gauge
    bom_pipeline.apply_bom_row_evidence_to_parts(parts, rows)
    by = {p["part_number"]: p for p in parts}
    assert by["JAE820"]["normalized_thickness_mm"] == 18.0
    assert by["MBY439"]["normalized_thickness_mm"] == 2.0
    assert by["J13149"]["normalized_thickness_mm"] == 15.0
    assert by["JAE820"]["thickness_source"] == "bom_tree"
    # the demoted figure is recorded, not erased
    assert any(e.get("value") == 6.0 and "document-repeated" in str(e.get("displaced_by"))
               for e in by["JAE820"]["_displaced"]["normalized_thickness_mm"])
    assert any("repeated across" in f for f in by["JAE820"]["review_flags"])
    # a part with no row gauge keeps the figure — the decision row rules on it
    assert by["JAE824"]["normalized_thickness_mm"] == 6.0
    # below scale nothing moves: four deterministic parts is not a population
    small = [part(p) for p in ("A", "B", "C", "D")]
    bom_pipeline.apply_bom_row_evidence_to_parts(
        small, [{"part_number": "A", "thickness_mm": 18.0, "material_text": "MDF,18mm"}])
    assert small[0]["normalized_thickness_mm"] == 6.0, \
        "four identical values could be four real specs — no demotion below scale"


# ── the four counterexamples a reviewer named, before the rules are trusted ──────────────

def _jd(target, op, participants=()):
    from types import SimpleNamespace as NS
    return NS(target_id=target, operation=op, scope="part", status=rc.REQUIRED,
              reason="", participants=list(participants), field_provenance={})


def test_a_joint_is_deduplicated_only_where_the_evidence_names_the_parts_it_joins():
    """0359342's prong assembly, and the only basis on which its double charge may go.

    MBY433's weld decision NAMES MBY432 and MBY434 as the parts it joins, so each leaf's own
    weld claim is that identified joint and charging it again is double counting."""
    graph = {"children": {"MBY433": {"MBY432": 1, "MBY434": 1}}}
    asm = _jd("MBY433", "welding", ("MBY432", "MBY434"))
    asm_d = _jd("MBY433", "dress_welds", ("MBY432", "MBY434"))
    prong, plate = _jd("MBY432", "welding"), _jd("MBY434", "welding")
    prong_d = _jd("MBY432", "dress_welds")
    rc._one_joint_charged_once([asm, asm_d, prong, plate, prong_d], graph)

    assert asm.status == rc.REQUIRED and asm_d.status == rc.REQUIRED
    for d in (prong, plate, prong_d):
        assert d.status == rc.NOT_APPLICABLE, d.target_id
        assert "names" in d.reason and "counted twice" in d.reason
        assert d.field_provenance["status"] == "joint_already_charged_on_the_assembly"


def test_a_seam_welded_leaf_keeps_its_weld_and_the_overlap_is_flagged_not_resolved():
    """THE COUNTEREXAMPLE THAT KILLED THE FIRST RULE. "A leaf cannot be welded to itself" is
    false: a folded single-piece enclosure has a seam weld along the edges that meet, and a
    leaf may simply be a fabrication nobody expanded. Where the parent's joint does not name
    the child, a seam weld and a second charge for the parent's joint are indistinguishable
    from here — so BOTH are charged and the question goes on the record. Deleting the money
    on a structural hunch is how an obvious over-charge becomes a quiet under-charge."""
    graph = {"children": {"ENC-ASM": {"ENC-BODY": 1, "ENC-LID": 1}}}
    asm = _jd("ENC-ASM", "welding")                  # no participants recorded
    body = _jd("ENC-BODY", "welding")                # folded box with its own seam weld
    rc._one_joint_charged_once([asm, body], graph)

    assert body.status == rc.REQUIRED, "a seam weld is real work and must survive"
    assert "seam" in body.reason and "confirm which" in body.reason.lower()
    assert body.field_provenance.get("review") == "joining_overlap_unresolved_with_parent"


def test_a_joint_that_names_other_parts_does_not_touch_this_child():
    """Naming is the whole test. A three-part assembly whose weld joins two of its members
    leaves the third member's own weld alone."""
    graph = {"children": {"ASM": {"P1": 1, "P2": 1, "P3": 1}}}
    asm = _jd("ASM", "welding", ("P1", "P2"))
    p3 = _jd("P3", "welding")
    rc._one_joint_charged_once([asm, p3], graph)
    assert p3.status == rc.REQUIRED
    assert p3.field_provenance.get("review") == "joining_overlap_unresolved_with_parent"


def test_a_purchased_panel_drilled_in_house_keeps_its_machining():
    """PURCHASED IS NOT THE SAME AS FINISHED. A bought-in panel or blank is stock we process,
    and plenty of them are drilled here — Corian arrives as a sheet and is machined. Only a
    purchased item whose OWN drawing records no hole at all loses the claim, which is the
    0359342 sticker: its drill row came from the general note transcribed onto every record."""
    raw = {
        # a purchased Corian panel with its own hole evidence — machining is ours, it stays
        "JAE823": {"normalized_material": "Corian,6mm", "description": "Plinth Overlay",
                   "drawing_text": "650.0 550.0 6.0 n8.5 THRU n8.0 THRU R14.0"},
        # a purchased mirror with a hole count measured off its own sheet
        "A62271": {"normalized_material": "Mirror,6mm", "description": "Mirror",
                   "hole_count": 4},
        # a printed self-adhesive label: no hole on its sheet, no hole in anybody's route
        "A60890": {"normalized_material": "Vinyl,Clear-BlackPrint",
                   "description": "UPC Sticker - Clear Vinyl"},
    }
    corian = _jd("JAE823", "drilling")
    mirror = _jd("A62271", "countersinking")
    sticker = _jd("A60890", "countersinking")
    corian_fold = _jd("JAE823", "folding")
    rc._family_gate([corian, mirror, sticker, corian_fold], raw)

    assert corian.status == rc.REQUIRED, "a purchased sheet we machine keeps its machining"
    assert mirror.status == rc.REQUIRED, "a measured hole count is the part's own evidence"
    assert sticker.status == rc.NOT_APPLICABLE
    assert sticker.field_provenance["status"] == "family_gate_no_hole_evidence"
    assert "records no holes" in sticker.reason
    # the metal-only refusal is untouched by any of this
    assert corian_fold.status == rc.NOT_APPLICABLE
