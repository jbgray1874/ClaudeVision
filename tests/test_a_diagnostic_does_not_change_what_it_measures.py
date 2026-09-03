r"""
test_a_diagnostic_does_not_change_what_it_measures.py

dxf_print_check wrote its PDFs next to the DXF it was checking. The next run of that job read
them as drawings:

    • Extracting 11908-21-01J_9mm MDF+ LAM_REV[A]_print_check.pdf
    • Extracting 11908-21-01J_9mm MDF+ LAM_REV[A]_print_check_merged.pdf

11908-21 was estimated from four PDFs where the pack has two, the extras at geometry
reliability 0.25, and they were staged into the shared folder along with everything else. A
tool for finding out why a drawing prints wrong must not leave anything behind in the pack.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "tools" / "dxf_print_check.py").read_text(encoding="utf-8")


def test_nothing_is_written_beside_the_drawing():
    """`with_name` on the SOURCE puts a file in the job folder. Every output must be built
    from the temp path instead."""
    tree = ast.parse(SRC)
    bad = [n.lineno for n in ast.walk(tree)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == "with_name"
           and isinstance(n.func.value, ast.Name) and n.func.value.id == "src"]
    assert not bad, f"src.with_name(...) at line(s) {bad} writes into the job folder"


def test_the_output_goes_to_temp():
    assert "Path(tempfile.gettempdir()) / (src.stem" in SRC


def test_every_file_it_writes_hangs_off_that_one_path():
    """The merged copy and the portal copy are derived from `out`, so moving `out` moves all
    three. One place decides where this tool writes."""
    for derived in ('out.with_name(out.stem + "_merged.pdf")',
                    'out.with_name(out.stem + "_as_the_portal.pdf")'):
        assert derived in SRC, f"{derived} is not derived from the temp path"


def test_the_docstring_no_longer_promises_to_write_beside_the_dxf():
    """It said so in its own instructions, which is how it got used that way."""
    head = SRC[:SRC.index('"""', 10)]
    assert "next to the DXF" not in head
    assert "TEMP" in head
