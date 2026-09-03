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
