r"""
test_a_drawing_is_printed_in_ink_on_paper.py

THE PRINT CAME OUT A BLACK SHEET.

drawings_print renders a DXF through ezdxf's drawing add-on, and RenderContext honours the
DXF's OWN background. A CAD model space is black with light entities on it — correct on a
screen and wrong on every printer. James, printing 11908-21-01J: one page, solid dark, pale
lines. Unreadable under strip lighting, and across a pack of eleven drawings it would empty a
toner cartridge.

BLACK ON WHITE, not merely inverted. A DXF carries entity colours by layer, and the mid-greys
and yellows that read fine on black are close to invisible on white. A drawing sent to a
printer is a line drawing, so every line is drawn in ink.

Falls back to the previous rendering on an ezdxf too old to carry the policies, because a
drawing printed the old way beats a drawing not printed at all.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SRC = (ROOT / "src" / "printable_converters.py").read_text(encoding="utf-8")


def _dxf_block() -> str:
    i = SRC.index("def _dxf_to_pdf(")
    return SRC[i:SRC.index("\ndef ", i + 10)]


def test_the_page_background_is_white_not_the_model_space():
    assert "BackgroundPolicy.WHITE" in _dxf_block(), (
        "the model space is black, and the printer is not")


def test_every_line_is_drawn_in_ink():
    """Inverting alone leaves a layer's mid-grey nearly invisible on white."""
    assert "ColorPolicy.BLACK" in _dxf_block()


def test_the_policies_are_handed_to_the_frontend_not_just_built():
    block = _dxf_block()
    assert "config=_cfg" in block, "a Configuration nothing is given to changes nothing"
    assert re.search(r"Frontend\(RenderContext\(doc\), backend, config=_cfg\)", block), (
        "the config must reach the Frontend that does the drawing")


def test_an_older_ezdxf_still_prints_rather_than_failing():
    """A drawing printed the old way beats a drawing not printed at all."""
    block = _dxf_block()
    assert "_cfg = None" in block and "except Exception" in block
    assert re.search(r"if _cfg is not None\s*\n\s*else Frontend\(RenderContext\(doc\), backend\)",
                     block), "there is no path for an ezdxf without the policies"


def test_the_policy_names_exist_in_the_installed_ezdxf():
    """Asserted against the library rather than trusted: a renamed enum would render a black
    page again and nothing else here would notice."""
    cfg = Path(pytest.importorskip("ezdxf").__file__).parent / "addons" / "drawing" / "config.py"
    text = cfg.read_text(encoding="utf-8")
    assert "class BackgroundPolicy" in text and "WHITE = auto()" in text
    assert "class ColorPolicy" in text and "BLACK = auto()" in text
    assert "background_policy: BackgroundPolicy" in text
    assert "color_policy: ColorPolicy" in text


# ── AND THEN THE PAGE CAME OUT BLANK ───────────────────────────────────────────
#
# The fix above was right and it revealed the real fault. James, on the same job with the
# white background in: one page, one of one, nothing on it. The dark sheet had never had a
# drawing on it — it was the background fill, and the geometry had been missing all along.
#
# layout.Page(0, 0, ...) does not mean "fit to the page". It means "make the page whatever
# size the drawing turns out to be", so ezdxf's fit-to-page had nothing to fit to. One stray
# entity a long way from the part — a construction point, a sheet-origin marker — and the
# page becomes the size of the DISTANCE to it, with the part a few thousandths of an inch
# across in a corner. Valid PDF, one page, blank to the eye.
#
# These tests render. Everything above this line proves a line was typed; everything below
# proves a drawing reached the paper, which is the thing that was actually wrong twice.

def _drawing_addon():
    return pytest.importorskip("ezdxf.addons.drawing.pymupdf",
                               reason="ezdxf's drawing add-on (needs Pillow)")


def _render(tmp_path, build, name="t"):
    import ezdxf
    import printable_converters as pc
    _drawing_addon()
    doc = ezdxf.new("R2010")
    build(doc, doc.modelspace())
    src = tmp_path / f"{name}.dxf"
    doc.saveas(src)
    return pc._dxf_to_pdf(src, tmp_path / f"{name}.pdf")


def _flat(doc, msp):
    msp.add_lwpolyline([(0, 0), (400, 0), (400, 300), (0, 300), (0, 0)])
    msp.add_circle((50, 50), 6)
    msp.add_circle((350, 250), 6)


def test_a_flat_pattern_reaches_the_paper_with_ink_on_it(tmp_path):
    """The whole of it, in one assertion: a drawing goes in, marks come out."""
    import printable_converters as pc
    out = _render(tmp_path, _flat)
    assert pc._ink_on_the_page(out), "the sheet is blank"


def test_it_is_printed_on_a_sheet_of_paper(tmp_path):
    """A3, not 'whatever size the drawing turned out to be'. A pack of flats that each come
    out a different size cannot be stapled, and an auto-sized page is what let a stray entity
    shrink a part out of sight."""
    import pymupdf
    out = _render(tmp_path, _flat)
    with pymupdf.open(str(out)) as doc:
        w_mm = doc[0].rect.width / 72 * 25.4
        h_mm = doc[0].rect.height / 72 * 25.4
    assert (round(w_mm), round(h_mm)) == (420, 297)


def test_the_paper_is_turned_to_suit_the_part(tmp_path):
    """A flat is usually wider than it is tall; when it is not, turning the paper is free."""
    import pymupdf
    out = _render(tmp_path, lambda d, m: m.add_lwpolyline(
        [(0, 0), (300, 0), (300, 400), (0, 400), (0, 0)]), name="tall")
    with pymupdf.open(str(out)) as doc:
        assert doc[0].rect.height > doc[0].rect.width


def test_a_stray_entity_far_from_the_part_is_named_not_shipped_blank(tmp_path):
    """THE FAULT ITSELF. A 400 x 300 flat and a single POINT five kilometres away. Before
    this, a valid one-page PDF with nothing visible on it — which in a merged pack reads as a
    drawing that was never included."""
    from printable_converters import ConversionFailed
    with pytest.raises(ConversionFailed) as e:
        _render(tmp_path, lambda d, m: (
            m.add_lwpolyline([(0, 0), (400, 0), (400, 300), (0, 300), (0, 0)]),
            m.add_point((5_000_000, 5_000_000))), name="stray")
    assert "blank" in str(e.value) and "5,000,000" in str(e.value), (
        "the reason has to carry the extents, or the cover page cannot say what to fix")


def test_a_drawing_whose_layers_are_switched_off_says_so(tmp_path):
    """The other way a flat prints as nothing, and the likelier one on a real pack: the cut
    layer is off in the file as issued. That is a sentence for design, not a blank sheet."""
    from printable_converters import ConversionFailed

    def off(doc, msp):
        doc.layers.add("CUT")
        doc.layers.get("CUT").off()
        msp.add_lwpolyline([(0, 0), (400, 0), (400, 300), (0, 300), (0, 0)],
                           dxfattribs={"layer": "CUT"})

    with pytest.raises(ConversionFailed) as e:
        _render(tmp_path, off, name="off")
    assert "switched off or frozen" in str(e.value)


def test_an_empty_model_space_is_a_named_failure(tmp_path):
    from printable_converters import ConversionFailed
    with pytest.raises(ConversionFailed):
        _render(tmp_path, lambda d, m: None, name="empty")


def test_the_blank_check_never_itself_stops_a_drawing_printing(tmp_path):
    """It answers None when it cannot tell, and None must not read as zero — otherwise a
    machine without pymupdf would report every drawing in the pack as blank."""
    import printable_converters as pc
    assert pc._ink_on_the_page(tmp_path / "does-not-exist.pdf") is None
    block = _dxf_block()
    assert "_ink is not None and _ink == 0" in block, (
        "an unanswerable check must not be evidence of a blank page")
