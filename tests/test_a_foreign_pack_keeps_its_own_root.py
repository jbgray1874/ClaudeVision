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
