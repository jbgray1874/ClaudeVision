"""No Shapely call may name an argument Shapely has renamed.

`Point(...).buffer(r, resolution=16)` sat on the LIVE measured-geometry path — src/
dxf_reader.py is a shim that loads dxf_reader.py.py, so the double-extension file is the
implementation, not a leftover. Shapely calls that parameter `resolution` in 1.x and
`quad_segs` in 2.x, and 2.1 deprecates the old spelling.

The deprecation itself is harmless. What it becomes is not: the call sits inside a
`try/except Exception: continue`, so on the release that removes the name it raises
TypeError, gets swallowed, and every hole silently stops being subtracted from net area.
No error, no flag, a quietly larger part on the rank-80 path.

Passing it positionally is correct on both majors — the second positional parameter has
always meant segments per quarter circle — and cannot rot.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

# Names Shapely has renamed across a major version. Spelling either one binds the caller
# to a Shapely era; the positional form belongs to neither.
RENAMED = ("resolution", "quad_segs", "quadsegs")


def _buffer_calls():
    for path in sorted(SRC.rglob("*.py*")):
        if path.suffix not in (".py",) and not path.name.endswith(".py.py"):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except Exception:                                           # pragma: no cover
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if ".buffer(" in line:
                yield path, line_no, line


def test_no_buffer_call_names_a_renamed_shapely_argument():
    offenders = []
    for path, line_no, line in _buffer_calls():
        call = line[line.index(".buffer("):]
        for name in RENAMED:
            if re.search(rf"\b{name}\s*=", call):
                offenders.append(f"{path.relative_to(SRC.parent)}:{line_no}: {line.strip()}")
    assert not offenders, (
        "Shapely buffer() called with a version-bound argument name. Pass it positionally "
        "— the second positional parameter means segments per quarter circle on every "
        "Shapely version:\n  " + "\n  ".join(offenders))


def test_the_live_reader_is_the_double_extension_file():
    """If this ever stops being true, the check above is guarding the wrong file.

    src/dxf_reader.py is eleven lines of shim. The implementation — and the Shapely call —
    lives in dxf_reader.py.py, which reads as a leftover and is not.
    """
    shim = (SRC / "dxf_reader.py").read_text(encoding="utf-8-sig")
    assert "dxf_reader.py.py" in shim, \
        "dxf_reader.py no longer loads dxf_reader.py.py — re-point this guard"
    assert (SRC / "dxf_reader.py.py").is_file()


def test_the_hole_subtraction_is_still_inside_a_swallowing_except():
    """Why the guard above is a test rather than a comment.

    If this loop ever grows an honest error path, a broken buffer() call would announce
    itself and a static guard would be belt and braces. While the except swallows
    everything, it cannot, and the only warning is a number that quietly got bigger.
    """
    text = (SRC / "dxf_reader.py.py").read_text(encoding="utf-8-sig")
    block = text[text.index("for e in (cut_circs or []):"):]
    block = block[:block.index("fill = ")]
    assert "except Exception:" in block and "continue" in block


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
