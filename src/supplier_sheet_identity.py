"""Join a supplier's stock identities, drawing numbers and BOM owners using its sheets.

No job-number table, fuzzy substitutions, pricing, or source-file writes. A conventional
nc1 drawing filename may name an otherwise raster sheet; conflicting printed identities
are retained for review rather than silently replaced.
"""
from __future__ import annotations
import re
from collections import defaultdict
from drawing_reference import (compact, finished_parts_on_sheet,
                               reference_in_file_name, sheet_drawing_reference)


def reconcile_sheet_identities(rows, sheets):
    sheets = list(sheets)
    own = defaultdict(set)
    for row in rows:
        for key in ('part_number', 'finished_part_no'):
            if row.get(key):
                own[str(row.get('bom_sheet') or '')].add(str(row[key]).strip())
    identities, claims, findings = {}, defaultdict(set), []
    for sheet, text in sheets:
        filename = str(sheet).rsplit('#', 1)[0].replace('\\', '/').rsplit('/', 1)[-1]
        file_ref = reference_in_file_name(filename) if re.match(r'(?i)^nc1-', filename) else None
        if file_ref:
            file_ref = file_ref[0] + '-' + file_ref[1:]
        printed = sheet_drawing_reference(text)
        if file_ref and printed and compact(file_ref) != compact(printed):
            findings.append({'code': 'sheet_filename_identity_conflict', 'sheet': sheet,
                             'filename': file_ref, 'printed': printed})
            continue
        ref = printed or file_ref
        if not ref:
            continue
        identities[sheet] = ref
        codes = finished_parts_on_sheet(text) - own[sheet]
        # A single-component detail often prints PART NO. rather than FINISHED PART NO.
        if not codes and not own[sheet]:
            codes = set(re.findall(r'(?i)(?<![A-Z])PART\s+NO\.?\s*[:\-\s]*(\d{7,8})(?!\d)', text))
        if len(codes) == 1:
            claims[next(iter(codes))].add(ref)
    aliases = {stock: next(iter(refs)) for stock, refs in claims.items()
               if len({compact(r) for r in refs}) == 1}
    for row in rows:
        stock = str(row.get('finished_part_no') or '').strip()
        # A line whose code IS the stock code (no drawing column read: "20126611 SHELF PANEL")
        # is the same claim as one that carries it beside a drawing reference (27 Nov 2026:
        # the 800 shelf's three lines stayed apart from their three sheets).
        if not stock and re.fullmatch(r'\d{6,10}', str(row.get('part_number') or '').strip()):
            stock = str(row.get('part_number')).strip()
        ref = aliases.get(stock)
        if ref and compact(ref) != compact(row.get('part_number')):
            original = str(row.get('part_number') or '')
            row.setdefault('part_number_original', original)
            if original:
                aliases[original] = ref
            row['part_number'] = ref
            row['drawing_reference'] = ref
            row.setdefault('finished_part_no', stock)
        sheet = str(row.get('bom_sheet') or '')
        owner = identities.get(sheet)
        if owner and compact(owner) != compact(row.get('bom_parent')):
            row.setdefault('bom_parent_original', row.get('bom_parent'))
            row['bom_parent'] = owner
            row['source_pdf'] = owner
            row['bom_parent_known'] = True
            row['bom_parent_from_file'] = sheet
        elif owner:
            row['bom_parent_from_file'] = sheet
        parent_stocks = [s for s, ref in aliases.items() if compact(ref) == compact(owner)] if owner else []
        if len(parent_stocks) == 1:
            row['parent_finished_part_no'] = parent_stocks[0]
    if rows and aliases:
        rows[0]['sheet_identity_aliases'] = aliases
    return findings


def reconcile_saved_sheet_identities(summary):
    """Reuse already-read page text, including source PDF identity, without opening PDFs."""
    sheets = []
    for page in summary.get('pages') or []:
        name = page.get('source_pdf_name')
        number = page.get('source_page_number') or page.get('page_number')
        if name and isinstance(number, int):
            text = page.get('normalized_text') or page.get('pdfplumber_text') or page.get('text_preview') or ''
            sheets.append((f'{name}#{number - 1}', text))
    rows = (summary.get('document_analysis') or {}).get('bom_rows') or []
    found = reconcile_sheet_identities(rows, sheets)
    if found:
        summary.setdefault('supplier_identity_findings', []).extend(found)
    return found
