"""12645 DRS External Shelter, 19:17 book (build 8fe2bc5): the body's own parts list prints
"Half Inch Whitworth Nut / M8 FULL NUT BZP GRADE 8" x120 and "4.8mm Hex Head TEK Screw" x16.
BOMs & Routes read both (qty own 120 / 16) and left qty effective blank, and neither reached
the Estimate: the 120 nuts and 16 screws were missing from a £3,493.86 unit with nothing to
say so. The model names the body "12645-01GA V2"; its sheet, its title block and the job's
drawing list number it "12645-01GA". The product reached the model's node, the rows the model
does not hold hung from the title block's, and that node was set aside as "outside the
product" with them. One drawing, one node, whatever version mark the model gave it (D-318)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc  # noqa: E402

FILES = {"job_source_pdfs": ["12645 - DRS External Shelter V2_REVA.PDF", "12645-01GA V2_REVA.PDF",
                             "12645-02GA_REVA.pdf"]}
_TOP = "12645 - DRS EXTERNAL SHELTER V2"


def _parts(extra=()):
    return [
        # the model's tree (apply_native_hierarchy_to_parts): the shelter, and the body under
        # the model's own name holding what the model holds — not the nuts, not the screws
        {"part_number": "12645 - DRS External Shelter V2", "quantity": 1,
         "is_assembly_parent": True, "is_sub_assembly": True,
         "assembly_children": ["12645-01GA V2", "12645-02GA"]},
        {"part_number": "12645-01GA V2", "quantity": 1, "is_assembly_parent": True,
         "is_sub_assembly": True, "assembly_children": ["12645-01-01M", "M8 Hex Head Bolt"]},
        # the body's own sheet, read by its title block
        {"part_number": "12645-01GA", "description": "BODY FRAME", "quantity": 1, "pages": [2]},
        {"part_number": "12645-01-01M", "description": "BACK PANEL", "quantity": 3},
        {"part_number": "12645-02GA", "description": "DOOR FRAME", "quantity": 1},
        {"part_number": "M8 HEX HEAD BOLT", "description": "M8x20mmHEX HEAD BOLT, BZP",
         "quantity": 120, "page_roles": ["bought_in"]},
        {"part_number": "4.8MMHEXHEADTEKSCREW", "description": "HEX HEAD TEK SCREW 4.8x15.9mm",
         "quantity": 16},
        {"part_number": "BI-NUT", "description": "M8 FULL NUT BZP GRADE 8", "quantity": 120,
         "page_roles": ["bought_in"]},
    ] + list(extra)


BOM = [
    {"part_number": "12645-01GA V2", "parent": _TOP, "qty": 1},
    {"part_number": "12645-02GA", "parent": _TOP, "qty": 1},
    {"part_number": "12645-01-01M", "parent": "12645-01GA", "qty": 3},
    {"part_number": "M8 Hex Head Bolt", "description": "M8x20mmHEX HEAD BOLT, BZP",
     "parent": "12645-01GA", "qty": 120},
    {"part_number": "Half Inch Whitworth Nut", "description": "M8 FULL NUT BZP GRADE 8",
     "parent": "12645-01GA", "qty": 120},
    {"part_number": "4.8MMHEXHEADTEKSCREW", "description": "HEX HEAD TEK SCREW 4.8x15.9mm",
     "parent": "12645-01GA", "qty": 16},
]


def _graph(parts=None, files=FILES):
    return rc.build_part_graph(parts or _parts(), bom_rows=BOM,
                               known_assemblies=rc.job_drawing_numbers(files),
                               declared_product="12645")


def test_the_nuts_and_screws_the_model_does_not_hold_reach_the_shelter():
    g = _graph()
    nodes = {n.part_number: n for n in g["nodes"]}
    assert not [i for i in g["issues"] if i.get("code") == "outside_the_product"]
    assert nodes["BI-NUT"].qty_per_unit == 120 and nodes["BI-NUT"].qty_trail
    assert nodes["4.8MMHEXHEADTEKSCREW"].qty_per_unit == 16
    assert nodes["4.8MMHEXHEADTEKSCREW"].qty_trail
    assert nodes["M8 HEX HEAD BOLT"].qty_per_unit == 120


def test_the_body_is_one_node():
    g = _graph()
    bodies = [n for n in g["nodes"] if n.part_number in ("12645-01GA", "12645-01GA V2")]
    assert len(bodies) == 1
    assert {"12645-01-01M", "BI-NUT", "4.8MMHEXHEADTEKSCREW"} <= {
        c.part_number for c in bodies[0].children}


def test_two_versions_of_one_drawing_are_not_joined():
    """A pack holding V1 and V2 of one sheet is a question for a person, not a join."""
    g = _graph(_parts([{"part_number": "12645-01GA V1", "quantity": 1,
                        "is_assembly_parent": True, "assembly_children": ["12645-01-01M"]}]))
    assert any(i.get("code") == "two_versions_of_one_drawing" for i in g["issues"])
    joined = {a for n in g["nodes"] for a in (n.evidence.get("raw_aliases") or [])}
    assert not joined & {"12645-01GA V1", "12645-01GA V2"}


def test_a_bare_code_the_job_never_opened_is_not_joined():
    files = {"job_source_pdfs": ["12645 - DRS External Shelter V2_REVA.PDF", "12645-02GA_REVA.pdf"]}
    g = _graph(files=files)
    assert not any("12645-01GA V2" in (n.evidence.get("raw_aliases") or []) for n in g["nodes"])


def test_the_joined_body_is_described_by_its_parts_list_not_a_column_header():
    """The verifier's catch: on the runner the body's title-block record reads "QTY." where a
    description sits (the 16:38 report printed "12645-01GA QTY. · assembly"). Joined, the
    body must keep the words its parts list printed — BODY FRAME."""
    parts = _parts()
    for p in parts:
        if p["part_number"] == "12645-01GA":
            p["description"] = "QTY."
    bom = [dict(BOM[0], description="BODY FRAME")] + BOM[1:]
    g = rc.build_part_graph(parts, bom_rows=bom,
                            known_assemblies=rc.job_drawing_numbers(FILES),
                            declared_product="12645")
    body = next(n for n in g["nodes"] if n.part_number in ("12645-01GA", "12645-01GA V2"))
    assert body.description == "BODY FRAME", body.description


def test_the_squashed_spelling_joins_the_same_body():
    """12645-01GAV2 is how the 16:38 book spelt the second body it bought for £557."""
    g = _graph(_parts([{"part_number": "12645-01GAV2", "description": "BODY FRAME",
                        "quantity": 1}]))
    bodies = [n.part_number for n in g["nodes"] if "01GA" in n.part_number.replace(" ", "")]
    assert len(bodies) == 1, bodies
