"""Read local ownership without confusing it with a rolled or order quantity (D-598h).

All formats use the compiler's existing children; no parallel BOM is created. A
fallback to those children is arithmetic evidence only. Independent reader-local
edges, or a hashed flat-product read, must corroborate it. Nothing is repaired.
"""
from math import isfinite, isclose


def key(value):
    return str(value or '').strip().upper()


def number(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and isfinite(value) and value > 0 else None)


def local_edges(summary, nodes, prices, part, root):
    """Return edges, basis and findings; never borrow qty_by_parent as an edge."""
    record = prices.get(part) or {}
    canonical = 'bom_parents' in record
    edges = (record.get('bom_parents') or []) if canonical else []
    if not canonical:
        for parent, node in nodes.items():
            for child in node.get('children') or []:
                if isinstance(child, dict) and key(child.get('part_number')) == part:
                    edges.append({'parent': parent, 'qty': child.get('qty')})
    basis = 'canonical_local_edges' if canonical else 'compiled_local_edges'
    if not isinstance(edges, list) or any(not isinstance(e, dict) for e in edges):
        return [], basis, [{'code': 'malformed_local_edges', 'part': part}]
    if not edges or part == root:
        return edges, basis, []
    issues = []
    raw = [r for r in (summary.get('manufacturing_writeup') or {}).get('parts', [])
           if isinstance(r, dict) and key(r.get('part_number')) == part]
    if len(raw) == 1 and raw[0].get('bom_parents'):
        def signature(values):
            return sorted((key(e.get('parent')), str(number(e.get('qty')))) for e in values
                          if isinstance(e, dict))
        if signature(raw[0]['bom_parents']) != signature(edges):
            issues.append({'code': 'reader_local_edge_disagreement', 'part': part})
        return edges, basis if canonical else 'compiled_edges_checked_against_reader', issues
    ledger = summary.get('read_ledger') or {}
    reads = [i for i in ledger.get('items', []) if isinstance(i, dict)
             and i.get('kind') == 'part' and key(i.get('record')) == part]
    # Flat one-product reads state counts per unit, not nested local multipliers.
    # Restrict this bridge to a single direct edge to the declared product.
    flat = len(edges) == 1 and key(edges[0]['parent']) == root
    if (flat and key(ledger.get('unit')) == root and ledger.get('raw_sha256')
            and len(reads) == 1 and reads[0].get('source_id')
            and isinstance(reads[0].get('as_read'), dict)):
        q = number(reads[0]['as_read'].get('quantity'))
        actual = number(edges[0]['qty'])
        if q is None or actual is None or not isclose(q, actual, abs_tol=1e-8, rel_tol=0):
            issues.append({'code': 'read_quantity_disagreement', 'part': part,
                           'read_quantity': q, 'local_quantity': actual})
        return edges, basis if canonical else 'compiled_edges_checked_against_flat_read', issues
    if canonical:
        # Preserve the existing canonical-edge path when no independent source exists.
        # Source population coverage separately reports which requirements it can test.
        return edges, basis, issues
    issues.append({'code': 'local_edge_source_unverified', 'part': part})
    return edges, 'compiled_edges_only', issues
