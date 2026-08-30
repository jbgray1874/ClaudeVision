import json
from pathlib import Path

p = sorted(Path('C:/ClaudeVision/input/history').rglob('*.formula_parse.json'))[0]
print(f"File: {p.name}\n")
data = json.load(open(p, encoding='utf-8'))
kc = data.get('key_cells') or {}

ops = kc.get('operation_rows') or []
print(f"operation_rows: {len(ops)} entries")
print("All addresses and values:")
for o in ops:
    addr  = o.get('address', '')
    val   = str(o.get('value', ''))[:35]
    left  = str((o.get('labels') or {}).get('left',  ''))[:25]
    left2 = str((o.get('labels') or {}).get('left_2',''))[:25]
    print(f"  {addr:8s}  val={val:37s}  left={left:27s}  left2={left2}")

print()
mats = kc.get('material_unit_prices') or []
print(f"material_unit_prices: {len(mats)} entries")
for m in mats[:10]:
    addr = m.get('address', '')
    val  = str(m.get('value', ''))[:35]
    left = str((m.get('labels') or {}).get('left', ''))[:30]
    print(f"  {addr:8s}  val={val:37s}  left={left}")

print()
tots = kc.get('totals') or []
print(f"totals: {len(tots)} entries")
for t in tots:
    addr = t.get('address', '')
    val  = str(t.get('value', ''))[:50]
    print(f"  {addr:8s}  val={val}")

print()
# Show parsed_entries for the Estimate sheet - first 5 with tags
pe = [e for e in (data.get('parsed_entries') or [])
      if str(e.get('sheet','')).upper() == 'ESTIMATE']
print(f"parsed_entries on Estimate sheet: {len(pe)}")
print("First 10:")
for e in pe[:10]:
    addr = e.get('address','')
    val  = str(e.get('value',''))[:30]
    tags = e.get('tags') or []
    left = str((e.get('labels') or {}).get('left',''))[:25]
    print(f"  {addr:8s}  val={val:32s}  tags={tags}  left={left}")

print()
# Show the estimate_sheet top-level structure if present
es = data.get('estimate_sheet') or {}
print(f"estimate_sheet keys: {list(es.keys())}")
