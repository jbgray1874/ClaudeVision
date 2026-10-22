import sys, json
sys.path.insert(0, 'src')
d = json.load(open('output/json/12242-01-GA Vue Sprung Cup Holder_revD.json', encoding='utf-8'))

parts = d.get('estimate_summary', {}).get('part_estimates', [])
print(f'{"Part":<22} {"£Unit":>7}  {"Source":<40} {"Conf":>5}  Note')
print("-" * 95)
for p in parts:
    pn   = p.get('part_number', '?')
    cost = float(p.get('unit_total_cost_gbp') or 0)

    # System cost path (bought-in parts)
    cb = p.get('cost_breakdown') or {}
    sc = cb.get('system_cost') or {}
    me = p.get('material_estimate') or {}

    if sc.get('applied_to_total'):
        # Bought-in — source is in system_cost
        ps   = sc.get('source') or {}
        src  = ps.get('source_name') or ps.get('source') or 'unknown'
        conf = float(ps.get('confidence') or 0)
        note = f"UNIT £{sc.get('unit_cost_gbp',0):.4f} each"
    else:
        # Fabricated — source is in material_estimate
        ps   = me.get('price_source') or {}
        src  = ps.get('source_name') or ps.get('source') or 'unknown'
        conf = float(ps.get('confidence') or 0)
        note = ps.get('applied_basis') or ''

    rev = ' * REVIEW' if (ps.get('review_required') if isinstance(ps,dict) else False) else ''
    print(f'{pn:<22} £{cost:>7.2f}  {src:<40} {conf:>5.2f}  {note}{rev}')
