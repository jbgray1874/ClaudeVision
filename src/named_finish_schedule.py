"""Cost named coats as passes, not extra physical components.

The area/rate labour model remains the normal shop model. Consumables use a
visible, configurable house budget per litre, never a claimed supplier quote.
Nothing here recognises a customer, product reference or particular coating brand.
"""
import hashlib
import math
import re


def apply_times(part, setup_min, run_min):
    schedule = part.get('finish_schedule') or {}
    stages = schedule.get('stages') or []
    passes = sum(int(s.get('passes') or 0) for s in stages)
    if schedule.get('operation') != 'wet_spray' or passes < 1:
        return setup_min, run_min
    if any(int(s.get('passes') or 0) <= 0 for s in stages):
        raise ValueError('Every named coating stage needs positive passes')
    part['finish_schedule_applied'] = {
        'passes': passes, 'stage_setups': len(stages), 'stages': stages,
        'basis': 'Normal area/rate labour per pass; one setup per distinct named stage. '
                 'Drying/curing elapsed time is not charged as booth labour.'}
    return round(setup_min * len(stages), 2), round(run_min * passes, 2)


def mint_consumables(parts):
    import config
    rule = dict(config.NAMED_WET_FINISH_CONSUMABLES)
    coverage = float(rule['coverage_m2_per_litre'])
    rate = float(rule['budget_gbp_per_litre'])
    waste = float(rule['waste_fraction'])
    if not all(math.isfinite(x) for x in (coverage, rate, waste)) or coverage <= 0 or rate <= 0 or waste < 0:
        raise ValueError('Invalid named wet-finish house allowance configuration')
    minted = []
    keys = {str(p.get('part_number')) for p in parts}
    for parent in list(parts):
        schedule = parent.get('finish_schedule') or {}
        area = float(parent.get('_powder_members_coated_m2') or 0)
        if not area:
            area = (2 * float(parent.get('blank_length_mm') or 0) *
                    float(parent.get('blank_width_mm') or 0) / 1e6)
        if schedule.get('operation') != 'wet_spray' or area <= 0:
            continue
        if any(parent.get(k) for k in ('is_bought_in', 'reference_only', 'supplied_by_third_party',
                                      'is_reference_only', 'for_reference_only')):
            continue
        # A separately priced coating material bill always wins over this budget.
        if any(p.get('coating_material_for') == parent.get('part_number') and
               not p.get('named_finish_consumable') for p in parts):
            continue
        if any(p.get('bom_parent') == parent.get('part_number') and
               not p.get('named_finish_consumable') and p.get('is_bought_in') and
               re.search(r'(?i)\bPAINT\b|\bPRIMER\b|\bBASECOAT\b|\bTOPCOAT\b|\bISOLATOR\b|\bLACQUER\b',
                         str(p.get('description') or '')) for p in parts):
            continue
        for stage in schedule.get('stages') or []:
            passes = int(stage.get('passes') or 0)
            if passes <= 0:
                raise ValueError('A named coat must have positive passes')
            token = hashlib.sha256(str(stage).encode()).hexdigest()[:10]
            pn = str(parent['part_number']) + '-FINMAT-' + token
            if pn in keys:
                continue
            litres = area * passes * (1 + waste) / coverage
            basis = (f"PROVISIONAL wet-finish material budget: {area:g} m2 x {passes} pass(es), "
                     f"{coverage:g} m2/litre, {waste:.0%} waste, GBP {rate:g}/litre. "
                     "Not a quote for the named coating; confirm its actual coverage and tin price.")
            rec = {'part_number': pn, 'description': 'Coating material allowance: ' + stage['description'],
                   'quantity': 1, 'bom_parent': parent['part_number'],
                   'bom_parents': [{'parent': parent['part_number'], 'qty': 1}],
                   'is_bought_in': True, 'page_roles': ['bought_in'],
                   'coating_material_for': parent['part_number'],
                   'named_finish_consumable': {'litres': litres, 'gbp_per_litre': rate,
                       'allowance_gbp': round(litres * rate, 4), 'basis': basis,
                       'stage': stage, 'coated_m2': area},
                   'review_flags': [basis], 'inferred_operations': []}
            parts.append(rec)
            keys.add(pn)
            minted.append(pn)
    return minted


def consumable_cost(part):
    allowance = part['named_finish_consumable']
    cost = float(allowance['allowance_gbp'])
    if not math.isfinite(cost) or cost <= 0:
        raise ValueError('Named coating allowance must carry positive finite money')
    return {'applied_unit_cost': cost, 'result': {'selected': {
        'source': 'wet_finish_house_allowance', 'price': cost, 'unit': 'each',
        'confidence': 0.3, 'metadata': {'provisional': True, **allowance}}}}
