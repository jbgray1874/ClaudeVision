import json

with open('output/json/0348389_ WICKER BASKET HOLDER.PDF.json', encoding='utf-8') as f:
    d = json.load(f)

print('=== PART QUALITY CHECK ===')
parts = d.get('manufacturing_writeup', {}).get('parts', d.get('parts', []))
for p in parts:
    pn   = str(p.get('part_number') or 'NONE')
    qty  = p.get('quantity', '?')
    mat  = str(p.get('normalized_material') or '?')
    l    = p.get('overall_length_mm', '-')
    w    = p.get('overall_width_mm', '-')
    ops  = p.get('textual_operations', [])
    flags = [f.get('flag') for f in p.get('review_flags', [])]
    print('  PN: %-35s qty=%-5s mat=%-15s dims=%sx%s' % (pn, qty, mat, l, w))
    if ops:   print('       ops  :', ops)
    if flags: print('       FLAGS:', flags)
    print()

print('=== LABOUR BREAKDOWN ===')
labour = d.get('cost_breakdown', {}).get('labour', {})
print('  Total: GBP', labour.get('total'))
for op, cost in (labour.get('by_operation') or {}).items():
    print('    %-22s: GBP %s' % (op, cost))
