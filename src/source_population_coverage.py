"""Check captured members against the existing graph, including completely lost nodes (D-598i).

This is a read-only projection, not a new BOM or a price writer. It consumes the
retained reader BOM rows and concept ledger. Document/CAD adapters that populate
neither are explicitly outside its coverage. No description/name matching, no
automatic reparenting and no inferred scope exclusions are allowed here.
"""
from collections import Counter
from math import isfinite, isclose


def identity(value):
    return ''.join(str(value or '').split()).upper()


def number(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and isfinite(value) and value > 0 else None)


def audit(summary, graph, prices):
    issues, trace = [], []
    root = identity(graph.get('product_root') or graph.get('declared_product'))
    raw_nodes = [n for n in graph.get('nodes', []) if isinstance(n, dict)]
    counts = Counter(identity(n.get('part_number')) for n in raw_nodes)
    ns = {identity(n.get('part_number')): n for n in raw_nodes
          if counts[identity(n.get('part_number'))] == 1}
    pc = Counter(identity(k) for k in prices)
    ps = {identity(k): p for k, p in prices.items() if pc[identity(k)] == 1}
    for part, count in counts.items():
        if count > 1:
            issues.append({'code': 'ambiguous_normalized_graph_identity', 'part': part})
    for part, count in pc.items():
        if count > 1:
            issues.append({'code': 'ambiguous_normalized_price_identity', 'part': part})

    def finding(code, part, **detail):
        issues.append({'code': code, 'part': part, **detail})

    # Both directions of the SAME canonical hierarchy must agree. This applies
    # even when no PDF/LLM source adapter exists (for example native CAD).
    for parent, node in ns.items():
        seen = set()
        for edge in node.get('children') or []:
            if not isinstance(edge, dict):
                finding('malformed_compiled_child', parent)
                continue
            child = identity(edge.get('part_number'))
            if not child or child in seen:
                finding('duplicate_or_missing_compiled_child', child, parent=parent)
            seen.add(child)
            if child not in ns:
                finding('compiled_child_missing', child, parent=parent)
                continue
            if parent not in {identity(p) for p in ns[child].get('parents', [])}:
                finding('compiled_parent_child_disagreement', child, parent=parent)
            price = ps.get(child) or {}
            if 'bom_parents' in price:
                edges = price.get('bom_parents') or []
                matches = [e for e in edges if isinstance(e, dict)
                           and identity(e.get('parent')) == parent] if isinstance(edges, list) else []
                q = number(edge.get('qty'))
                local = number(matches[0].get('qty')) if len(matches) == 1 else None
                if q is None or local is None or not isclose(q, local, abs_tol=1e-8, rel_tol=0):
                    finding('compiled_local_edge_disagreement', child, parent=parent,
                            graph_local=q, price_local=local)

    def require(part, source, parent=None):
        node = ns.get(part)
        if node is None:
            finding('captured_part_missing_from_graph', part, source=source, parent=parent)
        elif part not in ps and not (node.get('kind') == 'assembly' and node.get('children')):
            finding('captured_part_missing_from_prices', part, source=source, parent=parent)
        # An assembly can legitimately carry no material of its own. Its members
        # must still be tested; this does not exempt its operations or validate money.
        trace.append({'part': part, 'parent': parent, 'source': source,
                      'graph_present': node is not None, 'price_present': part in ps})

    rows = [r for r in (summary.get('document_analysis') or {}).get('bom_rows', [])
            if isinstance(r, dict)]
    pairs = {}
    for row in rows:
        parent, child = identity(row.get('bom_parent')), identity(row.get('part_number'))
        if parent and child and parent != child:
            pairs.setdefault((parent, child), []).append(row)
    # Select only the declared product's source descendants. This also sees a
    # whole missing subassembly; traversing the surviving graph alone cannot.
    reached = {root} if root else set()
    while True:
        more = {child for parent, child in pairs if parent in reached} - reached
        if not more:
            break
        reached.update(more)
    for (parent, child), source_rows in pairs.items():
        if parent not in reached:
            continue
        require(child, 'reader_bom', parent)
        if any(number(r.get('quantity')) is None for r in source_rows):
            finding('captured_local_quantity_unverified', child, parent=parent)
        node = ns.get(child)
        if node is not None and parent not in {identity(p) for p in node.get('parents', [])}:
            finding('captured_parent_link_missing', child, parent=parent)
    ledger = summary.get('read_ledger') or {}
    ledger_parts = [i for i in ledger.get('items', []) if isinstance(i, dict)
                    and i.get('kind') == 'part' and i.get('work', True)]
    selected_reads = []
    if identity(ledger.get('unit')) == root and root:
        selected_reads = ledger_parts
        read_counts = Counter(identity(i.get('record')) for i in selected_reads)
        for part, count in read_counts.items():
            if part and count > 1:
                finding('ambiguous_captured_part_identity', part, count=count)
        decisions = summary.get('estimator_decisions') or {}
        rulings = {str(k).lower(): v for k, v in (decisions.get('read_rulings') or {}).items()}
        for item in selected_reads:
            part = identity(item.get('record'))
            ruling = rulings.get(str(item.get('id')).lower()) or {}
            if (isinstance(ruling, dict) and ruling.get('ruling') == 'excluded'
                    and str(ruling.get('reason') or '').strip()
                    and str(decisions.get('decided_by') or '').strip()):
                trace.append({'part': part, 'source': 'read_ledger', 'state': 'explicitly_excluded',
                              'reason': ruling['reason'], 'decided_by': decisions['decided_by']})
                continue
            if not part:
                finding('captured_part_identity_unresolved', '', source_id=item.get('source_id'))
                continue
            require(part, 'read_ledger', root)
            as_read = item.get('as_read')
            q = number(as_read.get('quantity')) if isinstance(as_read, dict) else None
            if not ledger.get('raw_sha256') or not item.get('source_id') or q is None:
                finding('captured_quantity_source_unverified', part)
                continue
            for stage, value in [('graph', (ns.get(part) or {}).get('qty_per_unit')),
                                 ('price', (ps.get(part) or {}).get('quantity'))]:
                actual = number(value)
                if actual is not None and not isclose(actual, q, abs_tol=1e-8, rel_tol=0):
                    finding('captured_product_quantity_mismatch', part, stage=stage,
                            expected=q, actual=actual)
    checked = len(trace)
    return {'issues': issues, 'trace': trace,
            'coverage': 'captured_sources_only' if checked else 'no_selected_source_rows',
            'checked': checked,
            'outside_selected_product_rows': sum(len(v) for (p, _), v in pairs.items() if p not in reached),
            'scope': 'retained reader BOM and read-ledger parts; not uncaptured drawing content or charged cells'}
