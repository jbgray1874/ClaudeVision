import sys, json
sys.path.insert(0, 'src')
d = json.load(open('output/json/12242-01-GA Vue Sprung Cup Holder_revD.json', encoding='utf-8'))

parts = d.get('estimate_summary', {}).get('part_estimates', [])
print(f'{"Part":<22} {"£Unit":>7}  {"Source":<35} {"Conf":>5}')
print("-" * 80)
for p in parts:
    pn   = p.get('part_number', '?')
    cost = float(p.get('unit_total_cost_gbp') or 0)
    me   = p.get('material_estimate') or {}
    ps   = me.get('price_source') or p.get('price_source') or {}
    src  = ps.get('source_name') or ps.get('source') or ps.get('source_type') or 'unknown'
    conf = float(ps.get('confidence') or 0)
    rev  = '* REVIEW' if ps.get('review_required') else ''
    print(f'{pn:<22} £{cost:>7.2f}  {src:<35} {conf:>5.2f}  {rev}')
