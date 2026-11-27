"""A visible assembly is not discarded just because one supplier code did not join.

An unambiguous inferred join is labelled, not disguised as a title-block fact.
Never overrides an explicit alias, a buy/by-others ruling or alternative scope.
"""
import re
from drawing_reference import compact


def apply(summary):
    rows = (summary.get('document_analysis') or {}).get('bom_rows') or []
    if not rows:
        return []
    aliases = rows[0].setdefault('sheet_identity_aliases', {})
    declared = compact(summary.get('declared_product'))
    owner_refs = {compact(r.get('bom_parent')): str(r['bom_parent']) for r in rows if r.get('bom_parent')}
    explicit_children = {compact(aliases.get(str(r.get('part_number')), r.get('part_number'))) for r in rows}
    orphans = {k: v for k, v in owner_refs.items() if k != declared and k not in explicit_children}
    if len(orphans) != 1:
        return []
    candidates = {}
    by_part = {compact(p.get('part_number')): p for p in
               ((summary.get('manufacturing_writeup') or {}).get('parts') or summary.get('parts') or [])}
    for row in rows:
        pn = str(row.get('part_number') or '')
        if not re.fullmatch(r'\d{6,10}', pn) or pn in aliases:
            continue
        if not re.search(r'(?i)\bASSEMBLY\b|\bCARCASE\b|\bUNIT\b', str(row.get('description') or '')):
            continue
        if compact(row.get('bom_parent')) != declared:
            continue
        part = by_part.get(compact(pn), {})
        if any(part.get(k) or row.get(k) for k in ('is_bought_in', 'supplied_by_third_party',
               'reference_only', 'for_reference_only', 'superseded', 'is_alternative')):
            continue
        candidates[pn] = row
    if len(candidates) != 1:
        return []
    stock = next(iter(candidates))
    owner = next(iter(orphans.values()))
    # The inferred owner must have a sheet in THIS submitted pack, not just be
    # a drawing reference named somewhere in a supplier library.
    from owned_component_manufacturing import _owner
    own_pages = [p for p in summary.get('pages') or [] if _owner(p) == compact(owner)]
    if not own_pages:
        return []
    aliases[stock] = owner
    decision = {'stock': stock, 'drawing': owner, 'provisional': True,
        'basis': 'Unique unresolved assembly stock line and unique disconnected assembly sheet '
                 'in this submitted product pack. Assume an omitted identity link; retain and '
                 'price its visible members once. Confirm the supplier stock/drawing join.'}
    decisions = summary.setdefault('assembly_identity_inferences', [])
    if decision not in decisions:
        decisions.append(decision)
    if stock in by_part:
        by_part[stock]['is_sub_assembly'] = True
        by_part[stock].setdefault('review_flags', []).append(decision['basis'])
    return [decision]
