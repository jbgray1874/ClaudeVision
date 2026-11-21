"""The enquiry brief as one A4 page image.

STANDALONE ON PURPOSE (21 Nov 2026). A brief-only job (a description with no drawings) is staged
by the SERVICE, which drew this page with PyMuPDF. PyMuPDF is the engine's library and was never
in the service's own requirements, so on the estimating laptop the first description-only TTI row
ended in "ModuleNotFoundError: No module named 'pymupdf'" and an HTTP 500. This file imports
nothing but PyMuPDF, under either of its names, so staging can run it in the service where the
library is there, and otherwise out of process under the engine's Python, as printing already is:

    <engine python> -B brief_page.py <text file, utf-8> <page image to write>
"""
from __future__ import annotations

import sys
from pathlib import Path


def pymupdf_module():
    """PyMuPDF under its current name, or its older one. ImportError when neither is installed."""
    try:
        import pymupdf                                               # noqa: WPS433
        return pymupdf
    except ImportError:
        import fitz                                                  # noqa: WPS433
        return fitz


def draw(body: str, out: str) -> None:
    """Shrinks the type until the text fits; a brief is capped upstream, so it always does."""
    mu = pymupdf_module()
    for size in (11.0, 9.5, 8.0, 6.5, 5.0):
        doc = mu.open()
        try:
            page = doc.new_page(width=595, height=842)
            rc = page.insert_textbox(mu.Rect(42, 42, 553, 800), body, fontsize=size, fontname="helv")
            if rc >= 0 or size == 5.0:                 # fits, or as small as it goes
                page.get_pixmap(dpi=150).save(str(out))
                return
        finally:
            doc.close()


if __name__ == "__main__":
    draw(Path(sys.argv[1]).read_text(encoding="utf-8"), sys.argv[2])
