"""A SPACE IN A MODEL ASSEMBLY'S NAME IS NOT A SECOND ASSEMBLY (12773-01-GA 17:07, 12 Nov 2026).

The drawing printed the lower body as "…-02GA"; its model is named "…-02 GA". The model's
tree was not attached to the drawing's record, the product lost its edge to the lower body,
and eight lower-body lines were set aside as outside the product and never costed.
Reviewer: "Prove 12773's lower-body children."
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import source_connectors.solidworks as sw  # noqa: E402


def _parts():
    return [{"part_number": "X-01-GA", "description": "PRODUCT"},
            {"part_number": "X-02GA", "description": "LOWER BODY GA"},
            {"part_number": "X-03-101", "description": "UPPER BODY GA"},
            {"part_number": "X-02-101", "description": "SHELF PANEL"},
            {"part_number": "X-02-201", "description": "LOWER UPRIGHT"}]


TREE = {"X-01-GA": [("X-02 GA", 1.0), ("X-03-101", 1.0)],
        "X-02 GA": [("X-02-101", 2.0), ("X-02-201", 2.0)],
        "X-03-101": [("X-02-101", 2.0)]}


def _kids(parts, pn):
    return sorted(str(c) for p in parts if p["part_number"] == pn for c in (p.get("assembly_children") or []))


def test_the_product_keeps_its_edge_to_the_lower_body():
    parts = _parts()
    sw.apply_native_hierarchy_to_parts(parts, SimpleNamespace(hierarchy=TREE))
    assert _kids(parts, "X-01-GA") == ["X-02GA", "X-03-101"]


def test_the_lower_bodys_children_hang_from_the_drawings_record():
    parts = _parts()
    sw.apply_native_hierarchy_to_parts(parts, SimpleNamespace(hierarchy=TREE))
    assert _kids(parts, "X-02GA") == ["X-02-101", "X-02-201"]
    assert not any(p["part_number"] == "X-02 GA" for p in parts), "no second lower body is made"


def test_a_shared_child_keeps_both_owners():
    parts = _parts()
    sw.apply_native_hierarchy_to_parts(parts, SimpleNamespace(hierarchy=TREE))
    owners = sorted(p["part_number"] for p in parts if "X-02-101" in (p.get("assembly_children") or []))
    assert owners == ["X-02GA", "X-03-101"]


def test_two_records_answering_to_one_spelling_are_not_guessed_between():
    parts = _parts() + [{"part_number": "X-0 2GA", "description": "ANOTHER"}]
    sw.apply_native_hierarchy_to_parts(parts, SimpleNamespace(hierarchy=TREE))
    assert "X-02GA" not in _kids(parts, "X-01-GA") and "X-0 2GA" not in _kids(parts, "X-01-GA")


def test_a_hyphen_is_still_a_different_code():
    parts = [{"part_number": "X-01-GA"}, {"part_number": "X-02-GA"}, {"part_number": "X-09"}]
    sw.apply_native_hierarchy_to_parts(parts, SimpleNamespace(hierarchy={"X-01-GA": [("X-02GA", 1.0), ("X-09", 1.0)]}))
    assert "X-02-GA" not in _kids(parts, "X-01-GA")
