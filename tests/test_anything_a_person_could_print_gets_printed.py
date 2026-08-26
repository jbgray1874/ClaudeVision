"""Print should mean print.

The button merged PDFs and named everything else on a cover page. A job folder holds a finishing
spec, a customer's notes, a site photo, a cut list and a flat pattern — and an estimator was told
five of six files were "not a drawing". True, and useless.

    Finishing spec.docx   ->  not printed — '.docx' is not a drawing
    Site photo.jpg        ->  not printed — '.jpg' is not a drawing
    Cut list.xlsx         ->  not printed — '.xlsx' is not a drawing

So `printable_converters` turns anything a person could send to a printer into a PDF, and the
merge takes it from there.

WHAT THESE TESTS CAN AND CANNOT COVER, said plainly because it matters.

Text and images convert here — PyMuPDF is a hard dependency and does both. Those are tested for
real: a file goes in, a PDF with pages comes out.

DXF needs ezdxf, and Office needs Windows and a Word installation. NEITHER IS PRESENT IN CI, so
what is tested here is the GUARD: that an unavailable converter raises ConversionUnavailable
naming the missing piece, rather than throwing ImportError up through the merge and costing the
whole pack. The conversions themselves have to be verified on the laptop — and the guard is what
makes it safe to ship before that happens.

THE DISTINCTION THE COVER DEPENDS ON. ConversionUnavailable means THIS MACHINE cannot, and the
file is fine — "Word is not installed" tells somebody how to fix it. ConversionFailed means THIS
FILE cannot — look at the file. Collapsing the two gives a message that helps with neither, so
they are separate exceptions and separate tests.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("pc", _ROOT / "src" / "printable_converters.py")
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)

_dspec = importlib.util.spec_from_file_location("dp", _ROOT / "src" / "drawings_print.py")
dp = importlib.util.module_from_spec(_dspec)
_dspec.loader.exec_module(dp)


def _pages(path: Path) -> int:
    import pymupdf
    d = pymupdf.open(str(path))
    try:
        return d.page_count
    finally:
        d.close()


# ── the registry ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("suffix,what", [
    (".txt", "a text file"), (".csv", "a text file"),
    (".jpg", "an image"), (".png", "an image"),
    (".dxf", "a DXF drawing"), (".dwg", "a DWG drawing"),
    (".docx", "a Word document"), (".doc", "a Word document"),
    (".xlsx", "a spreadsheet"), (".pptx", "a presentation"),
])
def test_every_printable_format_is_described_in_words(suffix, what):
    """The cover prints this description. '.docx' means nothing to a reader; 'a Word document'
    does, and it is what makes the difference between a useful line and the old dismissal."""
    assert pc.describe_suffix(suffix) == what


def test_an_unknown_suffix_is_not_claimed():
    assert pc.describe_suffix(".zzz") is None
    assert pc.converter_for(".zzz") is None


def test_pdf_is_not_in_the_registry():
    """PDFs are merged directly. A converter for them would be a pointless round trip."""
    assert ".pdf" not in pc.CONVERTIBLE_SUFFIXES


def test_converting_something_unclaimed_says_so_rather_than_crashing():
    with pytest.raises(pc.ConversionUnavailable):
        pc.convert(Path("x.zzz"), Path("out.pdf"))


# ── text, converted for real ───────────────────────────────────────────────────

def test_a_text_file_becomes_pages(tmp_path):
    src = tmp_path / "finishing notes.txt"
    src.write_text("RAL 9005 matt\nTwo coats\nMask the threads\n", encoding="utf-8")
    out = pc.convert(src, tmp_path / "o.pdf")
    assert out.is_file() and _pages(out) >= 1


def test_the_text_page_carries_the_filename(tmp_path):
    """A loose page in a merged pack with no title is a page nobody can place."""
    import pymupdf
    src = tmp_path / "customer email.txt"
    src.write_text("please quote for 40 off\n", encoding="utf-8")
    out = pc.convert(src, tmp_path / "o.pdf")
    d = pymupdf.open(str(out))
    try:
        assert "customer email.txt" in d[0].get_text()
        assert "please quote for 40 off" in d[0].get_text()
    finally:
        d.close()


def test_a_long_line_wraps_rather_than_running_off_the_page(tmp_path):
    """A CSV row clipped at the margin is a row nobody can check."""
    import pymupdf
    src = tmp_path / "cut list.csv"
    src.write_text("part," + ",".join(f"col{i}" for i in range(60)) + "\n", encoding="utf-8")
    out = pc.convert(src, tmp_path / "o.pdf")
    d = pymupdf.open(str(out))
    try:
        assert "col59" in d[0].get_text(), "the end of the row was lost"
    finally:
        d.close()


def test_a_very_long_file_is_cut_off_and_says_so(tmp_path):
    """Truncating silently would hand somebody a document that looks complete."""
    import pymupdf
    src = tmp_path / "run.log"
    src.write_text("\n".join(f"line {i}" for i in range(pc._MAX_TEXT_LINES + 500)),
                   encoding="utf-8")
    out = pc.convert(src, tmp_path / "o.pdf")
    d = pymupdf.open(str(out))
    try:
        assert "cut off" in d[d.page_count - 1].get_text()
    finally:
        d.close()


def test_an_empty_text_file_still_produces_a_page(tmp_path):
    """Zero pages would be dropped by the merge as 'it has no pages', which is a confusing way
    to report an empty file."""
    src = tmp_path / "empty.txt"
    src.write_text("", encoding="utf-8")
    out = pc.convert(src, tmp_path / "o.pdf")
    assert _pages(out) == 1


# ── images, converted for real ─────────────────────────────────────────────────

def test_an_image_becomes_a_page(tmp_path):
    import pymupdf
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 240, 180))
    pix.clear_with(200)
    src = tmp_path / "site photo.png"
    pix.save(str(src))
    out = pc.convert(src, tmp_path / "o.pdf")
    assert _pages(out) == 1


def test_a_file_that_is_not_really_an_image_fails_as_a_file_problem(tmp_path):
    """ConversionFailed, not ConversionUnavailable — the machine is fine, the file is not."""
    src = tmp_path / "broken.png"
    src.write_bytes(b"this is not a png")
    with pytest.raises(pc.ConversionFailed):
        pc.convert(src, tmp_path / "o.pdf")


# ── the guards, which are what make this safe to ship before the laptop test ────

@pytest.mark.skipif(sys.platform == "win32", reason="the Windows path is tested on the laptop")
def test_office_on_a_non_windows_machine_says_which_machine(tmp_path):
    src = tmp_path / "spec.docx"
    src.write_bytes(b"x")
    with pytest.raises(pc.ConversionUnavailable) as exc:
        pc.convert(src, tmp_path / "o.pdf")
    assert "Windows" in str(exc.value)


def test_dwg_without_the_converter_names_the_setting(tmp_path, monkeypatch):
    """The message has to name SDI_DWG_CONVERTER, because that is the fix."""
    import config as engine_config
    monkeypatch.setattr(engine_config, "DWG_CONVERTER_PATH", None, raising=False)
    src = tmp_path / "flat.dwg"
    src.write_bytes(b"x")
    with pytest.raises(pc.ConversionUnavailable) as exc:
        pc.convert(src, tmp_path / "o.pdf")
    assert "SDI_DWG_CONVERTER" in str(exc.value)


def test_an_unavailable_converter_never_reaches_the_merge_as_an_exception(tmp_path):
    """The property the whole design rests on: one document Word cannot open must not cost the
    drawings beside it."""
    import pymupdf
    d = pymupdf.open()
    d.new_page()
    (tmp_path / "GA.PDF").write_bytes(d.tobytes())
    d.close()
    (tmp_path / "spec.docx").write_bytes(b"x")          # unconvertible in CI

    out = tmp_path / "merged.pdf"
    res = dp.build([str(tmp_path)], out, job="J1")
    assert [Path(p).name for p in res["printed"]] == ["GA.PDF"], "the PDF was lost"
    assert any("spec.docx" in s["path"] for s in res["skipped"])


def test_the_cover_says_what_is_missing_not_that_it_is_not_a_drawing(tmp_path):
    """The whole point. 'a Word document — Word conversion needs Windows' is actionable;
    "'.docx' is not a drawing" is not."""
    import pymupdf
    d = pymupdf.open()
    d.new_page()
    (tmp_path / "GA.PDF").write_bytes(d.tobytes())
    d.close()
    (tmp_path / "Finishing spec.docx").write_bytes(b"x")

    out = tmp_path / "merged.pdf"
    dp.build([str(tmp_path)], out, job="J1")
    doc = pymupdf.open(str(out))
    try:
        cover = doc[0].get_text()
        assert "is not a drawing" not in cover
        assert "Word document" in cover
    finally:
        doc.close()
