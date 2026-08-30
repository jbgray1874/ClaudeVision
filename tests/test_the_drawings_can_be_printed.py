"""Printing a pack must never quietly print less than the pack.

An estimate is checked against the drawings, and a pack is rarely all PDFs — there are DXFs,
DWGs and SolidWorks models in it too, and none of those is a printable page. If those are
dropped in silence the estimator is handed eight sheets of a twelve-drawing pack with nothing
to say four are missing, and they will review what they were given as though it were complete.

That is the same failure the missing-drawings work exists to prevent, one step further along:
an incomplete pack, presented as a whole one. So these tests are mostly about what is REFUSED
and what is DECLARED, not about the merging.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# By explicit path: prepending src/ makes the ENGINE's `config` beat the portal backend's for
# the whole process, and the backend's own tests then fail depending on collection order.
_spec = importlib.util.spec_from_file_location(
    "drawings_print", _ROOT / "src" / "drawings_print.py")
drawings_print = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drawings_print)

fitz = pytest.importorskip("fitz", reason="PyMuPDF is not installed in this environment")


def _pdf(path: Path, pages: int = 1, text: str = "drawing") -> Path:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100), f"{text} {i + 1}", fontsize=18)
    doc.save(str(path))
    doc.close()
    return path


# ── what gets collected ─────────────────────────────────────────────────────────────────

def test_a_job_folder_is_walked_because_that_is_what_a_pack_is(tmp_path):
    """The Drawings panel holds a job FOLDER as often as it holds files.

    Order is by FULL PATH, not by filename, so a pack that files its drawings into PDFs\\ and
    DXFs\\ prints each folder's contents together instead of interleaving them. The property
    that matters is that it is stable: the same pack must print the same way twice, or two
    printings of one job cannot be compared page for page.
    """
    pack = tmp_path / "11650-04"
    (pack / "sub").mkdir(parents=True)
    _pdf(pack / "b.pdf")
    _pdf(pack / "sub" / "a.pdf")

    printable, skipped = drawings_print.collect([str(pack)])
    assert [p.name for p in printable] == ["b.pdf", "a.pdf"], \
        "top-level drawings first, then each sub-folder's, in path order"
    assert printable == drawings_print.collect([str(pack)])[0], "and stable across calls"
    assert not skipped


def test_a_model_is_named_as_unprintable_not_dropped(tmp_path):
    _pdf(tmp_path / "ga.pdf")
    (tmp_path / "body.sldprt").write_text("0\nSECTION\n")
    (tmp_path / "part.SLDPRT").write_bytes(b"\x00")

    printable, skipped = drawings_print.collect([str(tmp_path)])
    assert [p.name for p in printable] == ["ga.pdf"]
    names = {p.name for p, _ in skipped}
    assert names == {"body.sldprt", "part.SLDPRT"}
    for _, why in skipped:
        assert "not a printable drawing" in why


def test_a_file_that_is_not_there_is_reported_not_ignored(tmp_path):
    _, skipped = drawings_print.collect([str(tmp_path / "gone.pdf")])
    assert skipped and "not found" in skipped[0][1]


def test_the_same_drawing_twice_prints_once(tmp_path):
    """A folder AND a file inside it is the obvious way to double a pack by accident."""
    _pdf(tmp_path / "ga.pdf")
    printable, _ = drawings_print.collect([str(tmp_path), str(tmp_path / "ga.pdf")])
    assert len(printable) == 1


# ── what the merged document says ───────────────────────────────────────────────────────

def test_a_clean_pack_prints_the_drawings_and_nothing_else(tmp_path):
    """No cover sheet when there is nothing to declare.

    An extra sheet on every print is an annoyance, and an annoyance is how a feature stops
    being used. The cover earns its place only when something is missing.
    """
    _pdf(tmp_path / "a.pdf", pages=2)
    _pdf(tmp_path / "b.pdf", pages=1)
    out = tmp_path / "merged.pdf"

    res = drawings_print.build([str(tmp_path)], out, job="11650-04")

    assert res["cover_page"] is False
    assert res["pages"] == 3, "three drawing pages, no cover"
    assert res["skipped_count"] == 0
    with fitz.open(str(out)) as doc:
        assert [t[1] for t in doc.get_toc()] == ["a.pdf", "b.pdf"], \
            "a bookmark per drawing, so a long pack can be navigated"


def test_an_incomplete_pack_says_so_on_the_paper(tmp_path):
    """The cover page is the only warning that survives the walk to the printer."""
    _pdf(tmp_path / "ga.pdf", pages=1)
    (tmp_path / "body.sldprt").write_text("0\n")
    out = tmp_path / "merged.pdf"

    res = drawings_print.build([str(tmp_path)], out, job="10575-02")

    assert res["cover_page"] is True
    assert res["pages"] == 2, "one drawing page plus the cover"
    with fitz.open(str(out)) as doc:
        cover = doc[0].get_text()
        assert "10575-02" in cover
        assert "NOT PRINTED" in cover
        assert "body.sldprt" in cover, "the missing file must be named, not merely counted"
        # The bookmarks must still point at the right pages once the cover has shifted them.
        toc = doc.get_toc()
        assert toc[0][2] == 1 and toc[1][1] == "ga.pdf" and toc[1][2] == 2


def test_one_corrupt_pdf_does_not_lose_the_others(tmp_path):
    """A password-protected or truncated file is common on a share, and it must cost one
    drawing rather than the whole print."""
    _pdf(tmp_path / "a.pdf")
    _pdf(tmp_path / "c.pdf")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4 truncated, not a document")
    out = tmp_path / "merged.pdf"

    res = drawings_print.build([str(tmp_path)], out)

    assert res["printed_count"] == 2
    assert res["skipped_count"] == 1
    assert "could not be opened" in res["skipped"][0]["reason"]
    with fitz.open(str(out)) as doc:
        assert "b.pdf" in doc[0].get_text()


def test_a_pack_with_nothing_printable_refuses_and_explains(tmp_path):
    """Silence here would produce an empty PDF, which reads as 'this job has no drawings'."""
    (tmp_path / "body.sldprt").write_text("0\n")
    (tmp_path / "part.SLDPRT").write_bytes(b"\x00")

    with pytest.raises(drawings_print.PrintInputError) as exc:
        drawings_print.build([str(tmp_path)], tmp_path / "out.pdf")
    msg = str(exc.value)
    # "Only PDFs can be printed" was removed from this message deliberately: it stopped being
    # true when text, images, DXF and Office documents gained converters, and a message naming
    # the wrong format sends somebody to look at the wrong files.
    assert "2 file" in msg
    assert "Only PDFs" not in msg
    assert "models" in msg or "geometry" in msg


def test_nothing_at_all_is_a_different_message(tmp_path):
    with pytest.raises(drawings_print.PrintInputError) as exc:
        drawings_print.build([], tmp_path / "out.pdf")
    assert "No drawings were given" in str(exc.value)
