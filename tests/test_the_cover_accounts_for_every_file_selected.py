"""Every file the estimator selected must be accounted for on the cover.

James selected five files for 10575-02. The cover accounted for four:

    1 printed          10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF
    2 NOT PRINTED      ..._DIBOND_3.0mm_Rev D.DXF   ·   10575-02-GA.SLDDRW
    1 ALSO IN THE PACK 10575-02-GA - V2 ... [Rev D].DWG

The fifth was `_sw_native_extract.json` — the SOLIDWORKS extract the engine writes beside the
drawings. `collect()` drops it and returns, so it appears in neither list and on no line of the
cover. It simply vanishes.

Dropping it from the RED list was right, and that was a deliberate earlier fix: it is not part of
the job and it is not a drawing, and a warning that cries wolf about a file nobody was going to
print is how the list stops being read. But dropping it from the page ENTIRELY is a different
mistake. Somebody who selected five files and can count four has no way to tell whether the fifth
was ignored on purpose or lost on the way — and "lost on the way" is exactly the failure this
cover exists to rule out.

So it is named, quietly, in grey, under its own heading. Not a gap, not a warning: a reconciliation
line, so the arithmetic works for the person holding the paper.

THE OTHER SILENT PATH, recorded so it is not forgotten: `collect()` also drops a file it has
already seen, which happens when the same path arrives twice (a folder plus a file inside it).
That one is a true no-op — the file IS accounted for, once — so it needs no line.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("dp", _ROOT / "src" / "drawings_print.py")
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)


def _pdf(path, pages=1):
    import pymupdf
    d = pymupdf.open()
    for _ in range(pages):
        d.new_page()
    d.save(str(path))
    d.close()


@pytest.fixture()
def pack(tmp_path):
    """The 10575-02 pack, as it actually is: five files."""
    _pdf(tmp_path / "10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF", 3)
    (tmp_path / "10575-02-GA - V2 Upright Vacuum Display [Rev D].DWG").write_bytes(b"")
    (tmp_path / "10575-02-009_DIBOND_3.0mm_Rev D.DXF").write_bytes(b"")
    (tmp_path / "10575-02-GA.SLDDRW").write_bytes(b"")
    (tmp_path / "_sw_native_extract.json").write_text("{}", encoding="utf-8")
    return tmp_path


# ── collect reports what it ignored ────────────────────────────────────────────

def test_collect_can_report_the_files_it_ignored(pack):
    ignored: list = []
    printable, skipped = dp.collect([str(pack)], ignored=ignored)
    assert [p.name for p in ignored] == ["_sw_native_extract.json"]


def test_the_optional_argument_is_genuinely_optional(pack):
    """Twelve existing call sites unpack two values. Adding a third return would have churned
    every one of them to carry a value they do not use.

    Asserted on the CALL, not on a count: DXF and DWG became convertible after this was written
    and the count moved from 1 to 3, while the property under test — that the argument may be
    omitted — never changed."""
    printable, skipped = dp.collect([str(pack)])
    assert isinstance(printable, list) and isinstance(skipped, list)
    assert "10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF" in [p.name for p in printable]


def test_the_ignored_file_is_in_neither_list(pack):
    """It must not creep into the red list — that was the fix this one has to preserve."""
    ignored: list = []
    printable, skipped = dp.collect([str(pack)], ignored=ignored)
    names = {p.name for p in printable} | {p.name for p, _ in skipped}
    assert "_sw_native_extract.json" not in names


def test_every_selected_file_lands_in_exactly_one_bucket(pack):
    """The arithmetic that failed. Five in, five accounted for."""
    ignored: list = []
    printable, skipped = dp.collect([str(pack)], ignored=ignored)
    total = len(printable) + len(skipped) + len(ignored)
    assert total == 5, (
        f"5 files selected, {total} accounted for — "
        f"printed {len(printable)}, skipped {len(skipped)}, ignored {len(ignored)}")


# ── and it reaches the paper ───────────────────────────────────────────────────

def test_the_cover_names_the_engine_file(pack, tmp_path):
    import pymupdf
    out = tmp_path / "merged.pdf"
    dp.build([str(pack)], out, job="10575-02")
    doc = pymupdf.open(str(out))
    try:
        cover = doc[0].get_text()
        assert "_sw_native_extract.json" in cover, (
            "the fifth file is still invisible; the count does not reconcile")
    finally:
        doc.close()


def test_the_engine_file_is_not_under_the_not_printed_heading(pack, tmp_path):
    """The earlier fix, held. It must be named without being called a gap."""
    import pymupdf
    out = tmp_path / "merged.pdf"
    dp.build([str(pack)], out, job="10575-02")
    doc = pymupdf.open(str(out))
    try:
        lines = doc[0].get_text().splitlines()
        at = next(i for i, ln in enumerate(lines) if "_sw_native_extract.json" in ln)
        above = "\n".join(lines[:at])
        assert above.rfind("NOT PRINTED") < above.rfind("IGNORED"), (
            "the engine artefact was filed under NOT PRINTED, which is what we fixed before")
    finally:
        doc.close()


def test_a_clean_pack_gains_no_extra_heading(tmp_path):
    """No engine file, no line about engine files. The cover stays as short as the pack allows."""
    import pymupdf
    _pdf(tmp_path / "GA.PDF", 2)
    (tmp_path / "GA-DETAIL.DXF").write_bytes(b"")
    out = tmp_path / "merged.pdf"
    dp.build([str(tmp_path)], out, job="J1")
    doc = pymupdf.open(str(out))
    try:
        assert "IGNORED" not in doc[0].get_text()
    finally:
        doc.close()
