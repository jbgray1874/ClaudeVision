"""Evidence gates, not geometry or commercial guesses. All counts have an explicit basis."""
from math import isfinite


def positive(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and isfinite(value) and value > 0


def hole_row_coverage(rows, part, holes_per_part, parts_per_product):
    if not positive(holes_per_part) or not positive(parts_per_product):
        return 'hole quantity basis unknown'
    counts = []
    for row in rows:
        by_part = row.get('holes_cut_by_part') or {}
        value = by_part.get(part)
        if row.get('holes_cut_basis') != 'per_finished_product' or not positive(value):
            continue
        counts.append(value)
    need = holes_per_part * parts_per_product
    if not counts:
        return 'no part-owned hole count with a stated per-finished-product basis'
    # A row aggregate does not identify stages: do not add laser and drill counts together.
    if len(counts) != 1:
        return 'multiple cutting stages claim these holes; assign feature coverage'
    if counts[0] < need:
        return f'charged hole count {counts[0]:g} is below required {need:g}'
    return None


def profile_extent(evidence, part):
    """Select a sourced overall extent, not a base dimension or a weight-derived guess."""
    candidates = [e for e in evidence if e.get('part') == part and e.get('role') == 'overall_profile'
                  and e.get('document') and e.get('page') and e.get('source_region')
                  and positive(e.get('length_mm')) and positive(e.get('width_mm'))]
    sizes = {(e['length_mm'], e['width_mm']) for e in candidates}
    if len(sizes) != 1:
        return {'verified':False,'reason':'overall profile missing or conflicting'}
    return {'verified':True,'extent_mm':list(next(iter(sizes))), 'sources':candidates,
            'contour_verified':False,'holes_verified':False}


def purchase_basis(required_article, evidence):
    """No cheap alternative, approximate article match or unexplained pack conversion."""
    if (not required_article or evidence.get('article') != required_article
            or not evidence.get('source') or not evidence.get('observed_at')
            or not positive(evidence.get('price_gbp'))
            or not positive(evidence.get('pieces_per_purchase_unit'))):
        return {'verified':False,'reason':'article, dated source or purchase unit missing'}
    return {'verified':True,'piece_price_gbp':evidence['price_gbp']/evidence['pieces_per_purchase_unit']}


def weld_run_coverage(requirements, rows):
    """Each explicitly identified joint side/run must name one charged stage.

    This adapter cannot turn a member count into joints. Missing capture is unresolved.
    Rows must carry the source-backed process/rate and saved-cell verification from adapters.
    """
    issues = []
    if not requirements:
        return ['joint_run_requirements_not_captured']
    seen = set()
    for req in requirements:
        key = req.get('id')
        if not key or key in seen:
            issues.append('joint_run_identity_ambiguous')
        seen.add(key)
        if not all(req.get(k) for k in ('joint_id','side','document','page','process')):
            issues.append(f'{key}:joint_scope_unverified')
        hits = [r for r in rows if key and key in r.get('joint_run_ids', [])]
        if len(hits) != 1:
            issues.append(f'{key}:expected_one_charged_stage')
        elif not (hits[0].get('process') == req.get('process')
                  and hits[0].get('rate_source') and positive(hits[0].get('rate_gbp_h'))
                  and hits[0].get('saved_cells_verified') is True):
            issues.append(f'{key}:process_rate_or_charge_unverified')
    return issues
