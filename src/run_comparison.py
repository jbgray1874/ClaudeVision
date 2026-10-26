"""Two saved runs of a job, compared by identity: what changed between them (D-579).

STAGE 2 OF THE STABILITY PROGRAMME. Five books of 401918-01-GA in one day were compared by
eye, figure by figure. This reads two saved records and says what differs: parts added,
removed or changed (quantity, material, stock, cost method, price source, features,
times), material rows by charge, routes by the writer's stable route_group_id with their
charges, the totals with their deltas, the release state, and the run's own metadata
(product, order quantity, build, reads reused). The read store already says which reads
changed; this says what that did to the price.

IDENTITY, NOT ADDRESS. A part is its canonical code; a material row is its code or the
code its description leads with; a route is its route_group_id. Row addresses are
evidence within one run and mean nothing across two, so a row that moved is not a
change. A quantity keeps its fraction. A missing total is None, not nought. A duplicate
or missing identity is a warning, never a silent overwrite, and an explicitly empty
canonical population is not permission to revive the pre-canonical one.

OBSERVED ONLY. Nothing here says why a figure moved: rates, quantity, interpretation,
inputs and code version all have to be considered before a delta is called a caused
improvement. Nothing here is written back; the projection is disposable and never feeds
pricing or manufacturing intent. Not a second model of the job. From the Codex stability
package of 22 Oct 2026, merged; CLI at tools/diagnose/compare_saved_runs.py.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math


def key(value):
    return str(value or '').strip().upper()


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def index(rows, identity, label, warnings):
    buckets = {}
    for row in rows:
        k = identity(row)
        if not k:
            warnings.append({'code': 'identity_missing', 'population': label})
            continue
        buckets.setdefault(k, []).append(row)
    for k, values in buckets.items():
        if len(values) != 1:
            warnings.append({'code': 'identity_ambiguous', 'population': label, 'identity': k, 'count': len(values)})
    return {k: v[0] for k, v in buckets.items() if len(v) == 1}


def projection(doc):
    """Disposable diagnostic view. Never persisted back into the costed record."""
    warnings = []
    es = doc.get('estimate_summary') or {}
    # An explicitly empty canonical population is not permission to revive old parts.
    parts = es.get('canonical_part_estimates') if 'canonical_part_estimates' in es else es.get('part_estimates')
    parts = parts or []
    known = {key(p.get('part_number')) for p in parts if p.get('part_number')}

    def material_identity(row):
        if row.get('part_code'):
            return key(row['part_code'])
        desc = key(row.get('description'))
        matches = [p for p in known if desc == p or desc.startswith(p + ' ')]
        return matches[0] if len(matches) == 1 else ''

    ps = index(parts, lambda r: key(r.get('part_number')), 'parts', warnings)
    part_view = {}
    for pn, p in ps.items():
        m = p.get('material_estimate') or {}
        proc = p.get('process_estimate') or {}
        part_view[pn] = {
            'description': p.get('description'), 'quantity': p.get('quantity'),
            'unit': p.get('unit_of_measure', p.get('unit')),
            'material': p.get('normalized_material'), 'thickness_mm': p.get('normalized_thickness_mm'),
            'stock_form': m.get('stock_form'), 'stock_estimate': m.get('stock_estimate'),
            'blank_length_mm': m.get('blank_length_mm'), 'blank_width_mm': m.get('blank_width_mm'),
            'set_aside': p.get('set_aside'), 'cost_method': m.get('cost_method'),
            'price_source': m.get('price_source'), 'unit_material_cost_gbp': m.get('unit_material_cost_gbp'),
            'manufacturing_features': proc.get('manufacturing_features'),
            'unit_times_min': proc.get('unit_times_min'),
        }
    final = doc.get('final_estimate') or {}
    if final.get('source') != 'excel_calculated':
        warnings.append({'code': 'calculated_readback_missing'})
    mats = index(final.get('material_rows') or [], material_identity, 'material', warnings)
    material = {pn: {k: r.get(k) for k in ('qty_per_unit','unit_price_gbp','scrap_pct','total_value_gbp','supplier','block')}
                for pn, r in mats.items()}
    groups = index((doc.get('workbook_labour') or {}).get('rows') or [],
                   lambda r: r.get('route_group_id'), 'route_groups', warnings)
    labour_rows = index(final.get('labour_rows') or [], lambda r: r.get('workbook_row'), 'labour_rows', warnings)
    routes = {}
    used = []
    for gid, group in groups.items():
        row = labour_rows.get(group.get('workbook_row'))
        if row is None:
            warnings.append({'code':'route_charge_missing', 'identity':gid})
        else:
            used.append(group.get('workbook_row'))
        routes[gid] = {
            'parts': sorted(key(x) for x in group.get('part_numbers') or []),
            'operations': sorted(group.get('engine_operations') or []),
            'rate_basis': group.get('rate_basis'),
            'charge': {k: (row or {}).get(k) for k in ('qty_per_unit','batch_hours','dept_rate_gbp_per_hour','setup_minutes','total_value_gbp')},
        }
    for row_no in set(labour_rows) - set(used):
        warnings.append({'code':'labour_without_route_identity', 'row':row_no})
    for row_no, count in Counter(used).items():
        if count > 1:
            warnings.append({'code':'route_charge_ambiguous','row':row_no,'count':count})
    metadata = {k: doc.get(k) for k in ('declared_product','requested_order_quantity','processed_at','staged_inputs')}
    metadata.update(build=es.get('engine_build'), reads=es.get('reads_reused'), run=doc.get('run_metadata'))
    return deepcopy({'metadata':metadata, 'parts':part_view, 'material':material, 'routes':routes,
                     'totals':final.get('totals') or {}, 'release':(doc.get('costed_job') or {}).get('release'),
                     'warnings':warnings})


def compare(before, after):
    a, b = projection(before), projection(after)
    changes = []
    for population in ('parts','material','routes'):
        for identity in sorted(set(a[population]) | set(b[population])):
            old, new = a[population].get(identity), b[population].get(identity)
            if old is None or new is None:
                changes.append({'population':population,'identity':identity,
                                'change':'added' if old is None else 'removed','before':old,'after':new})
            else:
                for field in sorted(set(old) | set(new)):
                    if old.get(field) != new.get(field):
                        changes.append({'population':population,'identity':identity,'change':'changed',
                                        'field':field,'before':old.get(field),'after':new.get(field)})
    totals = {}
    for field in ('material_gbp','labour_gbp','other_gbp','unit_gbp'):
        old, new = a['totals'].get(field), b['totals'].get(field)
        totals[field] = {'before':old,'after':new,'delta':new-old if numeric(old) and numeric(new) else None}
    same_product = key(a['metadata']['declared_product']) == key(b['metadata']['declared_product']) != ''
    same_qty = a['metadata']['requested_order_quantity'] == b['metadata']['requested_order_quantity'] is not None
    return {'schema':'run_comparison.v1', 'same_product':same_product, 'same_order_quantity':same_qty,
            'interpretation':'Observed differences only; no automatic causal attribution or approval.',
            'before':a['metadata'], 'after':b['metadata'], 'changes':changes, 'totals':totals,
            'release':{'before':a['release'],'after':b['release']},
            'warnings':{'before':a['warnings'],'after':b['warnings']}}
