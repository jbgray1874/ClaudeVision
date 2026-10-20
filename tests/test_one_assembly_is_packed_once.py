"""Two spellings of one assembly are not two things to pack.

11908-21's graph carried the same shipping tray twice — "11908-21" (the BOM's identity,
children including the bumpers) and "11908-21 GA" (the GA sheet's own name, children the
three boards) — and the per-root assembly mint charged a Packing Joinery row for EACH:
rows 98 and 99 of the 08:04 book, two packs for one tray. Tony's letter counts packing
among the labour; counting it twice is the faster way to lose him than missing it.

A trailing purely-alphabetic sheet-role token (GA, ASSY) names a ROLE, not a different
product. A digit in the tail names a different drawing — 7332-01's GA and GA2 are two
stands and must both pack.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")


def _required_assemblies(out):
    return [d for d in out["decisions"]
            if d["operation"] == "assembly" and d["status"] == "required"]


def test_the_tray_is_packed_once_under_its_fuller_name():
    from route_compiler import compile_job_route
    out = compile_job_route(
        [{"part_number": "11908-21", "description": "SUNGLASSES TRAY - LRG",
          "assembly_children": ["11908-21-01J", "FIXING1270"], "is_assembly_parent": True},
         {"part_number": "11908-21 GA", "description": "SUNGLASSES TRAY - LRG GA",
          "assembly_children": ["11908-21-01J"], "is_assembly_parent": True},
         {"part_number": "11908-21-01J", "description": "TRAY BASE",
          "normalized_material": "MDF"},
         {"part_number": "FIXING1270", "description": "BUMPON 19MM", "quantity": 4}],
        {"assemblies": [
            {"part_number": "11908-21", "children": [
                {"part_number": "11908-21-01J", "qty": 2},
                {"part_number": "FIXING1270", "qty": 4}]},
            {"part_number": "11908-21 GA", "children": [
                {"part_number": "11908-21-01J", "qty": 2}]}],
         "bom": [{"part_number": "11908-21-01J", "description": "TRAY BASE", "qty": 2,
                  "type": "fabricated"},
                 {"part_number": "FIXING1270", "description": "BUMPON 19MM", "qty": 4,
                  "is_bought_in": True}]})
    asm = _required_assemblies(out)
    targets = sorted(d["target_id"] for d in asm)
    assert len(asm) == 1, f"one tray, one pack — got {targets}"
    assert targets == ["11908-21"], \
        "the spelling with the fuller parts list (it knows about the bumpers) keeps the event"


def test_the_drawing_quantities_are_not_doubled_by_the_second_spelling():
    """The 09:57 book's own audit: quantity OWN 1/4/4, EFFECTIVE 2/8/8, "no reason
    recorded" — both spellings of the root cascaded one unit each into the same
    children. The colourway collapse missed it by one bumpon: Jaccard 3/4 = 0.75
    against its 0.8 bar. A same-spelling root whose children are CONTAINED in the
    other's is one assembly, and the drawing's own counts stand."""
    from route_compiler import build_part_graph
    graph = build_part_graph(
        [{"part_number": "11908-21", "description": "SUNGLASSES TRAY - LRG",
          "assembly_children": ["11908-21-01J", "11908-21-02J", "FIXING1270"],
          "is_assembly_parent": True},
         {"part_number": "11908-21 GA", "description": "SUNGLASSES TRAY - LRG GA",
          "assembly_children": ["11908-21-01J", "11908-21-02J"],
          "is_assembly_parent": True},
         {"part_number": "11908-21-01J", "description": "TRAY BASE",
          "normalized_material": "MDF"},
         {"part_number": "11908-21-02J", "description": "TRAY SIDE",
          "normalized_material": "MDF"},
         {"part_number": "FIXING1270", "description": "BUMPON 19MM", "quantity": 4}],
        {"assemblies": [
            {"part_number": "11908-21", "children": [
                {"part_number": "11908-21-01J", "qty": 1},
                {"part_number": "11908-21-02J", "qty": 4},
                {"part_number": "FIXING1270", "qty": 4}]},
            {"part_number": "11908-21 GA", "children": [
                {"part_number": "11908-21-01J", "qty": 1},
                {"part_number": "11908-21-02J", "qty": 4}]}]},
        None, None, None)
    q = graph["quantities"]
    assert q.get("11908-21-01J") == 1.0, q
    assert q.get("11908-21-02J") == 4.0, q
    assert q.get("FIXING1270") == 4.0, q


def test_a_hand_is_a_product_and_never_folds():
    """P1 from the 16 Sep review: the first cut stripped ANY trailing word, merged
    ABC-LEFT into ABC-RIGHT and deleted a real assembly whose children happened to be a
    subset. LEFT is a hand, not a sheet role — only the named role tokens (GA, ASSY, …)
    may ever be stripped, and containment excuses nothing without one."""
    from route_compiler import build_part_graph, compile_job_route
    parts = [
        {"part_number": "ABC-LEFT", "description": "LEFT CHEEK ASSEMBLY",
         "assembly_children": ["ABC-01", "ABC-02"], "is_assembly_parent": True},
        {"part_number": "ABC-RIGHT", "description": "RIGHT CHEEK ASSEMBLY",
         "assembly_children": ["ABC-01"], "is_assembly_parent": True},
        {"part_number": "ABC-01", "description": "PANEL", "normalized_material": "MDF"},
        {"part_number": "ABC-02", "description": "BRACKET"}]
    extract = {"assemblies": [
        {"part_number": "ABC-LEFT", "children": [
            {"part_number": "ABC-01", "qty": 1}, {"part_number": "ABC-02", "qty": 1}]},
        {"part_number": "ABC-RIGHT", "children": [{"part_number": "ABC-01", "qty": 1}]}]}
    graph = build_part_graph(parts, extract, None, None, None)
    assert "ABC-RIGHT" in {n.part_number for n in graph["nodes"]}, \
        "the RIGHT assembly must survive — a subset child list is not a spelling"
    assert graph["quantities"].get("ABC-01") == 2.0, \
        "the shared panel is genuinely taken by BOTH hands"
    out = compile_job_route(parts, extract)
    asm = _required_assemblies(out)
    assert len(asm) == 2, [d["target_id"] for d in asm]


def test_only_named_role_tokens_strip():
    from part_code_conventions import strip_assembly_role
    assert strip_assembly_role("11908-21 GA") == "11908-21"
    assert strip_assembly_role("11908-21-GA") == "11908-21"
    assert strip_assembly_role("7332-01 ASSY") == "7332-01"
    assert strip_assembly_role("ABC-LEFT") == "ABC-LEFT"
    assert strip_assembly_role("ABC-RIGHT") == "ABC-RIGHT"
    assert strip_assembly_role("7332-01 GA2") == "7332-01 GA2", "a digit is a drawing"


def test_the_answers_file_stems_obey_the_same_allowlist():
    import estimator_confirmed as ec
    assert ec.drawing_stems("10975-02-GA") == ["10975-02-GA", "10975-02"]
    assert ec.drawing_stems("ABC-LEFT") == ["ABC-LEFT"], \
        "one ABC_confirmed.json must not govern both hands"


def test_two_genuinely_different_stands_both_pack():
    """A digit in the tail is a different drawing: GA and GA2 are two stands (7332-01),
    and folding them is how a whole BOM went out doubled once before — in reverse."""
    from route_compiler import compile_job_route
    out = compile_job_route(
        [{"part_number": "7332-01 GA", "description": "STAND ONE",
          "assembly_children": ["7332-01-001"], "is_assembly_parent": True},
         {"part_number": "7332-01 GA2", "description": "STAND TWO",
          "assembly_children": ["7332-01-002"], "is_assembly_parent": True},
         {"part_number": "7332-01-001", "description": "PANEL A"},
         {"part_number": "7332-01-002", "description": "PANEL B"}],
        {"assemblies": [
            {"part_number": "7332-01 GA", "children": [
                {"part_number": "7332-01-001", "qty": 1}]},
            {"part_number": "7332-01 GA2", "children": [
                {"part_number": "7332-01-002", "qty": 1}]}],
         "bom": [{"part_number": "7332-01-001", "description": "PANEL A", "qty": 1,
                  "type": "fabricated"},
                 {"part_number": "7332-01-002", "description": "PANEL B", "qty": 1,
                  "type": "fabricated"}]})
    asm = _required_assemblies(out)
    assert len(asm) == 2, [d["target_id"] for d in asm]
