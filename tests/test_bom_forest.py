"""
An enquiry can ship more than one thing, and the BOM table knows who owns what.

Job 12392 is one enquiry with two general arrangements — a panel (02) and a bracket set
(04). The vision extract read only the first drawing. Everything on the second therefore
had no stated parent, was not the top assembly, and arrived at costing as a disconnected
leaf; the BOM row naming its owner was in the summary the whole time and this compiler had
never been given it.

Two defects, and they compound:

    THE THIRD SOURCE   the deterministic BOM read states parents, and only the description
                       rule and the extract were ever consulted
    ONE ROOT           the graph asked for THE top assembly, singular, so the second GA was
                       not a root, its subtree never cascaded a quantity, and it was
                       reported as an orphan

The target tree these tests hold to is the one the drawings state:

    12392-02-GA                    12392-04-GA
      201 -> 01M, 02M               04-01M x2
      TBM571 x8                     04-02M x2
      FIXING M4x8 x16               FIXING M4x8 x4
      17G

Every refusal is tested as carefully as every edge. An edge this cannot make is a visible
orphan; an edge it makes wrongly is a silent one, and the second is the expensive kind.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from route_compiler import build_part_graph, job_drawing_numbers, _roots_that_ship


PARTS = [
    {"part_number": "12392-02-GA", "description": "GENERAL ARRANGEMENT", "quantity": 1},
    {"part_number": "12392-02-201", "description": "PANEL ASSEMBLY", "quantity": 1},
    {"part_number": "12392-02-01M", "description": "FACE PANEL", "quantity": 1},
    {"part_number": "12392-02-02M", "description": "BACK PANEL", "quantity": 1},
    {"part_number": "12392-02-17G", "description": "GRAPHIC", "quantity": 1},
    {"part_number": "TBM571", "description": "STANDOFF", "quantity": 8},
    {"part_number": "FIXING", "description": "BUTTON HEAD SCREW M4x8", "quantity": 16},
    {"part_number": "12392-04-01M", "description": "MOD MOUNT BRACKET", "quantity": 2},
    {"part_number": "12392-04-02M", "description": "MOD MOUNT PLATE", "quantity": 2},
]

# What the vision pass returned: the 02 drawing only. This is the real shape of the failure —
# not a broken extract, a partial one.
EXTRACT_02_ONLY = {
    "top_assembly": {"part_number": "12392-02-GA"},
    "assemblies": [
        {"part_number": "12392-02-GA", "children": [
            {"part_number": "12392-02-201", "qty": 1},
            {"part_number": "12392-02-17G", "qty": 1},
            {"part_number": "TBM571", "qty": 8},
            {"part_number": "FIXING", "qty": 16},
        ]},
        {"part_number": "12392-02-201", "children": [
            {"part_number": "12392-02-01M", "qty": 1},
            {"part_number": "12392-02-02M", "qty": 1},
        ]},
    ],
}

# What the deterministic BOM reader saw: both drawings' tables, each row stamped with the
# title block that listed it.
BOM_ROWS = [
    {"part_number": "12392-02-201", "quantity": 1, "bom_parent": "12392-02-GA"},
    {"part_number": "12392-02-17G", "quantity": 1, "bom_parent": "12392-02-GA"},
    {"part_number": "TBM571", "quantity": 8, "bom_parent": "12392-02-GA"},
    {"part_number": "FIXING", "quantity": 16, "bom_parent": "12392-02-GA",
     "description": "BUTTON HEAD SCREW M4x8"},
    {"part_number": "12392-02-01M", "quantity": 1, "bom_parent": "12392-02-201"},
    {"part_number": "12392-02-02M", "quantity": 1, "bom_parent": "12392-02-201"},
    {"part_number": "12392-04-01M", "quantity": 2, "bom_parent": "12392-04-GA"},
    {"part_number": "12392-04-02M", "quantity": 2, "bom_parent": "12392-04-GA"},
    {"part_number": "FIXING", "quantity": 4, "bom_parent": "12392-04-GA",
     "description": "BUTTON HEAD SCREW M4x8"},
]

DRAWINGS = ["12392-02-GA", "12392-04-GA"]


def _graph(**kw):
    return build_part_graph(kw.get("parts", PARTS),
                            kw.get("extract", EXTRACT_02_ONLY),
                            kw.get("bom_rows", BOM_ROWS),
                            kw.get("drawings", DRAWINGS))


def test_the_defect_reproduces_without_the_bom():
    """The precondition. With only the extract, the 04 parts belong to nothing — which is
    exactly what job 12392 reported, six times, as a blocking invariant."""
    orphans = {i["part_number"] for i in build_part_graph(PARTS, EXTRACT_02_ONLY)["issues"]}
    assert "12392-04-01M" in orphans
    assert "12392-04-02M" in orphans


def test_the_bom_table_gives_the_unclaimed_parts_their_owner():
    g = _graph()
    assert g["parents"].get("12392-04-01M") == {"12392-04-GA"}
    assert g["parents"].get("12392-04-02M") == {"12392-04-GA"}


def test_no_node_is_left_disconnected():
    g = _graph()
    # NOT VACUOUS: the disconnected check only runs when the graph has roots, so an empty
    # issue list would also be what a graph that gave up entirely produced.
    assert g["top_assemblies"], "no roots means this assertion proves nothing"
    assert [i["part_number"] for i in g["issues"]] == []


def test_both_general_arrangements_are_roots():
    g = _graph()
    assert g["top_assemblies"] == ["12392-02-GA", "12392-04-GA"]
    assert set(_roots_that_ship(g)) == {"12392-02-GA", "12392-04-GA"}
    # top_assembly keeps its old meaning for every reader that means "the one anchor".
    assert g["top_assembly"] == "12392-02-GA"


def test_every_subtree_cascades_its_quantity():
    """With one root the second GA's subtree never ran, so its parts kept their own drawing
    quantity by accident rather than by descent — right here, wrong for the first multiplier
    a GA carries."""
    q = _graph()["quantities"]
    assert q["12392-04-01M"] == 2
    assert q["12392-04-02M"] == 2
    assert q["TBM571"] == 8
    assert q["12392-02-01M"] == 1


def test_the_bom_never_re_parents_a_part_the_extract_already_placed():
    """01M is the extract's child of 201 and the BOM's child of 201 too — but if a reader
    ever disagreed, the graph must keep the owner it already had. A wrong parent is worse
    than a missing one, so this source can only ever fill a hole."""
    contradicting = [dict(r) for r in BOM_ROWS]
    for row in contradicting:
        if row["part_number"] == "12392-02-01M":
            row["bom_parent"] = "12392-02-GA"       # the weaker, direct-to-GA edge
    g = _graph(bom_rows=contradicting)
    assert g["parents"]["12392-02-01M"] == {"12392-02-201"}, \
        "the sub-assembly edge must survive a BOM row that names the GA instead"


def test_a_parent_naming_nothing_we_know_makes_no_edge():
    """merge_boms falls back to "<file>#<page>" when no title block was read. A node
    invented from that would be a phantom assembly carrying real children."""
    rows = [{"part_number": "12392-04-01M", "quantity": 2,
             "bom_parent": "12392-04-GA.pdf#0"}]
    g = build_part_graph(PARTS, EXTRACT_02_ONLY, rows, DRAWINGS)
    assert "12392-04-01M" in {i["part_number"] for i in g["issues"]}
    assert not any("#" in n.part_number for n in g["nodes"])


def test_a_drawing_we_never_opened_is_not_an_assembly():
    """The exception that lets the second GA own its parts is evidence — we scanned that
    drawing. Take the evidence away and the refusal returns."""
    g = build_part_graph(PARTS, EXTRACT_02_ONLY, BOM_ROWS, ["12392-02-GA"])
    assert "12392-04-01M" in {i["part_number"] for i in g["issues"]}
    assert "12392-04-GA" not in g["parents"].get("12392-04-01M", set())


def test_the_orphan_says_which_owner_the_bom_named():
    """When an edge is refused, the label that was refused is the most actionable fact
    about why the node is still here."""
    parts = PARTS + [{"part_number": "12392-05-01M", "description": "SPACER",
                      "quantity": 1, "bom_parent": "12392-05-GA"}]
    issues = {i["part_number"]: i
              for i in build_part_graph(parts, EXTRACT_02_ONLY, BOM_ROWS, DRAWINGS)["issues"]}
    assert issues["12392-05-01M"]["bom_stated_parent"] == "12392-05-GA"
    assert issues["12392-05-01M"]["bom_stated_parent_is_a_known_node"] is False


def test_a_single_ga_job_is_unchanged():
    """The safety property. One drawing, one root, the same answer as before the forest."""
    parts = [p for p in PARTS if not p["part_number"].startswith("12392-04")]
    rows = [r for r in BOM_ROWS if r.get("bom_parent") != "12392-04-GA"]
    g = build_part_graph(parts, EXTRACT_02_ONLY, rows, ["12392-02-GA"])
    assert g["top_assemblies"] == ["12392-02-GA"]
    assert g["top_assembly"] == "12392-02-GA"
    assert [i["part_number"] for i in g["issues"]] == []
    # Identical to the same job compiled with no BOM rows at all.
    assert g["top_assembly"] == build_part_graph(parts, EXTRACT_02_ONLY)["top_assembly"]


def test_a_job_with_no_bom_rows_is_untouched():
    """Every job before this one passed no rows at all, and must compile bit-identically."""
    a = build_part_graph(PARTS, EXTRACT_02_ONLY)
    b = build_part_graph(PARTS, EXTRACT_02_ONLY, [], [])
    assert a["parents"] == b["parents"]
    assert a["quantities"] == b["quantities"]
    assert [i["part_number"] for i in a["issues"]] == [i["part_number"] for i in b["issues"]]


def test_the_drawing_numbers_come_from_the_files_we_opened():
    assert job_drawing_numbers({"job_source_pdfs": [
        {"name": "12392-02-GA.pdf"}, {"name": "12392-04-GA.pdf"},
    ]}) == ["12392-02-GA", "12392-04-GA"]
    assert job_drawing_numbers({}) == []
    # A descriptive file name yields whatever it says and no more — nothing is derived from
    # it, because a drawing whose number we do not know must not head a tree.
    assert "12392-04-GA" not in job_drawing_numbers(
        {"job_source_pdfs": [{"name": "Mod mount bracket set.pdf"}]})


# ── an assembly is not a blank ──────────────────────────────────────────────────────────

def test_an_assembly_does_not_keep_operations_only_a_blank_can_incur():
    """12392-02-201 is two steel panels bolted together. It collected CNC routing, edge
    banding and laminating from an MDF title block on another sheet of the same pack — three
    joinery operations on a thing no joinery touches, each unverifiable because no part on
    the assembly could have incurred them.

    The flag saying so has been written onto assembly parents for as long as the function
    has existed, and nothing ever read it."""
    from route_compiler import apply_canonical_evidence_to_parts

    parts = [dict(p) for p in PARTS]
    for part in parts:
        if part["part_number"] == "12392-02-201":
            part["textual_operations"] = ["cnc_routing", "edge_banding", "laminating",
                                          "assembly", "welding"]
    apply_canonical_evidence_to_parts(parts, EXTRACT_02_ONLY, BOM_ROWS, DRAWINGS)
    _201 = next(p for p in parts if p["part_number"] == "12392-02-201")

    assert _201["is_assembly_parent"] is True
    assert _201["textual_operations"] == ["assembly", "welding"], \
        "joining is what an assembly IS and must survive"
    assert set(_201["removed_operations"]) == {"cnc_routing", "edge_banding", "laminating"}
    assert any("leaf-only operations" in f for f in _201["review_flags"]), \
        "a strip nobody announces is the silent write these checks exist to catch"


def test_a_leaf_keeps_every_operation_it_has():
    """MUTATION: the same operations on a part that is NOT an assembly are untouched, so the
    classification is what decides — not the operation names."""
    from route_compiler import apply_canonical_evidence_to_parts

    parts = [dict(p) for p in PARTS]
    for part in parts:
        if part["part_number"] == "12392-02-01M":
            part["textual_operations"] = ["cnc_routing", "edge_banding", "laser_cutting"]
    apply_canonical_evidence_to_parts(parts, EXTRACT_02_ONLY, BOM_ROWS, DRAWINGS)
    _01m = next(p for p in parts if p["part_number"] == "12392-02-01M")
    assert _01m["textual_operations"] == ["cnc_routing", "edge_banding", "laser_cutting"]
    assert not _01m.get("removed_operations")


def test_a_weldment_parent_keeps_its_weld_and_its_finish():
    """Joining and finishing are deliberately outside the stripped set. A weldment that lost
    its weld would lose the job's real labour, and a welded frame is powder coated as one
    thing after joining — a case this engine handles on purpose."""
    import bought_in_policy
    part = {"is_assembly_parent": True,
            "textual_operations": ["welding", "spot_welding", "dress_welds", "glue",
                                   "bonding", "powder_coating", "wet_spray",
                                   "diamond_polish", "assembly", "hardware_insertion"]}
    assert bought_in_policy.strip_leaf_operations(part) == []
    assert len(part["textual_operations"]) == 10


def test_the_two_operation_vocabularies_do_not_contradict_each_other():
    """LEAF_ONLY_OPS is a subset of FABRICATION_OPS by design — anything a purchased part
    cannot incur, plus the joinery names FABRICATION_OPS spells differently. Two lists of
    operation names maintained separately are two lists that disagree."""
    import bought_in_policy as bp
    _extra = bp.LEAF_ONLY_OPS - bp.FABRICATION_OPS
    assert _extra <= {"edgebanding", "laminating", "lamination", "veneering"}, \
        f"a leaf-only op that is not a fabrication op at all: {_extra}"
    # Joining and finishing must never appear in the stripped set.
    assert not (bp.LEAF_ONLY_OPS & {"welding", "spot_welding", "resistance_welding",
                                    "dress_welds", "glue", "gluing", "bonding",
                                    "powder_coating", "wet_spray", "diamond_polish"})


def test_the_title_block_spelling_is_the_one_that_actually_arrives():
    """THE NEAR MISS. merge_boms takes the parent from the title block verbatim — its own
    docstring gives "1282 - GA" as the example — while this module's clean_part_number only
    uppercases and collapses whitespace. So the reader says "12392-04 - GA" and the graph
    says "12392-04-GA", and an edge matched on one would never find the other.

    Every test above is written in the graph's spelling and would have passed while the whole
    BOM hierarchy source did nothing at all on a real drawing. This is the third time in this
    codebase that a correct rule was handed a spelling it did not accept."""
    rows = [{"part_number": "12392-04-01M", "quantity": 2, "bom_parent": "12392-04 - GA"},
            {"part_number": "12392-04-02M", "quantity": 2, "bom_parent": "12392-04 - GA"}]
    g = build_part_graph(PARTS, EXTRACT_02_ONLY, rows, DRAWINGS)
    assert g["parents"].get("12392-04-01M") == {"12392-04-GA"}
    assert g["top_assemblies"] == ["12392-02-GA", "12392-04-GA"]
    assert [i["part_number"] for i in g["issues"]] == []


def test_a_drawing_file_named_in_the_spaced_form_is_still_recognised():
    g = build_part_graph(
        PARTS, EXTRACT_02_ONLY,
        [{"part_number": "12392-04-01M", "quantity": 2, "bom_parent": "12392-04-GA"}],
        job_drawing_numbers({"job_source_pdfs": [{"name": "12392-04 - GA.pdf"}]}))
    assert g["parents"].get("12392-04-01M") == {"12392-04-GA"}


# ── one predicate, asked by every pass ───────────────────────────────────────────────────

def test_every_spelling_of_parent_reaches_one_answer():
    """estimator.py records the defect in its own comment: "both suppressions here and in
    estimate_part keyed on is_assembly_parent, a different name for the same idea". The
    canonical graph then added a fifth spelling. A union, so no consumer can recognise FEWER
    parents than it did — the failure direction is a parent charged as a leaf, which books
    material and fabrication twice."""
    import bought_in_policy as bp
    for record, expect in (
        ({"canonical_kind": "assembly"}, "canonical part graph"),
        ({"is_assembly_parent": True}, "flagged an assembly parent"),
        ({"is_sub_assembly": True}, "sub-assembly"),
        ({"assembly_children": ["12392-02-01M"]}, "children of its own"),
    ):
        assert expect in bp.assembly_reason(record), record
    assert not bp.is_assembly({"part_number": "12392-02-01M"})
    assert not bp.is_assembly({"assembly_children": []})


def test_an_assembly_charged_as_a_blank_is_blocking():
    import invariants
    found = invariants.check_an_assembly_is_not_charged_as_a_blank({"parts": [
        {"part_number": "12392-02-201", "canonical_kind": "assembly",
         "unit_material_cost_gbp": 4.12, "textual_operations": ["cnc_routing"]},
    ]})
    assert len(found) == 1
    assert found[0]["severity"] == invariants.BLOCKING
    assert found[0]["detail"]["parts"][0]["leaf_operations"] == ["cnc_routing"]
    assert found[0]["detail"]["material_gbp"] == 4.12


def test_a_measured_flat_outranks_a_transcribed_tree():
    """The estimator says so where it decides; claiming here would contradict the pass that
    priced it. A part with its own geometry is a fabricated leaf whatever a hierarchy said."""
    import invariants
    assert invariants.check_an_assembly_is_not_charged_as_a_blank({"parts": [
        {"part_number": "12392-02-01M", "is_sub_assembly": True,
         "dxf_measured_outline": True, "unit_material_cost_gbp": 4.12},
    ]}) == []


def test_a_parent_carrying_only_joining_or_finish_is_not_claimed():
    import invariants
    assert invariants.check_an_assembly_is_not_charged_as_a_blank({"parts": [
        {"part_number": "12392-02-201", "canonical_kind": "assembly",
         "unit_material_cost_gbp": 0.0,
         "textual_operations": ["welding", "powder_coating", "assembly"]},
    ]}) == []


def test_the_assembly_scope_check_is_registered():
    import invariants
    assert invariants.check_an_assembly_is_not_charged_as_a_blank in invariants.CHECKS
