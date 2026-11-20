"""ONE PRODUCT'S PACK, NOT ITS WHOLE FAMILY'S (20 Nov 2026).

Row 140 of the TTI tracker: 11671-01-GA17 is one of seventeen products (GA1 to GA17) sharing
the family 11671-01-. Every drawing of the family went into GA17's pack, 565 drawings, and the
service refused it ("past the 400 limit"). Made-up numbers below; the shape is kept.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pack_resolver as pr  # noqa: E402


def _job(tmp: Path, gas: int = 3):
    tech = tmp / "TTI" / "50005 - Stands" / "50005-Technical"
    tech.mkdir(parents=True)
    names = []
    for g in range(1, gas + 1):
        names.append(f"50005-01-GA{g}.pdf")
        names += [f"50005-01-{g:02d}{k}M.pdf" for k in ("A", "B")]       # each GA's own parts
    names.append("50005-01-99M.pdf")                                     # a common part
    out = []
    for i, n in enumerate(names):
        p = tech / n
        p.write_text(n)
        out.append((p, p.stat().st_size, 1_000_000 + i))
    return [(tech, out, False)]


def _read(path: Path) -> str:
    stem = path.stem
    if "-GA" in stem:
        g = int(stem.rsplit("GA", 1)[1])
        return (f"ITEM DWG NO. DESCRIPTION QTY\n1 50005-01-{g:02d}AM PANEL 1\n2 50005-01-{g:02d}BM RAIL 2\n"
                f"3 50005-01-99M FOOT 4\nSTAND {stem} A")
    return ""


def _members(m):
    return sorted(x["drawing"] for x in m["members"])


def test_the_pack_is_what_this_ga_calls_for_not_its_sibling_products(tmp_path):
    m = pr.resolve("50005-01-GA3", _job(tmp_path), client="TTI", read_text=_read, area_rank=lambda f: 0)
    assert _members(m) == ["50005-01-03AM", "50005-01-03BM", "50005-01-99M", "50005-01-GA3"], _members(m)
    assert "50005-01-GA1" in m["left_out_other_products"]
    assert any("other products' GAs" in a for a in m["assumptions"])


def test_a_family_with_one_ga_keeps_its_other_drawings_as_before(tmp_path):
    """THE CONTROL: with no other product in the family, nothing is left out."""
    rows = _job(tmp_path, gas=1)
    extra = rows[0][0] / "50005-01-77M.pdf"
    extra.write_text("x")
    rows[0][1].append((extra, 1, 1_000_900))
    m = pr.resolve("50005-01-GA1", rows, client="TTI", read_text=_read, area_rank=lambda f: 0)
    assert "50005-01-77M" in _members(m)
    assert "left_out_other_products" not in m


def test_an_unread_ga_leaves_nothing_out(tmp_path):
    """With the GA's own list unread nothing is known about what it calls for, so nothing is
    dropped on a guess."""
    m = pr.resolve("50005-01-GA3", _job(tmp_path), client="TTI", read_text=lambda p: "",
                   area_rank=lambda f: 0)
    assert "left_out_other_products" not in m
