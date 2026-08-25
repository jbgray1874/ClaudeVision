"""The NOT PRINTED list must only contain drawings that are actually missing from the paper.

Printing the 10575-02 pack produced a cover sheet listing four files in red under "These are part
of the job and are not in this print. They are listed so the pack is not reviewed as if it were
complete." Two of those four were not gaps at all:

  _sw_native_extract.json                 the ENGINE wrote this. It is not part of the job and
                                          was never a drawing.
  10575-02-GA ... [Rev D].DWG             the same GA was printed, from the PDF sitting beside it.
                                          The reviewer is holding that drawing.

Which leaves one real gap - a DXF with no PDF twin - buried in a list of three false alarms. The
list exists to catch exactly that one case, and a list that cries wolf is a list nobody reads.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.append(str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("dp", _ROOT / "src" / "drawings_print.py")
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)


# The real 10575-02 pack, as the Drawings panel held it.
PACK = [
    "10575-02-009_DIBOND_3.0mm_Rev D.DXF",
    "10575-02-GA - V2 Upright Vacuum Display [Rev D].DWG",
    "10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF",
    "10575-02-GA.SLDDRW",
    "_sw_native_extract.json",
]


@pytest.fixture()
def pack(tmp_path):
    for n in PACK:
        (tmp_path / n).write_bytes(b"x")
    return tmp_path


# ── the engine's own file is not a hole in the pack ────────────────────────────────────

def test_the_engine_extract_is_not_listed_as_a_missing_drawing(pack):
    printable, skipped = dp.collect([str(pack)])
    names = [p.name for p, _ in skipped]
    assert "_sw_native_extract.json" not in names, \
        "the engine's own extract was reported as a drawing missing from the print"


def test_the_engine_extract_is_not_printed_either(pack):
    printable, _ = dp.collect([str(pack)])
    assert "_sw_native_extract.json" not in [p.name for p in printable]


def test_an_unrecognised_file_is_still_reported(pack):
    """Dropping the engine's artefact must not become dropping anything inconvenient. A file
    nobody can account for is exactly what the list is for."""
    (pack / "notes.txt").write_bytes(b"x")
    _, skipped = dp.collect([str(pack)])
    assert "notes.txt" in [p.name for p, _ in skipped]


# ── a drawing printed from its PDF twin is not missing ─────────────────────────────────

def test_the_dwg_and_the_pdf_of_one_drawing_share_a_stem(pack):
    """The mechanism the cover relies on. If this ever stops holding, the split below is
    silently wrong rather than loudly wrong."""
    printable, skipped = dp.collect([str(pack)])
    stems = {p.stem.lower() for p in printable}
    dwg = next(p for p, _ in skipped if p.suffix.lower() == ".dwg")
    assert dwg.stem.lower() in stems


def test_only_the_dxf_is_a_genuine_gap(pack):
    """The DXF has no PDF twin; the DWG does; the SLDDRW does (same stem as the GA PDF? no -
    10575-02-GA vs the long GA name, so it is a gap too). Asserted explicitly so the split is
    pinned rather than assumed."""
    printable, skipped = dp.collect([str(pack)])
    stems = {p.stem.lower() for p in printable}
    gaps = sorted(p.name for p, _ in skipped if p.stem.lower() not in stems)
    covered = sorted(p.name for p, _ in skipped if p.stem.lower() in stems)

    assert covered == ["10575-02-GA - V2 Upright Vacuum Display [Rev D].DWG"]
    assert gaps == ["10575-02-009_DIBOND_3.0mm_Rev D.DXF", "10575-02-GA.SLDDRW"]


# ── the sentence on the paper ──────────────────────────────────────────────────────────

def test_one_drawing_follows_rather_than_follow():
    """It read "1 drawing follow this page." on every single-drawing print."""
    src = (_ROOT / "src" / "drawings_print.py").read_text(encoding="utf-8")
    assert "'follows' if n == 1 else 'follow'" in src


def test_the_pack_still_prints(pack):
    """End to end: the merge still produces a PDF, with the one real GA in it."""
    pytest.importorskip("fitz")
    out = pack / "merged.pdf"
    # A one-page PDF the merger can actually open.
    import fitz
    d = fitz.open(); d.new_page(width=595, height=842)
    (pack / "10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF").write_bytes(d.tobytes())
    d.close()

    res = dp.build([str(pack)], out, job="10575-02")
    assert out.is_file()
    assert [Path(p).name for p in res["printed"]] == \
        ["10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF"]
    # and the engine's artefact is absent from BOTH sides of the report
    assert all("_sw_native_extract" not in str(s) for s in res.get("skipped", []))
