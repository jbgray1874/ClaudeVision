"""bom_tree resolved the quantities correctly and the sheet still carried three.

THE 12349-02 FAILURE, AND THE LOG THAT FOUND IT. The console said, on the run in question:

    [bom_tree] the GA shows 3 x 12349-02-69-100 — install context, not the unit...
    [bom_tree] the GA shows 3 x 12349-02-69-08J — install context, not the unit...

and the Estimate sheet still showed 3 of the Lid, 3 of the Front Cover, 6 powder-coat bookings.
The older logs rule out the obvious explanation:

    [bom_tree] 12349-02-69-04M qty 1 KEPT (GA tree said 3) — stronger source

The PART RECORD held 1 the whole time. Nothing about correcting part records could have fixed
this, and I spent an afternoon fixing the wrong end before reading that line.

THERE ARE TWO CASCADES. route_compiler.build_part_graph walks the same tree independently —

    for _root in top_ids: add_descendants(_root, 1.0, set())
    ... add_descendants(child_id, factor * child_qty, next_path)

— and wb_populate takes the workbook quantity from THAT graph's node. The graph has never heard
of install context, so it multiplied the GA's 3 into everything below it. One rule, two
implementations, and the sheet reads the one without it.

So the EDGE is corrected, not the node. A main-GA row IS the child edge the graph reads, so
dividing it there means both cascades start from the same number — and a third one, if anybody
writes it, inherits the rule for free.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from route_compiler import compile_job_route                            # noqa: E402

GA = "12349-02-69-GA"


def _graph_qty(ga_row_qty: int) -> float:
    rows = [{"part_number": "12349-02-69-100", "quantity": ga_row_qty, "source_pdf": GA,
             "bom_parent": GA},
            {"part_number": "12349-02-69-04M", "quantity": 1,
             "source_pdf": "12349-02-69-100", "bom_parent": "12349-02-69-100"}]
    graph = compile_job_route(
        [{"part_number": "12349-02-69-100"}, {"part_number": "12349-02-69-04M"}],
        {}, rows, [GA], {})
    by_code = {n["part_number"]: n.get("qty_per_unit") for n in (graph.get("nodes") or [])}
    return by_code["12349-02-69-04M"]


def test_the_graph_multiplies_the_ga_row_into_every_leaf():
    """Not a defect on its own — it is the correct cascade for a bay. It becomes one when the
    GA quantity is an arrangement and nothing tells the graph so."""
    assert _graph_qty(3) == 3.0


def test_correcting_the_ga_row_moves_the_graph_the_workbook_reads():
    """THE FIX, AT THE ONLY POINT THAT REACHES BOTH CASCADES."""
    assert _graph_qty(1) == 1.0


def test_the_row_correction_is_wired_into_the_scan():
    """The arithmetic above is worth nothing if nothing applies it to the record. file_scan
    divides the main-GA rows once bom_tree has said the GA quantity is install context."""
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    block = src[src.index("AND THE SAME CORRECTION ON THE ROWS"):]
    block = block[:block.index("except Exception as _bte")]
    assert 'install_context' in block
    assert 'main_ga' in block
    assert '_row["quantity"] = _q // _n' in block
    assert "_q % _n == 0" in block, \
        "only where it divides evenly — five across three is not a per-arrangement quantity"
    assert "divided by" in block, "and it says so on the console rather than silently"


def test_the_correction_does_nothing_without_install_context():
    """A bay has none, so its rows are untouched and it still multiplies."""
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    block = src[src.index("AND THE SAME CORRECTION ON THE ROWS"):]
    block = block[:block.index("except Exception as _bte")]
    assert "if _ctx and _main:" in block
    assert "if _n > 1:" in block
