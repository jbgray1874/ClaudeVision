import json
import sys
from pathlib import Path

json_path = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path(r"output/json/11367-09-GA - Shelf Lightbox_revD.json")
)
data = json.load(json_path.open(encoding="utf-8"))
print("JSON:", json_path)

# Check data['parts'] - these are likely the raw scan parts
raw_parts = data.get('parts', [])
print('data[parts] count:', len(raw_parts))
if raw_parts:
    print('raw part keys:', list(raw_parts[0].keys())[:20])

# Check manufacturing_writeup
mfg = data.get('manufacturing_writeup') or {}
mfg_parts = mfg.get('parts', [])
print('manufacturing_writeup[parts] count:', len(mfg_parts))
if mfg_parts:
    print('mfg part keys:', list(mfg_parts[0].keys())[:20])

# Find 11367-09-08A in raw parts
for label, part_list in [('data[parts]', raw_parts), ('manufacturing_writeup', mfg_parts)]:
    p = next((p for p in part_list if '08A' in str(p.get('part_number', ''))), None)
    if p:
        print(f'\n--- 11367-09-08A in {label} ---')
        print('  materials:', p.get('materials'))
        print('  material:', p.get('material'))
        print('  normalized_material:', p.get('normalized_material'))
        print('  page_roles:', p.get('page_roles'))
        print('  pages:', p.get('pages'))
        print('  textual_operations:', p.get('textual_operations'))
        print('  all keys:', list(p.keys()))
    else:
        print(f'\n11367-09-08A NOT in {label}')
        print('  part numbers:', [p.get('part_number') for p in part_list[:5]])