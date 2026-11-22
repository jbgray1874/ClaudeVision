"""Carry an exact BOM purchase reference to pricing, without merging hands or inventing rates."""
from __future__ import annotations

import math
import re
from collections import defaultdict


def catalogue_reference(description):
    """Conservative printed form: article - supplier name - SKU description.

    Not a fuzzy alias: a plain description, drawing code, dimension or guessed article
    supplies no catalogue key. Different SKUs on the same drawing identity are a conflict.
    """
    text = ' '.join(str(description or '').split())
    if re.search(r'\b(?:GUESS|TBC|TBD|UNKNOWN)\b', text, re.I):
        return None
    bits = re.split(r'\s+-\s+', text)
    if len(bits) != 3:
        return None
    article, supplier, tail = bits
    code = tail.split(' ')[0]
    if (not article or not re.search(r'[A-Za-z]', supplier)
            or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*-[A-Za-z0-9-]*\d[A-Za-z0-9-]*', code)):
        return None
    return {'supplier': supplier, 'code': code.upper(), 'description': text}


def stamp_bom_purchase_references(parts, bom_rows):
    """Exact part identity only, including HANDED; no price or quantity is copied."""
    from part_code_conventions import bare_code
    from bought_in_policy import is_bought_in
    by_code = defaultdict(list)
    for row in bom_rows or []:
        if not isinstance(row, dict):
            continue
        ref = catalogue_reference(row.get('description'))
        code = bare_code(row.get('part_number') or row.get('part_code') or '')
        if ref and code:
            by_code[code].append({**ref, 'part_number': row.get('part_number') or row.get('part_code'),
                                 'page': row.get('page_number', row.get('page')),
                                 'sheet': row.get('bom_sheet')})
    count = 0
    for part in parts or []:
        if not isinstance(part, dict) or not is_bought_in(part):
            continue
        refs = by_code.get(bare_code(part.get('part_number') or ''), [])
        identities = {(r['supplier'].casefold(), r['code']) for r in refs}
        if len(identities) != 1:
            # A replay must not retain an earlier exact-BOM alias after that
            # evidence disappears or becomes contradictory. Never clear an
            # independent, deliberately corrected price-chain description.
            old = part.get('purchase_reference') or {}
            if old.get('source') == 'exact_bom_description':
                if part.get('price_chain_description') == old.get('description'):
                    part.pop('price_chain_description', None)
                part.pop('purchase_reference', None)
        if len(identities) > 1:
            note = 'Conflicting supplier references on this exact BOM item; confirm which article is purchased.'
            if part.get('review_flags') is None:
                part['review_flags'] = []
            if note not in (part.get('review_flags') or []):
                part.setdefault('review_flags', []).append(note)
            continue
        if len(identities) != 1:
            continue
        ref = refs[0]
        # A deliberate size-reading correction must not be overwritten by a BOM transcription.
        if part.get('price_chain_description') and not part.get('purchase_reference'):
            continue
        part['purchase_reference'] = {**ref, 'source': 'exact_bom_description'}
        part['price_chain_description'] = ref['description']
        count += 1
    return count


def lookup_codes(part):
    """Only a reference recorded by the exact-BOM reader enters the catalogue search."""
    ref = part.get('purchase_reference') or {}
    if ref.get('source') != 'exact_bom_description':
        return []
    parsed = catalogue_reference(ref.get('description'))
    if not parsed or parsed['code'] != ref.get('code') or parsed['supplier'] != ref.get('supplier'):
        return []
    return [parsed['code']]


def mark_missing_purchase(part, unit_price):
    """A handling/raw-material charge is not a purchase price. Add a visible ruling."""
    try:
        priced = math.isfinite(float(unit_price)) and float(unit_price) > 0
    except (TypeError, ValueError):
        priced = False
    if priced:
        return False
    ref = part.get('purchase_reference') or {}
    subject = ' '.join(x for x in (ref.get('supplier'), ref.get('code')) if x)
    note = ('PURCHASE PRICE MISSING: ' + str(part.get('part_number') or 'item')
            + (f' ({subject})' if subject else '')
            + '. Material or fitting charges do not include the bought-in article. '
              'Obtain the supplier specification, unit of sale and quoted price; do not treat this item as free.')
    part['purchase_price_missing'] = True
    part['estimator_input_required'] = True
    if part.get('review_flags') is None:
        part['review_flags'] = []
    if note not in (part.get('review_flags') or []):
        part.setdefault('review_flags', []).append(note)
    from source_precedence import raise_manufacturing_question
    raise_manufacturing_question(part, note, 'Purchase price remains unresolved; any other charges stay visible.',
                                 'Confirm the supplier article and enter an evidenced purchase price.',
                                 'purchase_evidence.mark_missing_purchase')
    return True
