"""Offline service-Python capability check; no API, shares, queues or settings writes."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sdi-intelligence-backend'))
from brief_renderer import render_brief_png


def main():
    print('Interpreter:', sys.executable)
    png = render_brief_png('DEPENDENCY SMOKE TEST ONLY. Two plywood panels, 300 x 600 mm.')
    if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) < 1000:
        raise RuntimeError('Brief renderer did not produce a valid PNG')
    import pymupdf
    with pymupdf.open(stream=png, filetype='png') as image:
        if image.page_count != 1:
            raise RuntimeError('Brief renderer returned an invalid image')
    print('PASS: PyMuPDF', pymupdf.VersionBind, 'rendered and reopened a brief in memory.')
    print('No queue, service restart, workbook or share writes.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('FAIL:', str(exc), file=sys.stderr)
        sys.exit(1)
