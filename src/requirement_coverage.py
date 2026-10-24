"""Shadow adapter for normal-pack requirements, using existing identities and charge IDs.

This is not another BOM and never prices or repairs records. The caller supplies captured
requirements BEFORE interpretation and actual saved-workbook charge evidence AFTER it.
Absent capture is incomplete coverage, not a vacuous pass. Physical and operation coverage
are distinct. Until adapters supply these fields this module must not claim live acceptance.
"""
from collections import Counter
from math import isfinite


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def audit(requirements, parts, charges):
    findings = []
    if not requirements:
        return {'passed': False, 'coverage': 'incomplete', 'findings': ['requirements_not_captured']}
    def duplicates(rows, field):
        return [key for key, count in Counter(r.get(field) for r in rows).items() if not key or count > 1]
    for rows, field, label in ((requirements, 'id', 'requirement'), (parts, 'part_number', 'part'),
                               (charges, 'charge_id', 'charge')):
        if duplicates(rows, field):
            findings.append(label + '_identity_ambiguous')
    by_part = {p.get('part_number'): p for p in parts}
    by_charge = {c.get('charge_id'): c for c in charges}
    for r in requirements:
        prefix = str(r.get('id')) + ':'
        if not r.get('document') or not isinstance(r.get('page'), int) or r['page'] < 1:
            findings.append(prefix + 'source_missing')
        if r.get('state') == 'excluded':
            if not r.get('ruling') or not r.get('approved_by'):
                findings.append(prefix + 'exclusion_unapproved')
            continue
        p = by_part.get(r.get('part_number'))
        if p is None:
            findings.append(prefix + 'part_missing')
            continue
        if (not number(r.get('quantity')) or r['quantity'] <= 0
                or not number(p.get('quantity')) or p.get('quantity') != r['quantity']):
            findings.append(prefix + 'quantity_mismatch')
        ids = r.get('charge_ids') or []
        if not ids:
            findings.append(prefix + 'charge_missing')
        for cid in ids:
            c = by_charge.get(cid)
            if not c or r['id'] not in c.get('requirement_ids', []):
                findings.append(prefix + 'coverage_not_named')
                continue
            if (not c.get('cell') or c.get('saved_value') != c.get('value')
                    or not number(c.get('value')) or c['value'] <= 0):
                findings.append(prefix + 'charged_cell_unverified')
            if r.get('operation') and r['operation'] not in c.get('operations', []):
                findings.append(prefix + 'operation_missing')
            if not c.get('basis_verified'):
                findings.append(prefix + 'charge_basis_unverified')
    return {'passed': not findings, 'coverage': 'captured_scope_only', 'findings': findings}
