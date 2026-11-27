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
