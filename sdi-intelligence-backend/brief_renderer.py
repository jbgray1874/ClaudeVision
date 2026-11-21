"""Description-only staging renderer. No shares, queue, engine or external calls."""
from __future__ import annotations
import importlib


class BriefRendererUnavailable(RuntimeError):
    pass


def render_brief_png(text: str) -> bytes:
    try:
        pdf = importlib.import_module('pymupdf')
    except (ImportError, OSError) as exc:
        raise BriefRendererUnavailable(
            'Description-only staging requires PyMuPDF in the SERVICE virtualenv '
            '(sdi-intelligence-backend/.venv), not just the engine virtualenv. '
            'Install the service requirements and run tools/check_service_brief_renderer.py '
            'with the service Python. Nothing queued.'
        ) from exc
    body = 'ENQUIRY BRIEF\n\n' + text
    for size in (11.0, 9.5, 8.0, 6.5, 5.0):
        doc = pdf.open()
        try:
            page = doc.new_page(width=595, height=842)
            rc = page.insert_textbox(pdf.Rect(42, 42, 553, 800), body,
                                     fontsize=size, fontname='helv')
            if rc >= 0:
                return page.get_pixmap(dpi=150).tobytes('png')
        finally:
            doc.close()
    # Never price a silently truncated or empty brief page.
    raise ValueError('Enquiry brief does not fit its staging page; shorten it. Nothing queued.')
