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
    nobody can account for is exactly what the list is for.

    `notes.txt` used to be the example here. It is now CONVERTIBLE — text files are printed —
    so the example moved to a suffix nothing claims. The rule under test has not changed.
    """
    (pack / "mystery.zzz").write_bytes(b"x")
    _, skipped = dp.collect([str(pack)])
    assert "mystery.zzz" in [p.name for p, _ in skipped]


def test_a_text_file_is_printed_rather_than_named(pack):
    """The rule that replaced it: a text file is something a person can print, so it prints."""
    (pack / "finishing notes.txt").write_bytes(b"RAL 9005 matt\n")
    printable, _ = dp.collect([str(pack)])
    assert "finishing notes.txt" in [p.name for p in printable]


# ── a drawing printed from its PDF twin is not missing ─────────────────────────────────

def test_the_stem_match_still_separates_a_twin_from_a_gap():
    """The mechanism the cover relies on, tested on the shape rather than on the pack.

    DXF and DWG are CONVERTIBLE now, so on a machine with ezdxf they are printed and never reach
    the skipped list at all. The stem rule still governs everything that does reach it — a model
    beside its own PDF is not a gap — so it is tested with a model, which no converter claims.
    """
    printed = [Path("10575-02-GA.PDF"), Path("10575-02-009.PDF")]
    skipped = [Path("10575-02-GA.SLDASM"), Path("10575-02-777.SLDPRT")]
    stems = {p.stem.lower() for p in printed}
    covered = sorted(p.name for p in skipped if p.stem.lower() in stems)
    gaps = sorted(p.name for p in skipped if p.stem.lower() not in stems)
    assert covered == ["10575-02-GA.SLDASM"]
    assert gaps == ["10575-02-777.SLDPRT"]


def test_a_drawing_format_is_never_given_the_old_dismissal(pack):
    """The invariant that holds whether or not this machine can render a DXF.

    With ezdxf present the DXF prints. Without it, the converter says WHICH piece is missing.
    Neither outcome may be the old catch-all sentence, and it must never simply vanish.
    """
    printable, skipped = dp.collect([str(pack)])
    dxf = "10575-02-009_DIBOND_3.0mm_Rev D.DXF"
    assert dxf in [p.name for p in printable] + [p.name for p, _ in skipped], "it vanished"
    for p, why in skipped:
        if p.suffix.lower() in (".dxf", ".dwg"):
            assert "is not a drawing" not in why, f"{p.name}: {why}"


# ── the sentence on the paper ──────────────────────────────────────────────────────────

def test_one_drawing_follows_rather_than_follow():
    """It read "1 drawing follow this page." on every single-drawing print.

    Asserted on BEHAVIOUR, not on the source text. This test used to grep for the exact
    conditional expression and broke the moment the sentence moved into a helper — while the
    grammar it exists to protect was still perfectly correct. A test that fails on a refactor and
    would pass on a regression is worse than no test.
    """
    assert dp._cover_count_line(printed_files=1, pages=1) == "1 sheet follows this page."
    assert dp._cover_count_line(printed_files=2, pages=2) == "2 sheets follow this page."


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
