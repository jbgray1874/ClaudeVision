"""Orientation-aware printed dimensions, not stock callouts or drawing-vector lengths.

This is an evidence reader, not a pricing or CAD operation. A number on a drawing
is not a measured contour. Its two axes may supply a disclosed blank allowance.
"""
from pathlib import Path
import hashlib
import math
import re

_DIMENSION = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*(CUT)?\s*$', re.I)


def read_axes(path, page_index=0):
    import fitz
    path = Path(path)
    data = path.read_bytes()
    with fitz.open(stream=data, filetype='pdf') as document:
        page = document[page_index]
        axes = {'horizontal': [], 'vertical': []}
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines') or []:
                text = ' '.join(s['text'] for s in line.get('spans') or []).strip()
                match = _DIMENSION.fullmatch(text)
                if not match:
                    continue
                value = float(match[1])
                if not math.isfinite(value) or not 5 < value < 20000:
                    continue
                x0, y0, x1, y1 = line['bbox']
                # Supplier borders normally put revision/title data at the right
                # or bottom. This is explicitly an envelope heuristic, not scale.
                if x0 > page.rect.width * .80 or y0 > page.rect.height * .90:
                    continue
                dx, dy = line['dir']
                axis = 'horizontal' if abs(dx) > .9 else 'vertical' if abs(dy) > .9 else None
                if axis:
                    axes[axis].append({'mm': value, 'cut_label': bool(match[2])})
        if not all(axes.values()):
            return None
        values = []
        for axis in ('horizontal', 'vertical'):
            labelled = [a['mm'] for a in axes[axis] if a['cut_label']]
            values.append(max(labelled or [a['mm'] for a in axes[axis]]))
        return {'axes_mm': values, 'annotations': axes,
                'pdf_sha256': hashlib.sha256(data).hexdigest(), 'source_page_index': page_index,
                'basis': 'Printed dimension text separated by orientation on the owned PDF; '
                         'provisional envelope unless the flat is independently confirmed.'}


def capture(summary):
    """Enrich pages once during a live scan. Offline recovery never calls this implicitly."""
    changed = []
    for page in summary.get('pages') or []:
        if page.get('printed_dimension_axes'):
            continue
        path = page.get('source_pdf_path')
        if not path or Path(path).name.lower() != str(page.get('source_pdf_name') or '').lower():
            continue
        try:
            axes = read_axes(path, max(0, int(page.get('source_page_number') or 1) - 1))
        except (OSError, ValueError, RuntimeError, IndexError):
            continue  # Keep text-based allowances and the missing evidence visible.
        if axes:
            page['printed_dimension_axes'] = axes
            changed.append(page.get('page_number'))
    return changed


def read_saved_pages(summary, drawings_dir=None):
    """Read printed axes into a COPIED saved record's pages, from each page's own PDF.

    For recovery from saved evidence: the record was saved before this reader existed.
    The PDF is the page's saved ``source_pdf_path`` or, with ``drawings_dir``, the one
    file of that exact name under that folder. Only the page's own named file is read,
    on its own saved page number. Returns an audit; a page that cannot be read is listed
    with its reason, never guessed. The caller must pass a copy: the pages are enriched.
    """
    index = {}
    if drawings_dir:
        for f in Path(drawings_dir).rglob('*'):
            if f.is_file() and f.suffix.lower() == '.pdf':
                index.setdefault(f.name.lower(), []).append(f)
    audit = {'read': [], 'not_read': []}
    for page in summary.get('pages') or []:
        name = str(page.get('source_pdf_name') or '')
        if page.get('printed_dimension_axes') or not name.lower().endswith('.pdf'):
            continue
        where = {'page': page.get('page_number'), 'file': name}
        if drawings_dir:
            found = index.get(name.lower(), [])
            digests = {hashlib.sha256(f.read_bytes()).hexdigest() for f in found}
            if len(digests) != 1:
                audit['not_read'].append(dict(where, reason='no file of that name under the folder'
                                              if not found else 'several different files share that name'))
                continue
            path = found[0]
        else:
            path = Path(str(page.get('source_pdf_path') or ''))
            if not str(page.get('source_pdf_path') or '') or path.name.lower() != name.lower():
                audit['not_read'].append(dict(where, reason='saved path does not name this file'))
                continue
        try:
            axes = read_axes(path, max(0, int(page.get('source_page_number') or 1) - 1))
        except (OSError, ValueError, RuntimeError, IndexError) as exc:
            audit['not_read'].append(dict(where, reason=f'{type(exc).__name__}: {exc}'[:160]))
            continue
        if not axes:
            audit['not_read'].append(dict(where, reason='no printed dimension on both axes'))
            continue
        page['printed_dimension_axes'] = axes
        audit['read'].append(dict(where, axes_mm=axes['axes_mm'], pdf_sha256=axes['pdf_sha256']))
    return audit
