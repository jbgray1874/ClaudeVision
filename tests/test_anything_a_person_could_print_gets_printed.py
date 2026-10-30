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
def test_office_on_a_non_windows_machine_says_which_machine(tmp_path, monkeypatch):
    """With the switch ON, the next thing checked is the platform. Enabled explicitly here
    because Office became opt-in after this was written — and the platform guard still has to
    hold for anyone who turns it on."""
    monkeypatch.setattr(pc, "OFFICE_ENABLED", True)
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


# ── the hang, and why Office runs in a child process ───────────────────────────
#
# The first pack printed with Office conversion enabled hung on the estimating page. Spreadsheets
# in the file list, Excel opened through COM, and something in it raised a dialog nobody could
# see. A COM call waiting on a modal dialog blocks UNINTERRUPTIBLY — no timeout, no
# KeyboardInterrupt, no way to give up — so the print never returned.
#
# In-process there is no fix. A subprocess can be killed; a blocked COM call cannot. These pin the
# shape of that fix so nobody quietly moves it back in-process for tidiness.

def test_office_conversion_has_a_timeout():
    assert isinstance(pc.OFFICE_TIMEOUT_SECONDS, (int, float))
    assert 30 <= pc.OFFICE_TIMEOUT_SECONDS <= 600, (
        "long enough that a big spreadsheet finishes, short enough that a dialog is caught")


def test_office_runs_out_of_process():
    """The property that makes the timeout possible at all."""
    src = (_ROOT / "src" / "printable_converters.py").read_text(encoding="utf-8")
    at = src.index("def _office_to_pdf(")
    body = src[at:src.index("def _kill_stray_office")]
    assert "subprocess.run" in body, "an in-process COM call cannot be timed out"
    assert "TimeoutExpired" in body
    assert "OFFICE_TIMEOUT_SECONDS" in body


def test_a_timeout_is_reported_as_a_file_problem_not_a_machine_problem():
    """Word being installed and Word hanging on one document are different situations, and the
    cover has to say which. A timeout means: look at that file."""
    src = (_ROOT / "src" / "printable_converters.py").read_text(encoding="utf-8")
    at = src.index("except subprocess.TimeoutExpired:")
    block = src[at:at + 500]
    assert "ConversionFailed" in block
    assert "ConversionUnavailable" not in block


def test_the_two_meanings_survive_the_process_boundary():
    """An exception type does not cross a process boundary. The child prints a marker and the
    parent reads it, or 'Word is not installed' and 'this file is corrupt' become one message."""
    src = (_ROOT / "src" / "printable_converters.py").read_text(encoding="utf-8")
    assert 'UNAVAILABLE:' in src
    at = src.index("def _office_child_main")
    child = src[at:]
    assert "UNAVAILABLE:" in child, "the child must emit the marker"
    parent = src[src.index("def _office_to_pdf("):src.index("def _kill_stray_office")]
    assert 'startswith("UNAVAILABLE:")' in parent, "the parent must read it"


def test_the_child_entry_point_exists_and_takes_two_paths():
    assert hasattr(pc, "_office_child_main")
    src = (_ROOT / "src" / "printable_converters.py").read_text(encoding="utf-8")
    assert '"--office"' in src, "the dispatcher and the child must agree on the flag"


@pytest.mark.skipif(sys.platform == "win32", reason="taskkill is real on Windows")
def test_the_stray_killer_is_a_no_op_off_windows(tmp_path):
    pc._kill_stray_office(tmp_path / "o.pdf")          # must not raise


# ── it must never close a document somebody is working in ──────────────────────
#
# The first version killed EVERY Excel, Word and PowerPoint on the machine, reasoning that
# "nobody is working in Excel while a print is running". The first time it ran it closed a Word
# document that had been open since the previous afternoon, and a PowerPoint deck. Neither had
# anything to do with the print.
#
# An assumption about how somebody uses their own laptop is not a safety mechanism.

def test_it_kills_by_process_id_and_never_by_image_name():
    src = (_ROOT / "src" / "printable_converters.py").read_text(encoding="utf-8")
    at = src.index("def _kill_stray_office")
    body = src[at:src.index("def _office_pids")]
    assert '"/IM"' not in body, (
        "killing by image name closes every Office window on the machine, including documents "
        "somebody is working in")
    assert '"/PID"' in body


def test_with_nothing_recorded_it_kills_nothing(tmp_path, monkeypatch):
    """The safe default. A stray Office process that slows the next conversion is a much smaller
    problem than shutting a document somebody has open."""
    calls = []
    monkeypatch.setattr(pc.subprocess, "run",
                        lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(pc.sys, "platform", "win32")
    pc._kill_stray_office(tmp_path / "never-written.pdf")
    assert calls == [], "it tried to kill something with no process id recorded"


def test_the_recorded_id_is_the_one_that_is_killed(tmp_path, monkeypatch):
    out = tmp_path / "o.pdf"
    pc._pid_file(out).write_text("4242", encoding="utf-8")
    seen = []
    monkeypatch.setattr(pc.sys, "platform", "win32")
    monkeypatch.setattr(pc.subprocess, "run", lambda cmd, **k: seen.append(cmd))
    pc._kill_stray_office(out)
    assert seen and seen[0][:3] == ["taskkill", "/F", "/PID"]
    assert seen[0][3] == "4242"


def test_the_marker_is_cleared_so_a_later_print_cannot_reuse_it(tmp_path, monkeypatch):
    """A stale id would name a process that has since been recycled to something else."""
    out = tmp_path / "o.pdf"
    pc._pid_file(out).write_text("4242", encoding="utf-8")
    monkeypatch.setattr(pc.sys, "platform", "win32")
    monkeypatch.setattr(pc.subprocess, "run", lambda cmd, **k: None)
    pc._kill_stray_office(out)
    assert not pc._pid_file(out).exists()


def test_the_child_only_records_when_exactly_one_process_appeared():
    """Two appearing at once means we cannot tell which is ours, and killing the wrong one is
    the whole failure this is here to prevent. Recording nothing is the right answer."""
    src = (_ROOT / "src" / "printable_converters.py").read_text(encoding="utf-8")
    assert "len(started) == 1" in src


# ── the engine's own output is not a drawing ───────────────────────────────────
#
# The Drawings panel holds a job FOLDER, and after a run that folder holds what the engine wrote.
# Print was opening Excel — through COM — to render the AI's own estimate workbook back into a
# page. That is what hung the first real print. An estimator pressing Print wants the drawings;
# they already have the estimate, it is the thing they are checking against.

@pytest.mark.parametrize("name", [
    "10575-02_20260824_162345.xlsx",
    "10575-02_20260825_183903.xlsx",
    "10575-02_quote.html",
    "10575-02_report.html",
    "10575-02_parity_bundle.json",
])
def test_a_run_deliverable_is_recognised_as_engine_output(name):
    assert dp.is_engine_output(name)


@pytest.mark.parametrize("name", [
    "10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF",
    "10575-02-009_DIBOND_3.0mm_Rev D.DXF",
    "Finishing spec.docx",
    "10575-02-GA (Rev D) Cordless Vacuum Display - V2.xls",   # the MANUAL estimate, not ours
])
def test_a_real_document_is_not_mistaken_for_engine_output(name):
    """The manual estimate is somebody's work, not a run deliverable. Excluding it would hide a
    file an estimator may well want."""
    assert not dp.is_engine_output(name)


def test_engine_output_is_never_opened(tmp_path):
    """Not merged, not converted, not even opened — which is the point, since opening it is what
    took ninety seconds of Excel per file."""
    import pymupdf
    d = pymupdf.open()
    d.new_page()
    (tmp_path / "GA.PDF").write_bytes(d.tobytes())
    d.close()
    (tmp_path / "10575-02_20260824_162345.xlsx").write_bytes(b"not really a workbook")
    (tmp_path / "10575-02_quote.html").write_text("<html></html>", encoding="utf-8")

    res = dp.build([str(tmp_path)], tmp_path / "m.pdf", job="10575-02")
    assert [Path(p).name for p in res["printed"]] == ["GA.PDF"]
    assert not any("_20260824_" in s["path"] for s in res["skipped"]), \
        "it reached the skipped list, which means it was opened"


# ── Office is opt-in ───────────────────────────────────────────────────────────

def test_office_is_off_unless_asked_for():
    """It is the only converter that drives another application, and the only one that can hang
    on something this process cannot see. Off by default is the difference between a Print button
    that is reliable and one that is not."""
    assert pc.OFFICE_ENABLED is False or "SDI_PRINT_OFFICE" in __import__("os").environ


def test_the_message_names_the_switch(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "OFFICE_ENABLED", False)
    src = tmp_path / "spec.docx"
    src.write_bytes(b"x")
    with pytest.raises(pc.ConversionUnavailable) as exc:
        pc.convert(src, tmp_path / "o.pdf")
    assert "SDI_PRINT_OFFICE" in str(exc.value), "a reader must be told how to turn it on"
