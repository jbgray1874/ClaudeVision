"""Surgical AiCost updates: preserve every other ZIP member, including richData."""
from __future__ import annotations
import io
import copy
import os
from pathlib import Path
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from tti_concept_inputs import S, read_plan, reread_options, sha


def money(value):
    if isinstance(value, bool): raise ValueError('boolean is not a price')
    try: n = Decimal(str(value))
    except InvalidOperation as exc: raise ValueError('invalid unit price') from exc
    if not n.is_finite() or n <= 0: raise ValueError('missing/zero/negative unit price: hold for review')
    return n.quantize(Decimal('0.01'))


def patch_cell(xml, address, price):
    """Change one existing blank numeric/text cell; never touch formulas or pictures."""
    root = ET.fromstring(xml)
    cells = [c for c in root.findall(f'{{{S}}}sheetData/{{{S}}}row/{{{S}}}c') if c.get('r') == address]
    if len(cells) != 1: raise ValueError(f'{address}: expected one existing cost cell')
    c = cells[0]
    if c.find(f'{{{S}}}f') is not None or c.get('vm') or c.get('cm'):
        raise ValueError('refusing formula or metadata cost cell')
    # A merged target is ambiguous, including its top-left cell.
    from openpyxl.utils.cell import range_boundaries, coordinate_to_tuple
    rr, cc = coordinate_to_tuple(address)
    for merge in root.findall(f'{{{S}}}mergeCells/{{{S}}}mergeCell'):
        x1,y1,x2,y2 = range_boundaries(merge.get('ref'))
        if x1 <= cc <= x2 and y1 <= rr <= y2: raise ValueError('merged cost cell')
    text = xml.decode('utf-8')
    pattern = re.compile(r'<c\b(?=[^>]*\br="' + re.escape(address) + r'")[^>]*?(?:/>|>.*?</c>)', re.S)
    matches = list(pattern.finditer(text))
    if len(matches) != 1: raise ValueError('unsupported worksheet cell serialization')
    m = matches[0]
    opening = m.group().split('>',1)[0].rstrip('/')
    opening = re.sub(r'\s+t="[^"]*"', '', opening)
    replacement = opening + '><v>' + str(money(price)) + '</v></c>'
    result = (text[:m.start()] + replacement + text[m.end():]).encode('utf-8')
    ET.fromstring(result)
    return result


def write_cost(workbook, item, price, sheet='Milwaukee'):
    """Revalidate identity and existing value immediately before atomic replacement.

    The batch archives the original workbook once on BOTH roots before any call.
    Requires Excel closed. A competing editor detected before replacement stops it.
    No openpyxl save, formula rewrites, or thumbnail re-encoding occurs.
    """
    path = Path(workbook); price = money(price)
    require_closed(path)
    plan, _ = read_plan(path,sheet,**reread_options(item))
    row = next((r for r in plan['rows'] if r['row'] == item['row']), None)
    if not row or row['fingerprint'] != item['fingerprint'] or row['cost_cell'] != item['cost_cell']:
        raise ValueError('source row changed; no write-back')
    if row['cost_before'] not in (None,''):
        if money(row['cost_before']) == price:
            return {'already_written':True, 'workbook_sha256':plan['workbook_sha256']}
        raise ValueError('AiCost already contains a different value; no overwrite')
    raw = path.read_bytes()
    if sha(raw) != plan['workbook_sha256']: raise ValueError('workbook changed during validation')
    member = plan['sheet_member']
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        edited = patch_cell(z.read(member),row['cost_cell'],price)
        fd, tmp = tempfile.mkstemp(prefix=path.stem+'.concept-',suffix='.xlsx',dir=path.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp,'w') as dest:
                dest.comment = z.comment
                for info in z.infolist(): dest.writestr(copy.copy(info), edited if info.filename == member else z.read(info.filename))
            with zipfile.ZipFile(tmp) as check:
                if check.namelist() != z.namelist(): raise ValueError('workbook member set changed')
                for name in z.namelist():
                    if name != member and check.read(name) != z.read(name): raise ValueError('non-target workbook data changed')
            after = sha(Path(tmp).read_bytes())
            if sha(path.read_bytes()) != sha(raw): raise ValueError('workbook changed before replace; close Excel and retry')
            require_closed(path)
            os.replace(tmp,path)  # Fails safely if Excel holds the workbook open.
            return {'already_written':False,'before_sha256':sha(raw),'workbook_sha256':after,
                    'cell':row['cost_cell'],'unit_gbp':str(price)}
        finally:
            if os.path.exists(tmp): os.unlink(tmp)


def require_closed(path):
    path=Path(path)
    if any((path.parent/name).exists() for name in ('~$'+path.name,'~$'+path.name[2:])):
        raise RuntimeError('Excel owner file exists: close the tracker before pricing/write-back')
