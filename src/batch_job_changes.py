"""Explicit per-drawing material changes for a batch; no prices, no global defaults."""
import hashlib
import json
import math
from pathlib import Path


def load_changes(path, client):
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or set(data) != {'client', 'drawings'}:
        raise ValueError('Changes file must contain only client and drawings')
    if str(data['client']).strip().casefold() != str(client).strip().casefold():
        raise ValueError('Changes file belongs to a different client')
    if not isinstance(data['drawings'], dict) or not data['drawings']:
        raise ValueError('Changes file must name its drawings')
    from customer_changes import build_changes_file
    result = {}
    for drawing, payload in data['drawings'].items():
        code = str(drawing).strip().upper()
        if not code or code in result:
            raise ValueError('Blank or duplicate drawing in changes file')
        if not isinstance(payload, dict) or not isinstance(payload.get('changes'), list):
            raise ValueError(f'{code}: changes must be a list')
        for ch in payload['changes']:
            if (not isinstance(ch, dict) or ch.get('accepted') is not True
                    or ch.get('field') not in {'material', 'thickness_mm', 'finish'}):
                raise ValueError(f'{code}: only explicitly accepted material/gauge/finish changes are supported')
            if ch['field'] == 'thickness_mm':
                v = ch.get('value')
                if isinstance(v, bool) or not math.isfinite(float(v)) or float(v) <= 0:
                    raise ValueError(f'{code}: invalid thickness')
        checked, errors = build_changes_file(payload, code)
        if errors or not checked.get('changes'):
            raise ValueError(f'{code}: ' + '; '.join(errors or ['no accepted changes']))
        # Keep the submitted form: the service independently validates and files it.
        result[code] = payload
    return result


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest() if payload else ''


def bind_changes(rows, changes):
    found = {str(r.get('drawing') or '').strip().upper() for r in rows}
    if set(changes) - found:
        raise ValueError('Changes name drawings outside the selected rows: ' + ', '.join(sorted(set(changes)-found)))
    for row in rows:
        code = str(row.get('drawing') or '').strip().upper()
        if code in changes:
            row['_customer_changes'] = changes[code]
